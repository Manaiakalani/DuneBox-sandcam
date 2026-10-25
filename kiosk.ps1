<#
.SYNOPSIS
    Keeps DuneBox running on an unattended PC (museum, classroom, library).

.DESCRIPTION
    Starts sandcam and restarts it whenever it exits or crashes, waiting longer
    between restarts if it keeps failing. On start it fast-forwards this
    checkout and syncs dependencies. With -WithDuneBox it also supervises
    DuneBox (C++) (..\DuneBox\bin\Magic-Sand.exe) and replaces that exe when
    a newer public release is published. A failed update still launches the
    copy already on disk.

    -Install registers a Windows scheduled task that runs this watchdog when you
    sign in, so the sandbox comes back by itself after a reboot or power cut.
    Pair it with automatic sign-in and the opening hours in the dashboard.

    Log: kiosk.log next to this script.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\kiosk.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\kiosk.ps1 -Install -WithDuneBox
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\kiosk.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch] $WithDuneBox,
    [switch] $Install,
    [switch] $Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root     = $PSScriptRoot
$Log      = Join-Path $Root 'kiosk.log'
$TaskName = 'DuneBox kiosk'

function Write-Log([string] $Message) {
    $line = '{0:yyyy-MM-dd HH:mm:ss}  {1}' -f (Get-Date), $Message
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed the '$TaskName' task."
    return
}

if ($Install) {
    $argsLine = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$PSCommandPath`""
    if ($WithDuneBox) { $argsLine += ' -WithDuneBox' }
    $action   = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argsLine -WorkingDirectory $Root
    $trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description 'Starts DuneBox at sign-in and restarts it if it stops.' -Force | Out-Null
    Write-Host "Installed '$TaskName': DuneBox starts when $env:USERNAME signs in."
    Write-Host 'Tip: turn on automatic sign-in so it also starts after a power cut.'
    return
}

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

function Update-GitCheckout {
    param(
        [Parameter(Mandatory = $true)][string] $Dir,
        [Parameter(Mandatory = $true)][string] $Name
    )
    if (-not (Test-Path (Join-Path $Dir '.git'))) {
        Write-Log "$Name source checkout not found at $Dir."
        return $false
    }
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Write-Log "git not found. Starting the installed $Name."
        return $false
    }
    $code = Invoke-Timed -File $git.Source -ArgumentList @('pull', '--ff-only', '--quiet') `
        -WorkingDirectory $Dir -TimeoutSec 45
    if ($code -eq 0) {
        Write-Log "$Name source is up to date."
        return $true
    }
    if ($code -eq 124) {
        Write-Log "$Name source update timed out. Starting the current checkout."
    } else {
        Write-Log "$Name source update failed (git exit $code). Starting the current checkout."
    }
    return $false
}

