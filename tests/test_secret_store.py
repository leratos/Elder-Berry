"""Tests: SecretStore – Verschlüsselte Credential-Verwaltung."""
import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from elder_berry.core.secret_store import (
    SecretNotFoundError,
    SecretStore,
    SecretStoreError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """SecretStore mit temporärem Verzeichnis."""
    return SecretStore(base_dir=tmp_path)


@pytest.fixture
def store_with_data(store):
    """SecretStore mit vorausgefüllten Daten."""
    store.set("matrix_password", "geheim123")
    store.set("api_key", "sk-abc-xyz")
    return store


# ---------------------------------------------------------------------------
# Basis-Operationen
# ---------------------------------------------------------------------------

class TestBasicOperations:
    def test_set_and_get(self, store):
        store.set("key1", "value1")
        assert store.get("key1") == "value1"

    def test_get_nonexistent_raises(self, store):
        with pytest.raises(SecretNotFoundError, match="nicht gefunden"):
            store.get("nope")

    def test_get_or_none_returns_value(self, store):
        store.set("key1", "value1")
        assert store.get_or_none("key1") == "value1"

    def test_get_or_none_returns_none(self, store):
        assert store.get_or_none("nope") is None

    def test_set_overwrites(self, store):
        store.set("key1", "old")
        store.set("key1", "new")
        assert store.get("key1") == "new"

    def test_delete(self, store):
        store.set("key1", "value1")
        store.delete("key1")
        assert not store.has("key1")

    def test_delete_nonexistent_raises(self, store):
        with pytest.raises(SecretNotFoundError):
            store.delete("nope")

    def test_has_true(self, store):
        store.set("key1", "value1")
        assert store.has("key1") is True

    def test_has_false(self, store):
        assert store.has("nope") is False

    def test_list_keys_empty(self, store):
        assert store.list_keys() == []

    def test_list_keys(self, store_with_data):
        keys = store_with_data.list_keys()
        assert sorted(keys) == ["api_key", "matrix_password"]


# ---------------------------------------------------------------------------
# Verschlüsselung
# ---------------------------------------------------------------------------

class TestEncryption:
    def test_secrets_file_is_encrypted(self, store, tmp_path):
        store.set("password", "geheim")
        raw = (tmp_path / "secrets.enc").read_bytes()
        # Verschlüsselter Inhalt ist NICHT der Plaintext
        assert b"geheim" not in raw
        assert b"password" not in raw

    def test_key_file_created(self, store, tmp_path):
        store.set("x", "y")
        assert (tmp_path / "secret.key").exists()

    def test_key_file_is_valid_fernet_key(self, store, tmp_path):
        store.set("x", "y")
        key = (tmp_path / "secret.key").read_bytes().strip()
        # Kein Fehler heißt: gültiger Key
        Fernet(key)

    def test_key_persists_across_instances(self, tmp_path):
        store1 = SecretStore(base_dir=tmp_path)
        store1.set("key1", "value1")

        store2 = SecretStore(base_dir=tmp_path)
        assert store2.get("key1") == "value1"

    def test_wrong_key_raises(self, tmp_path):
        store = SecretStore(base_dir=tmp_path)
        store.set("key1", "value1")

        # Key-Datei mit anderem Key überschreiben
        wrong_key = Fernet.generate_key()
        (tmp_path / "secret.key").write_bytes(wrong_key)

        store2 = SecretStore(base_dir=tmp_path)
        with pytest.raises(SecretStoreError, match="nicht entschlüsselt"):
            store2.get("key1")


# ---------------------------------------------------------------------------
# Unicode + Sonderzeichen
# ---------------------------------------------------------------------------

class TestSpecialValues:
    def test_unicode_value(self, store):
        store.set("gruss", "Héllo Wörld 🎉")
        assert store.get("gruss") == "Héllo Wörld 🎉"

    def test_empty_string(self, store):
        store.set("empty", "")
        assert store.get("empty") == ""

    def test_long_value(self, store):
        long_val = "x" * 10_000
        store.set("long", long_val)
        assert store.get("long") == long_val

    def test_special_chars_in_key(self, store):
        store.set("matrix.password@server", "pw")
        assert store.get("matrix.password@server") == "pw"

    def test_json_value(self, store):
        val = json.dumps({"token": "abc", "refresh": "xyz"})
        store.set("tokens", val)
        parsed = json.loads(store.get("tokens"))
        assert parsed["token"] == "abc"


# ---------------------------------------------------------------------------
# Mehrere Secrets
# ---------------------------------------------------------------------------

class TestMultipleSecrets:
    def test_multiple_independent(self, store):
        store.set("a", "1")
        store.set("b", "2")
        store.set("c", "3")
        assert store.get("a") == "1"
        assert store.get("b") == "2"
        assert store.get("c") == "3"

    def test_delete_one_keeps_others(self, store_with_data):
        store_with_data.delete("matrix_password")
        assert not store_with_data.has("matrix_password")
        assert store_with_data.get("api_key") == "sk-abc-xyz"

    def test_overwrite_one_keeps_others(self, store_with_data):
        store_with_data.set("matrix_password", "neues_pw")
        assert store_with_data.get("matrix_password") == "neues_pw"
        assert store_with_data.get("api_key") == "sk-abc-xyz"


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_base_dir_created_on_first_use(self, tmp_path):
        nested = tmp_path / "sub" / "dir"
        store = SecretStore(base_dir=nested)
        store.set("key1", "val1")
        assert nested.exists()
        assert store.get("key1") == "val1"

    def test_empty_secrets_file_deleted_all(self, store):
        store.set("a", "1")
        store.delete("a")
        # Leeres Dict ist immer noch gültig
        assert store.list_keys() == []

    def test_properties(self, tmp_path):
        store = SecretStore(base_dir=tmp_path)
        assert store.key_path == tmp_path / "secret.key"
        assert store.secrets_path == tmp_path / "secrets.enc"

    def test_custom_filenames(self, tmp_path):
        store = SecretStore(
            base_dir=tmp_path,
            key_file="my.key",
            secrets_file="my.enc",
        )
        store.set("x", "y")
        assert (tmp_path / "my.key").exists()
        assert (tmp_path / "my.enc").exists()
        assert store.get("x") == "y"
