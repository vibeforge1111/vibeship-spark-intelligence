#!/usr/bin/env python3
"""Run a real-time OpenClaw x Spark end-to-end benchmark."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib.openclaw_paths import discover_openclaw_workspaces
from lib.production_gates import evaluate_gates, load_live_metrics
from lib.service_control import service_status


SPARK_DIR = Path.home() / ".spark"
HOOK_SPOOL = SPARK_DIR / "openclaw_hook_events.jsonl"
QUEUE_FILE = SPARK_DIR / "queue" / "events.jsonl"
REQUESTS_FILE = SPARK_DIR / "advice_feedback_requests.jsonl"
FEEDBACK_FILE = SPARK_DIR / "advice_feedback.jsonl"
OUTCOME_FILE = SPARK_DIR / "meta_ralph" / "outcome_tracking.json"
ENGINE_FILE = SPARK_DIR / "advisory_engine_alpha.jsonl"
FALLBACK_ADVISORY = SPARK_DIR / "llm_advisory.md"


def _resolve_openclaw_executable() -> Optional[str]:
    candidates = [
        shutil.which("openclaw"),
        shutil.which("openclaw.cmd"),
        str(Path.home() / ".npm-global" / "openclaw.cmd"),
        str(Path.home() / ".npm-global" / "openclaw"),
    ]
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        p = Path(text)
        if p.exists():
            return str(p)
        # Keep PATH-resolved names too.
        if text.lower() in {"openclaw", "openclaw.cmd"}:
            return text
    return None


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _parse_ts(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        ts = float(value)
        return ts / 1000.0 if ts > 2e10 else ts
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _tail_jsonl(path: Path, max_lines: int = 5000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[-max(1, int(max_lines)) :]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _in_window(ts: float, now_ts: float, window_s: float) -> bool:
    return ts > 0 and (now_ts - ts) <= window_s


def _extract_json_blob(text: str) -> Optional[Dict[str, Any]]:
    blob = str(text or "").strip()
    if not blob:
        return None
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(blob):
        if ch != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(blob[idx:])
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _run_canary_turn(agent: str, prompt: str, timeout_s: int) -> Dict[str, Any]:
    exe = _resolve_openclaw_executable()
    if not exe:
        return {
            "prompt": prompt,
            "exit_code": 127,
            "duration_ms": 0,
            "has_json_payload": False,
            "payload_count": 0,
            "response_preview": "",
            "logs_tail": "openclaw executable not found",
        }

    cmd = [exe, "agent", "--local", "--agent", agent, "-m", prompt, "--json"]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(30, int(timeout_s)),
            check=False,
        )
    except FileNotFoundError:
        return {
            "prompt": prompt,
            "exit_code": 127,
            "duration_ms": int((time.time() - t0) * 1000),
            "has_json_payload": False,
            "payload_count": 0,
            "response_preview": "",
            "logs_tail": f"openclaw executable not found: {exe}",
        }
    except subprocess.TimeoutExpired as e:
        output = "\n".join([str(e.stdout or ""), str(e.stderr or "")]).strip()
        return {
            "prompt": prompt,
            "exit_code": 124,
            "duration_ms": int((time.time() - t0) * 1000),
            "has_json_payload": False,
            "payload_count": 0,
            "response_preview": "",
            "logs_tail": (output[-600:] if output else "canary timed out"),
        }
    elapsed_ms = int((time.time() - t0) * 1000)
    combined = "\n".join([proc.stdout or "", proc.stderr or ""]).strip()
    payload = _extract_json_blob(combined)
    text_payloads = list((payload or {}).get("payloads") or [])
    return {
        "prompt": prompt,
        "exit_code": int(proc.returncode),
        "duration_ms": elapsed_ms,
        "has_json_payload": payload is not None,
        "payload_count": len(text_payloads),
        "response_preview": (
            str((text_payloads[0] or {}).get("text") or "")[:240]
            if text_payloads and isinstance(text_payloads[0], dict)
            else ""
        ),
        "logs_tail": combined[-600:],
    }


def _canary_suite(agent: str, timeout_s: int) -> Dict[str, Any]:
    prompts = [
        (
            "Spark realtime benchmark canary A. Run one Bash tool call to execute "
            "`echo SPARK_REALTIME_CANARY_A`, then provide one actionable recommendation."
        ),
        (
            "Spark realtime benchmark canary B. Read AGENTS.md from the workspace, then "
            "reply with one action and one measurable success criterion."
        ),
    ]
    turns = [_run_canary_turn(agent=agent, prompt=p, timeout_s=timeout_s) for p in prompts]
    success = all(t["exit_code"] == 0 and t["has_json_payload"] for t in turns)
    return {"agent": agent, "turns": turns, "ok": success}


def _hook_metrics(now_ts: float, window_s: float) -> Dict[str, Any]:
    rows = _tail_jsonl(HOOK_SPOOL, max_lines=5000)
    pairs: List[Tuple[float, str]] = []
    for row in rows:
        ts = _parse_ts(row.get("ts") or row.get("timestamp"))
        hook = str(row.get("hook") or row.get("event") or "").strip().lower()
        if hook in {"llm_input", "llm_output"} and ts > 0:
            pairs.append((ts, hook))
    recent = [p for p in pairs if _in_window(p[0], now_ts, window_s)]
    counts = Counter(h for _, h in recent)
    latest_ts = max((ts for ts, _ in pairs), default=0.0)
    return {
        "path": str(HOOK_SPOOL),
        "exists": HOOK_SPOOL.exists(),
        "rows_tail": len(pairs),
        "window_rows": len(recent),
        "llm_input_window": int(counts.get("llm_input", 0)),
        "llm_output_window": int(counts.get("llm_output", 0)),
        "latest_age_s": (round(now_ts - latest_ts, 2) if latest_ts > 0 else None),
    }


def _queue_hook_metrics(now_ts: float, window_s: float) -> Dict[str, Any]:
    rows = _tail_jsonl(QUEUE_FILE, max_lines=12000)
    hook_ts: List[float] = []
    for row in rows:
        data = row.get("data") or {}
        payload = data.get("payload") if isinstance(data, dict) else {}
        if not isinstance(payload, dict):
            continue
        if str(payload.get("type") or "") != "openclaw_hook":
            continue
        ts = _safe_float(row.get("timestamp"))
        if ts > 0:
            hook_ts.append(ts)
    recent = [ts for ts in hook_ts if _in_window(ts, now_ts, window_s)]
    latest_ts = max(hook_ts) if hook_ts else 0.0
    return {
        "path": str(QUEUE_FILE),
        "exists": QUEUE_FILE.exists(),
        "hook_rows_tail": len(hook_ts),
        "hook_rows_window": len(recent),
        "latest_age_s": (round(now_ts - latest_ts, 2) if latest_ts > 0 else None),
    }


def _advisory_engine_metrics(now_ts: float, window_s: float) -> Dict[str, Any]:
    rows = _tail_jsonl(ENGINE_FILE, max_lines=10000)
    recent: List[Dict[str, Any]] = []
    for row in rows:
        ts = _safe_float(row.get("ts"))
        if _in_window(ts, now_ts, window_s):
            recent.append(row)
    event_counts = Counter(str(r.get("event") or "unknown") for r in recent)
    route_counts = Counter(str(r.get("route") or "unknown") for r in recent)
    return {
        "path": str(ENGINE_FILE),
        "exists": ENGINE_FILE.exists(),
        "rows_window": len(recent),
        "event_counts": dict(event_counts),
        "route_counts": dict(route_counts),
    }


def _coverage(rows: Iterable[Dict[str, Any]], key: str) -> Optional[float]:
    data = list(rows)
    if not data:
        return None
    good = 0
    for row in data:
        value = str(row.get(key) or "").strip()
        if value:
            good += 1
    return round((good / len(data)) * 100.0, 2)


def _feedback_metrics(now_ts: float, window_s: float) -> Dict[str, Any]:
    requests = _tail_jsonl(REQUESTS_FILE, max_lines=8000)
    feedback = _tail_jsonl(FEEDBACK_FILE, max_lines=8000)
    req_recent = [r for r in requests if _in_window(_safe_float(r.get("created_at")), now_ts, window_s)]
    fb_recent = [r for r in feedback if _in_window(_safe_float(r.get("created_at")), now_ts, window_s)]
    req_schema2 = [r for r in req_recent if int(r.get("schema_version") or 0) >= 2]
    fb_schema2 = [r for r in fb_recent if int(r.get("schema_version") or 0) >= 2]
    return {
        "requests_file": str(REQUESTS_FILE),
        "feedback_file": str(FEEDBACK_FILE),
        "requests_window": len(req_recent),
        "requests_schema_v2_window": len(req_schema2),
        "requests_trace_coverage_pct": _coverage(req_schema2, "trace_id"),
        "requests_run_id_coverage_pct": _coverage(req_schema2, "run_id"),
        "requests_group_key_coverage_pct": _coverage(req_schema2, "advisory_group_key"),
        "feedback_window": len(fb_recent),
        "feedback_schema_v2_window": len(fb_schema2),
        "feedback_trace_coverage_pct": _coverage(fb_schema2, "trace_id"),
    }


def _outcome_metrics(now_ts: float, window_s: float) -> Dict[str, Any]:
    obj = _read_json(OUTCOME_FILE)
    records = list(obj.get("records") or [])
    recent: List[Dict[str, Any]] = []
    for row in records:
        ts = max(_parse_ts(row.get("outcome_at")), _parse_ts(row.get("retrieved_at")))
        if _in_window(ts, now_ts, window_s):
            recent.append(row)
    strict = []
    for row in recent:
        rt = str(row.get("trace_id") or "").strip()
        ot = str(row.get("outcome_trace_id") or "").strip()
        if rt and ot and rt == ot:
            strict.append(row)
    strict_with_outcome = [
        r
        for r in strict
        if str(r.get("outcome") or "").strip().lower() in {"good", "bad", "neutral"}
    ]
    strict_good = [
        r
        for r in strict_with_outcome
        if str(r.get("outcome") or "").strip().lower() == "good"
    ]
    source_mix = Counter(str(r.get("source") or "unknown") for r in strict_with_outcome)
    outcome_mix = Counter(str(r.get("outcome") or "unknown") for r in strict_with_outcome)
    strict_eff = (len(strict_good) / len(strict_with_outcome)) if strict_with_outcome else None
    return {
        "path": str(OUTCOME_FILE),
        "exists": OUTCOME_FILE.exists(),
        "records_window": len(recent),
        "strict_window": len(strict),
        "strict_with_outcome_window": len(strict_with_outcome),
        "strict_effectiveness_window": (round(strict_eff, 4) if strict_eff is not None else None),
        "source_mix": dict(source_mix),
        "outcome_mix": dict(outcome_mix),
    }


def _workspace_metrics(now_ts: float) -> Dict[str, Any]:
    rows = []
    for ws in discover_openclaw_workspaces(include_nonexistent=True):
        context = ws / "SPARK_CONTEXT.md"
        advisory = ws / "SPARK_ADVISORY.md"
        notif = ws / "SPARK_NOTIFICATIONS.md"
        row = {
            "workspace": str(ws),
            "exists": ws.exists(),
            "context_exists": context.exists(),
            "advisory_exists": advisory.exists(),
            "notifications_exists": notif.exists(),
            "context_age_s": (round(now_ts - context.stat().st_mtime, 2) if context.exists() else None),
            "advisory_age_s": (round(now_ts - advisory.stat().st_mtime, 2) if advisory.exists() else None),
        }
        rows.append(row)

    existing = [r for r in rows if r.get("exists")]
    any_context = any(r.get("context_exists") for r in existing)
    any_advisory = any(r.get("advisory_exists") for r in existing)
    fallback_age = (
        round(now_ts - FALLBACK_ADVISORY.stat().st_mtime, 2)
        if FALLBACK_ADVISORY.exists()
        else None
    )
    return {
        "workspaces": rows,
        "existing_workspaces": len(existing),
        "any_context": any_context,
        "any_advisory": any_advisory,
        "fallback_advisory_exists": FALLBACK_ADVISORY.exists(),
        "fallback_advisory_age_s": fallback_age,
    }


def _advisory_emit_health(
    *,
    engine_metrics: Dict[str, Any],
    workspace_metrics: Dict[str, Any],
    window_s: float,
) -> Dict[str, Any]:
    event_counts = dict(engine_metrics.get("event_counts") or {})
    emitted = int(event_counts.get("emitted") or 0)
    dedupe_suppressed = int(event_counts.get("global_dedupe_suppressed") or 0)

    advisory_ages = [
        _safe_float(row.get("advisory_age_s"))
        for row in list(workspace_metrics.get("workspaces") or [])
        if row.get("advisory_exists")
    ]
    fallback_age = _safe_float(workspace_metrics.get("fallback_advisory_age_s"))
    recent_workspace_advisory = any(age >= 0 and age <= window_s for age in advisory_ages)
    recent_fallback_advisory = bool(
        workspace_metrics.get("fallback_advisory_exists")
        and fallback_age >= 0
        and fallback_age <= window_s
    )
    recent_advisory_delivery = recent_workspace_advisory or recent_fallback_advisory

    if emitted >= 1:
        mode = "emitted"
        ok = True
    elif dedupe_suppressed >= 1 and recent_advisory_delivery:
        mode = "dedupe_suppressed_recent_delivery"
        ok = True
    else:
        mode = "no_effective_delivery_signal"
        ok = False

    return {
        "ok": bool(ok),
        "mode": mode,
        "emitted": emitted,
        "global_dedupe_suppressed": dedupe_suppressed,
        "recent_workspace_advisory": bool(recent_workspace_advisory),
        "recent_fallback_advisory": bool(recent_fallback_advisory),
    }


def _check(ok: bool, name: str, detail: Any, failure_level: str = "fail") -> Dict[str, Any]:
    level = "pass" if ok else failure_level
    return {"name": name, "status": level, "detail": detail}


def _render_md(report: Dict[str, Any]) -> str:
    checks = list(report.get("checks") or [])
    lines = [
        "# OpenClaw Realtime E2E Benchmark",
        "",
        f"- Generated: `{report.get('generated_at')}`",
        f"- Window minutes: `{report.get('window_minutes')}`",
        f"- Status: `{report.get('status')}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for row in checks:
        lines.append(
            f"| {row.get('name')} | `{row.get('status')}` | `{str(row.get('detail'))[:180]}` |"
        )

    hooks = report.get("hook_metrics") or {}
    queue = report.get("queue_hook_metrics") or {}
    engine = report.get("advisory_engine_metrics") or {}
    outcomes = report.get("outcome_metrics") or {}
    feedback = report.get("feedback_metrics") or {}
    lines.extend(
        [
            "",
            "## Live Signal Snapshot",
            "",
            f"- Hook spool (window): input={hooks.get('llm_input_window')} output={hooks.get('llm_output_window')}",
            f"- Hook ingest queue rows (window): {queue.get('hook_rows_window')}",
            f"- Advisory engine rows (window): {engine.get('rows_window')} events={engine.get('event_counts')}",
            f"- Strict outcomes (window): {outcomes.get('strict_with_outcome_window')} effectiveness={outcomes.get('strict_effectiveness_window')}",
            f"- Feedback requests schema_v2 (window): {feedback.get('requests_schema_v2_window')} trace_coverage={feedback.get('requests_trace_coverage_pct')}",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def run_benchmark(
    *,
    window_minutes: int,
    run_canary: bool,
    canary_agent: str,
    canary_timeout_s: int,
    settle_seconds: int,
) -> Dict[str, Any]:
    now_ts = time.time()
    window_s = max(60, int(window_minutes) * 60)

    canary = None
    if run_canary:
        canary = _canary_suite(agent=canary_agent, timeout_s=canary_timeout_s)
        if settle_seconds > 0:
            time.sleep(max(0, int(settle_seconds)))
        now_ts = time.time()

    svc = service_status(bridge_stale_s=120, include_pulse_probe=False)
    hooks = _hook_metrics(now_ts=now_ts, window_s=window_s)
    queue = _queue_hook_metrics(now_ts=now_ts, window_s=window_s)
    engine = _advisory_engine_metrics(now_ts=now_ts, window_s=window_s)
    feedback = _feedback_metrics(now_ts=now_ts, window_s=window_s)
    outcomes = _outcome_metrics(now_ts=now_ts, window_s=window_s)
    workspace = _workspace_metrics(now_ts=now_ts)
    advisory_emit = _advisory_emit_health(
        engine_metrics=engine,
        workspace_metrics=workspace,
        window_s=window_s,
    )

    live_metrics = load_live_metrics()
    gates = evaluate_gates(live_metrics)

    core_ok = all(
        bool((svc.get(name) or {}).get("running"))
        for name in ("sparkd", "bridge_worker", "scheduler", "watchdog")
    )
    checks = [
        _check(core_ok, "core_services_running", {k: (svc.get(k) or {}).get("running") for k in ("sparkd", "bridge_worker", "scheduler", "watchdog")}),
        _check(
            hooks.get("llm_input_window", 0) >= 1 and hooks.get("llm_output_window", 0) >= 1,
            "hook_spool_llm_input_output",
            {"llm_input_window": hooks.get("llm_input_window"), "llm_output_window": hooks.get("llm_output_window")},
        ),
        _check(
            queue.get("hook_rows_window", 0) >= 1,
            "hook_ingested_to_queue",
            {"hook_rows_window": queue.get("hook_rows_window")},
        ),
        _check(
            int(engine.get("rows_window") or 0) >= 1,
            "advisory_engine_activity",
            {"rows_window": engine.get("rows_window"), "events": engine.get("event_counts")},
            failure_level="warn",
        ),
        _check(
            bool(advisory_emit.get("ok")),
            "advisory_engine_emitted_nonzero",
            advisory_emit,
            failure_level="warn",
        ),
        _check(
            workspace.get("any_context", False),
            "workspace_context_delivery",
            {"existing_workspaces": workspace.get("existing_workspaces"), "any_context": workspace.get("any_context")},
        ),
        _check(
            bool(workspace.get("any_advisory") or workspace.get("fallback_advisory_exists")),
            "advisory_delivery_surface",
            {
                "any_workspace_advisory": workspace.get("any_advisory"),
                "fallback_advisory_exists": workspace.get("fallback_advisory_exists"),
            },
            failure_level="warn",
        ),
        _check(
            int(feedback.get("requests_schema_v2_window") or 0) > 0,
            "schema_v2_feedback_requests",
            {
                "requests_schema_v2_window": feedback.get("requests_schema_v2_window"),
                "trace_coverage_pct": feedback.get("requests_trace_coverage_pct"),
            },
            failure_level="warn",
        ),
        _check(
            int(outcomes.get("strict_with_outcome_window") or 0) >= 1,
            "strict_outcome_signal",
            {
                "strict_with_outcome_window": outcomes.get("strict_with_outcome_window"),
                "strict_effectiveness_window": outcomes.get("strict_effectiveness_window"),
            },
            failure_level="warn",
        ),
        _check(
            bool(gates.get("ready")),
            "production_gates_ready",
            {"ready": gates.get("ready"), "failed_checks": [c.get("name") for c in gates.get("checks", []) if not c.get("ok")]},
        ),
    ]

    if canary is not None:
        checks.append(
            _check(
                bool(canary.get("ok")),
                "openclaw_canary_turns",
                {"agent": canary.get("agent"), "turns_ok": [t.get("exit_code") == 0 and t.get("has_json_payload") for t in canary.get("turns", [])]},
                failure_level="warn",
            )
        )

    statuses = [c.get("status") for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_minutes": int(window_minutes),
        "status": overall,
        "checks": checks,
        "canary": canary,
        "service_status": svc,
        "hook_metrics": hooks,
        "queue_hook_metrics": queue,
        "advisory_engine_metrics": engine,
        "feedback_metrics": feedback,
        "outcome_metrics": outcomes,
        "workspace_metrics": workspace,
        "production_gates": {
            "metrics": asdict(live_metrics),
            "result": gates,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Realtime OpenClaw x Spark E2E benchmark")
    ap.add_argument("--window-minutes", type=int, default=60, help="Recent window for live-signal checks")
    ap.add_argument("--run-canary", action=argparse.BooleanOptionalAction, default=True, help="Run live OpenClaw canary turns before checks")
    ap.add_argument("--canary-agent", default="spark-speed", help="OpenClaw agent id used for canary turns")
    ap.add_argument("--canary-timeout-s", type=int, default=120, help="Per-turn canary timeout")
    ap.add_argument("--settle-seconds", type=int, default=10, help="Wait time after canary before sampling files")
    ap.add_argument("--out-dir", type=Path, default=Path("docs") / "reports" / "openclaw")
    args = ap.parse_args()

    report = run_benchmark(
        window_minutes=int(args.window_minutes),
        run_canary=bool(args.run_canary),
        canary_agent=str(args.canary_agent),
        canary_timeout_s=int(args.canary_timeout_s),
        settle_seconds=int(args.settle_seconds),
    )

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{ts}_openclaw_realtime_e2e_benchmark.json"
    md_path = out_dir / f"{ts}_openclaw_realtime_e2e_benchmark.md"

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")

    print(str(json_path))
    print(str(md_path))
    return 0 if report.get("status") != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
