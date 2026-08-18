@echo off
:: DuneBox-sandcam Launcher - installs Python + deps if needed, then runs
setlocal enabledelayedexpansion

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

:: Install dependencies + run
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
