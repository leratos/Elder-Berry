#!/usr/bin/env bash
# Elder-Berry – Linux Bootstrap-Script (RPi5 / Ubuntu)
# Verwendung: bash install.sh
#
# Voraussetzungen:
#   - Python 3.12+ oder 3.13 (System-Python auf Bookworm)
#   - Git installiert
#   - Internet-Verbindung

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/elder-berry}"
REPO_URL="${REPO_URL:-https://github.com/Leratos/Elder-Berry.git}"

echo ""
echo "=================================================="
echo "  Elder-Berry – Installation"
echo "=================================================="
echo ""

# 1. Python prüfen
echo "[1/5] Python prüfen..."
PYTHON=""
for cmd in python3.13 python3.12 python3; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1)
        echo "  OK: $version"
        PYTHON="$cmd"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "  FEHLER: Python 3.12+ nicht gefunden!"
    exit 1
fi

# 2. Git prüfen
echo "[2/5] Git prüfen..."
if command -v git &>/dev/null; then
    echo "  OK: $(git --version)"
else
    echo "  FEHLER: Git nicht gefunden!"
    echo "  sudo apt install git"
    exit 1
fi

# 3. Repository klonen
echo "[3/5] Repository klonen..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  Repository existiert bereits – git pull"
    cd "$INSTALL_DIR"
    git pull --ff-only
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
echo "  OK: $INSTALL_DIR"

# 4. Python venv erstellen + Dependencies
echo "[4/5] Virtual Environment + Dependencies..."
cd "$INSTALL_DIR"
if [ ! -d ".venv" ]; then
    "$PYTHON" -m venv .venv
    echo "  venv erstellt"
fi
.venv/bin/pip install -e ".[matrix,remote,memory,stt]" --quiet
echo "  OK: Dependencies installiert"

# 5. Ollama-Hinweis
echo "[5/5] Ollama prüfen..."
if command -v ollama &>/dev/null; then
    echo "  OK: $(ollama --version 2>&1)"
else
    echo "  Ollama nicht gefunden (optional)"
    echo "  Für Offline-LLM: https://ollama.com/download"
fi

# Fertig
echo ""
echo "=================================================="
echo "  Installation abgeschlossen!"
echo "=================================================="
echo ""
echo "Starte Setup-Wizard..."
cd "$INSTALL_DIR"
.venv/bin/python scripts/setup_wizard.py
