<#
.SYNOPSIS
    Fast-forward the sandcam checkout and sync its dependencies.

.DESCRIPTION
    Called by run.bat before launch. Exit 0 to start the copy already on disk.
    Exit 10 when run.bat itself changed, so run.bat starts the new file once.
    Windows reads a .bat line by line, so the launcher must not keep reading a
    file that this pull just replaced.

    A missing git checkout, a failed pull, a failed sync, or a timeout exits 0.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = $PSScriptRoot
$Launcher = Join-Path $Root 'run.bat'

function Invoke-Timed {
    param(
        [Parameter(Mandatory = $true)][string] $File,
        [string[]] $ArgumentList = @(),
        [Parameter(Mandatory = $true)][string] $WorkingDirectory,
        [Parameter(Mandatory = $true)][int] $TimeoutSec
    )
    $params = @{
        FilePath         = $File
        WorkingDirectory = $WorkingDirectory
        PassThru         = $true
        WindowStyle      = 'Hidden'
    }
    if ($ArgumentList.Count -gt 0) { $params.ArgumentList = $ArgumentList }
    $proc = Start-Process @params
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        try { $proc.Kill() } catch {}
        return 124
    }
    if ($null -eq $proc.ExitCode) { return 1 }
    return [int]$proc.ExitCode
}

function Get-LauncherHash {
    if (-not (Test-Path -LiteralPath $Launcher)) { return '' }
    return (Get-FileHash -Algorithm SHA256 -Path $Launcher).Hash
}

try {
    $before = Get-LauncherHash
    if (-not (Test-Path -LiteralPath (Join-Path $Root '.git'))) {
        Write-Host '  No sandcam git checkout. Starting the installed copy.'
        exit 0
    }
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Write-Host '  git not found. Starting the installed sandcam.'
        exit 0
    }

    # A public checkout needs no login. Refuse a credential prompt so the
    # timeout is the only way this can wait.
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'Never'
    $code = Invoke-Timed -File $git.Source -ArgumentList @('pull', '--ff-only', '--quiet') `
        -WorkingDirectory $Root -TimeoutSec 45
    if ($code -ne 0) {
        if ($code -eq 124) {
            Write-Host '  sandcam update timed out. Starting the current checkout.'
        } else {
            Write-Host "  sandcam update failed (git exit $code). Starting the current checkout."
        }
        exit 0
    }

    Write-Host '  sandcam source is up to date.'
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvCmd) {
        Write-Host '  uv not found. Starting the current sandcam checkout.'
    } else {
        Write-Host '  Syncing sandcam dependencies...'
        $code = Invoke-Timed -File $uvCmd.Source -ArgumentList @('sync', '--extra', 'kinect-v2') `
            -WorkingDirectory $Root -TimeoutSec 180
        if ($code -eq 0) {
            Write-Host '  sandcam dependencies are in sync.'
        } elseif ($code -eq 124) {
            Write-Host '  sandcam dependency sync timed out. Starting the current checkout.'
        } else {
            Write-Host "  sandcam dependency sync failed (uv exit $code). Starting the current checkout."
        }
    }

    $after = Get-LauncherHash
    if ($before -ne '' -and $after -ne $before) {
        Write-Host '  Launcher updated. Starting it again.'
        exit 10
    }
    exit 0
} catch {
    Write-Host "  sandcam update failed ($($_.Exception.Message)). Starting the current checkout."
    exit 0
}
