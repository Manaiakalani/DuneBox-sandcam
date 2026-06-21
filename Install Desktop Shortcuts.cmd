@echo off
:: One-click setup: puts DuneBox shortcut(s) on your desktop.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-desktop-shortcuts.ps1"
echo.
pause
