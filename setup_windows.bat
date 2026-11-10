@echo off
setlocal
cd /d "%~dp0"
set "NUI_PY="
py -3.12-64 -c "import struct; assert struct.calcsize('P') == 8" >nul 2>&1
if not errorlevel 1 set "NUI_PY=py -3.12-64"
if defined NUI_PY goto create_env
py -3.11-64 -c "import struct; assert struct.calcsize('P') == 8" >nul 2>&1
if not errorlevel 1 set "NUI_PY=py -3.11-64"
if defined NUI_PY goto create_env
echo Install 64-bit Python 3.12 or 3.11 from python.org, including Python Launcher.
goto fail
:create_env
if exist ".venv\Scripts\python.exe" goto install
%NUI_PY% -m venv .venv
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -c "import struct,sys; assert struct.calcsize('P') == 8 and sys.version_info[:2] in [(3,11),(3,12)], 'Use Python 3.11/3.12 64-bit'"
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto fail
".venv\Scripts\python.exe" download_model.py
if errorlevel 1 goto fail
echo Setup complete. Run start_preview.bat first, then start_nui.bat.
pause
exit /b 0
:fail
echo Setup failed. Read the error message above.
pause
exit /b 1
