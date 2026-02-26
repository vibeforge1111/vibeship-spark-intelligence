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

REM R3 chip profile defaults (overridable via environment).
if "%SPARK_CHIP_REQUIRE_LEARNING_SCHEMA%"=="" set SPARK_CHIP_REQUIRE_LEARNING_SCHEMA=1
if "%SPARK_CHIP_OBSERVER_ONLY%"=="" set SPARK_CHIP_OBSERVER_ONLY=1
if "%SPARK_CHIP_MIN_LEARNING_EVIDENCE%"=="" set SPARK_CHIP_MIN_LEARNING_EVIDENCE=2
if "%SPARK_CHIP_MIN_CONFIDENCE%"=="" set SPARK_CHIP_MIN_CONFIDENCE=0.65
if "%SPARK_CHIP_MIN_SCORE%"=="" set SPARK_CHIP_MIN_SCORE=0.25
if "%SPARK_CHIP_MERGE_MIN_CONFIDENCE%"=="" set SPARK_CHIP_MERGE_MIN_CONFIDENCE=0.65
if "%SPARK_CHIP_MERGE_MIN_QUALITY%"=="" set SPARK_CHIP_MERGE_MIN_QUALITY=0.62

REM Phase 1 advisory/learning flags (overridable via environment).
if "%SPARK_ADVISORY_AGREEMENT_GATE%"=="" set SPARK_ADVISORY_AGREEMENT_GATE=1
if "%SPARK_ADVISORY_AGREEMENT_MIN_SOURCES%"=="" set SPARK_ADVISORY_AGREEMENT_MIN_SOURCES=2
if "%SPARK_PIPELINE_IMPORTANCE_SAMPLING%"=="" set SPARK_PIPELINE_IMPORTANCE_SAMPLING=1
if "%SPARK_PIPELINE_LOW_KEEP_RATE%"=="" set SPARK_PIPELINE_LOW_KEEP_RATE=0.25
if "%SPARK_MACROS_ENABLED%"=="" set SPARK_MACROS_ENABLED=1
if "%SPARK_MACRO_MIN_COUNT%"=="" set SPARK_MACRO_MIN_COUNT=3

REM Phase 2 memory flags (overridable via environment).
if "%SPARK_MEMORY_PATCHIFIED%"=="" set SPARK_MEMORY_PATCHIFIED=1
if "%SPARK_MEMORY_PATCH_MAX_CHARS%"=="" set SPARK_MEMORY_PATCH_MAX_CHARS=600
if "%SPARK_MEMORY_PATCH_MIN_CHARS%"=="" set SPARK_MEMORY_PATCH_MIN_CHARS=120
if "%SPARK_MEMORY_DELTAS%"=="" set SPARK_MEMORY_DELTAS=1
if "%SPARK_MEMORY_DELTA_MIN_SIM%"=="" set SPARK_MEMORY_DELTA_MIN_SIM=0.86

REM Phase 3 advisory intelligence flags (overridable via environment).
if "%SPARK_OUTCOME_PREDICTOR%"=="" set SPARK_OUTCOME_PREDICTOR=1

REM Advisory: action-first formatting (put Next check command on first line)
if "%SPARK_ADVISORY_ACTION_FIRST%"=="" set SPARK_ADVISORY_ACTION_FIRST=1
REM Advisory route rollout: alpha-first by default. Set canary/engine explicitly to override.
if "%SPARK_ADVISORY_ROUTE%"=="" set SPARK_ADVISORY_ROUTE=alpha

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
