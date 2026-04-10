# Elder-Berry – Windows Bootstrap-Script
# Verwendung: powershell -ExecutionPolicy Bypass -File install.ps1
#
# Voraussetzungen:
#   - Python 3.12+ installiert (py Launcher)
#   - Git installiert
#   - Internet-Verbindung

param(
    [string]$InstallDir = "C:\Dev\Elder-Berry",
    [string]$RepoUrl = "https://github.com/Leratos/Elder-Berry.git"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host ("=" * 50) -ForegroundColor Cyan
Write-Host "  Elder-Berry – Installation" -ForegroundColor Cyan
Write-Host ("=" * 50) -ForegroundColor Cyan
Write-Host ""

# 1. Python prüfen
Write-Host "[1/5] Python prüfen..." -ForegroundColor Yellow
try {
    $pyVersion = py -3.12 --version 2>&1
    Write-Host "  OK: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  FEHLER: Python 3.12+ nicht gefunden!" -ForegroundColor Red
    Write-Host "  Installiere Python von https://python.org" -ForegroundColor Red
    exit 1
}

# 2. Git prüfen
Write-Host "[2/5] Git prüfen..." -ForegroundColor Yellow
try {
    $gitVersion = git --version 2>&1
    Write-Host "  OK: $gitVersion" -ForegroundColor Green
} catch {
    Write-Host "  FEHLER: Git nicht gefunden!" -ForegroundColor Red
    Write-Host "  Installiere Git von https://git-scm.com" -ForegroundColor Red
    exit 1
}

# 3. Repository klonen
Write-Host "[3/5] Repository klonen..." -ForegroundColor Yellow
if (Test-Path "$InstallDir\.git") {
    Write-Host "  Repository existiert bereits – git pull" -ForegroundColor Yellow
    Push-Location $InstallDir
    git pull --ff-only
    Pop-Location
} else {
    git clone $RepoUrl $InstallDir
}
Write-Host "  OK: $InstallDir" -ForegroundColor Green

# 4. Python venv erstellen + Dependencies
Write-Host "[4/5] Virtual Environment + Dependencies..." -ForegroundColor Yellow
Push-Location $InstallDir
if (-not (Test-Path ".venv")) {
    py -3.12 -m venv .venv
    Write-Host "  venv erstellt" -ForegroundColor Green
}
& .venv\Scripts\pip.exe install -e ".[windows,tts-neural,avatar,matrix,remote,memory,stt]" --quiet
Write-Host "  OK: Dependencies installiert" -ForegroundColor Green
Pop-Location

# 5. Ollama-Hinweis
Write-Host "[5/5] Ollama prüfen..." -ForegroundColor Yellow
try {
    $ollamaVersion = ollama --version 2>&1
    Write-Host "  OK: $ollamaVersion" -ForegroundColor Green
} catch {
    Write-Host "  Ollama nicht gefunden (optional)" -ForegroundColor Yellow
    Write-Host "  Für Offline-LLM: https://ollama.com/download" -ForegroundColor Yellow
}

# Fertig – Setup-Wizard starten
Write-Host ""
Write-Host ("=" * 50) -ForegroundColor Green
Write-Host "  Installation abgeschlossen!" -ForegroundColor Green
Write-Host ("=" * 50) -ForegroundColor Green
Write-Host ""
Write-Host "Starte Setup-Wizard..." -ForegroundColor Cyan
Push-Location $InstallDir
& .venv\Scripts\python.exe scripts/setup_wizard.py
Pop-Location
