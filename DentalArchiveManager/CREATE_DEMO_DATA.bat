@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 --version >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
  )
)
if not defined PYTHON_EXE (
  where python >nul 2>nul
  if not errorlevel 1 (
    python --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=python"
  )
)
if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
  set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
)
if not defined PYTHON_EXE (
  echo Python 3 is required. Run START_APP.bat first to install it.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
)

".venv\Scripts\python.exe" create_demo_data.py
echo.
echo Demo folder: %CD%\DEMO_DENTAL_DATA
pause
endlocal
