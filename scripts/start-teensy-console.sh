#!/usr/bin/env bash
set -euo pipefail

# Resolve project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${APP_HOME:-$(cd "$SCRIPT_DIR/.." && pwd)}"
VENV_DIR="$PROJECT_DIR/.venv"
REQ_FILE="$PROJECT_DIR/requirements.txt"
STAMP_FILE="$VENV_DIR/.requirements-stamp"
ENV_FILE="$PROJECT_DIR/.env"

cd "$PROJECT_DIR"

# Load environment overrides from .env if present
if [[ -f "$ENV_FILE" ]]; then
  # export all variables from the file
  set -a
  source "$ENV_FILE"
  set +a
fi

# Defaults if not provided via environment
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
LOG_LEVEL="${LOG_LEVEL:-info}"

# Create virtual environment if missing
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# Install/update dependencies if the venv is fresh or requirements changed.
if [[ ! -f "$STAMP_FILE" || "$REQ_FILE" -nt "$STAMP_FILE" ]]; then
  pip install --upgrade pip
  pip install -r "$REQ_FILE"
  touch "$STAMP_FILE"
fi

exec "$VENV_DIR/bin/uvicorn" app.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --log-level "$LOG_LEVEL"
