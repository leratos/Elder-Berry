#Requires -Version 5.1
<#
.SYNOPSIS
    Resilient SSH reverse tunnel with auto-reconnect.

.DESCRIPTION
    Keeps an SSH reverse tunnel alive that exposes a local service on a
    remote server. Automatically reconnects on network drops or SSH failures.

.NOTES
    1. Copy this file to ssh-tunnel.ps1
    2. Fill in your values in the Config section below
    3. Install as Scheduled Task:
       powershell -ExecutionPolicy Bypass -File scripts\Install-SshTunnelTask.ps1
#>

# ── Config (ANPASSEN!) ─────────────────────────────────────────────────────
$RemoteUser       = "your-user"          # SSH-User auf dem Server
$RemoteHost       = "your-server.com"    # Server-Hostname oder IP
$RemotePort       = 12345                # Port auf dem Server (Remote-Seite)
$LocalPort        = 8080                 # Lokaler Port der weitergeleitet wird
$SshAliveInterval = 15                   # Keepalive-Interval in Sekunden
$SshAliveCountMax = 3                    # Max fehlgeschlagene Keepalives
$RetryDelaySec    = 5                    # Initiale Wartezeit bei Reconnect
$MaxRetryDelay    = 120                  # Maximale Wartezeit (Backoff-Cap)
$LogFile          = "$PSScriptRoot\..\logs\ssh-tunnel.log"

# ── Functions ───────────────────────────────────────────────────────────────

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts [$Level] $Message"
    Write-Host $line
    $dir = Split-Path $LogFile -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Test-SshAvailable {
    $cmd = Get-Command ssh -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Write-Log "ssh.exe not found in PATH. Install OpenSSH or add it to PATH." "FATAL"
        exit 1
    }
}

function Start-Tunnel {
    $sshArgs = @(
        "-N",
        "-R", "127.0.0.1:${RemotePort}:127.0.0.1:${LocalPort}",
        "-o", "ServerAliveInterval=$SshAliveInterval",
        "-o", "ServerAliveCountMax=$SshAliveCountMax",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=10",
        "-o", "BatchMode=yes",
        "${RemoteUser}@${RemoteHost}"
    )
    Write-Log "Starting tunnel: ssh $($sshArgs -join ' ')"
    $process = Start-Process -FilePath "ssh" -ArgumentList $sshArgs `
        -NoNewWindow -PassThru -Wait
    return $process.ExitCode
}

# ── Main Loop ───────────────────────────────────────────────────────────────

Test-SshAvailable
Write-Log "SSH tunnel watchdog starting (local :$LocalPort -> $RemoteHost :$RemotePort)"

$currentDelay = $RetryDelaySec
$consecutiveFailures = 0

while ($true) {
    $exitCode = Start-Tunnel

    if ($exitCode -eq 0) {
        # Clean exit (e.g. server reboot) — reset backoff
        Write-Log "Tunnel exited cleanly (exit code 0). Reconnecting in ${RetryDelaySec}s..."
        $currentDelay = $RetryDelaySec
        $consecutiveFailures = 0
    }
    else {
        $consecutiveFailures++
        Write-Log "Tunnel failed (exit code $exitCode, attempt #$consecutiveFailures). Retrying in ${currentDelay}s..." "WARN"
        # Exponential backoff, capped
        $currentDelay = [Math]::Min($currentDelay * 2, $MaxRetryDelay)
    }

    # Reset backoff after 5 consecutive successes worth of time
    if ($consecutiveFailures -ge 10) {
        Write-Log "Too many consecutive failures. Waiting ${MaxRetryDelay}s before next attempt." "ERROR"
        $currentDelay = $MaxRetryDelay
    }

    Start-Sleep -Seconds $currentDelay
}
