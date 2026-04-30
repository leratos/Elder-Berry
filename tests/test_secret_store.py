"""Tests: SecretStore – Verschlüsselte Credential-Verwaltung."""

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from elder_berry.core.secret_store import (
    KEYRING_SERVICE,
    KEYRING_USERNAME_PREFIX,
    KeyringUnavailableError,
    SecretNotFoundError,
    SecretStore,
    SecretStoreError,
)


def _username_for(base_dir) -> str:
    """Berechnet den erwarteten Keyring-Username fuer einen base_dir.

    Spiegelt die Logik in ``SecretStore._keyring_username`` (sha256-16
    des absoluten Pfads, mit Prefix). Wir reimplementieren sie hier,
    damit die Tests die Invariante unabhaengig vom Produktionscode
    ueberwachen.
    """
    resolved = str(Path(base_dir).resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    return f"{KEYRING_USERNAME_PREFIX}:{digest}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    """SecretStore mit temporärem Verzeichnis im File-Fallback-Modus.

    Phase 65 (M-1): Die allermeisten Tests pruefen Verhalten, das nicht
    vom Keyring abhaengt (set/get/delete/encryption). Mit ``use_keyring=
    False`` bleiben sie deterministisch -- ansonsten wuerden sie den
    OS-Keyring des Dev-/CI-Systems anfassen (nicht-hermetisch!). Die
    Keyring-Integration selbst wird in einer eigenen Testklasse weiter
    unten mit gemocktem ``keyring``-Modul getestet.
    """
    return SecretStore(base_dir=tmp_path, use_keyring=False)


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
        # Nur im File-Fallback sinnvoll: der Test manipuliert die
        # Key-Datei direkt. Im Keyring-Modus existiert die Datei gar nicht.
        store = SecretStore(base_dir=tmp_path, use_keyring=False)
        store.set("key1", "value1")

        # Key-Datei mit anderem Key überschreiben
        wrong_key = Fernet.generate_key()
        (tmp_path / "secret.key").write_bytes(wrong_key)

        store2 = SecretStore(base_dir=tmp_path, use_keyring=False)
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
        store = SecretStore(base_dir=nested, use_keyring=False)
        store.set("key1", "val1")
        assert nested.exists()
        assert store.get("key1") == "val1"

    def test_empty_secrets_file_deleted_all(self, store):
        store.set("a", "1")
        store.delete("a")
        # Leeres Dict ist immer noch gültig
        assert store.list_keys() == []

    def test_properties(self, tmp_path):
        store = SecretStore(base_dir=tmp_path, use_keyring=False)
        assert store.key_path == tmp_path / "secret.key"
        assert store.secrets_path == tmp_path / "secrets.enc"

    def test_custom_filenames(self, tmp_path):
        store = SecretStore(
            base_dir=tmp_path,
            key_file="my.key",
            secrets_file="my.enc",
            use_keyring=False,
        )
        store.set("x", "y")
        assert (tmp_path / "my.key").exists()
        assert (tmp_path / "my.enc").exists()
        assert store.get("x") == "y"


# ---------------------------------------------------------------------------
# Phase 65 (M-1): Keyring-Integration (+ Migration)
# ---------------------------------------------------------------------------


class _FakeKeyring:
    """Minimaler In-Memory-Keyring fuer Tests.

    Bildet ``keyring.get_password``/``keyring.set_password``/
    ``keyring.delete_password`` nach. Genug, um Migration und
    Verify-before-Delete sauber zu pruefen.
    """

    def __init__(self) -> None:
        self._storage: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._storage.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._storage[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._storage.pop((service, username), None)


@pytest.fixture
def fake_keyring(monkeypatch):
    """Patcht das global importierte ``keyring``-Modul auf einen FakeKeyring.

    Sorgt ausserdem dafuer, dass ``_keyring_available()`` True zurueckgibt,
    indem ``_FailKeyring`` auf eine Klasse gepatched wird, die sicher
    NICHT mit dem Fake-Backend matcht.
    """
    fake = _FakeKeyring()
    monkeypatch.setattr("elder_berry.core.secret_store.keyring", fake)
    monkeypatch.setattr("elder_berry.core.secret_store._HAS_KEYRING", True)

    # Fail-Check: isinstance(backend, _FailKeyring) darf nicht truthy werden.
    class _NotAFailKeyring:
        pass

    monkeypatch.setattr(
        "elder_berry.core.secret_store._FailKeyring",
        _NotAFailKeyring,
    )
    # get_keyring() liefert irgendwas, das nicht _NotAFailKeyring ist
    monkeypatch.setattr(fake, "get_keyring", object, raising=False)
    # Aber unser _keyring_available() nutzt keyring.get_keyring() -- das ist
    # jetzt der fake. Lass das via fake auch existieren:
    fake.get_keyring = object  # type: ignore[attr-defined]
    return fake


class TestKeyringAvailability:
    """Entscheidungslogik: Keyring ja/nein."""

    def test_auto_uses_keyring_when_available(self, tmp_path, fake_keyring):
        store = SecretStore(base_dir=tmp_path)
        # Triggert _get_fernet() -> Key landet im Fake-Keyring, KEINE Datei
        store.set("x", "y")
        assert fake_keyring.get_password(KEYRING_SERVICE, _username_for(tmp_path))
        assert not (tmp_path / "secret.key").exists()

    def test_auto_falls_back_when_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "elder_berry.core.secret_store._HAS_KEYRING",
            False,
        )
        store = SecretStore(base_dir=tmp_path)
        store.set("x", "y")
        # Fallback-Pfad -> Datei ist da
        assert (tmp_path / "secret.key").exists()

    def test_explicit_false_always_uses_file(self, tmp_path, fake_keyring):
        store = SecretStore(base_dir=tmp_path, use_keyring=False)
        store.set("x", "y")
        assert (tmp_path / "secret.key").exists()
        # Keyring wurde NICHT angefasst
        assert (
            fake_keyring.get_password(KEYRING_SERVICE, _username_for(tmp_path)) is None
        )

    def test_explicit_true_raises_when_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "elder_berry.core.secret_store._HAS_KEYRING",
            False,
        )
        store = SecretStore(base_dir=tmp_path, use_keyring=True)
        with pytest.raises(KeyringUnavailableError, match="kein Keyring-Backend"):
            store.set("x", "y")

    def test_fail_backend_counts_as_unavailable(self, tmp_path, monkeypatch):
        """Wenn keyring installiert, aber Default-Backend = FailKeyring."""

        # Wir konstruieren explizit den Fall: _HAS_KEYRING=True, aber
        # get_keyring() liefert eine Instanz der gleichen Klasse, die
        # _FailKeyring ist.
        class _Fail:
            pass

        fake = MagicMock()
        fake.get_keyring.return_value = _Fail()
        monkeypatch.setattr("elder_berry.core.secret_store.keyring", fake)
        monkeypatch.setattr("elder_berry.core.secret_store._HAS_KEYRING", True)
        monkeypatch.setattr("elder_berry.core.secret_store._FailKeyring", _Fail)

        store = SecretStore(base_dir=tmp_path)
        store.set("x", "y")
        # Fallback -> Datei
        assert (tmp_path / "secret.key").exists()

    def test_get_keyring_raising_counts_as_unavailable(
        self,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        """Backend-Discovery kann selbst raisen -- z.B. libsecret
        installiert aber keine DBus-Session, oder macOS Keychain-
        Dienst unerreichbar. Auto-Mode MUSS robust auf File-Fallback
        gehen statt den Start zu crashen.
        """
        import logging

        fake = MagicMock()
        fake.get_keyring.side_effect = RuntimeError(
            "DBus session bus not available",
        )
        monkeypatch.setattr("elder_berry.core.secret_store.keyring", fake)
        monkeypatch.setattr("elder_berry.core.secret_store._HAS_KEYRING", True)

        with caplog.at_level(logging.WARNING, logger="elder_berry.core.secret_store"):
            store = SecretStore(base_dir=tmp_path)
            store.set("x", "y")

        # Auto-Mode fiel sauber auf Datei zurueck
        assert (tmp_path / "secret.key").exists()
        # Die Ursache wurde als WARNING geloggt (damit ops weiss, warum
        # der Keyring nicht genutzt wurde).
        messages = " ".join(r.message for r in caplog.records)
        assert "Backend-Discovery fehlgeschlagen" in messages


class TestKeyringMigration:
    """Migration vom alten Plaintext-Key in den Keyring."""

    def test_migrates_existing_key_file(self, tmp_path, fake_keyring, caplog):
        # Alte Situation: Datei existiert bereits mit einem Key.
        old_key = Fernet.generate_key()
        (tmp_path / "secret.key").write_bytes(old_key)

        import logging

        with caplog.at_level(logging.INFO, logger="elder_berry.core.secret_store"):
            store = SecretStore(base_dir=tmp_path)
            store.set("x", "y")

        # Keyring hat den Key
        stored = fake_keyring.get_password(KEYRING_SERVICE, _username_for(tmp_path))
        assert stored == old_key.decode("ascii")
        # Alte Datei ist weg
        assert not (tmp_path / "secret.key").exists()
        # Log-Nachricht
        migration_logged = any(
            "Migriere" in r.message or "migriert" in r.message for r in caplog.records
        )
        assert migration_logged

    def test_secrets_remain_readable_after_migration(self, tmp_path, fake_keyring):
        """Wichtigster Case: Nach Migration koennen wir alte Secrets noch lesen."""
        # Secrets mit File-Modus schreiben
        file_store = SecretStore(base_dir=tmp_path, use_keyring=False)
        file_store.set("matrix_password", "geheim123")
        file_store.set("api_key", "sk-abc-xyz")
        assert (tmp_path / "secret.key").exists()

        # Neuer SecretStore mit Keyring-Modus -> sollte migrieren
        kr_store = SecretStore(base_dir=tmp_path)  # auto-mode
        # Werte sind immer noch lesbar!
        assert kr_store.get("matrix_password") == "geheim123"
        assert kr_store.get("api_key") == "sk-abc-xyz"
        # Datei wurde bei der Migration geloescht
        assert not (tmp_path / "secret.key").exists()

    def test_no_file_no_keyring_entry_creates_new(self, tmp_path, fake_keyring):
        """Gruene Wiese: weder Datei noch Keyring -> neuer Key im Keyring."""
        store = SecretStore(base_dir=tmp_path)
        store.set("x", "y")
        assert fake_keyring.get_password(KEYRING_SERVICE, _username_for(tmp_path))
        assert not (tmp_path / "secret.key").exists()

    def test_existing_keyring_entry_used_directly(self, tmp_path, fake_keyring):
        """Key ist schon im Keyring -> direkt nutzen, keine Migration."""
        existing = Fernet.generate_key()
        fake_keyring.set_password(
            KEYRING_SERVICE,
            _username_for(tmp_path),
            existing.decode("ascii"),
        )

        store = SecretStore(base_dir=tmp_path)
        store.set("x", "y")

        # Kein Neuanlegen im Keyring (Wert unveraendert)
        assert fake_keyring.get_password(
            KEYRING_SERVICE,
            _username_for(tmp_path),
        ) == existing.decode("ascii")

    def test_different_base_dirs_get_independent_keys(
        self,
        tmp_path,
        fake_keyring,
    ):
        """PR #113 Review (P1): Zwei Stores mit verschiedenen base_dirs
        duerfen sich NICHT den gleichen Keyring-Eintrag teilen.

        Szenario: Instance A migriert seine secret.key in den Keyring.
        Ohne per-base_dir-Scope wuerde Instance B (eigene secret.key +
        secrets.enc in einem anderen Verzeichnis) den Keyring-Eintrag
        von A abholen, seine eigene Migration ueberspringen und seine
        secrets.enc nicht mehr dekodieren koennen.
        """
        dir_a = tmp_path / "profile_a"
        dir_b = tmp_path / "profile_b"
        dir_a.mkdir()
        dir_b.mkdir()

        # A legt Secrets an (auto-mode -> landet im Keyring unter user_a)
        store_a = SecretStore(base_dir=dir_a)
        store_a.set("token", "value_from_a")

        # B hat einen anderen base_dir. Auto-mode -> eigener Keyring-
        # Eintrag unter user_b. B setzt dort ein anderes Secret.
        store_b = SecretStore(base_dir=dir_b)
        store_b.set("token", "value_from_b")

        # Zwei verschiedene Eintraege im Keyring, beide unabhaengig
        user_a = _username_for(dir_a)
        user_b = _username_for(dir_b)
        assert user_a != user_b
        assert fake_keyring.get_password(KEYRING_SERVICE, user_a)
        assert fake_keyring.get_password(KEYRING_SERVICE, user_b)
        # Die Keys sind tatsaechlich verschieden (verschluesseln mit
        # unterschiedlichem Fernet-Key)
        assert fake_keyring.get_password(
            KEYRING_SERVICE, user_a
        ) != fake_keyring.get_password(KEYRING_SERVICE, user_b)

        # Beide Stores koennen ihre eigenen Werte lesen
        assert SecretStore(base_dir=dir_a).get("token") == "value_from_a"
        assert SecretStore(base_dir=dir_b).get("token") == "value_from_b"

    def test_second_base_dir_does_not_skip_its_own_migration(
        self,
        tmp_path,
        fake_keyring,
    ):
        """PR #113 Review (P1): Regression der urspruenglichen Phase-65-
        Implementierung -- A migriert, B findet faelschlicherweise A's
        Keyring-Entry und ueberspringt die Migration seiner eigenen
        secret.key -> secrets.enc nicht mehr entschluesselbar.

        Mit per-base_dir-Scope sehen wir das nicht -- B muss seine
        eigene Migration durchlaufen.
        """
        dir_a = tmp_path / "A"
        dir_b = tmp_path / "B"
        dir_a.mkdir()
        dir_b.mkdir()

        # A macht seinen Store komplett (Datei + Keyring-Migration)
        SecretStore(base_dir=dir_a).set("x", "from-A")

        # B kommt aus File-Mode (hat eigene secret.key + secrets.enc)
        file_b = SecretStore(base_dir=dir_b, use_keyring=False)
        file_b.set("x", "from-B")
        assert (dir_b / "secret.key").exists()
        key_b_before = (dir_b / "secret.key").read_bytes()

        # Jetzt B mit auto-mode -- MUSS seine eigene Datei migrieren,
        # nicht A's Keyring-Entry uebernehmen.
        kr_b = SecretStore(base_dir=dir_b)
        assert kr_b.get("x") == "from-B"  # Die eigenen Secrets, nicht A's!
        assert not (dir_b / "secret.key").exists()  # Datei weg nach Migration

        # Der im Keyring fuer B gelandete Key ist der aus B's secret.key,
        # NICHT der aus A's Migration.
        user_b = _username_for(dir_b)
        assert fake_keyring.get_password(
            KEYRING_SERVICE, user_b
        ) == key_b_before.decode("ascii")

    def test_verify_mismatch_aborts_migration(self, tmp_path, fake_keyring):
        """Wenn Re-Read vom Keyring etwas anderes liefert als geschrieben,
        darf die alte Datei nicht geloescht werden."""
        # Setup: alte Datei
        old_key = Fernet.generate_key()
        (tmp_path / "secret.key").write_bytes(old_key)

        # Fake keyring: set_password speichert, aber get_password liefert
        # was anderes (Simulation eines broken Backends).
        original_get = fake_keyring.get_password

        expected_user = _username_for(tmp_path)

        def broken_get(service, username):
            # Fuer den Master-Key liefern wir einen falschen Wert zurueck.
            if (service, username) == (KEYRING_SERVICE, expected_user):
                val = original_get(service, username)
                if val is None:
                    return None
                return "GARBAGE-WRONG-VALUE"
            return original_get(service, username)

        fake_keyring.get_password = broken_get  # type: ignore[method-assign]

        store = SecretStore(base_dir=tmp_path)
        with pytest.raises(SecretStoreError, match="verifiziert"):
            store.set("x", "y")

        # Alte Datei MUSS noch da sein -- Datenverlust darf nicht passieren.
        assert (tmp_path / "secret.key").exists()
        assert (tmp_path / "secret.key").read_bytes() == old_key


class TestKeyringOpExceptionFallback:
    """Auto-Mode faellt auf Datei zurueck wenn get/set_password eine Exception wirft.

    PR #113 Review-Feedback: Nur ``get_keyring()`` war defensiv behandelt.
    ``get_password``/``set_password`` koennen aber ebenfalls raisen
    (gesperrter Keychain, fehlende Session). Im Auto-Mode muss der Store
    robust auf File-Fallback wechseln.
    """

    def test_get_password_exception_auto_falls_back_to_file(
        self,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        """get_password wirft im Auto-Mode -> Fallback auf Datei, kein Crash."""
        import logging

        fake = MagicMock()
        # get_keyring() gibt ein gueltiges (non-Fail) Backend zurueck
        fake.get_keyring.return_value = object()
        # aber get_password wirft
        fake.get_password.side_effect = RuntimeError("Keychain locked")
        monkeypatch.setattr("elder_berry.core.secret_store.keyring", fake)
        monkeypatch.setattr("elder_berry.core.secret_store._HAS_KEYRING", True)
        monkeypatch.setattr(
            "elder_berry.core.secret_store._FailKeyring",
            type("_NotFail", (), {}),
        )

        with caplog.at_level(logging.WARNING, logger="elder_berry.core.secret_store"):
            store = SecretStore(base_dir=tmp_path)  # auto-mode
            store.set("k", "v")
            assert store.get("k") == "v"

        # Fallback -> secret.key existiert
        assert (tmp_path / "secret.key").exists()
        # Warning wurde geloggt
        messages = " ".join(r.message for r in caplog.records)
        assert "Keyring-Operation fehlgeschlagen" in messages
        assert "Fallback" in messages

    def test_set_password_exception_auto_falls_back_to_file(
        self,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        """set_password wirft im Auto-Mode (neue Key-Anlage) -> Fallback auf Datei."""
        import logging

        fake = MagicMock()
        fake.get_keyring.return_value = object()
        fake.get_password.return_value = None  # kein existierender Key
        fake.set_password.side_effect = OSError("D-Bus unavailable")
        monkeypatch.setattr("elder_berry.core.secret_store.keyring", fake)
        monkeypatch.setattr("elder_berry.core.secret_store._HAS_KEYRING", True)
        monkeypatch.setattr(
            "elder_berry.core.secret_store._FailKeyring",
            type("_NotFail", (), {}),
        )

        with caplog.at_level(logging.WARNING, logger="elder_berry.core.secret_store"):
            store = SecretStore(base_dir=tmp_path)
            store.set("k", "v")

        assert (tmp_path / "secret.key").exists()
        messages = " ".join(r.message for r in caplog.records)
        assert "Keyring-Operation fehlgeschlagen" in messages

    def test_get_password_exception_strict_raises(
        self,
        tmp_path,
        monkeypatch,
    ):
        """use_keyring=True + get_password-Exception -> SecretStoreError (kein Fallback)."""
        fake = MagicMock()
        fake.get_keyring.return_value = object()
        fake.get_password.side_effect = RuntimeError("Keychain locked")
        monkeypatch.setattr("elder_berry.core.secret_store.keyring", fake)
        monkeypatch.setattr("elder_berry.core.secret_store._HAS_KEYRING", True)
        monkeypatch.setattr(
            "elder_berry.core.secret_store._FailKeyring",
            type("_NotFail", (), {}),
        )

        store = SecretStore(base_dir=tmp_path, use_keyring=True)
        with pytest.raises(SecretStoreError, match="use_keyring=True"):
            store.set("k", "v")
        # Im Strikt-Mode darf keine Datei angelegt werden
        assert not (tmp_path / "secret.key").exists()
