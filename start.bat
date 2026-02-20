:: activate .venv or create it if it doesn't exist
@echo off
cd /d "%~dp0"

:: variables
set "PY=python"
set "VENV=.venv"
set "ActivateScript=%VENV%\Scripts\activate.bat"
set "PipExe=%VENV%\Scripts\pip.exe"
set "PyExe=%VENV%\Scripts\python.exe"

:: check if python is in path
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH. Please install Python 3.6+ and ensure it's in your system PATH.
    exit /b 1
)

:: if .venv does not exist, create it
if not exist "%ActivateScript%" (
    "%PY%" -m venv .venv || (echo [ERROR] Failed to create virtual environment.& exit /b 1)
    echo [INFO] Created virtual environment in .venv
)

:: disable pip version check (annoying)
set "PIP_DISABLE_PIP_VERSION_CHECK=1"

if /i "%~1"=="s" (
    echo [INFO] Skipping dependency installation.
    goto :activate
)

:: upgrade pip
"%PYEXE%" -m pip install --upgrade pip setuptools wheel || echo [WARN] Failed to upgrade pip. Continuing anyway.

:: install dependencies
if exist "requirements.txt" (
    "%PipExe%" install -r requirements.txt || (echo [ERROR] Failed to install dependencies from requirements.txt.& exit /b 1)
    echo [INFO] Installed dependencies from requirements.txt.
)
if exist "pyproject.toml" (
    "%PipExe%" install -e . || (echo [ERROR] Failed to install dependencies from pyproject.toml.& exit /b 1)
    echo [INFO] Installed dependencies from pyproject.toml.
)

:: activate the virtual environment
:activate
call "%ActivateScript%" || (echo [ERROR] Failed to activate virtual environment.& exit /b 1)
echo [OK] .venv activated. to deactivate, run: deactivate