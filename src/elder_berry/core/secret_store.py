"""SecretStore – Fernet-verschlüsselte Credential-Verwaltung.

Speichert Secrets (z.B. Matrix-Bot-Token, API-Keys) verschlüsselt auf der
Festplatte. Der Fernet-Masterkey liegt bevorzugt im **OS-Keyring**
(Windows Credential Manager / DPAPI, macOS Keychain, Linux Secret
Service), mit Fallback auf eine chmod-600-Datei wenn kein Backend
verfuegbar ist.

Phase 65 (M-1): Migration vom alten Plaintext-Key-File (~/.elder-berry/
secret.key) in den OS-Keyring laeuft automatisch beim naechsten Start
-- mit Verify-before-Delete, also ohne Risiko fuer Datenverlust.

Verwendung:
    store = SecretStore()
    store.set("matrix_password", "geheim123")
    pw = store.get("matrix_password")
    store.delete("matrix_password")
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

DEFAULT_BASE_DIR = Path.home() / ".elder-berry"
DEFAULT_KEY_FILE = "secret.key"
DEFAULT_SECRETS_FILE = "secrets.enc"

# Phase 65 (M-1): Keyring-Service/User fuer den Fernet-Masterkey.
KEYRING_SERVICE = "elder-berry"
KEYRING_USERNAME = "master-key"


# Lazy-safe Import von keyring: wenn die Lib fehlt, operieren wir
# automatisch im Fallback-Modus (Plaintext-Datei + Warning).
try:
    import keyring
    import keyring.errors as keyring_errors
    from keyring.backends.fail import Keyring as _FailKeyring
    _HAS_KEYRING = True
except ImportError:  # pragma: no cover -- auf supported Platforms ist keyring dabei
    keyring = None
    keyring_errors = None
    _FailKeyring = None  # type: ignore[assignment]
    _HAS_KEYRING = False


class SecretStoreError(Exception):
    """Basisklasse für SecretStore-Fehler."""


class SecretNotFoundError(SecretStoreError, KeyError):
    """Secret existiert nicht."""


class KeyringUnavailableError(SecretStoreError):
    """``use_keyring=True`` wurde verlangt, aber kein Backend ist da."""


class SecretStore:
    """Verschlüsselter Key-Value-Store für sensible Credentials.

    Nutzt Fernet (AES-128-CBC + HMAC-SHA256) aus der cryptography-Library.

    Masterkey-Speicherung (Phase 65 M-1):

    - **Primaer**: OS-Keyring (Windows Credential Manager via DPAPI,
      macOS Keychain, Linux Secret Service). Gebunden an den OS-Benutzer
      -- Dateisystem-Zugriff allein reicht nicht mehr, um die Secrets
      zu entschluesseln.
    - **Fallback**: ``~/.elder-berry/secret.key`` als Plaintext-Datei
      mit chmod 600. Wird nur benutzt, wenn kein Keyring-Backend
      verfuegbar ist (z.B. headless Linux ohne libsecret).
    - **Migration**: Wenn beim ersten Start der Keyring verfuegbar ist
      UND eine alte Plaintext-Key-Datei existiert, wird der Key einmalig
      in den Keyring verschoben. Die Migration verifiziert den Keyring-
      Write durch Re-Read, BEVOR die alte Datei geloescht wird -- bei
      irgendeinem Fehler bleibt die Datei unangetastet.

    Parameters
    ----------
    base_dir : Path | None
        Verzeichnis fuer die secrets.enc (und optional secret.key).
        Default: ``~/.elder-berry``.
    use_keyring : bool | None
        ``True``  -> strikt Keyring; raised ``KeyringUnavailableError``
                     wenn kein Backend da ist.
        ``False`` -> ignoriert Keyring komplett, nutzt Plaintext-Datei.
        ``None`` (Default) -> Auto: Keyring wenn vorhanden, sonst
                     Fallback mit Warning im Log.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        key_file: str = DEFAULT_KEY_FILE,
        secrets_file: str = DEFAULT_SECRETS_FILE,
        *,
        use_keyring: bool | None = None,
    ) -> None:
        self._base_dir = base_dir or DEFAULT_BASE_DIR
        self._key_path = self._base_dir / key_file
        self._secrets_path = self._base_dir / secrets_file
        self._fernet: Fernet | None = None
        self._use_keyring = use_keyring

    # ------------------------------------------------------------------
    # Keyring-Helpers (M-1)
    # ------------------------------------------------------------------

    @staticmethod
    def _keyring_available() -> bool:
        """Probe: Ist ein funktionierendes Keyring-Backend verfuegbar?

        Wir wollen keinen echten Write-Test machen (invasiv). Stattdessen
        pruefen wir, ob das Default-Backend *nicht* der Fail-Keyring ist
        -- der ist die neutrale Variante von ``keyring``, die bei jedem
        Schreibversuch raised.
        """
        if not _HAS_KEYRING:
            return False
        backend = keyring.get_keyring()
        if _FailKeyring is not None and isinstance(backend, _FailKeyring):
            return False
        return True

    def _decide_use_keyring(self) -> bool:
        """Entscheidet einmalig, ob Keyring genutzt wird."""
        if self._use_keyring is False:
            return False
        available = self._keyring_available()
        if self._use_keyring is True:
            if not available:
                raise KeyringUnavailableError(
                    "use_keyring=True, aber kein Keyring-Backend verfuegbar. "
                    "Installiere libsecret-tools (Linux), oder setze "
                    "use_keyring=False fuer den Datei-Fallback."
                )
            return True
        # Auto-Mode
        if not available:
            logger.warning(
                "Kein OS-Keyring-Backend verfuegbar -- Fallback auf "
                "Plaintext-Datei (chmod 600). Fuer Produktion bitte "
                "Secret-Service/Keychain installieren."
            )
        return available

    def _load_key_from_keyring(self) -> bytes | None:
        """Liest den Fernet-Key aus dem OS-Keyring. None wenn nicht gesetzt."""
        value = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if value:
            return value.encode("ascii")
        return None

    def _save_key_to_keyring(self, key: bytes) -> None:
        """Speichert den Fernet-Key im OS-Keyring + Verify per Re-Read.

        Wirft ``SecretStoreError`` wenn der verifikations-Read nicht das
        Original zurueckliefert -- dann ist die Migration abgebrochen
        und die Aufruf-Seite loescht die alte Datei *nicht*.
        """
        key_str = key.decode("ascii")
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key_str)
        verify = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if verify != key_str:
            raise SecretStoreError(
                "Keyring-Write konnte nicht verifiziert werden. "
                "Migration abgebrochen, alte Datei bleibt unangetastet."
            )

    # ------------------------------------------------------------------
    # Interne File-Helpers (Fallback-Pfad)
    # ------------------------------------------------------------------

    def _ensure_base_dir(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _load_key_from_file(self) -> bytes:
        """Legacy-Pfad: Key aus Plaintext-Datei."""
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        try:
            self._key_path.chmod(0o600)
        except OSError:
            logger.debug("chmod 600 nicht moeglich (Windows?), uebersprungen")
        logger.info("Neuer Encryption-Key generiert: %s", self._key_path)
        return key

    # ------------------------------------------------------------------
    # Haupt-Resolver fuer den Fernet-Instance
    # ------------------------------------------------------------------

    def _get_fernet(self) -> Fernet:
        """Gibt die Fernet-Instanz zurück. Lädt oder generiert den Key."""
        if self._fernet is not None:
            return self._fernet

        self._ensure_base_dir()
        use_keyring = self._decide_use_keyring()

        if use_keyring:
            key = self._load_key_from_keyring()
            if key is None:
                # Migration von alter Plaintext-Datei, oder Neuanlage.
                if self._key_path.exists():
                    logger.info(
                        "Migriere Master-Key aus %s in den OS-Keyring...",
                        self._key_path,
                    )
                    key = self._key_path.read_bytes().strip()
                    self._save_key_to_keyring(key)  # raised on verify-fail
                    # Erst jetzt loeschen -- wir haben den Keyring-Write
                    # erfolgreich verifiziert.
                    self._key_path.unlink()
                    logger.warning(
                        "Master-Key erfolgreich in den OS-Keyring migriert, "
                        "alte Datei %s geloescht. Secrets sind jetzt an den "
                        "OS-Benutzer gebunden -- bei User-/Maschinenwechsel "
                        "wird der Store unbenutzbar. Backup von %s + Export "
                        "der Secret-Werte empfohlen.",
                        self._key_path, self._secrets_path,
                    )
                else:
                    key = Fernet.generate_key()
                    self._save_key_to_keyring(key)
                    logger.info(
                        "Neuer Master-Key im OS-Keyring erzeugt "
                        "(service=%s, user=%s).",
                        KEYRING_SERVICE, KEYRING_USERNAME,
                    )
        else:
            key = self._load_key_from_file()

        self._fernet = Fernet(key)
        return self._fernet

    # ------------------------------------------------------------------
    # Public API -- unveraendert seit Phase 57
    # ------------------------------------------------------------------

    def _load_secrets(self) -> dict[str, str]:
        """Entschlüsselt und lädt die Secrets-Datei. Leeres Dict wenn nicht vorhanden."""
        if not self._secrets_path.exists():
            return {}

        fernet = self._get_fernet()
        encrypted = self._secrets_path.read_bytes()

        try:
            decrypted = fernet.decrypt(encrypted)
        except InvalidToken as e:
            raise SecretStoreError(
                "Secrets konnten nicht entschlüsselt werden. "
                "Key-Datei passt nicht oder Datei ist beschädigt."
            ) from e

        return json.loads(decrypted.decode("utf-8"))

    def _save_secrets(self, data: dict[str, str]) -> None:
        """Verschlüsselt und speichert die Secrets-Datei."""
        self._ensure_base_dir()
        fernet = self._get_fernet()
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        encrypted = fernet.encrypt(plaintext)
        self._secrets_path.write_bytes(encrypted)

    def get(self, key: str) -> str:
        """Liest ein Secret. Wirft SecretNotFoundError wenn nicht vorhanden."""
        secrets = self._load_secrets()
        if key not in secrets:
            raise SecretNotFoundError(f"Secret '{key}' nicht gefunden")
        return secrets[key]

    def get_or_none(self, key: str) -> str | None:
        """Liest ein Secret. Gibt None zurück wenn nicht vorhanden."""
        try:
            return self.get(key)
        except SecretNotFoundError:
            return None

    def set(self, key: str, value: str) -> None:
        """Speichert oder aktualisiert ein Secret."""
        secrets = self._load_secrets()
        secrets[key] = value
        self._save_secrets(secrets)
        logger.debug("Secret '%s' gespeichert", key)

    def delete(self, key: str) -> None:
        """Löscht ein Secret. Wirft SecretNotFoundError wenn nicht vorhanden."""
        secrets = self._load_secrets()
        if key not in secrets:
            raise SecretNotFoundError(f"Secret '{key}' nicht gefunden")
        del secrets[key]
        self._save_secrets(secrets)
        logger.debug("Secret '%s' gelöscht", key)

    def has(self, key: str) -> bool:
        """Prüft ob ein Secret existiert."""
        secrets = self._load_secrets()
        return key in secrets

    def list_keys(self) -> list[str]:
        """Gibt alle gespeicherten Secret-Keys zurück (ohne Werte)."""
        return list(self._load_secrets().keys())

    @property
    def key_path(self) -> Path:
        """Pfad zur (Legacy-)Key-Datei. Nur noch genutzt im Fallback-Modus."""
        return self._key_path

    @property
    def secrets_path(self) -> Path:
        """Pfad zur Secrets-Datei."""
        return self._secrets_path
