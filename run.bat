@echo off
setlocal
rem Ensure we run from this script's folder (project root)
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "REQ_FILE=requirements.txt"

:: pick python (system)
where python >nul 2>&1
if errorlevel 1 (
  echo No python found in PATH. Install Python 3.
  exit /b 1
)

:: create venv if missing
if not exist "%VENV_DIR%\" (
  echo Creating virtualenv in %VENV_DIR%...
  python -m venv "%VENV_DIR%"
)

set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

:: upgrade pip
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel >nul

:: install requirements (simple: always install if file exists and no hash logic in batch)
if exist "%REQ_FILE%" (
  echo Installing requirements from %REQ_FILE%...
  "%VENV_PIP%" install -r "%REQ_FILE%"
  if errorlevel 1 (
    echo Failed to install requirements. Aborting.
    exit /b 1
  )
)

:: install package in editable mode
echo Installing package in editable mode...
"%VENV_PIP%" install -e .
if errorlevel 1 (
  echo Failed to install package in editable mode. Aborting.
  exit /b 1
)

"%VENV_PY%" -c "import drift" >nul 2>&1
if errorlevel 1 (
  echo Drift package is not importable even after install. Aborting.
  exit /b 1
)

:: run
"%VENV_PY%" -m drift %*
endlocal
