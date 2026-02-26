@echo off
set "PY=%SPARK_PYTHON%"
if "%PY%"=="" set "PY=python"
%PY% adapters\codex_hook_bridge.py %*
