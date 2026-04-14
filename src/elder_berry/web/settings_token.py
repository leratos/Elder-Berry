"""Settings-Token Manager (Phase 52.1a).

Persistiert einen statischen Token, der vom Settings-Dashboard für
schreibende Operationen verlangt wird. Der Token wird beim ersten Start
generiert, in einer Datei abgelegt und einmal in die Konsole geloggt.

Pfad: ``${ELDER_BERRY_HOME}/settings_token`` – auf POSIX mit ``chmod 600``.

Rotation: Token rotiert nur durch manuelles Löschen der Datei.
"""

from __future__ import annotations

import logging
import os
import secrets as _secrets
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


class SettingsTokenError(Exception):
    """Fehler beim Lesen, Schreiben oder Validieren des Settings-Tokens."""


class SettingsTokenManager:
    """Lädt oder erzeugt den Settings-Token und prüft eingehende Requests.

    Parameters
    ----------
    token_path : Path
        Vollständiger Pfad zur Token-Datei (z.B. ELDER_BERRY_HOME/settings_token).
    token_length : int
        Länge des erzeugten Tokens in Bytes (Default 32 → 64 Hex-Zeichen).

    Notes
    -----
    Die Datei wird auf POSIX-Systemen mit ``chmod 600`` versehen. Auf
    Windows verlässt sich die Klasse auf den Default-User-ACL-Schutz im
    Profil-Pfad – ein zusätzlicher Schutz wird bewusst nicht gesetzt, um
    Plattform-Eigenheiten nicht zu maskieren.
    """

    DEFAULT_TOKEN_BYTES = 32
    _MIN_TOKEN_LENGTH = 16

    def __init__(
        self,
        token_path: Path,
        token_length: int = DEFAULT_TOKEN_BYTES,
    ) -> None:
        if token_length < self._MIN_TOKEN_LENGTH:
            raise SettingsTokenError(
                f"token_length muss >= {self._MIN_TOKEN_LENGTH} sein.",
            )
        self._path = Path(token_path)
        self._token_length = token_length
        self._token: str | None = None

    @property
    def path(self) -> Path:
        return self._path

    def load_or_create(self) -> str:
        """Liest den Token aus der Datei oder erzeugt einen neuen.

        Gibt den Token zurück. Logged eine Info-Zeile mit dem Pfad. Wenn
        ein neuer Token erzeugt wurde, wird er zusätzlich in voller Länge
        in die Konsole geloggt (Single-User-Setup).
        """
        if self._path.exists():
            try:
                token = self._path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise SettingsTokenError(
                    f"Token-Datei {self._path} konnte nicht gelesen werden: {exc}",
                ) from exc
            if not token:
                logger.warning(
                    "Settings-Token Datei %s ist leer – erzeuge neuen Token.",
                    self._path,
                )
                token = self._generate_and_persist()
            else:
                self._token = token
                logger.info("Settings-Token geladen aus %s", self._path)
            return token

        return self._generate_and_persist()

    def _generate_and_persist(self) -> str:
        token = _secrets.token_hex(self._token_length)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(token, encoding="utf-8")
        except OSError as exc:
            raise SettingsTokenError(
                f"Token-Datei {self._path} konnte nicht geschrieben werden: {exc}",
            ) from exc

        if os.name == "posix":
            try:
                self._path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except OSError as exc:
                logger.warning(
                    "chmod 600 auf %s fehlgeschlagen: %s", self._path, exc,
                )

        self._token = token
        logger.info(
            "Settings-Token erzeugt und gespeichert: %s", self._path,
        )
        logger.info(
            "Settings-Token (für 'X-Saleria-Settings-Token' Header): %s",
            token,
        )
        return token

    def get(self) -> str:
        """Gibt den aktuell geladenen Token zurück.

        Raises
        ------
        SettingsTokenError
            Wenn ``load_or_create()`` noch nicht aufgerufen wurde.
        """
        if self._token is None:
            raise SettingsTokenError(
                "Token wurde noch nicht geladen – load_or_create() aufrufen.",
            )
        return self._token

    def validate(self, candidate: str | None) -> bool:
        """Vergleicht einen eingehenden Token konstant-zeitig.

        Gibt False zurück bei None, leerem String oder Mismatch.
        """
        if not candidate or self._token is None:
            return False
        return _secrets.compare_digest(candidate, self._token)
