#Requires -Version 5.1
<#
.SYNOPSIS
    Resilient SSH reverse tunnel with auto-reconnect.

.DESCRIPTION
    Keeps an SSH reverse tunnel alive that exposes a local service on a
    remote server. Automatically reconnects on network drops or SSH failures.
    Includes network pre-check to avoid fail2ban triggers.

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
$RetryDelaySec    = 10                   # Initiale Wartezeit bei Reconnect
$MaxRetryDelay    = 600                  # Max Wartezeit (10 Min, verhindert fail2ban)
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

function Test-ServerReachable {
    <#
    .SYNOPSIS
        Quick TCP check on port 22 before attempting SSH.
        Prevents unnecessary SSH attempts when VPN/network is down.
    #>
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $result = $tcp.BeginConnect($RemoteHost, 22, $null, $null)
        $success = $result.AsyncWaitHandle.WaitOne(5000)
        if ($success) {
            $tcp.EndConnect($result)
        }
        $tcp.Close()
        return $success
    }
    catch {
        return $false
    }
}

function Clear-RemotePort {
    <#
    .SYNOPSIS
        Kills stale sshd processes holding the remote port after a connection drop.
        Requires passwordless sudo for fuser on the server (see docs/ssh-tunnel.md).
    #>
    Write-Log "Clearing stale port $RemotePort on $RemoteHost..."
    $output = & ssh -o "ConnectTimeout=5" -o "BatchMode=yes" `
        "${RemoteUser}@${RemoteHost}" `
        "sudo fuser -k ${RemotePort}/tcp 2>&1; echo EXIT_CODE=`$?" 2>&1
    $sshExit = $LASTEXITCODE
    foreach ($line in $output) {
        if ($line -and $line.ToString().Trim()) {
            Write-Log "  fuser: $line"
        }
    }
    if ($sshExit -eq 0) {
        Write-Log "Remote port $RemotePort cleared (ssh exit=$sshExit)."
    } else {
        Write-Log "Could not clear remote port (ssh exit=$sshExit)." "WARN"
    }
}

function Start-Tunnel {
    $sshCmd = "ssh -N -R 127.0.0.1:${RemotePort}:127.0.0.1:${LocalPort} -o ServerAliveInterval=$SshAliveInterval -o ServerAliveCountMax=$SshAliveCountMax -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -o BatchMode=yes ${RemoteUser}@${RemoteHost}"
    Write-Log "Starting tunnel: $sshCmd"
    & ssh -N -R "127.0.0.1:${RemotePort}:127.0.0.1:${LocalPort}" `
        -o "ServerAliveInterval=$SshAliveInterval" `
        -o "ServerAliveCountMax=$SshAliveCountMax" `
        -o "ExitOnForwardFailure=yes" `
        -o "ConnectTimeout=10" `
        -o "BatchMode=yes" `
        "${RemoteUser}@${RemoteHost}" 2>&1 | ForEach-Object { Write-Log "SSH: $_" }
    return $LASTEXITCODE
}

# ── Main Loop ───────────────────────────────────────────────────────────────

Test-SshAvailable
Write-Log "SSH tunnel watchdog starting (local :$LocalPort -> $RemoteHost :$RemotePort)"

$currentDelay = $RetryDelaySec
$consecutiveFailures = 0

while ($true) {
    # Netzwerk-Check: kein SSH-Versuch wenn Server nicht erreichbar
    if (-not (Test-ServerReachable)) {
        $consecutiveFailures++
        $currentDelay = [Math]::Min($currentDelay * 2, $MaxRetryDelay)
        Write-Log "Server not reachable (TCP 22). Network/VPN down? Waiting ${currentDelay}s... (check #$consecutiveFailures)" "WARN"
        Start-Sleep -Seconds $currentDelay
        continue
    }

    # Port räumen nur wenn vorher Fehler auftraten (Zombie wahrscheinlich)
    if ($consecutiveFailures -gt 0) {
        Clear-RemotePort
    }

    $exitCode = Start-Tunnel

    if ($exitCode -eq 0) {
        # Clean exit (e.g. server reboot) — reset backoff
        Write-Log "Tunnel exited cleanly (exit code 0). Reconnecting in ${RetryDelaySec}s..."
        $currentDelay = $RetryDelaySec
        $consecutiveFailures = 0
    }
    else {
        $consecutiveFailures++
        $currentDelay = [Math]::Min($currentDelay * 2, $MaxRetryDelay)
        Write-Log "Tunnel failed (exit code $exitCode, attempt #$consecutiveFailures). Retrying in ${currentDelay}s..." "WARN"
    }

    Start-Sleep -Seconds $currentDelay
}
