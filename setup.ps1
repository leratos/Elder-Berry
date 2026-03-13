# Elder-Berry – Tower PC Setup (Windows, PowerShell)
# Aufruf: .\setup.ps1
# Voraussetzung: Python 3.12 installiert, Ollama installiert

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "`n=== Elder-Berry Setup ===" -ForegroundColor Cyan

# --- Python 3.12 pruefen ---
$python = $null
foreach ($cmd in @("py -3.12", "python3.12", "python")) {
    try {
        $ver = & ($cmd.Split()[0]) ($cmd.Split()[1..99] + @("--version")) 2>&1
        if ($ver -match "3\.12") { $python = $cmd; break }
    } catch {}
}
if (-not $python) {
    Write-Host "[FEHLER] Python 3.12 nicht gefunden. Bitte installieren: https://python.org" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python: $python" -ForegroundColor Green

# --- .venv erstellen falls nicht vorhanden ---
$venvPath = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "[...] Erstelle .venv ..." -ForegroundColor Yellow
    & ($python.Split()[0]) ($python.Split()[1..99] + @("-m", "venv", $venvPath))
    Write-Host "[OK] .venv erstellt" -ForegroundColor Green
} else {
    Write-Host "[OK] .venv vorhanden" -ForegroundColor Green
}

# --- pip & Paket installieren ---
$pip = Join-Path $venvPath "Scripts\pip.exe"
Write-Host "[...] Installiere Abhaengigkeiten ..." -ForegroundColor Yellow
& $pip install -q -e $ProjectRoot
Write-Host "[OK] Pakete installiert" -ForegroundColor Green

# --- .env anlegen falls nicht vorhanden ---
$envFile    = Join-Path $ProjectRoot ".env"
$envExample = Join-Path $ProjectRoot ".env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "[OK] .env aus .env.example erstellt – bitte OPENROUTER_API_KEY eintragen!" -ForegroundColor Yellow
} else {
    Write-Host "[OK] .env vorhanden" -ForegroundColor Green
}

# --- Ollama pruefen ---
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "[OK] Ollama gefunden" -ForegroundColor Green
    Write-Host "     Stelle sicher dass Ollama laeuft: ollama serve" -ForegroundColor DarkGray
    Write-Host "     Empfohlenes Modell laden:         ollama pull llama3.1:14b" -ForegroundColor DarkGray
} else {
    Write-Host "[WARN] Ollama nicht im PATH. Installieren: https://ollama.com" -ForegroundColor Yellow
}

# --- Tests ausfuehren ---
$pytest = Join-Path $venvPath "Scripts\pytest.exe"
Write-Host "`n[...] Fuehre Tests aus ..." -ForegroundColor Yellow
& $pytest (Join-Path $ProjectRoot "tests") -v --tb=short
if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[OK] Alle Tests bestanden – Setup abgeschlossen!" -ForegroundColor Green
} else {
    Write-Host "`n[WARN] Einige Tests schlugen fehl. Bitte Ausgabe pruefen." -ForegroundColor Yellow
}

Write-Host @"

Naechste Schritte:
  1. .env oeffnen und OPENROUTER_API_KEY eintragen (falls noch nicht)
  2. Ollama starten:    ollama serve
  3. Modell laden:      ollama pull llama3.1:14b
  4. Venv aktivieren:  .\.venv\Scripts\Activate.ps1
"@ -ForegroundColor Cyan
