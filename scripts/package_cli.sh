#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DIST_DIR="${DIST_DIR:-dist}"
BUILD_DIR="${BUILD_DIR:-build}"

echo "[package] using python: $($PYTHON_BIN --version 2>&1)"

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "[package] PyInstaller not found, installing..."
  "$PYTHON_BIN" -m pip install --user pyinstaller
fi

"$PYTHON_BIN" -m PyInstaller \
  --onefile \
  --name quicut \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --specpath "$BUILD_DIR" \
  src/quicut.py

echo "[package] done: $DIST_DIR/quicut"
