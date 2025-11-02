#!/usr/bin/env bash
set -euo pipefail

# Config
VENV_DIR=".venv"
REQ_FILE="requirements.txt"

# Find a usable Python (prefer python3)
if command -v python3 >/dev/null 2>&1; then
  SYS_PY="python3"
elif command -v python >/dev/null 2>&1; then
  SYS_PY="python"
else
  echo "No python found in PATH. Install Python 3." >&2
  exit 1
fi

# Create venv if missing
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtualenv in $VENV_DIR..."
  "$SYS_PY" -m venv "$VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# Ensure pip/setuptools/wheel are recent
"$VENV_PY" -m pip install --upgrade pip setuptools wheel >/dev/null

# If requirements.txt exists, install only when changed
if [ -f "$REQ_FILE" ]; then
  # compute hash using system python (reliable)
  REQ_HASH=$("$SYS_PY" -c "import hashlib,sys;print(hashlib.sha256(open('$REQ_FILE','rb').read()).hexdigest())")
  HASH_FILE="$VENV_DIR/.req_hash"

  if [ ! -f "$HASH_FILE" ] || [ "$REQ_HASH" != "$(cat "$HASH_FILE")" ]; then
    echo "Installing requirements from $REQ_FILE..."
    "$VENV_PIP" install -r "$REQ_FILE"
    echo "$REQ_HASH" > "$HASH_FILE"
  else
    echo "requirements.txt unchanged — skipping pip install."
  fi
fi

# Install the project in editable mode every run to ensure import path is correct
echo "Installing package in editable mode..."
"$VENV_PIP" install -e .

# Verify the package is importable before trying to run it
if ! "$VENV_PY" -c "import drift" >/dev/null 2>&1; then
  echo "Drift package is not importable even after install. Aborting." >&2
  exit 1
fi

# Run the project
exec "$VENV_PY" -m drift "$@"
