[CmdletBinding()]
param(
    [switch]$Disable
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    if ($Disable) {
        git config --unset core.hooksPath 2>$null
        Write-Host "Disabled Elder-Berry versioned Git hooks."
        return
    }

    git config core.hooksPath .githooks
    Write-Host "Enabled Elder-Berry versioned Git hooks: core.hooksPath=.githooks"
    Write-Host "Commit messages now need: Journal: elder-berry#<id>"
}
finally {
    Pop-Location
}
