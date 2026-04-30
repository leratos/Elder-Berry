"""Tests: SelfcheckCommandHandler – Systemgesundheitsprüfung."""

from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.selfcheck_commands import (
    SELFCHECK_PATTERN,
    SelfcheckCommandHandler,
    _get_service_detail,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def secret_store():
    store = MagicMock()
    store.list_keys.return_value = ["key1", "key2"]
    return store


@pytest.fixture
def handler(tmp_path, secret_store):
    return SelfcheckCommandHandler(
        project_root=tmp_path,
        secret_store=secret_store,
    )


@pytest.fixture
def handler_minimal():
    return SelfcheckCommandHandler(project_root=None, secret_store=None)


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------


class TestSelfcheckPattern:
    @pytest.mark.parametrize(
        "text",
        [
            "selfcheck",
            "self check",
            "system check",
            "systemcheck",
            "prüf dich",
            "prüfdich",
            "alles ok?",
            "alles ok",
            "gesundheitscheck",
        ],
    )
    def test_valid_patterns(self, text):
        assert SELFCHECK_PATTERN.match(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "selfcheck bitte",
            "mach self check",
            "status",
        ],
    )
    def test_invalid_patterns(self, text):
        assert SELFCHECK_PATTERN.match(text) is None


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class TestSelfcheckInterface:
    def test_simple_commands(self, handler):
        assert "selfcheck" in handler.simple_commands

    def test_keywords(self, handler):
        kw = handler.keywords
        assert "selfcheck" in kw
        assert len(kw["selfcheck"]) > 0

    def test_command_descriptions(self, handler):
        descs = handler.command_descriptions
        assert any("selfcheck" in d.lower() or "gesundheit" in d.lower() for d in descs)


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


