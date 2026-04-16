"""Tests: Bootstrap-Scripts – Syntax und Inhalt prüfen."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


class TestInstallSh:
    @pytest.mark.skipif(
        sys.platform == "win32" or shutil.which("bash") is None,
        reason="Bash nicht verfügbar (Windows CI ohne WSL)",
    )
    def test_syntax_valid(self):
        """Bash-Script ist syntaktisch korrekt."""
        script = _SCRIPTS_DIR / "install.sh"
        assert script.exists(), "install.sh nicht gefunden"
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax-Fehler: {result.stderr}"

    def test_checks_python(self):
        """Script prüft Python-Version."""
        content = (_SCRIPTS_DIR / "install.sh").read_text()
        assert "python3" in content.lower()

    def test_creates_venv(self):
        """Script erstellt venv."""
        content = (_SCRIPTS_DIR / "install.sh").read_text()
        assert "venv" in content

    def test_pip_install(self):
        """Script installiert Dependencies."""
        content = (_SCRIPTS_DIR / "install.sh").read_text()
        assert "pip install" in content

    def test_starts_wizard(self):
        """Script startet Setup-Wizard am Ende."""
        content = (_SCRIPTS_DIR / "install.sh").read_text()
        assert "setup_wizard" in content


class TestInstallPs1:
    def test_exists(self):
        """PowerShell-Script existiert."""
        script = _SCRIPTS_DIR / "install.ps1"
        assert script.exists(), "install.ps1 nicht gefunden"

    def test_checks_python(self):
        """Script prüft Python-Version."""
        content = (_SCRIPTS_DIR / "install.ps1").read_text()
        assert "py -3.12" in content or "python" in content.lower()

    def test_creates_venv(self):
        """Script erstellt venv."""
        content = (_SCRIPTS_DIR / "install.ps1").read_text()
        assert "venv" in content

    def test_pip_install(self):
        """Script installiert Dependencies."""
        content = (_SCRIPTS_DIR / "install.ps1").read_text()
        assert "pip" in content.lower()

    def test_starts_wizard(self):
        """Script startet Setup-Wizard am Ende."""
        content = (_SCRIPTS_DIR / "install.ps1").read_text()
        assert "setup_wizard" in content


# ---------------------------------------------------------------------------
# Phase 53.1 – Härtung (kein --quiet, Exit-Code-Checks, Smoke-Test,
# Ollama-Kostenhinweis, Step-Counter 1..6)
# ---------------------------------------------------------------------------


def _ps1_text() -> str:
    return (_SCRIPTS_DIR / "install.ps1").read_text(encoding="utf-8")


def _sh_text() -> str:
    return (_SCRIPTS_DIR / "install.sh").read_text(encoding="utf-8")


class TestPipNotQuiet:
    """--quiet darf nicht mehr am pip install-Aufruf hängen (53.1)."""

    def test_ps1_no_quiet_on_pip_line(self):
        lines = [
            line for line in _ps1_text().splitlines()
            if "pip.exe install" in line or (
                "pip " in line and "install" in line and "#" not in line[:line.find("pip")]
            )
        ]
        assert lines, "pip install-Zeile nicht gefunden"
        for line in lines:
            assert "--quiet" not in line, f"--quiet noch vorhanden: {line}"

    def test_sh_no_quiet_on_pip_line(self):
        lines = [
            line for line in _sh_text().splitlines()
            if "pip install" in line and not line.lstrip().startswith("#")
        ]
        assert lines, "pip install-Zeile nicht gefunden"
        for line in lines:
            assert "--quiet" not in line, f"--quiet noch vorhanden: {line}"


class TestExplicitErrorHandling:
    """Nach pip install wird der Fehlerpfad mit Meldung behandelt (53.1)."""

    def test_ps1_checks_lastexitcode_after_pip(self):
        text = _ps1_text()
        pip_idx = text.find("pip.exe install")
        assert pip_idx > 0
        # In den nächsten ~500 Zeichen muss $LASTEXITCODE geprüft werden
        window = text[pip_idx:pip_idx + 500]
        assert "$LASTEXITCODE" in window
        assert "pip install fehlgeschlagen" in text

    def test_sh_guards_pip_install(self):
        text = _sh_text()
        assert "if ! .venv/bin/pip install" in text
        assert "pip install fehlgeschlagen" in text


class TestPostInstallSmokeTest:
    """`python -c 'import elder_berry'` nach der Installation (53.1)."""

    def test_ps1_smoke_present(self):
        text = _ps1_text()
        assert "import elder_berry" in text
        # Fehlerpfad ist nach dem import-Aufruf vorhanden
        after = text[text.find("import elder_berry"):]
        assert "$LASTEXITCODE" in after
        assert "elder_berry-Package konnte nicht importiert werden" in after

    def test_sh_smoke_present(self):
        text = _sh_text()
        assert "import elder_berry" in text
        assert "elder_berry-Package konnte nicht importiert werden" in text


class TestOllamaHint:
    """Ollama-Warnung mit Kostenhinweis zur Cloud-API (53.1)."""

    def test_ps1_mentions_cost(self):
        assert "kostenpflichtig" in _ps1_text()

    def test_sh_mentions_cost(self):
        assert "kostenpflichtig" in _sh_text()

    def test_ps1_still_links_download(self):
        assert "ollama.com/download" in _ps1_text()

    def test_sh_still_links_download(self):
        assert "ollama.com/download" in _sh_text()


class TestStepCounterConsistent:
    """Der [n/N]-Counter in beiden Scripts läuft jetzt bis 6 (53.1)."""

    def test_ps1_has_six_steps(self):
        text = _ps1_text()
        for n in range(1, 7):
            assert f"[{n}/6]" in text, f"Schritt [{n}/6] fehlt in install.ps1"
        assert "[1/5]" not in text

    def test_sh_has_six_steps(self):
        text = _sh_text()
        for n in range(1, 7):
            assert f"[{n}/6]" in text, f"Schritt [{n}/6] fehlt in install.sh"
        assert "[1/5]" not in text
