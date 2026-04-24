"""Tests für user_friendly_error() und not_configured() aus base.py."""


from elder_berry.comms.commands.base import (
    SETUP_STEPS,
    CommandHandler,
    CommandResult,
    user_friendly_error,
)


# -- user_friendly_error --------------------------------------------------

class TestUserFriendlyError:
    """Tests für die Exception → Nutzertext-Konvertierung."""

    # --- Netzwerk ---

    def test_connection_refused(self):
        exc = ConnectionRefusedError("[Errno 111] Connection refused")
        msg = user_friendly_error(exc, "E-Mail")
        assert "nicht erreichbar" in msg
        assert "E-Mail" in msg
        assert "❌" in msg

    def test_connection_error(self):
        exc = ConnectionError("host unreachable")
        msg = user_friendly_error(exc)
        assert "nicht erreichbar" in msg

    def test_timeout_error(self):
        exc = TimeoutError("read timed out")
        msg = user_friendly_error(exc, "Kalender")
        assert "Zeitüberschreitung" in msg
        assert "Kalender" in msg

    def test_httpx_connect_error(self):
        """httpx.ConnectError hat ConnectError im Typnamen."""

        class ConnectError(Exception):
            pass

        exc = ConnectError("connection failed")
        msg = user_friendly_error(exc)
        assert "Verbindung fehlgeschlagen" in msg

    # --- Auth / API ---

    def test_401_unauthorized(self):
        exc = Exception("HTTP 401 Unauthorized")
        msg = user_friendly_error(exc, "Anthropic")
        assert "Zugangsdaten" in msg
        assert "setup" in msg

    def test_403_forbidden(self):
        exc = Exception("403 Forbidden")
        msg = user_friendly_error(exc)
        assert "Zugriff verweigert" in msg

    def test_404_not_found(self):
        exc = Exception("404 Not Found")
        msg = user_friendly_error(exc)
        assert "Nicht gefunden" in msg

    def test_429_rate_limit(self):
        exc = Exception("429 Too Many Requests")
        msg = user_friendly_error(exc)
        assert "viele Anfragen" in msg

    def test_rate_limit_exception_type(self):

        class RateLimitError(Exception):
            pass

        exc = RateLimitError("slow down")
        msg = user_friendly_error(exc)
        assert "viele Anfragen" in msg

    def test_500_server_error(self):
        exc = Exception("500 Internal Server Error")
        msg = user_friendly_error(exc)
        assert "Serverfehler" in msg

    def test_502_bad_gateway(self):
        exc = Exception("502 Bad Gateway")
        msg = user_friendly_error(exc)
        assert "Serverfehler" in msg

    # --- Dateisystem ---

    def test_file_not_found(self):
        exc = FileNotFoundError("report.pdf")
        msg = user_friendly_error(exc, "Dokument")
        assert "nicht gefunden" in msg
        assert "Dokument" in msg

    def test_permission_error(self):
        exc = PermissionError("access denied")
        msg = user_friendly_error(exc)
        assert "Berechtigung" in msg

    # --- Daten ---

    def test_value_error(self):
        exc = ValueError("invalid date format")
        msg = user_friendly_error(exc)
        assert "Ungültige Daten" in msg

    def test_key_error(self):
        exc = KeyError("missing_field")
        msg = user_friendly_error(exc)
        assert "Ungültige Daten" in msg

    # --- Fallback ---

    def test_generic_exception_short(self):
        exc = RuntimeError("something broke")
        msg = user_friendly_error(exc)
        assert "Fehler: something broke" in msg
        assert "❌" in msg

    def test_generic_exception_long_truncated(self):
        long_msg = "x" * 200
        exc = RuntimeError(long_msg)
        msg = user_friendly_error(exc)
        assert len(msg) < 200
        assert "..." in msg

    def test_no_context(self):
        exc = TimeoutError("timeout")
        msg = user_friendly_error(exc)
        assert not msg.startswith("❌ : ")  # kein leerer Prefix

    def test_with_context(self):
        exc = TimeoutError("timeout")
        msg = user_friendly_error(exc, "Wetter")
        assert msg.startswith("❌ Wetter: ")


# -- not_configured --------------------------------------------------------

class _DummyHandler(CommandHandler):
    """Minimaler Handler zum Testen von not_configured()."""

    def execute(self, command: str, raw_text: str) -> CommandResult:
        return CommandResult(command=command, success=True)


class TestNotConfigured:
    """Tests für CommandHandler.not_configured()."""

    def test_basic(self):
        result = _DummyHandler.not_configured("mails", "E-Mail")
        assert not result.success
        assert "E-Mail" in result.text
        assert "nicht konfiguriert" in result.text
        assert "⚠" in result.text
        assert "setup" in result.text.lower()

    def test_with_step(self):
        result = _DummyHandler.not_configured("mails", "E-Mail", setup_step=5)
        assert "Schritt 5" in result.text

    def test_without_step(self):
        result = _DummyHandler.not_configured("cloud_upload", "Nextcloud")
        assert "Schritt" not in result.text
        assert "Nextcloud" in result.text

    def test_command_preserved(self):
        result = _DummyHandler.not_configured("termine", "Kalender", setup_step=4)
        assert result.command == "termine"


# -- SETUP_STEPS -----------------------------------------------------------

class TestSetupSteps:
    """Grundlegende Prüfungen des Step-Mappings."""

    def test_all_values_are_ints(self):
        for key, step in SETUP_STEPS.items():
            assert isinstance(step, int), f"{key} hat keinen int-Wert"

    def test_known_services(self):
        assert SETUP_STEPS["email"] == 5
        assert SETUP_STEPS["nextcloud"] == 4
        assert SETUP_STEPS["anthropic"] == 2
        assert SETUP_STEPS["matrix"] == 3

    def test_steps_in_valid_range(self):
        for key, step in SETUP_STEPS.items():
            assert 1 <= step <= 8, f"{key}: Schritt {step} außerhalb 1-8"
