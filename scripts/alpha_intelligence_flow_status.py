#!/usr/bin/env python3
"""Generate Alpha intelligence-flow status snapshot and tracker row."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.alpha_preflight_bundle import evaluate_alpha_preflight
from lib.observatory.config import load_config

OBS_DIR = ROOT / "_observatory"
SNAPSHOT_JSON = OBS_DIR / "alpha_intelligence_flow_snapshot.json"
SNAPSHOT_MD = OBS_DIR / "alpha_intelligence_flow.md"
TRACKER_JSONL = Path.home() / ".spark" / "logs" / "alpha_intelligence_tracker.jsonl"


def _status_label(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=True) + "\n")


def _render_markdown(payload: Dict[str, Any]) -> str:
    ts = str(payload.get("timestamp") or "")
    ready = bool(payload.get("ready", False))
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    services = payload.get("services") if isinstance(payload.get("services"), dict) else {}
    codex = payload.get("codex_hooks") if isinstance(payload.get("codex_hooks"), dict) else {}
    codex_summary = codex.get("summary") if isinstance(codex.get("summary"), dict) else {}
    codex_derived = codex_summary.get("derived") if isinstance(codex_summary.get("derived"), dict) else {}
    production = payload.get("production_gates") if isinstance(payload.get("production_gates"), dict) else {}

    lines: List[str] = []
    lines.append("# Alpha Intelligence Flow Status")
    lines.append("")
    lines.append(f"- generated_at_utc: `{ts}`")
    lines.append(f"- bundled_ready: `{ready}`")
    lines.append("")
    lines.append("## Flow Path (Alpha Runtime)")
    lines.append("1. `codex_hook_bridge` maps session rows into hook events.")
    lines.append("2. `hooks/observe.py` processes events and forwards intelligence signals.")
    lines.append("3. `lib/advisory_engine_alpha.py` runs pre/post/prompt advisory loop.")
    lines.append("4. Queue/bridge/memory/distillation pipelines update long-term intelligence.")
    lines.append("5. `lib/production_gates.py` validates production readiness.")
    lines.append("")
    lines.append("## Health Snapshot")
    lines.append("| Check | Status | Value |")
    lines.append("|---|---|---|")
    for row in checks:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        status = _status_label(bool(row.get("ok")))
        value = row.get("value")
        lines.append(f"| `{name}` | `{status}` | `{json.dumps(value, ensure_ascii=True)[:140]}` |")

    lines.append("")
    lines.append("## Key Metrics")
    lines.append(f"- production_gates: `{production.get('passed')}/{production.get('total')}`")
    lines.append(f"- codex_mode: `{codex_summary.get('mode')}`")
    lines.append(f"- codex_observe_success_ratio: `{codex_derived.get('observe_success_ratio_window')}`")
    lines.append(f"- codex_observe_latency_p95_ms: `{codex_derived.get('observe_latency_p95_ms')}`")
    lines.append(f"- codex_unknown_exit_ratio: `{codex_derived.get('unknown_exit_ratio')}`")
    lines.append(f"- codex_window_activity_rows: `{codex_derived.get('window_activity_rows')}`")
    lines.append("")
    lines.append("## Services")
    for name in ("sparkd", "bridge_worker", "scheduler", "watchdog", "codex_bridge", "mind", "pulse"):
        svc = services.get(name) if isinstance(services.get(name), dict) else {}
        lines.append(f"- {name}: `running={svc.get('running')}`")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    payload = evaluate_alpha_preflight(bridge_stale_s=90)
    payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()

    OBS_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    md = _render_markdown(payload)
    SNAPSHOT_MD.write_text(md, encoding="utf-8")

    cfg = load_config()
    vault_page = Path(cfg.vault_dir).expanduser() / "_observatory" / "alpha_intelligence_flow.md"
    try:
        vault_page.parent.mkdir(parents=True, exist_ok=True)
        vault_page.write_text(md, encoding="utf-8")
    except Exception:
        pass

    codex = payload.get("codex_hooks") if isinstance(payload.get("codex_hooks"), dict) else {}
    codex_summary = codex.get("summary") if isinstance(codex.get("summary"), dict) else {}
    codex_derived = codex_summary.get("derived") if isinstance(codex_summary.get("derived"), dict) else {}
    tracker_row = {
        "ts": datetime.now(timezone.utc).timestamp(),
        "adapter": "alpha_intelligence_tracker",
        "ready": bool(payload.get("ready")),
        "production_ready": bool((payload.get("production_gates") or {}).get("ready")),
        "codex_gates_passing": bool((codex.get("gates") or {}).get("passing")),
        "codex_observe_success_ratio": codex_derived.get("observe_success_ratio_window"),
        "codex_observe_latency_p95_ms": codex_derived.get("observe_latency_p95_ms"),
        "codex_unknown_exit_ratio": codex_derived.get("unknown_exit_ratio"),
    }
    _append_jsonl(TRACKER_JSONL, tracker_row)

    print(
        json.dumps(
            {
                "ok": True,
                "ready": bool(payload.get("ready")),
                "snapshot_json": str(SNAPSHOT_JSON),
                "snapshot_md": str(SNAPSHOT_MD),
                "tracker_jsonl": str(TRACKER_JSONL),
                "vault_md": str(vault_page),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
