@echo off
REM Spark Intelligence - Windows Startup Script
REM Starts: mind (8080), sparkd (8787), bridge_worker, pulse (8765), watchdog

setlocal
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
if "%SPARK_PULSE_DIR%"=="" (
    set "SPARK_PULSE_DIR=%~dp0..\vibeship-spark-pulse"
    if not exist "%SPARK_PULSE_DIR%\app.py" echo [warn] vibeship-spark-pulse not found. Set SPARK_PULSE_DIR env var.
)
cd /d %~dp0

REM Keep runtime behavior in tuneables/config_authority; only set alpha safety contract defaults here.
if "%SPARK_ADVISORY_ROUTE%"=="" set SPARK_ADVISORY_ROUTE=alpha
if "%SPARK_ADVISORY_ALPHA_ENABLED%"=="" set SPARK_ADVISORY_ALPHA_ENABLED=1
if "%SPARK_MEMORY_SPINE_CANONICAL%"=="" set SPARK_MEMORY_SPINE_CANONICAL=1
if "%SPARK_VALIDATE_AND_STORE%"=="" set SPARK_VALIDATE_AND_STORE=1
if "%SPARK_BRIDGE_LLM_ADVISORY_SIDECAR_ENABLED%"=="" set SPARK_BRIDGE_LLM_ADVISORY_SIDECAR_ENABLED=0
if "%SPARK_BRIDGE_LLM_EIDOS_SIDECAR_ENABLED%"=="" set SPARK_BRIDGE_LLM_EIDOS_SIDECAR_ENABLED=0
if "%SPARK_EMBED_BACKEND%"=="" set SPARK_EMBED_BACKEND=auto

REM Mind is now managed by service_control.py (spark up/down).
:start_spark
echo.
echo =============================================
echo   SPARK - Self-Evolving Intelligence Layer
echo =============================================
echo.

set "SPARK_ARGS="
if /I "%SPARK_LITE%"=="1" set "SPARK_ARGS=--lite"
if /I "%SPARK_NO_MIND%"=="1" set "SPARK_ARGS=%SPARK_ARGS% --no-mind"
if /I "%SPARK_NO_PULSE%"=="1" set "SPARK_ARGS=%SPARK_ARGS% --no-pulse"
if /I "%SPARK_NO_WATCHDOG%"=="1" set "SPARK_ARGS=%SPARK_ARGS% --no-watchdog"

python -m spark.cli up %SPARK_ARGS%
python -m spark.cli services

echo.
echo Press any key to exit (services will continue running)...
pause > nul
