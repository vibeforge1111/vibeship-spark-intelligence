# Getting Started (5 Minutes)

If you are new: follow this page first.
For the full canonical onboarding path, see `docs/SPARK_ONBOARDING_COMPLETE.md`.
For the full map, see `docs/DOCS_INDEX.md`.
Command style: this guide uses explicit interpreter commands (`python -m spark.cli ...`) for portability.

## 0) Prereqs

- Python 3.10+ (Windows one-command bootstrap auto-installs latest Python 3 via `winget` when missing)
- `pip`
- Git
- Windows one-command path: PowerShell
- Mac/Linux one-command path: `curl` + `bash`

## 1) Install

### Option A: Windows One Command (Repo + venv + install + up + health)

```powershell
irm https://raw.githubusercontent.com/vibeforge1111/vibeship-spark-intelligence/main/install.ps1 | iex
```

Optional re-check (from repo root):

```powershell
.\.venv\Scripts\python -m spark.cli up
.\.venv\Scripts\python -m spark.cli health
```

### Option B: Mac/Linux One Command (Repo + venv + install + up)

```bash
curl -fsSL https://raw.githubusercontent.com/vibeforge1111/vibeship-spark-intelligence/main/install.sh | bash
```

Then run a ready check (from repo root):

```bash
./.venv/bin/python -m spark.cli up
./.venv/bin/python -m spark.cli health
```

### Option C: Installer (Recommended for full OpenClaw stack)

- Windows: clone `spark-openclaw-installer` and run `install.ps1`
- Mac/Linux: clone `spark-openclaw-installer` and run `install.sh`

See `README.md` for the exact commands.

### Option D: Manual (Repo)

```bash
cd /path/to/vibeship-spark-intelligence
python3 -m venv .venv
# Mac/Linux:
source .venv/bin/activate
python -m pip install -e .[services]
```

```powershell
# Windows (no activate needed):
cd C:\path\to\vibeship-spark-intelligence
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[services]"
```

If you see `externally-managed-environment`, use the virtualenv block above and
re-run installation inside it.

## 2) Start Services

### Windows (repo)

```bat
start_spark.bat
```

```powershell
# Equivalent without PATH assumptions:
.\.venv\Scripts\python -m spark.cli up
```

### Mac/Linux (repo)

```bash
python -m spark.cli up
# or: spark up
```

## 3) Verify Health

CLI:
```bash
python -m spark.cli health
```

HTTP:
- sparkd liveness: `http://127.0.0.1:8787/health` (plain `ok`)
- sparkd status: `http://127.0.0.1:8787/status` (JSON)
- Mind (if enabled): `http://127.0.0.1:8080/health`

## 4) Observability

- Spark Pulse (web dashboard): `http://localhost:8765`
- Obsidian Observatory: `python scripts/generate_observatory.py --force`

See `docs/OBSIDIAN_OBSERVATORY_GUIDE.md` for full observatory setup.

## 5) Connect Your Coding Agent

If you use Claude Code or Cursor:
- Claude Code: `docs/claude_code.md`
- Cursor/VS Code: `docs/cursor.md`

The goal is simple:
- Spark writes learnings to context files.
- Your agent reads them and adapts.

Next after setup:
- Daily runtime operations and CLI workflow: `docs/QUICKSTART.md`
- Configure behavior (thresholds, timing, gates): `docs/QUICKSTART.md#configuring-tuneables`
- Full config reference (231 keys, 31 sections): `docs/TUNEABLES_REFERENCE.md`

## Troubleshooting (Fast)

- Port already in use: change ports via env (see `lib/ports.py` and `docs/QUICKSTART.md`).
- Health is red: start via `start_spark.bat` / `spark up` (not manual scripts) so watchdog + workers come up correctly.
- Queue shows 0 events: you may simply not have run any tool interactions yet in this session.
