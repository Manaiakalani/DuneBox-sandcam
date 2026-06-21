<#
.SYNOPSIS
    Installs (or refreshes) the DuneBox desktop shortcuts. Safe to re-run.

.DESCRIPTION
    Creates two desktop shortcuts so anyone can launch DuneBox with a
    double-click:

      * "DuneBox"                  -> this app (DuneBox-sandcam), works today,
                                      drives terrain live from the Kinect v2
                                      (or the mouse simulator if no sensor).
      * "DuneBox (Magic-Sand C++)" -> the sibling C++ app (..\DuneBox), if that
                                      repo is present next to this one.

    The script is idempotent: re-running it just updates the shortcuts in place.
    It also removes the legacy "DuneBox-sandcam" shortcut, now superseded by
    the primary "DuneBox" icon.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\install-desktop-shortcuts.ps1
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = $PSScriptRoot
$Desktop  = [Environment]::GetFolderPath('Desktop')
$Shell    = New-Object -ComObject WScript.Shell

# Ensure a sandcam icon exists (committed to the repo; regenerate if absent).
function Initialize-SandcamIcon {
    param([string]$Path)

    if (Test-Path $Path) { return $Path }

    Write-Warning "icon.ico missing - generating a fallback with System.Drawing."
    try {
        Add-Type -AssemblyName System.Drawing
        $bmp = [System.Drawing.Bitmap]::new(64, 64, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $g   = [System.Drawing.Graphics]::FromImage($bmp)
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $g.Clear([System.Drawing.Color]::Transparent)
        $sky  = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 38, 52, 92))
        $sand = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 214, 156, 88))
        $g.FillEllipse($sky, 2, 2, 60, 60)
        $g.FillPie($sand, 2, 30, 60, 36, 0, 180)
        $hicon = $bmp.GetHicon()
        $icon  = [System.Drawing.Icon]::FromHandle($hicon)
        $fs    = [System.IO.File]::Create($Path)
        $icon.Save($fs)
        $fs.Dispose(); $icon.Dispose(); $g.Dispose(); $bmp.Dispose()
        return $Path
    }
    catch {
        Write-Warning "Icon fallback failed ($_); the shortcut will use a default icon."
        return $null
    }
}

function Set-DesktopShortcut {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [string] $Target,
        [Parameter(Mandatory)] [string] $WorkingDirectory,
        [string] $IconPath,
        [string] $Description
    )

    $linkPath = Join-Path $Desktop "$Name.lnk"
    $sc = $Shell.CreateShortcut($linkPath)
    $sc.TargetPath       = $Target
    $sc.WorkingDirectory = $WorkingDirectory
    $sc.WindowStyle      = 7          # launch the console minimized, stays clean
    if ($Description) { $sc.Description = $Description }
    if ($IconPath -and (Test-Path $IconPath)) { $sc.IconLocation = "$IconPath,0" }
    $sc.Save()
    Write-Host "  [+] $linkPath"
}

Write-Host "Installing DuneBox desktop shortcuts..."

# 1) Primary: the working sandcam app, branded simply as "DuneBox".
$sandcamBat  = Join-Path $RepoRoot 'run.bat'
$sandcamIcon = Initialize-SandcamIcon (Join-Path $RepoRoot 'icon.ico')
if (-not (Test-Path $sandcamBat)) { throw "Missing launcher: $sandcamBat" }
Set-DesktopShortcut -Name 'DuneBox' -Target $sandcamBat -WorkingDirectory $RepoRoot `
    -IconPath $sandcamIcon -Description 'DuneBox AR sandbox (Kinect v2 / mouse simulator)'

# 2) Secondary: the sibling C++ Magic-Sand app, if its repo is present.
$cppRoot = Join-Path (Split-Path $RepoRoot -Parent) 'DuneBox'
$cppBat  = Join-Path $cppRoot 'run.bat'
if (Test-Path $cppBat) {
    $cppIcon = Join-Path $cppRoot 'icon.ico'
    Set-DesktopShortcut -Name 'DuneBox (Magic-Sand C++)' -Target $cppBat -WorkingDirectory $cppRoot `
        -IconPath $cppIcon -Description 'DuneBox Magic-Sand C++ renderer'
} else {
    Write-Host "  [ ] Sibling C++ repo not found at $cppRoot - skipping that shortcut."
}

# 3) Remove the legacy shortcut now superseded by "DuneBox".
$legacy = Join-Path $Desktop 'DuneBox-sandcam.lnk'
if (Test-Path $legacy) {
    $old = $Shell.CreateShortcut($legacy)
    if ([string]::Equals($old.TargetPath, $sandcamBat, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item $legacy -Force
        Write-Host "  [-] Removed legacy DuneBox-sandcam.lnk (superseded by DuneBox)"
    }
}

Write-Host "Done. Double-click DuneBox on your desktop to run."