class TestSelfcheckExecute:
    def test_unknown_command(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False

    @patch("urllib.request.urlopen")
    @patch("elder_berry.comms.commands.selfcheck_commands.run_cmd")
    @patch("shutil.disk_usage")
    def test_selfcheck_happy_path(self, mock_disk, mock_run_cmd, mock_urlopen, handler):
        """Selfcheck mit allen Prüfungen (Git, Disk, Ollama etc.)."""
        import json
        from elder_berry.comms.commands.cmd_utils import CmdResult

        # Git-Commands mocken
        mock_run_cmd.side_effect = [
            CmdResult(success=True, output="main"),  # branch
            CmdResult(success=True, output=""),  # status (clean)
            CmdResult(success=True, output=""),  # fetch
            CmdResult(success=True, output="0"),  # behind
            CmdResult(success=True, output="No broken"),  # pip check
        ]

        # Disk
        mock_disk.return_value = MagicMock(
            total=500 * 1024**3,
            used=200 * 1024**3,
            free=300 * 1024**3,
        )

        # Ollama – Mock urllib.request.urlopen
        ollama_resp = MagicMock()
        ollama_resp.status = 200
        ollama_resp.__enter__ = MagicMock(return_value=ollama_resp)
        ollama_resp.__exit__ = MagicMock(return_value=False)
        ollama_resp.read.return_value = json.dumps(
            {"models": [{"name": "phi4:14b"}]},
        ).encode()
        mock_urlopen.return_value = ollama_resp

        result = handler.execute("selfcheck", "selfcheck")
        assert result.success is True
        assert "Systemcheck" in result.text
        assert "Git" in result.text
        assert "Python" in result.text

    @patch("elder_berry.comms.commands.selfcheck_commands.run_cmd")
    @patch("shutil.disk_usage")
    def test_selfcheck_with_warnings(self, mock_disk, mock_run_cmd, handler):
        """Selfcheck mit uncommitted changes → Warnung."""
        from elder_berry.comms.commands.cmd_utils import CmdResult

        mock_run_cmd.side_effect = [
            CmdResult(success=True, output="main"),
            CmdResult(success=True, output="M file.py"),  # dirty
            CmdResult(success=True, output=""),
            CmdResult(success=True, output="3"),  # behind
            CmdResult(success=True, output="No broken"),
        ]

        mock_disk.return_value = MagicMock(
            total=500 * 1024**3,
            used=200 * 1024**3,
            free=300 * 1024**3,
        )

        result = handler.execute("selfcheck", "selfcheck")
        assert "Warnung" in result.text or "⚠️" in result.text

    @patch("shutil.disk_usage")
    def test_selfcheck_no_project_root(self, mock_disk, handler_minimal):
        """Selfcheck ohne project_root → Git-Warnung."""
        mock_disk.return_value = MagicMock(
            total=500 * 1024**3,
            used=200 * 1024**3,
            free=300 * 1024**3,
        )
        result = handler_minimal.execute("selfcheck", "selfcheck")
        assert "Systemcheck" in result.text
        assert "nicht konfiguriert" in result.text


# ---------------------------------------------------------------------------
# Service-Check Tests (Fähigkeiten)
# ---------------------------------------------------------------------------


class TestServiceChecks:
    """Tests für die Fähigkeiten-Prüfung (Service-Connectivity)."""

    def _make_handler(self, tmp_path, services=None):
        store = MagicMock()
        store.list_keys.return_value = []
        return SelfcheckCommandHandler(
            project_root=tmp_path,
            secret_store=store,
            services=services or {},
        )

    @patch("urllib.request.urlopen")
    @patch("elder_berry.comms.commands.selfcheck_commands.run_cmd")
    @patch("shutil.disk_usage")
    def test_services_section_appears(
        self,
        mock_disk,
        mock_run_cmd,
        mock_urlopen,
        tmp_path,
    ):
        """Wenn Services vorhanden, erscheint 'Fähigkeiten' im Output."""
        from elder_berry.comms.commands.cmd_utils import CmdResult

        mock_run_cmd.return_value = CmdResult(success=True, output="main")
        mock_disk.return_value = MagicMock(
            total=500 * 1024**3,
            used=200 * 1024**3,
            free=300 * 1024**3,
        )
        mock_urlopen.side_effect = Exception("no ollama")

        svc = MagicMock()
        svc.is_available.return_value = True
        handler = self._make_handler(tmp_path, {"weather": svc})

        result = handler.execute("selfcheck", "selfcheck")
        assert "Fähigkeiten" in result.text
        assert "Wetter" in result.text

    def test_service_available(self, tmp_path):
        """Service mit is_available() == True → ✅."""
        svc = MagicMock()
        svc.is_available.return_value = True
        handler = self._make_handler(tmp_path, {"weather": svc})

        ok, _ = handler._probe_service("weather", svc)
        assert ok is True

    def test_service_unavailable(self, tmp_path):
        """Service mit is_available() == False → ❌."""
        svc = MagicMock()
        svc.is_available.return_value = False
        handler = self._make_handler(tmp_path, {"weather": svc})

        ok, detail = handler._probe_service("weather", svc)
        assert ok is False
        assert "nicht erreichbar" in detail

    def test_service_is_online(self, tmp_path):
        """Service mit is_online() == True → ✅."""
        svc = MagicMock(spec=[])  # no is_available
        svc.is_online = MagicMock(return_value=True)
        svc._base_url = "http://rpi5:8000"

        ok, _ = SelfcheckCommandHandler._probe_service("robot_client", svc)
        assert ok is True

    def test_service_is_online_false(self, tmp_path):
        """Service mit is_online() == False → ❌."""
        svc = MagicMock(spec=[])
        svc.is_online = MagicMock(return_value=False)

        ok, detail = SelfcheckCommandHandler._probe_service("robot_client", svc)
        assert ok is False

    def test_service_db_store_exists(self, tmp_path):
        """Store mit existierender _db_path → ✅."""
        db_file = tmp_path / "notes.db"
        db_file.touch()
        svc = MagicMock(spec=[])  # no is_available, no is_online
        svc._db_path = db_file

        ok, detail = SelfcheckCommandHandler._probe_service("note_store", svc)
        assert ok is True
        assert "notes.db" in detail

    def test_service_db_store_missing(self, tmp_path):
        """Store mit fehlender _db_path → ❌."""
        svc = MagicMock(spec=[])
        svc._db_path = tmp_path / "missing.db"

        ok, detail = SelfcheckCommandHandler._probe_service("note_store", svc)
        assert ok is False
        assert "nicht gefunden" in detail

    def test_service_exception(self, tmp_path):
        """Service der Exception wirft → ❌ mit Fehlermeldung."""
        svc = MagicMock()
        svc.is_available.side_effect = ConnectionError("timeout")

        ok, detail = SelfcheckCommandHandler._probe_service("weather", svc)
        assert ok is False
        assert "timeout" in detail

    def test_service_no_probe_method(self, tmp_path):
        """Service ohne is_available/is_online/_db_path → OK (vorhanden = gut)."""
        svc = MagicMock(spec=[])  # no relevant methods

        ok, _ = SelfcheckCommandHandler._probe_service("audio_router", svc)
        assert ok is True

    def test_not_configured_shows_dash(self, tmp_path):
        """Nicht übergebener Service → ➖ nicht konfiguriert."""
        handler = self._make_handler(tmp_path, {"weather": None})
        # weather=None wird beim dict-Aufbau rausgefiltert? Nein, None ist erlaubt.
        # Tatsächlich: im _check_services wird svc is None → ➖
        checks: list[str] = []
        handler._services["weather"] = None
        handler._check_services(checks)
        text = "\n".join(checks)
        assert "➖" in text
        assert "nicht konfiguriert" in text

    def test_register_service(self, tmp_path):
        """register_service() fügt Services nachträglich hinzu."""
        handler = self._make_handler(tmp_path, {})
        assert "tts" not in handler._services

        svc = MagicMock()
        handler.register_service("tts", svc)
        assert handler._services["tts"] is svc

    def test_register_service_none_ignored(self, tmp_path):
        """register_service(key, None) ignoriert den Aufruf."""
        handler = self._make_handler(tmp_path, {})
        handler.register_service("tts", None)
        assert "tts" not in handler._services

    @patch("urllib.request.urlopen")
    @patch("elder_berry.comms.commands.selfcheck_commands.run_cmd")
    @patch("shutil.disk_usage")
    def test_full_selfcheck_with_mixed_services(
        self,
        mock_disk,
        mock_run_cmd,
        mock_urlopen,
        tmp_path,
    ):
        """Voller Selfcheck mit Mix aus verfügbaren und kaputten Services."""
        from elder_berry.comms.commands.cmd_utils import CmdResult

        mock_run_cmd.return_value = CmdResult(success=True, output="main")
        mock_disk.return_value = MagicMock(
            total=500 * 1024**3,
            used=200 * 1024**3,
            free=300 * 1024**3,
        )
        mock_urlopen.side_effect = Exception("no ollama")

        # Zwei Services: einer OK, einer kaputt
        ok_svc = MagicMock()
        ok_svc.is_available.return_value = True

        bad_svc = MagicMock()
        bad_svc.is_available.return_value = False

        handler = self._make_handler(
            tmp_path,
            {
                "calendar": ok_svc,
                "email_client": bad_svc,
            },
        )

        result = handler.execute("selfcheck", "selfcheck")
        assert "Kalender" in result.text
        assert "IMAP" in result.text
        assert "✅" in result.text  # calendar OK
        assert "❌" in result.text  # email broken + ollama

    @patch("urllib.request.urlopen")
    @patch("elder_berry.comms.commands.selfcheck_commands.run_cmd")
    @patch("shutil.disk_usage")
    def test_service_errors_count(
        self,
        mock_disk,
        mock_run_cmd,
        mock_urlopen,
        tmp_path,
    ):
        """Kaputte Services erhöhen den Error-Count im Header."""
        from elder_berry.comms.commands.cmd_utils import CmdResult

        mock_run_cmd.return_value = CmdResult(success=True, output="main")
        mock_disk.return_value = MagicMock(
            total=500 * 1024**3,
            used=200 * 1024**3,
            free=300 * 1024**3,
        )
        # Ollama OK
        import json

        ollama_resp = MagicMock()
        ollama_resp.__enter__ = MagicMock(return_value=ollama_resp)
        ollama_resp.__exit__ = MagicMock(return_value=False)
        ollama_resp.read.return_value = json.dumps(
            {"models": [{"name": "test"}]},
        ).encode()
        mock_urlopen.return_value = ollama_resp

        bad_svc = MagicMock()
        bad_svc.is_available.return_value = False

        handler = self._make_handler(tmp_path, {"email_client": bad_svc})
        result = handler.execute("selfcheck", "selfcheck")
        # Should show error count in header
        assert "Fehler" in result.text
        assert result.success is False


# ---------------------------------------------------------------------------
# _get_service_detail Tests
# ---------------------------------------------------------------------------


class TestGetServiceDetail:
    def test_calendar_caldav(self):
        svc = MagicMock()
        type(svc).__name__ = "CalDAVCalendarClient"
        assert "CalDAV" in _get_service_detail("calendar", svc)

    def test_calendar_google(self):
        svc = MagicMock()
        type(svc).__name__ = "GoogleCalendarClient"
        assert "Google" in _get_service_detail("calendar", svc)

    def test_email_host(self):
        svc = MagicMock()
        svc._host = "imap.example.com"
        assert _get_service_detail("email_client", svc) == "imap.example.com"

    def test_tts_engine_name(self):
        svc = MagicMock()
        type(svc).__name__ = "CoquiTTSEngine"
        assert "CoquiTTSEngine" in _get_service_detail("tts", svc)

    def test_unknown_key(self):
        svc = MagicMock()
        assert _get_service_detail("something_new", svc) == ""


# ---------------------------------------------------------------------------
# TowerAgent im Selfcheck
# ---------------------------------------------------------------------------


class TestTowerAgentSelfcheck:
    def test_tower_agent_online(self):
        """TowerAgent online → synchroner HTTP-Check, ✅ im Check."""
        import httpx as _httpx
        from elder_berry.comms.commands.selfcheck_commands import (
            SelfcheckCommandHandler,
        )

        tower = MagicMock(spec=[])  # spec=[] verhindert auto-Attribute
        tower.host = "127.0.0.1:12769"

        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch.object(_httpx, "get", return_value=mock_response):
            ok, detail = SelfcheckCommandHandler._probe_service("tower_agent", tower)
        assert ok is True
        assert "127.0.0.1:12769" in detail

    def test_tower_agent_offline(self):
        """TowerAgent offline → ⚠️ im Check (optional)."""
        import httpx as _httpx
        from elder_berry.comms.commands.selfcheck_commands import (
            SelfcheckCommandHandler,
        )

        tower = MagicMock(spec=[])
        tower.host = "127.0.0.1:12769"

        with patch.object(_httpx, "get", side_effect=Exception("Connection refused")):
            ok, detail = SelfcheckCommandHandler._probe_service("tower_agent", tower)
        assert ok is False

    def test_tower_agent_in_check_order(self):
        """TowerAgent erscheint im Selfcheck-Output."""
        from elder_berry.comms.commands.selfcheck_commands import (
            SelfcheckCommandHandler,
        )

        handler = SelfcheckCommandHandler(services={"tower_agent": None})
        checks = []
        handler._check_services(checks)
        tower_line = [c for c in checks if "Tower" in c]
        assert len(tower_line) == 1
        assert "➖" in tower_line[0]  # nicht konfiguriert

    def test_is_online_property_handled(self):
        """is_online als Property (nicht Methode) wird korrekt behandelt."""
        from elder_berry.comms.commands.selfcheck_commands import (
            SelfcheckCommandHandler,
        )

        # Simuliere ein Objekt mit is_online als Property (nicht callable)
        class FakeService:
            is_online = True

        svc = FakeService()
        ok, _ = SelfcheckCommandHandler._probe_service("some_service", svc)
        assert ok is True
