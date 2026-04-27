"""SessionRevocationList -- Phase 70 (H-1).

Server-seitige Sperrliste fuer Dashboard-Session-Cookies. Schliesst die
Luecke, dass ``response.delete_cookie()`` den Cookie nur im Browser
loescht: der HMAC-signierte Token bleibt bis ``exp`` valide und kann
nach Diebstahl repliziert werden, solange er nicht hier auftaucht.

Design
------
- In-Memory-Set (asyncio nicht noetig, der Lookup in
  :meth:`DashboardAuthManager.verify_session` ist sync).
- Schluessel: SHA-256 des Cookie-Strings -- der Cookie selbst landet
  nie im Speicher (vermeidet versehentliches Echo in Logs/Heap-Dumps).
- Eintraege halten zusaetzlich einen ``expires_at``-Timestamp; nach
  Ablauf werden sie beim naechsten Cleanup-Tick verworfen, weil der
  Cookie sowieso nicht mehr verifizieren wuerde.
- Optionaler ``persist_path``: schreibt die Liste atomar als JSON
  (mtime-getriggert), damit ein Tower-Restart eine in-flight
  Revocation nicht wieder zu einem gueltigen Replay macht. Format
  ist absichtlich trivial gehalten -- kein Kreuzversionierung,
  kein Schema-Header. Format-Bruch -> Datei wird verworfen + neu
  angelegt.

Trade-off vs. ``rotate_session_secret()``
-----------------------------------------
- Single-Session-Revocation (das hier) -> trifft nur diesen Cookie.
  Andere Geraete bleiben eingeloggt. Default fuer den
  /api/dashboard/logout-Endpoint.
- Secret-Rotation (``logout-all``) -> trifft *alle* Sessions inkl.
  des Aufrufers (der bekommt aber sofort ein frisches Cookie).
  Drastischer; gewollt fuer "alle Geraete abmelden".
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)
security_logger = logging.getLogger("elder_berry.security")

_DEFAULT_CLEANUP_INTERVAL = 300  # 5 Min zwischen Bereinigungen
_MAX_ENTRIES_HARD_CAP = 100_000  # Defensiv: Cap, falls Persistenz amok laeuft


class SessionRevocationList:
    """Sperrliste fuer Session-Cookies, optional persistent.

    Parameters
    ----------
    persist_path : Path | None
        Wenn gesetzt: JSON-Backup der aktiven Eintraege. Wird beim
        Konstruktor einmal eingelesen, bei jedem :meth:`revoke`
        atomar neu geschrieben. ``None`` -> rein in-memory
        (Tower-Restart loescht Sperrliste; akzeptabel, weil der
        Cookie nach Restart auch via Secret-Rotation rausfliegen
        kann).
    cleanup_interval_seconds : int
        Wie haeufig abgelaufene Eintraege weggeworfen werden. Default
        300 s. Cleanup laeuft lazy: nur wenn :meth:`is_revoked` oder
        :meth:`revoke` aufgerufen werden.
    """

    def __init__(
        self,
        persist_path: Path | None = None,
        cleanup_interval_seconds: int = _DEFAULT_CLEANUP_INTERVAL,
    ) -> None:
        if cleanup_interval_seconds < 1:
            raise ValueError("cleanup_interval_seconds muss >= 1 sein")
        self._persist_path = persist_path
        self._cleanup_interval = cleanup_interval_seconds
        self._entries: dict[str, float] = {}
        self._lock = threading.Lock()
        self._last_cleanup: float = 0.0
        if persist_path is not None:
            self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def revoke(
        self,
        cookie_value: str,
        expires_at: float,
        now: float | None = None,
    ) -> None:
        """Setzt einen Cookie auf die Sperrliste.

        ``expires_at`` muss der ``exp``-Wert aus dem Cookie-Payload
        sein. Liegt er in der Vergangenheit, ist der Eintrag direkt
        eine No-Op (Cookie wuerde Signatur-Check ohnehin nicht mehr
        ueberleben).
        """
        ts = now if now is not None else time.time()
        if expires_at <= ts:
            return
        digest = self._hash(cookie_value)
        with self._lock:
            self._maybe_cleanup(ts)
            if len(self._entries) >= _MAX_ENTRIES_HARD_CAP:
                # Sehr defensiv: wenn der Hard-Cap reisst, faellt der
                # neueste Eintrag auf den Boden -- besser als unbegrenzt
                # wachsen. In der Praxis unerreichbar.
                security_logger.error(
                    "SessionRevocationList: Hard-Cap %d erreicht, "
                    "neuer revoke wird verworfen", _MAX_ENTRIES_HARD_CAP,
                )
                return
            self._entries[digest] = float(expires_at)
            self._persist()
        security_logger.info(
            "Session revoked (digest=%s, ttl=%ds)",
            digest[:12], int(expires_at - ts),
        )

    def is_revoked(
        self, cookie_value: str, now: float | None = None,
    ) -> bool:
        """``True`` wenn der Cookie auf der Sperrliste steht."""
        ts = now if now is not None else time.time()
        digest = self._hash(cookie_value)
        with self._lock:
            self._maybe_cleanup(ts)
            entry = self._entries.get(digest)
            if entry is None:
                return False
            if entry <= ts:
                # Abgelaufen -> Eintrag direkt weg
                self._entries.pop(digest, None)
                return False
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    # ------------------------------------------------------------------
    # Interna
    # ------------------------------------------------------------------

    @staticmethod
    def _hash(cookie_value: str) -> str:
        return hashlib.sha256(cookie_value.encode("utf-8")).hexdigest()

    def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self._cleanup_interval:
            return
        before = len(self._entries)
        stale = [k for k, exp in self._entries.items() if exp <= now]
        for k in stale:
            del self._entries[k]
        self._last_cleanup = now
        if stale:
            logger.debug(
                "SessionRevocationList: %d/%d Eintraege abgelaufen, entfernt",
                len(stale), before,
            )
            self._persist()

    def _load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "SessionRevocationList: Persistenz-Datei %s kaputt (%s) "
                "-- starte mit leerer Sperrliste",
                self._persist_path, exc,
            )
            return
        if not isinstance(raw, dict):
            return
        now = time.time()
        loaded: dict[str, float] = {}
        for digest, exp in raw.items():
            if not isinstance(digest, str) or not isinstance(exp, (int, float)):
                continue
            if exp <= now:
                continue
            loaded[digest] = float(exp)
        self._entries = loaded
        if loaded:
            logger.info(
                "SessionRevocationList: %d aktive Eintraege aus %s geladen",
                len(loaded), self._persist_path,
            )

    def _persist(self) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._persist_path.with_suffix(
                self._persist_path.suffix + ".tmp",
            )
            tmp.write_text(
                json.dumps(self._entries, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp.replace(self._persist_path)
        except OSError as exc:
            logger.warning(
                "SessionRevocationList: Persistenz nach %s fehlgeschlagen (%s)",
                self._persist_path, exc,
            )
