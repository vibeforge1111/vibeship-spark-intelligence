#!/usr/bin/env python3
"""Wipe and regenerate Spark Observatory surfaces for Alpha runtime."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from lib.observatory.config import load_config


ROOT = Path(__file__).resolve().parents[1]
LOCAL_OBS = ROOT / "_observatory"
REPORTS_DIR = ROOT / "docs" / "reports"


def _run(cmd: List[str]) -> Dict[str, Any]:
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "cmd": cmd,
        "returncode": int(proc.returncode),
        "stdout_tail": (proc.stdout or "")[-1000:],
        "stderr_tail": (proc.stderr or "")[-1000:],
        "ok": proc.returncode == 0,
    }


def _delete_path(path: Path, removed: List[str]) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    removed.append(str(path))


def main() -> int:
    ap = argparse.ArgumentParser(description="Wipe and regenerate observatory outputs for alpha.")
    ap.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    ap.add_argument("--keep-reports", action="store_true", help="Keep docs/reports files.")
    args = ap.parse_args()

    cfg = load_config()
    vault_observatory = Path(cfg.vault_dir).expanduser() / "_observatory"
    report_patterns = (
        "*_codex_hooks.md",
        "*_workflow_fidelity.md",
        "*_memory_quality_observatory.md",
        "*_alpha_intelligence_flow.md",
    )

    targets = [LOCAL_OBS, vault_observatory]
    if not args.keep_reports:
        for pattern in report_patterns:
            targets.extend(REPORTS_DIR.glob(pattern))

    if not args.yes:
        print("This will delete observatory outputs:")
        for t in targets:
            print(f"- {t}")
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print(json.dumps({"ok": False, "skipped": True}, indent=2))
            return 1

    removed: List[str] = []
    for target in targets:
        _delete_path(target, removed)

    runs = [
        _run([sys.executable, "scripts/generate_observatory.py", "--force"]),
        _run([sys.executable, "scripts/codex_hooks_observatory.py"]),
        _run([sys.executable, "scripts/workflow_fidelity_observatory.py"]),
        _run([sys.executable, "scripts/memory_quality_observatory.py"]),
        _run([sys.executable, "scripts/alpha_intelligence_flow_status.py"]),
    ]

    ok = all(bool(r.get("ok")) for r in runs)
    payload = {
        "ok": ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "removed_count": len(removed),
        "removed": removed,
        "regeneration_runs": runs,
        "vault_observatory": str(vault_observatory),
        "local_observatory": str(LOCAL_OBS),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

