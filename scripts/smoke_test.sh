#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[smoke] ffmpeg not found; running dry-run only"
  touch "$TMP_DIR/input.mp4"
  "$PYTHON_BIN" src/quicut.py \
    --input "$TMP_DIR/input.mp4" \
    --duration 30 \
    --cuts 10 20 \
    --list-segments \
    --plan-json "$TMP_DIR/plan.json" \
    --dry-run
  echo "[smoke] dry-run smoke test passed"
  exit 0
fi

ffmpeg -f lavfi -i testsrc=size=320x240:rate=25 -t 5 -pix_fmt yuv420p "$TMP_DIR/input.mp4" -y -loglevel error

"$PYTHON_BIN" src/quicut.py \
  --input "$TMP_DIR/input.mp4" \
  --cuts 00:00:01 00:00:03 \
  --output-dir "$TMP_DIR/output" \
  --mode copy

count="$(find "$TMP_DIR/output" -name '*.mp4' | wc -l | tr -d ' ')"
if [ "$count" != "3" ]; then
  echo "[smoke] expected 3 output files, got $count"
  exit 1
fi

echo "[smoke] full smoke test passed"
