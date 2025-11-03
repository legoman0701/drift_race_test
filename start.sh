#!/usr/bin/env bash
# start.sh — create/activate .venv, upgrade tooling, install deps
# Use:  source ./start.sh    (or: . ./start.sh)
# If you run ./start.sh without sourcing, activation won't persist. That's how shells work.

set -Eeuo pipefail

# Go to the script's directory
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
cd "$SCRIPT_DIR"

# Pick a Python
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[ERROR] Python 3 not found. Install it first."
  return 1 2>/dev/null || exit 1
fi

VENV=".venv"
ACT="$VENV/bin/activate" # Activation script
PIP="$VENV/bin/pip"
PYEXE="$VENV/bin/python"

# Create venv if missing
if [[ ! -f "$ACT" ]]; then
  # On Debian/Ubuntu, if this fails: sudo apt install -y python3-venv
  "$PY" -m venv "$VENV"
  echo "[INFO] Created virtual environment in $VENV"
fi

# Quiet pip’s update nag
export PIP_DISABLE_PIP_VERSION_CHECK=1

# Upgrade base tooling (don’t hard-fail on hiccups)
if ! "$PYEXE" -m pip install --upgrade pip setuptools wheel --disable-pip-version-check; then
  echo "[WARN] Failed to upgrade pip tooling. Continuing."
fi
echo "[INFO] Upgraded pip, setuptools, and wheel."

# Install dependencies if present
if [[ -f "requirements.txt" ]]; then
  "$PIP" install -r requirements.txt --disable-pip-version-check
  echo "[INFO] Installed dependencies from requirements.txt."
fi

if [[ -f "pyproject.toml" ]]; then
  "$PIP" install -e . --disable-pip-version-check
  echo "[INFO] Installed dependencies from pyproject.toml."
fi

# Activate into the current shell
# shellcheck disable=SC1090
source "$ACT"
echo "[OK] .venv activated. To deactivate, run:  deactivate"
