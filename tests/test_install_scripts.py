"""Tests: Bootstrap-Scripts – Syntax und Inhalt prüfen."""
import subprocess
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


class TestInstallSh:
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
