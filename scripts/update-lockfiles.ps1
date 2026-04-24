# Phase 65 (M-3): Regeneriert die Dependency-Lockfiles via pip-compile.
#
# Drei Lockfiles:
#   requirements-tower.lock  -- Core + windows + tower   (MUSS auf Windows generiert werden, wegen pyautogui/pycaw)
#   requirements-dev.lock    -- Core + robot + agent + dev (cross-platform; fuer CI+Devs)
#   requirements-rpi5.lock   -- Core + robot + agent + matrix + memory + nextcloud + harmony (MUSS auf Linux/RPi5 generiert werden)
#
# Aufruf:
#   powershell -ExecutionPolicy Bypass -File scripts/update-lockfiles.ps1
#
# RPi5-Lockfile muss separat auf dem RPi5 generiert werden:
#   bash scripts/update-lockfiles.sh rpi5

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Compile-Lockfile {
    param(
        [string] $OutputFile,
        [string[]] $Extras,
        [string] $Description
    )
    Write-Host ""
    Write-Host "=== $Description ===" -ForegroundColor Cyan
    Write-Host "Output: $OutputFile"
    Write-Host "Extras: $($Extras -join ', ')"

    $extrasArg = ($Extras | ForEach-Object { "--extra=$_" }) -join " "
    $cmd = "python -m piptools compile pyproject.toml $extrasArg --output-file=$OutputFile --resolver=backtracking --strip-extras --quiet"
    Write-Host "> $cmd"
    Invoke-Expression $cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip-compile fehlgeschlagen fuer $OutputFile"
        exit $LASTEXITCODE
    }
    Write-Host "OK: $OutputFile" -ForegroundColor Green
}

Compile-Lockfile `
    -OutputFile "requirements-tower.lock" `
    -Extras @("windows", "tower") `
    -Description "Tower-Lockfile (Windows, voller Stack)"

Compile-Lockfile `
    -OutputFile "requirements-dev.lock" `
    -Extras @("robot", "agent", "dev") `
    -Description "Dev/CI-Lockfile (cross-platform Core)"

Write-Host ""
Write-Host "Fertig. RPi5-Lockfile bitte auf dem RPi5 selbst generieren:" -ForegroundColor Yellow
Write-Host "  bash scripts/update-lockfiles.sh rpi5"
