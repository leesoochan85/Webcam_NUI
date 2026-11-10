@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
echo LIVE mode starts paused. F8: enable/pause. F10: exit from any window.
".venv\Scripts\python.exe" main.py --live %*
if errorlevel 1 pause
exit /b
:missing
echo Run setup_windows.bat first.
pause
exit /b 1
