@echo off
setlocal
cd /d "%~dp0"

call :detect_python
if not defined PYTHON_EXE call :offer_python_install
if not defined PYTHON_EXE exit /b 1

if not exist ".venv\Scripts\python.exe" (
  echo Creating local environment...
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv .venv
  if errorlevel 1 (
    echo Failed to create the local environment.
    pause
    exit /b 1
  )
)

echo Installing or checking dependencies...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)

start "Dental Archive Manager" ".venv\Scripts\pythonw.exe" app.py
endlocal
exit /b 0

:detect_python
set "PYTHON_EXE="
set "PYTHON_ARGS="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 --version >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
    exit /b 0
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python --version >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=python"
    exit /b 0
  )
)
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
  set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
)
exit /b 0

:offer_python_install
echo Python 3 was not found.
where winget >nul 2>nul
if errorlevel 1 (
  echo Opening the official Python download page.
  start "" "https://www.python.org/downloads/windows/"
  echo Install Python and enable "Add python.exe to PATH", then run START_APP.bat again.
  pause
  exit /b 0
)
choice /M "Install Python 3.13 automatically with Windows Package Manager"
if errorlevel 2 (
  start "" "https://www.python.org/downloads/windows/"
  echo Install Python and enable "Add python.exe to PATH", then run START_APP.bat again.
  pause
  exit /b 0
)
winget install --id Python.Python.3.13 --exact --source winget --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  echo Automatic installation failed. Opening the official download page.
  start "" "https://www.python.org/downloads/windows/"
  pause
  exit /b 0
)
call :detect_python
if not defined PYTHON_EXE (
  echo Python was installed. Close this window and run START_APP.bat once more.
  pause
)
exit /b 0
