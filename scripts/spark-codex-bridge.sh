#!/usr/bin/env sh
set -e

PY="${SPARK_PYTHON:-python3}"
exec "$PY" adapters/codex_hook_bridge.py "$@"