function Update-Sandcam {
    if (-not (Update-GitCheckout -Dir $Root -Name 'sandcam')) { return }
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvCmd) {
        Write-Log 'uv not found. Starting the current sandcam checkout.'
        return
    }
    $code = Invoke-Timed -File $uvCmd.Source -ArgumentList @('sync', '--extra', 'kinect-v2') `
        -WorkingDirectory $Root -TimeoutSec 180
    if ($code -eq 0) {
        Write-Log 'sandcam dependencies are in sync.'
    } elseif ($code -eq 124) {
        Write-Log 'sandcam dependency sync timed out. Starting the current checkout.'
    } else {
        Write-Log "sandcam dependency sync failed (uv exit $code). Starting the current checkout."
    }
}

function Update-DuneBoxApp {
    $cppRoot = Join-Path (Split-Path $Root -Parent) 'DuneBox'
    Update-GitCheckout -Dir $cppRoot -Name 'DuneBox' | Out-Null
    $bin = Join-Path $cppRoot 'bin'
    $exe = Join-Path $bin 'Magic-Sand.exe'
    $checker = Join-Path $cppRoot 'release-is-newer.ps1'
    $extractor = Join-Path $cppRoot 'extract-release.ps1'
    if (-not (Test-Path $checker) -or -not (Test-Path $extractor)) {
        Write-Log "DuneBox updater scripts are not in $cppRoot."
        return
    }
    $code = Invoke-Timed -File 'powershell.exe' -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $checker,
        '-Repo', 'Manaiakalani/DuneBox', '-BinDir', $bin
    ) -WorkingDirectory $cppRoot -TimeoutSec 30
    if ($code -ne 0) { return }

    Write-Log 'A newer DuneBox release is available. Updating...'
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) {
        Write-Log 'gh not found. Starting the installed DuneBox.'
        return
    }
    $zip = Join-Path $env:TEMP 'DuneBox-windows-x64.zip'
    if (Test-Path $zip) { Remove-Item $zip -Force }
    $code = Invoke-Timed -File $gh.Source -ArgumentList @(
        'release', 'download', '--repo', 'Manaiakalani/DuneBox',
        '--pattern', 'DuneBox-windows-x64.zip', '--output', $zip
    ) -WorkingDirectory $cppRoot -TimeoutSec 180
    if ($code -ne 0 -or -not (Test-Path $zip)) {
        Write-Log 'Could not download the DuneBox update. Starting the installed copy.'
        return
    }
    $code = Invoke-Timed -File 'powershell.exe' -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $extractor, $zip, $bin
    ) -WorkingDirectory $cppRoot -TimeoutSec 180
    if ($code -eq 0 -and (Test-Path $exe)) {
        Write-Log 'DuneBox updated. Live settings were left in place.'
    } else {
        Write-Log 'DuneBox extract failed. Starting the installed copy.'
    }
    if (Test-Path $zip) { Remove-Item $zip -Force -ErrorAction SilentlyContinue }
}

Update-Sandcam
if ($WithDuneBox) { Update-DuneBoxApp }

# Each app: how to start it, the running process and crash backoff
$apps = [System.Collections.Generic.List[hashtable]]::new()
$uv = (Get-Command uv -ErrorAction SilentlyContinue)
if (-not $uv) { throw 'uv not found. Run run.bat once to install it.' }
$apps.Add(@{
    Name = 'sandcam'
    File = $uv.Source
    Args = 'run --frozen --with "websockets>=12.0" --with comtypes --with pykinect2 python main.py'
    Dir  = $Root
    Proc = $null; Started = [datetime]::MinValue; Delay = 5
})
if ($WithDuneBox) {
    $exe = Join-Path (Split-Path $Root -Parent) 'DuneBox\bin\Magic-Sand.exe'
    if (Test-Path $exe) {
        $apps.Add(@{
            Name = 'DuneBox'; File = $exe; Args = ''; Dir = (Split-Path $exe)
            Proc = $null; Started = [datetime]::MinValue; Delay = 5
        })
    } else {
        Write-Log "DuneBox not found at $exe. Run ..\DuneBox\run.bat once to download it."
    }
}

Write-Log "Watchdog started for $(($apps | ForEach-Object Name) -join ' and ')"
while ($true) {
    foreach ($app in $apps) {
        if ($app.Proc -and -not $app.Proc.HasExited) { continue }
        if ($app.Proc) {
            $ran = (Get-Date) - $app.Started
            # Quick exits mean a crash loop: back off up to a minute
            $app.Delay = if ($ran.TotalSeconds -lt 30) { [Math]::Min($app.Delay * 2, 60) } else { 5 }
            Write-Log ("{0} exited (code {1}) after {2:N0}s; restarting in {3}s" -f `
                $app.Name, $app.Proc.ExitCode, $ran.TotalSeconds, $app.Delay)
            Start-Sleep -Seconds $app.Delay
        }
        $params = @{ FilePath = $app.File; WorkingDirectory = $app.Dir; PassThru = $true; WindowStyle = 'Minimized' }
        if ($app.Args) { $params.ArgumentList = $app.Args }
        $app.Proc = Start-Process @params
        $app.Started = Get-Date
        Write-Log "Started $($app.Name) (pid $($app.Proc.Id))"
    }
    Start-Sleep -Seconds 2
}
