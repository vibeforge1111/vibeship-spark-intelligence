#!/usr/bin/env bash
# Spark bootstrap for macOS/Linux
# Clone (if needed) -> create venv -> install -> start services

set -euo pipefail

REPO_URL="https://github.com/vibeforge1111/vibeship-spark-intelligence.git"
TARGET_DIR="$(pwd)/vibeship-spark-intelligence"
SKIP_UP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)
      REPO_URL="$2"
      shift 2
      ;;
    --target-dir)
      TARGET_DIR="$2"
      shift 2
      ;;
    --skip-up)
      SKIP_UP=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 is required but not found in PATH." >&2
    exit 1
  fi
}

resolve_base_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  echo "Python 3.10+ is required but was not found in PATH." >&2
  exit 1
}

echo "============================================="
echo "  SPARK - macOS/Linux bootstrap"
echo "============================================="
echo

need_cmd git
BASE_PY="$(resolve_base_python)"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Cloning repo into: $TARGET_DIR"
  git clone "$REPO_URL" "$TARGET_DIR"
elif [[ ! -f "$TARGET_DIR/pyproject.toml" ]]; then
  echo "Target dir exists but does not look like this repo: $TARGET_DIR" >&2
  exit 1
else
  echo "Using existing repo: $TARGET_DIR"
fi

cd "$TARGET_DIR"

echo "Checking Python version..."
"$BASE_PY" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY

VENV_PY="$TARGET_DIR/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "Creating virtual environment..."
  "$BASE_PY" -m venv .venv
fi

echo "Installing Spark (services extras)..."
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -e ".[services]"

if [[ "$SKIP_UP" -eq 1 ]]; then
  echo
  echo "Install complete."
  echo "Start later with: $VENV_PY -m spark.cli onboard --quick --yes"
  exit 0
fi

echo
"$VENV_PY" -m spark.cli onboard --quick --yes
