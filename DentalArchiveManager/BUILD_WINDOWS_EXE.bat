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

if not exist ".build-venv\Scripts\python.exe" "%PYTHON_EXE%" %PYTHON_ARGS% -m venv .build-venv
".build-venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-build.txt
if errorlevel 1 (
  pause
  exit /b 1
)

".build-venv\Scripts\pyinstaller.exe" --noconfirm DentalArchiveManager.spec
if errorlevel 1 (
  pause
  exit /b 1
)

echo.
echo Ready: dist\DentalArchiveManager.exe
pause
endlocal
