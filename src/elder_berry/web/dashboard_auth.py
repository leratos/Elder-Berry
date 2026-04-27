"""DashboardAuthManager – Phase 58 + Phase 70.

Login-Layer für das Settings-Dashboard. Speichert ein bcrypt-Passwort-Hash
im SecretStore und gibt zeitsignierte Session-Cookies aus
(HMAC-SHA256).

Komponenten
-----------
- ``set_password(pw)`` / ``verify_password(pw)`` – bcrypt-Hash im
  SecretStore unter Key ``dashboard_password_hash``.
- ``issue_session()`` / ``verify_session(cookie)`` /
  ``extend_session(cookie)`` – HMAC-signiertes Cookie mit ``iat`` +
  ``iat_original`` + ``exp``. Sliding renewal liefert ein neues
  Cookie zurück und behaelt das ``iat_original`` aus dem alten Cookie
  bei (siehe Phase 70 H-4).
- Session-Secret in ``dashboard_session_secret`` – auto-generiert
  beim ersten Aufruf (32 Byte ``secrets.token_urlsafe``).
- TTL (sliding): ``DashboardAuthManager(ttl_hours=12)``, Range 1–168.
- Absoluter Cap (Phase 70 H-4): ``max_absolute_lifetime_hours``
  (Default 24 h). Sliding renewal verlaengert nicht ueber diesen Punkt
  -- nach Ablauf wird ein Re-Login erzwungen.
- Server-side Revocation (Phase 70 H-1): optionaler
  :class:`SessionRevocationList`-Parameter. Logout markiert den
  konkreten Cookie als gesperrt; ``verify_session()`` prueft die
  Sperrliste nach erfolgreicher Signatur.

Tower-Restart invalidiert keine Sessions, solange Session-Secret +
(falls konfiguriert) Persistenz der Sperrliste erhalten bleiben. Wird
das Session-Secret rotiert (``rotate_session_secret``), verfallen alle
bisherigen Cookies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets as _secrets
import time
from typing import TYPE_CHECKING

import bcrypt

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.web.session_revocation_list import SessionRevocationList

logger = logging.getLogger(__name__)


PASSWORD_HASH_KEY = "dashboard_password_hash"
SESSION_SECRET_KEY = "dashboard_session_secret"
COOKIE_NAME = "eb_dashboard_session"

DEFAULT_TTL_HOURS = 12
MIN_TTL_HOURS = 1
MAX_TTL_HOURS = 168

# Phase 70 (H-4): absoluter Cap. Sliding-Renewal verlaengert nicht
# darueber hinaus -- nach Ablauf wird ein frischer Login erzwungen,
# selbst wenn ein gestohlener Cookie laufend per /api/* getouched wird.
DEFAULT_MAX_ABSOLUTE_LIFETIME_HOURS = 24
MIN_MAX_ABSOLUTE_LIFETIME_HOURS = 1
MAX_MAX_ABSOLUTE_LIFETIME_HOURS = 24 * 30  # 30 Tage Hard-Cap

# bcrypt cost factor – 12 ist 2026 ein guter Kompromiss zwischen
# Sicherheit und CPU-Zeit auf Tower-Hardware.
BCRYPT_ROUNDS = 12


class DashboardAuthError(Exception):
    """Basis-Exception für Auth-Probleme."""


class InvalidPasswordError(DashboardAuthError):
    """Passwort-Verify hat fehlgeschlagen."""


class InvalidSessionError(DashboardAuthError):
    """Session-Cookie ist ungültig, abgelaufen oder manipuliert."""


class PasswordNotSetError(DashboardAuthError):
    """Es wurde noch kein Dashboard-Passwort gesetzt."""


class DashboardAuthManager:
    """Verwaltet Dashboard-Passwort und Session-Cookies.

    Parameters
    ----------
    secret_store : SecretStore
        Persistenz für Hash und Session-Secret.
    ttl_hours : int
        Session-Lebensdauer in Stunden (Default 12, Range 1–168).
    """

    def __init__(
        self,
        secret_store: SecretStore,
        ttl_hours: int = DEFAULT_TTL_HOURS,
        *,
        max_absolute_lifetime_hours: int = DEFAULT_MAX_ABSOLUTE_LIFETIME_HOURS,
        revocation_list: SessionRevocationList | None = None,
    ) -> None:
        if not MIN_TTL_HOURS <= ttl_hours <= MAX_TTL_HOURS:
            raise ValueError(
                f"ttl_hours muss zwischen {MIN_TTL_HOURS} und "
                f"{MAX_TTL_HOURS} liegen, bekam {ttl_hours}"
            )
        if not (
            MIN_MAX_ABSOLUTE_LIFETIME_HOURS
            <= max_absolute_lifetime_hours
            <= MAX_MAX_ABSOLUTE_LIFETIME_HOURS
        ):
            raise ValueError(
                "max_absolute_lifetime_hours muss zwischen "
                f"{MIN_MAX_ABSOLUTE_LIFETIME_HOURS} und "
                f"{MAX_MAX_ABSOLUTE_LIFETIME_HOURS} liegen, bekam "
                f"{max_absolute_lifetime_hours}"
            )
        if max_absolute_lifetime_hours * 3600 < ttl_hours * 3600:
            # Sliding-TTL > absolute-Cap waere ein Konfigurationsfehler:
            # das Cookie wuerde direkt nach Ausgabe schon den Cap reissen.
            raise ValueError(
                "max_absolute_lifetime_hours darf nicht kleiner sein als "
                "ttl_hours -- sonst ist das frisch ausgestellte Cookie "
                "schon ueber dem absoluten Cap"
            )
        self._store = secret_store
        self._ttl_seconds = ttl_hours * 3600
        self._max_absolute_lifetime_seconds = max_absolute_lifetime_hours * 3600
        self._revocation_list = revocation_list

    # -- Passwort-Management ----------------------------------------- #

    def is_password_set(self) -> bool:
        """True wenn ein Dashboard-Passwort konfiguriert wurde."""
        return self._store.has(PASSWORD_HASH_KEY)

    def set_password(self, password: str) -> None:
        """Speichert ein neues Dashboard-Passwort (bcrypt-Hash)."""
        if not password or len(password) < 8:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein")
        # bcrypt limitiert auf 72 Bytes – Hash längerer PWs ist trivial,
        # aber ein Hinweis ist sauberer als stiller Truncate.
        if len(password.encode("utf-8")) > 72:
            raise ValueError(
                "Passwort darf maximal 72 Bytes (UTF-8) lang sein"
            )
        hashed = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
        )
        self._store.set(PASSWORD_HASH_KEY, hashed.decode("ascii"))
        logger.info("Dashboard-Passwort aktualisiert (bcrypt rounds=%d)",
                    BCRYPT_ROUNDS)

    def verify_password(self, password: str) -> bool:
        """Prüft ein Klartext-Passwort gegen den gespeicherten Hash.

        Wirft :class:`PasswordNotSetError` wenn noch kein PW gesetzt
        wurde – die Differenzierung gegenüber ``return False`` ist
        wichtig für die Login-UI (zeigt „Setup nötig" statt
        „falsches PW").
        """
        stored = self._store.get_or_none(PASSWORD_HASH_KEY)
        if stored is None:
            raise PasswordNotSetError(
                "Kein Dashboard-Passwort gesetzt – siehe Setup-Wizard"
            )
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"),
                stored.encode("ascii"),
            )
        except (ValueError, TypeError) as exc:
            logger.error("bcrypt-Check fehlgeschlagen: %s", exc)
            return False

    # -- Session-Cookie (HMAC-signiert, stateless) ------------------- #

    def _get_session_secret(self) -> bytes:
        """Lädt oder generiert das Session-Signing-Secret."""
        existing = self._store.get_or_none(SESSION_SECRET_KEY)
        if existing:
            return existing.encode("ascii")
        new_secret = _secrets.token_urlsafe(32)
        self._store.set(SESSION_SECRET_KEY, new_secret)
        logger.info("Neues dashboard_session_secret generiert (32 B)")
        return new_secret.encode("ascii")

    def rotate_session_secret(self) -> None:
        """Invalidiert alle bestehenden Sessions durch Secret-Rotation."""
        new_secret = _secrets.token_urlsafe(32)
        self._store.set(SESSION_SECRET_KEY, new_secret)
        logger.warning("dashboard_session_secret rotiert – alle "
                       "bestehenden Sessions sind ungültig")

    def issue_session(
        self,
        now: float | None = None,
        iat_original: int | None = None,
    ) -> tuple[str, int]:
        """Erzeugt ein neues Session-Cookie.

        Parameters
        ----------
        iat_original : int | None
            Wenn gesetzt: ``iat_original`` wird aus der bisherigen
            Session uebernommen (Sliding-Renewal). ``None`` = neuer
            Login, ``iat_original`` = jetzt.

        Returns
        -------
        tuple[str, int]
            ``(cookie_value, expires_at_unix_ts)``
        """
        ts = int(now if now is not None else time.time())
        exp = ts + self._ttl_seconds
        payload = {
            "iat": ts,
            "iat_original": int(iat_original) if iat_original is not None else ts,
            "exp": exp,
        }
        return self._sign_payload(payload), exp

    def verify_session(
        self, cookie_value: str | None, now: float | None = None,
    ) -> dict[str, int]:
        """Prüft ein Cookie und gibt das Payload zurück.

        Reihenfolge der Checks (alle harten Aborts werfen
        :class:`InvalidSessionError`):

        1. Cookie vorhanden + Format
        2. HMAC-Signatur (Phase 58)
        3. Payload-Struktur, ``exp`` nicht abgelaufen
        4. Phase 70 (H-4): absoluter Cap ueber ``iat_original`` --
           wenn das Feld fehlt (Cookie aus alter Phase-58/65-Welt),
           fallen wir auf ``iat`` zurueck. Konsequenz: bestehende
           Sessions verlieren beim Deploy keinen Zugang sofort,
           werden aber spaetestens nach ``max_absolute_lifetime``
           ausgestiegen.
        5. Phase 70 (H-1): Revocation-Check.
        """
        if not cookie_value:
            raise InvalidSessionError("Cookie fehlt")
        try:
            raw_payload, raw_sig = cookie_value.rsplit(".", 1)
        except ValueError as exc:
            raise InvalidSessionError("Cookie-Format ungültig") from exc
        secret = self._get_session_secret()
        expected_sig = self._compute_signature(raw_payload, secret)
        if not hmac.compare_digest(expected_sig, raw_sig):
            raise InvalidSessionError("Signatur ungültig")
        try:
            payload_bytes = base64.urlsafe_b64decode(_pad(raw_payload))
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise InvalidSessionError("Payload nicht lesbar") from exc
        if not isinstance(payload, dict) or "exp" not in payload:
            raise InvalidSessionError("Payload-Struktur ungültig")
        ts = int(now if now is not None else time.time())
        if ts >= int(payload["exp"]):
            raise InvalidSessionError("Session abgelaufen")

        # Phase 70 (H-4): absoluter Cap
        iat_original = payload.get("iat_original", payload.get("iat"))
        if iat_original is not None:
            try:
                iat_original_int = int(iat_original)
            except (TypeError, ValueError) as exc:
                raise InvalidSessionError(
                    "iat_original im Payload ist kein Integer",
                ) from exc
            if ts - iat_original_int >= self._max_absolute_lifetime_seconds:
                raise InvalidSessionError(
                    "Session ueberschreitet absoluten Lifetime-Cap "
                    f"({self._max_absolute_lifetime_seconds // 3600} h)"
                )

        # Phase 70 (H-1): Revocation-Check
        if self._revocation_list is not None and self._revocation_list.is_revoked(
            cookie_value, now=ts,
        ):
            raise InvalidSessionError("Session wurde server-seitig widerrufen")

        return payload

    def extend_session(
        self, cookie_value: str, now: float | None = None,
    ) -> tuple[str, int]:
        """Sliding-Renewal: validiert + gibt frisches Cookie zurück.

        Behaelt das ``iat_original`` aus dem alten Cookie bei, damit
        der absolute Cap (Phase 70 H-4) nicht durch jede Renewal-Runde
        zurueckgesetzt wird.

        Wirft :class:`InvalidSessionError` wenn die alte Session
        ungueltig ist (Signatur, exp, absoluter Cap, Revocation).
        """
        payload = self.verify_session(cookie_value, now=now)
        iat_original = payload.get("iat_original", payload.get("iat"))
        return self.issue_session(now=now, iat_original=iat_original)

    def revoke_session(
        self, cookie_value: str | None, now: float | None = None,
    ) -> bool:
        """Setzt einen Cookie auf die Sperrliste (Phase 70 H-1).

        Macht nichts, wenn keine :class:`SessionRevocationList`
        injiziert wurde (Tests, Setup-Wizard) oder das Cookie ohnehin
        keine valide Session ist.

        Returns
        -------
        bool
            ``True`` wenn der Cookie tatsaechlich revoked wurde
            (gueltige Session + Liste vorhanden), sonst ``False``.
        """
        if not cookie_value or self._revocation_list is None:
            return False
        try:
            payload = self.verify_session(cookie_value, now=now)
        except InvalidSessionError:
            # Schon ungueltig (abgelaufen, manipuliert, bereits
            # revoked) -- kein zusaetzlicher Eintrag noetig.
            return False
        self._revocation_list.revoke(
            cookie_value,
            expires_at=float(payload["exp"]),
            now=now,
        )
        return True

    # -- Interne Helpers --------------------------------------------- #

    def _sign_payload(self, payload: dict) -> str:
        secret = self._get_session_secret()
        payload_bytes = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
        sig = self._compute_signature(encoded, secret)
        return f"{encoded}.{sig}"

    @staticmethod
    def _compute_signature(payload_b64: str, secret: bytes) -> str:
        digest = hmac.new(
            secret,
            payload_b64.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    @property
    def max_absolute_lifetime_seconds(self) -> int:
        return self._max_absolute_lifetime_seconds

    @property
    def revocation_list(self) -> SessionRevocationList | None:
        return self._revocation_list


def _pad(value: str) -> bytes:
    """Repariert urlsafe-base64-Padding."""
    pad = (-len(value)) % 4
    return (value + "=" * pad).encode("ascii")
