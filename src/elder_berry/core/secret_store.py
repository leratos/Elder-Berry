"""SecretStore – Fernet-verschlüsselte Credential-Verwaltung.

Speichert Secrets (z.B. Matrix-Bot-Token, API-Keys) verschlüsselt auf der Festplatte.
Key-Datei und Secrets-Datei liegen standardmäßig unter ~/.elder-berry/.

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
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

DEFAULT_BASE_DIR = Path.home() / ".elder-berry"
DEFAULT_KEY_FILE = "secret.key"
DEFAULT_SECRETS_FILE = "secrets.enc"


class SecretStoreError(Exception):
    """Basisklasse für SecretStore-Fehler."""


class SecretNotFoundError(SecretStoreError, KeyError):
    """Secret existiert nicht."""


class SecretStore:
    """Verschlüsselter Key-Value-Store für sensible Credentials.

    Nutzt Fernet (AES-128-CBC + HMAC-SHA256) aus der cryptography-Library.
    - Key wird in einer separaten Datei gespeichert (secret.key)
    - Secrets werden als verschlüsseltes JSON gespeichert (secrets.enc)
    - Beide Dateien liegen standardmäßig unter ~/.elder-berry/
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        key_file: str = DEFAULT_KEY_FILE,
        secrets_file: str = DEFAULT_SECRETS_FILE,
    ) -> None:
        self._base_dir = base_dir or DEFAULT_BASE_DIR
        self._key_path = self._base_dir / key_file
        self._secrets_path = self._base_dir / secrets_file
        self._fernet: Fernet | None = None

    def _ensure_base_dir(self) -> None:
        """Erstellt das Basisverzeichnis falls nötig."""
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _get_fernet(self) -> Fernet:
        """Gibt die Fernet-Instanz zurück. Lädt oder generiert den Key."""
        if self._fernet is not None:
            return self._fernet

        self._ensure_base_dir()

        if self._key_path.exists():
            key = self._key_path.read_bytes().strip()
            logger.debug("Encryption-Key geladen von %s", self._key_path)
        else:
            key = Fernet.generate_key()
            self._key_path.write_bytes(key)
            # Nur Owner darf lesen/schreiben (soweit OS es unterstützt)
            try:
                self._key_path.chmod(0o600)
            except OSError:
                # Windows unterstützt chmod nicht vollständig – akzeptabel
                logger.debug("chmod 600 nicht möglich (Windows?), übersprungen")
            logger.info("Neuer Encryption-Key generiert: %s", self._key_path)

        self._fernet = Fernet(key)
        return self._fernet

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
        """Pfad zur Key-Datei."""
        return self._key_path

    @property
    def secrets_path(self) -> Path:
        """Pfad zur Secrets-Datei."""
        return self._secrets_path
