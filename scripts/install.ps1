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
Write-Host "[1/6] Python prüfen..." -ForegroundColor Yellow
try {
    $pyVersion = py -3.12 --version 2>&1
    Write-Host "  OK: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  FEHLER: Python 3.12+ nicht gefunden!" -ForegroundColor Red
    Write-Host "  Installiere Python von https://python.org" -ForegroundColor Red
    exit 1
}

# 2. Git prüfen
Write-Host "[2/6] Git prüfen..." -ForegroundColor Yellow
try {
    $gitVersion = git --version 2>&1
    Write-Host "  OK: $gitVersion" -ForegroundColor Green
} catch {
    Write-Host "  FEHLER: Git nicht gefunden!" -ForegroundColor Red
    Write-Host "  Installiere Git von https://git-scm.com" -ForegroundColor Red
    exit 1
}

# 3. Repository klonen
Write-Host "[3/6] Repository klonen..." -ForegroundColor Yellow
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
# Phase 53.1: --quiet entfernt, damit pip-Fehler sichtbar sind statt erst
# beim ersten Start durch fehlende Module aufzufallen. $LASTEXITCODE wird
# explizit geprüft, weil & ... bei pip-Warnings kein Exception wirft.
Write-Host "[4/6] Virtual Environment + Dependencies..." -ForegroundColor Yellow
Push-Location $InstallDir
if (-not (Test-Path ".venv")) {
    py -3.12 -m venv .venv
    Write-Host "  venv erstellt" -ForegroundColor Green
}
& .venv\Scripts\pip.exe install -e ".[windows,tts-neural,avatar,matrix,remote,memory,stt]"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  FEHLER: pip install fehlgeschlagen (Exit $LASTEXITCODE)" -ForegroundColor Red
    Write-Host "  Siehe pip-Output oben für Details." -ForegroundColor Red
    Write-Host "  Tipp: Proxy/Firewall, Disk-Space und VC++ Build-Tools prüfen." -ForegroundColor Yellow
    Pop-Location
    exit 1
}
Write-Host "  OK: Dependencies installiert" -ForegroundColor Green
Pop-Location

# 5. Post-Install-Smoke-Test
Write-Host "[5/6] Smoke-Test: elder_berry importierbar?" -ForegroundColor Yellow
Push-Location $InstallDir
& .venv\Scripts\python.exe -c "import elder_berry; print('  import OK:', elder_berry.__name__)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  FEHLER: elder_berry-Package konnte nicht importiert werden." -ForegroundColor Red
    Write-Host "  Prüfe ob 'pip install -e .' sauber durchlief." -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# 6. Ollama-Hinweis
Write-Host "[6/6] Ollama prüfen..." -ForegroundColor Yellow
try {
    $ollamaVersion = ollama --version 2>&1
    Write-Host "  OK: $ollamaVersion" -ForegroundColor Green
} catch {
    Write-Host "  Ollama nicht gefunden (optional)" -ForegroundColor Yellow
    Write-Host "  Ohne Ollama laufen LLM-Anfragen ausschließlich über die" -ForegroundColor Yellow
    Write-Host "  Anthropic Cloud-API (kostenpflichtig pro Token)." -ForegroundColor Yellow
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
