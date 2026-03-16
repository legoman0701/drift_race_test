# activate or create .venv and select it

param (
    [switch]$s # use -s to skipping dependency installation
)

$ErrorActionPreference = "Stop" # stop on errors
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'  # quiet pip's update ping

# variables
$PY = "python"
$VENV = ".venv"
$ActivateScript = $VENV + "\Scripts\Activate.ps1"
$PipExe = $VENV + "\Scripts\pip.exe"
$PythonExe = $VENV + "\Scripts\python.exe"

# if .venv does not exist, create it
if (-not (Test-Path $ActivateScript)) {
    & $PY -m venv $VENV
    Write-Host "[INFO] Created virtual environment in $VENV"
}

if (-not $s) {
    # upgrade pip
    & $PythonExe -m pip install --upgrade pip setuptools wheel
    Write-Host "[INFO] Upgraded pip, setuptools, and wheel."
    
    # install dependencies
    if (Test-Path "requirements.txt") {
        & $PipExe install -r requirements.txt
        Write-Host "[INFO] Installed dependencies from requirements.txt."
    }
    if (Test-Path "pyproject.toml") {
        & $PipExe install -e .
        Write-Host "[INFO] Installed dependencies from pyproject.toml."
    }
} else {
    Write-Host "[INFO] Skipping dependency installation due to -s switch."
}

# activate .venv
& $ActivateScript
Write-Host "[OK] .venv activated. to deactivate, run: deactivate"