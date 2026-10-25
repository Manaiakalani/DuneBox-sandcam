<#
.SYNOPSIS
    Keeps DuneBox running on an unattended PC (museum, classroom, library).

.DESCRIPTION
    Starts sandcam and restarts it whenever it exits or crashes, waiting longer
    between restarts if it keeps failing. With -WithDuneBox it also supervises
    DuneBox (C++) (..\DuneBox\bin\Magic-Sand.exe).

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
