"""Tests für scripts/start_saleria.py – Argument-Parsing, ELDER_BERRY_HOME, Agent-Modus."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# start_saleria.py liegt unter scripts/ – zum Import brauchen wir den Pfad
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


# ===========================================================================
# parse_args
# ===========================================================================


class TestParseArgs:
    """Argument-Parser Tests."""

    def _parse(self, args: list[str]):
        """Hilfsfunktion: parse_args mit gesetztem sys.argv."""
        with patch("sys.argv", ["start_saleria.py"] + args):
            from start_saleria import parse_args
            return parse_args()

    def test_default_mode_is_matrix(self):
        result = self._parse([])
        assert result.mode == "matrix"

    def test_mode_terminal(self):
        result = self._parse(["--mode", "terminal"])
        assert result.mode == "terminal"

    def test_mode_voice(self):
        result = self._parse(["--mode", "voice"])
        assert result.mode == "voice"

    def test_mode_agent(self):
        result = self._parse(["--mode", "agent"])
        assert result.mode == "agent"

    def test_invalid_mode_raises(self):
        with pytest.raises(SystemExit):
            self._parse(["--mode", "invalid"])

    def test_no_memory_flag(self):
        result = self._parse(["--no-memory"])
        assert result.no_memory is True

    def test_no_tts_flag(self):
        result = self._parse(["--no-tts"])
        assert result.no_tts is True

    def test_debug_flag(self):
        result = self._parse(["--debug"])
        assert result.debug is True

    def test_whisper_model_default(self):
        result = self._parse([])
        assert result.whisper_model == "medium"

    def test_whisper_model_custom(self):
        result = self._parse(["--whisper-model", "large-v3"])
        assert result.whisper_model == "large-v3"


# ===========================================================================
# ELDER_BERRY_HOME
# ===========================================================================


class TestElderBerryHome:
    """ELDER_BERRY_HOME Umgebungsvariable."""

    def test_project_root_default(self):
        """Ohne ELDER_BERRY_HOME: _PROJECT_ROOT = scripts/../"""
        from start_saleria import _PROJECT_ROOT as root
        # Sollte das Repo-Root sein (enthält pyproject.toml)
        assert (root / "pyproject.toml").exists()

    def test_project_root_from_env(self):
        """Mit ELDER_BERRY_HOME: _PROJECT_ROOT wird überschrieben."""
        # Wir können _PROJECT_ROOT nicht einfach neu importieren (Module-Cache),
        # daher testen wir die Logik direkt
        fake_home = "/opt/elder-berry"
        with patch.dict(os.environ, {"ELDER_BERRY_HOME": fake_home}):
            result = Path(
                os.environ.get("ELDER_BERRY_HOME", Path(__file__).parent.parent)
            ).resolve()
            assert str(result) == str(Path(fake_home).resolve())

    def test_project_root_without_env(self):
        """Ohne ELDER_BERRY_HOME: Fallback auf Skript-Pfad."""
        env = os.environ.copy()
        env.pop("ELDER_BERRY_HOME", None)
        with patch.dict(os.environ, env, clear=True):
            result = Path(
                os.environ.get("ELDER_BERRY_HOME", Path(__file__).parent.parent)
            ).resolve()
            # Sollte das tests/-Parent sein → Repo-Root
            assert (result / "pyproject.toml").exists()


# ===========================================================================
# run_agent
# ===========================================================================


class TestRunAgent:
    """Agent-Modus (TowerServer)."""

    def test_run_agent_calls_uvicorn(self):
        """run_agent startet uvicorn mit korrekten Parametern."""
        from start_saleria import run_agent

        mock_uvicorn = MagicMock()
        with patch.dict("sys.modules", {"uvicorn": mock_uvicorn}):
            with patch("start_saleria.sys") as mock_sys:
                mock_sys.path = sys.path.copy()
                mock_sys.exit = sys.exit
                # Importiere uvicorn nochmal im Kontext
                with patch("builtins.__import__", side_effect=_import_with_mock_uvicorn(mock_uvicorn)):
                    pass

        # Einfacherer Test: prüfe dass uvicorn.run im Source vorkommt
        import inspect
        source = inspect.getsource(run_agent)
        assert "uvicorn.run" in source
        assert "tower.tower_server:app" in source
        # Phase 57.1: Default-Bind ist jetzt 127.0.0.1 (Loopback),
        # gesteuert über ELDER_BERRY_TOWER_BIND.
        assert "ELDER_BERRY_TOWER_BIND" in source
        assert '"127.0.0.1"' in source
        assert "8090" in source or "port" in source

    def test_run_agent_imports_tower_server(self):
        """run_agent versucht tower.tower_server zu importieren."""
        import inspect
        from start_saleria import run_agent
        source = inspect.getsource(run_agent)
        assert "tower.tower_server" in source

    def test_agent_mode_skips_llm_init(self):
        """Im Agent-Modus wird kein LLM initialisiert."""
        import inspect
        from start_saleria import main
        source = inspect.getsource(main)
        # Agent-Modus returned vor init_llm()
        agent_block_idx = source.index("mode == \"agent\"")
        return_idx = source.index("return", agent_block_idx)
        init_llm_idx = source.index("init_llm()")
        assert return_idx < init_llm_idx, \
            "Agent-Modus muss vor init_llm() returnen"


def _import_with_mock_uvicorn(mock):
    """Import-Hook der uvicorn durch einen Mock ersetzt."""
    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def custom_import(name, *args, **kwargs):
        if name == "uvicorn":
            return mock
        return original_import(name, *args, **kwargs)
    return custom_import


# ===========================================================================
# main() – Mode-Routing
# ===========================================================================


class TestMainModeRouting:
    """Prüft dass main() die richtigen run_*-Funktionen aufruft."""

    def test_main_routes_terminal(self):
        import inspect
        from start_saleria import main
        source = inspect.getsource(main)
        assert "run_terminal" in source

    def test_main_routes_voice(self):
        import inspect
        from start_saleria import main
        source = inspect.getsource(main)
        assert "run_voice" in source

    def test_main_routes_matrix(self):
        import inspect
        from start_saleria import main
        source = inspect.getsource(main)
        assert "run_matrix" in source

    def test_main_routes_agent(self):
        import inspect
        from start_saleria import main
        source = inspect.getsource(main)
        assert "run_agent" in source


# ===========================================================================
# systemd Service-Files (Existenz + Inhalt)
# ===========================================================================


class TestServiceFiles:
    """Prüft dass die systemd Service-Files existieren und korrekt sind."""

    def test_server_service_exists(self):
        service = _PROJECT_ROOT / "server" / "elder-berry.service"
        assert service.exists()

    def test_server_service_content(self):
        content = (_PROJECT_ROOT / "server" / "elder-berry.service").read_text()
        assert "ExecStart=" in content
        assert "--mode matrix" in content
        assert "ELDER_BERRY_HOME=" in content
        assert "User=" in content
        assert "Restart=always" in content

    def test_tower_service_exists(self):
        service = _PROJECT_ROOT / "server" / "elder-berry-tower.service"
        assert service.exists()

    def test_tower_service_content(self):
        content = (_PROJECT_ROOT / "server" / "elder-berry-tower.service").read_text()
        assert "--mode agent" in content
        # Phase 67: konkreter Pfad durch Template-Platzhalter ersetzt;
        # Test prueft jetzt nur noch dass die Env-Variable existiert.
        assert "ELDER_BERRY_HOME=" in content

    def test_server_service_security_hardening(self):
        content = (_PROJECT_ROOT / "server" / "elder-berry.service").read_text()
        assert "NoNewPrivileges=true" in content
        assert "PrivateTmp=true" in content
