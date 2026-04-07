#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Registers the SSH tunnel watchdog as a Windows Scheduled Task.

.DESCRIPTION
    Creates a task that:
    - Starts at user logon
    - Restarts on failure (every 60s, up to 999 times)
    - Runs the ssh-tunnel.ps1 watchdog script

.NOTES
    1. Copy this file to Install-SshTunnelTask.ps1
    2. Adjust $TaskName and $Description if needed
    3. Run from an elevated PowerShell:
       powershell -ExecutionPolicy Bypass -File scripts\Install-SshTunnelTask.ps1
#>

$TaskName    = "Elder-Berry SSH Tunnel"
$ScriptPath  = Join-Path $PSScriptRoot "ssh-tunnel.ps1"
$Description = "Keeps the SSH reverse tunnel alive (auto-reconnect on failure)"

# ── Validate ────────────────────────────────────────────────────────────────
if (-not (Test-Path $ScriptPath)) {
    Write-Error "Script not found: $ScriptPath"
    Write-Error "Copy ssh-tunnel.example.ps1 to ssh-tunnel.ps1 and fill in your values first."
    exit 1
}

# ── Remove existing task if present ─────────────────────────────────────────
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# ── Build task ──────────────────────────────────────────────────────────────
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`"" `
    -WorkingDirectory $PSScriptRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Seconds 60) `
    -RestartCount 999 `
    -ExecutionTimeLimit (New-TimeSpan -Days 9999)

# ── Register ────────────────────────────────────────────────────────────────
Register-ScheduledTask `
    -TaskName $TaskName `
    -Description $Description `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest

Write-Host ""
Write-Host "Scheduled Task '$TaskName' created successfully." -ForegroundColor Green
Write-Host "  - Trigger: At logon"
Write-Host "  - Restart: Every 60s on failure (up to 999x)"
Write-Host "  - Script:  $ScriptPath"
Write-Host ""
Write-Host "To start it now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To check status:  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "To remove:        Unregister-ScheduledTask -TaskName '$TaskName'"
