@echo off
:: DuneBox-sandcam Launcher - installs Python + uv if needed, fast-forwards
:: this checkout, then runs. A failed update still starts the copy on disk.
:: Path additions stay above setlocal so a one-time relaunch can still see them.
title DuneBox sandcam

cd /d "%~dp0"

:: Check for Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  Python not found. Installing via winget...
    winget install --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements >nul 2>&1
    set "PATH=%PATH%;%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts"
)

:: Check for uv
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo  Installing uv package manager...
    powershell -Command "irm https://astral.sh/uv/install.ps1 | iex" >nul 2>&1
    set "PATH=%PATH%;%USERPROFILE%\.local\bin"
)

setlocal enabledelayedexpansion

:: --updated: this file was replaced by the pull below, and the new copy is
:: already running. Skip a second pull. The parenthesis block is read in full
:: before git runs, so the relaunch still happens if the pull replaces run.bat.
if /I "%~1"=="--updated" goto :launch

(
echo  Checking for sandcam updates...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update-checkout.ps1"
if errorlevel 10 (
    "%~f0" --updated
    exit /b 0
)
)

:launch
echo  Starting DuneBox sandcam...
echo  (No Kinect? No problem - mouse simulator mode activates automatically)
echo.
:: --frozen: use the committed lock (the sensor extras can't be re-resolved
::   without native SDKs). --with pykinect2/comtypes: the Kinect v2 (SDK)
::   backend needs these pure-Python bindings; they aren't in the lock, so
::   overlay them (harmless when unused - imported only for kinect_v2_sdk).
::   websockets is already in the lock. Together these make launch reliable
::   even on a freshly-synced venv.
uv run --frozen --with "websockets>=12.0" --with "comtypes" --with "pykinect2" python main.py
