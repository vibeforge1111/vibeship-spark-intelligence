"""Generate a reverse-engineered advisory path page for Obsidian."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .config import spark_dir

_SPARK_DIR = spark_dir()
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return data if isinstance(data, dict) else {}


def _read_json_array(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _read_jsonl(path: Path, max_rows: int = 6000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        return []
    if max_rows > 0 and len(rows) > max_rows:
        rows = rows[-max_rows:]
    return rows


def _parse_ts(row: Dict[str, Any]) -> float:
    for key in ("ts", "timestamp", "created_ts", "updated_ts"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except Exception:
                pass
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return float(dt.timestamp())
            except Exception:
                pass
    return 0.0


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _fmt_pct(part: float, whole: float) -> str:
    if whole <= 0:
        return "0.0%"
    return f"{(100.0 * float(part) / float(whole)):.1f}%"


def _classify_reason(reason: str) -> str:
    text = str(reason or "").strip().lower()
    if not text:
        return "other"
    if "global_dedupe" in text:
        return "global_dedupe"
    if "fallback_budget" in text or "fallback budget" in text:
        return "fallback_rate_limit"
    if "budget exhausted" in text:
        return "budget_exhausted"
    if "on cooldown" in text:
        return "tool_cooldown"
    if "shown " in text and "ttl" in text:
        return "shown_ttl"
    if "phase=" in text or "during exploration phase" in text:
        return "context_phase_guard"
    if "context_repeat" in text or "early_exit_context_repeat" in text:
        return "context_repeat"
    if "duplicate" in text or "repeat" in text:
        return "duplicate_repeat"
    return "other"


def _top(counter: Counter, limit: int = 8) -> List[tuple[str, int]]:
    out = []
    for key, value in counter.most_common(limit):
        out.append((str(key), int(value)))
    return out


def _window_rows(rows: List[Dict[str, Any]], window_s: int) -> List[Dict[str, Any]]:
    if not rows:
        return []
    cutoff = time.time() - float(window_s)
    out: List[Dict[str, Any]] = []
    for row in rows:
        ts = _parse_ts(row)
        if ts <= 0 or ts >= cutoff:
            out.append(row)
    return out


def _collect_runtime(window_s: int = 86400) -> Dict[str, Any]:
    ledger_file = _SPARK_DIR / "advisory_decision_ledger.jsonl"
    emit_file = _SPARK_DIR / "advisory_emit.jsonl"
    engine_file = _SPARK_DIR / "advisory_engine_alpha.jsonl"
    implicit_file = _SPARK_DIR / "advisor" / "implicit_feedback.jsonl"

    ledger_rows = _window_rows(_read_jsonl(ledger_file, max_rows=12000), window_s=window_s)
    ledger_source = "advisory_decision_ledger"
    if not ledger_rows:
        engine_rows = _window_rows(_read_jsonl(engine_file, max_rows=12000), window_s=window_s)
        if engine_rows:
            ledger_source = "advisory_engine_alpha_fallback"
            normalized: List[Dict[str, Any]] = []
            for row in engine_rows:
                event = str(row.get("event") or "").strip().lower()
                if event == "emitted":
                    normalized.append({**row, "outcome": "emitted"})
                elif event in {
                    "gate_no_emit",
                    "context_repeat_blocked",
                    "text_repeat_blocked",
                    "question_like_blocked",
                    "global_dedupe_suppressed",
                    "emit_failed",
                    "synth_empty",
                    "no_gate_emissions",
                    "no_ranked_advice",
                    "exception",
                }:
                    normalized.append({**row, "outcome": "blocked"})
            ledger_rows = normalized
        else:
            emit_rows = _window_rows(_read_jsonl(emit_file, max_rows=12000), window_s=window_s)
            if emit_rows:
                ledger_source = "advisory_emit_fallback"
                ledger_rows = [{**row, "outcome": "emitted"} for row in emit_rows]
    implicit_rows = _window_rows(_read_jsonl(implicit_file, max_rows=12000), window_s=window_s)

    outcomes: Counter = Counter()
    suppress_buckets: Counter = Counter()
    suppress_reasons: Counter = Counter()
    tools: Counter = Counter()
    routes: Counter = Counter()
    sources: Counter = Counter()

    newest_ts = 0.0
    for row in ledger_rows:
        ts = _parse_ts(row)
        newest_ts = max(newest_ts, ts)

        outcome = str(row.get("outcome") or "unknown").strip().lower() or "unknown"
        outcomes[outcome] += 1

        tool = str(row.get("tool") or "?").strip() or "?"
        route = str(row.get("route") or "?").strip() or "?"
        tools[tool] += 1
        routes[route] += 1

        row_sources = row.get("source_counts")
        if isinstance(row_sources, dict):
            for source_name, source_count in row_sources.items():
                try:
                    sources[str(source_name)] += int(source_count or 0)
                except Exception:
                    continue

        found_reasons = False
        for entry in row.get("suppressed_reasons") or []:
            reason = ""
            count = 1
            if isinstance(entry, dict):
                reason = str(entry.get("reason") or "").strip()
                try:
                    count = max(1, int(entry.get("count") or 1))
                except Exception:
                    count = 1
            elif isinstance(entry, str):
                reason = entry.strip()
            if not reason:
                continue
            found_reasons = True
            suppress_reasons[reason] += count
            suppress_buckets[_classify_reason(reason)] += count

        if not found_reasons:
            for entry in row.get("suppressed") or []:
                if not isinstance(entry, dict):
                    continue
                reason = str(entry.get("reason") or "unknown").strip()
                if not reason:
                    continue
                synthetic = f"global_dedupe:{reason}"
                suppress_reasons[synthetic] += 1
                suppress_buckets[_classify_reason(synthetic)] += 1

    feedback_signals: Counter = Counter()
    feedback_tools: Counter = Counter()
    for row in implicit_rows:
        signal = str(row.get("signal") or "unknown").strip().lower() or "unknown"
        tool = str(row.get("tool") or "?").strip() or "?"
        feedback_signals[signal] += 1
        feedback_tools[tool] += 1

    followed = int(feedback_signals.get("followed", 0) + feedback_signals.get("helpful", 0))
    not_followed = int(
        feedback_signals.get("ignored", 0)
        + feedback_signals.get("unhelpful", 0)
        + feedback_signals.get("not_followed", 0)
    )
    feedback_eval_total = followed + not_followed

    total_rows = len(ledger_rows)
    emitted = int(outcomes.get("emitted", 0))
    blocked = int(outcomes.get("blocked", 0))

    return {
        "window_s": int(window_s),
        "ledger_source": ledger_source,
        "ledger_file": str(ledger_file),
        "emit_file": str(emit_file),
        "engine_file": str(engine_file),
        "implicit_file": str(implicit_file),
        "ledger_rows": total_rows,
        "outcomes": dict(outcomes),
        "emitted": emitted,
        "blocked": blocked,
        "emit_rate": _fmt_pct(emitted, max(total_rows, 1)),
        "latest_ledger_ts": newest_ts,
        "suppression_buckets": dict(suppress_buckets),
        "suppression_reasons_top": _top(suppress_reasons, limit=12),
        "tools_top": _top(tools, limit=8),
        "routes_top": _top(routes, limit=8),
        "sources_top": _top(sources, limit=10),
        "implicit_rows": len(implicit_rows),
        "feedback_signals": dict(feedback_signals),
        "followed": followed,
        "not_followed": not_followed,
        "follow_rate": _fmt_pct(followed, max(feedback_eval_total, 1)),
        "feedback_tools_top": _top(feedback_tools, limit=8),
    }


def _collect_tuneables() -> Dict[str, Any]:
    tuneables = _read_json(_SPARK_DIR / "tuneables.json")
    engine = tuneables.get("advisory_engine") if isinstance(tuneables.get("advisory_engine"), dict) else {}
    gate = tuneables.get("advisory_gate") if isinstance(tuneables.get("advisory_gate"), dict) else {}
    packet = (
        tuneables.get("advisory_packet_store")
        if isinstance(tuneables.get("advisory_packet_store"), dict)
        else {}
    )
    advisor = tuneables.get("advisor") if isinstance(tuneables.get("advisor"), dict) else {}
    prefetch = (
        tuneables.get("advisory_prefetch")
        if isinstance(tuneables.get("advisory_prefetch"), dict)
        else {}
    )
    return {
        "engine": engine,
        "gate": gate,
        "packet": packet,
        "advisor": advisor,
        "prefetch": prefetch,
    }


def _load_good_suppressed(limit: int = 10) -> List[Dict[str, Any]]:
    path = _REPO_ROOT / "reports" / "runtime" / "good_but_suppressed_24h.json"
    rows = _read_json_array(path)
    return rows[: max(0, int(limit))]


def _improvement_rows(runtime: Dict[str, Any], tune: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    buckets = runtime.get("suppression_buckets") or {}
    total_suppressed = sum(int(v or 0) for v in buckets.values())
    shown = int(buckets.get("shown_ttl", 0) or 0)
    dedupe = int(buckets.get("global_dedupe", 0) or 0)
    budget = int(buckets.get("budget_exhausted", 0) or 0)
    cooldown = int(buckets.get("tool_cooldown", 0) or 0)

    shown_ratio = (shown / max(total_suppressed, 1)) if total_suppressed else 0.0
    dedupe_ratio = (dedupe / max(total_suppressed, 1)) if total_suppressed else 0.0
    budget_ratio = (budget / max(total_suppressed, 1)) if total_suppressed else 0.0
    cooldown_ratio = (cooldown / max(total_suppressed, 1)) if total_suppressed else 0.0

    if shown_ratio >= 0.30:
        out.append(
            {
                "priority": "P0/P1",
                "focus": "Shown TTL dominates suppression",
                "evidence": f"shown_ttl={shown} ({_fmt_pct(shown, max(total_suppressed, 1))} of suppressions)",
                "change": "DONE: source-aware TTL multipliers (baseline 0.5x, bank 0.6x, trigger 0.7x, mind 0.75x, cognitive/eidos 1.0x). Monitor if ratio drops below 50%.",
                "where": "lib/advisory_gate.py (SOURCE_TTL_MULTIPLIERS + _shown_ttl_for_advice)",
            }
        )
    if dedupe_ratio >= 0.15:
        out.append(
            {
                "priority": "P1",
                "focus": "Global dedupe still heavy",
                "evidence": f"global_dedupe={dedupe} ({_fmt_pct(dedupe, max(total_suppressed, 1))})",
                "change": "Move from single cooldown to category-aware dedupe windows and source quotas.",
                "where": "lib/advisory_engine_alpha.py + advisory dedupe logs (global_dedupe_suppressed)",
            }
        )
    if budget_ratio >= 0.08:
        out.append(
            {
                "priority": "P1/P2",
                "focus": "Budget cap suppressing otherwise emit-worthy advice",
                "evidence": f"budget_exhausted={budget} ({_fmt_pct(budget, max(total_suppressed, 1))})",
                "change": "DONE: dynamic budget — WARNING items +1, high confidence spread +1, hard cap base+2.",
                "where": "lib/advisory_gate.py (evaluate dynamic budget)",
            }
        )
    if cooldown_ratio >= 0.08:
        out.append(
            {
                "priority": "P2",
                "focus": "Tool cooldown hiding advice bursts",
                "evidence": f"tool_cooldown={cooldown} ({_fmt_pct(cooldown, max(total_suppressed, 1))})",
                "change": "DONE: tool-family multipliers (Read/Grep/Glob 0.5x, Bash 0.7x, Edit/Write 1.2x). Applied at both gate check and suppress time.",
                "where": "lib/advisory_gate.py (TOOL_COOLDOWN_MULTIPLIERS) + lib/advisory_engine_alpha.py",
            }
        )

    emit_rate = str(runtime.get("emit_rate") or "0.0%")
    follow_rate = str(runtime.get("follow_rate") or "0.0%")
    out.append(
        {
            "priority": "P2",
            "focus": "Balance emissions against observed follow rate",
            "evidence": f"emit_rate={emit_rate}, follow_rate={follow_rate}",
            "change": "Add per-intent emit target bands and alert when emission drops below floor while follow remains high.",
            "where": "lib/advisory_engine_alpha.py + reports/runtime diagnostics",
        }
    )

    if bool((tune.get("prefetch") or {}).get("worker_enabled", False)) is False:
        out.append(
            {
                "priority": "P2",
                "focus": "Prefetch worker disabled",
                "evidence": "advisory_prefetch.worker_enabled=false",
                "change": "Enable for active sessions or keep disabled and remove queue complexity to reduce drift.",
                "where": "lib/advisory_prefetch_worker.py + tuneables",
            }
        )
    return out


def generate_advisory_reverse_engineering(data: Dict[int, Dict[str, Any]]) -> str:
    """Build a reverse-engineered advisory path page with runtime evidence."""
    runtime = _collect_runtime(window_s=86400)
    tune = _collect_tuneables()
    good_suppressed = _load_good_suppressed(limit=10)
    improvements = _improvement_rows(runtime, tune)

    queue_pending = int((data.get(2) or {}).get("estimated_pending", 0) or 0)
    insights_total = int((data.get(6) or {}).get("total_insights", 0) or 0)
    eidos_distillations = int((data.get(7) or {}).get("distillations", 0) or 0)

    lines: List[str] = []
    lines.append("---")
    lines.append("title: Advisory Reverse Engineering")
    lines.append("tags:")
    lines.append("  - observatory")
    lines.append("  - advisory")
    lines.append("  - reverse-engineering")
    lines.append("  - diagnostics")
    lines.append("---")
    lines.append("")
    lines.append("# Advisory Reverse Engineering")
    lines.append("")
    lines.append(f"> Generated: {_fmt_ts(time.time())}")
    lines.append("> Scope: advisory path, upstream intelligence feeders, suppression controls, and tuning targets.")
    lines.append("")

    lines.append("## Runtime Snapshot (Last 24h)")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Ledger rows (24h) | {runtime.get('ledger_rows', 0)} |")
    lines.append(
        f"| Outcomes | emitted={runtime.get('emitted', 0)}, blocked={runtime.get('blocked', 0)}, raw={runtime.get('outcomes', {})} |"
    )
    lines.append(f"| Emit rate | {runtime.get('emit_rate', '0.0%')} |")
    lines.append(f"| Most recent ledger event | {_fmt_ts(float(runtime.get('latest_ledger_ts', 0.0) or 0.0))} |")
    lines.append(f"| Implicit feedback rows (24h) | {runtime.get('implicit_rows', 0)} |")
    lines.append(
        f"| Follow rate | {runtime.get('follow_rate', '0.0%')} (followed={runtime.get('followed', 0)}, not_followed={runtime.get('not_followed', 0)}) |"
    )
    lines.append(f"| Queue pending (current) | {queue_pending} |")
    lines.append(f"| Cognitive insights (current) | {insights_total} |")
    lines.append(f"| EIDOS distillations (current) | {eidos_distillations} |")
    lines.append("")

    lines.append("## End-to-End Advisory Path")
    lines.append("")
    lines.append("| Stage | Main code path | Read dependencies | Write artifacts | Notes / failure points |")
    lines.append("|---|---|---|---|---|")
    lines.append("| 1. Hook ingress | `hooks/observe.py` (`on_user_prompt`, `on_pre_tool`, `on_post_tool`) | Hook payload, tool input, trace ids | `quick_capture(...)` event rows | If hook config missing, nothing downstream runs. |")
    lines.append("| 2. Queue ingest | `lib/queue.py:quick_capture` | lock file, queue state | `~/.spark/queue/events.jsonl`, overflow sidecar | Queue contention can still reduce observability quality if overflow merge/backpressure is not healthy. |")
    lines.append("| 3. Bridge cycle processing | `lib/bridge_cycle.py:run_bridge_cycle` | recent queue events | pipeline/memory/chip/eidos updates | If bridge worker stalls, intelligence feeders lag and advisory quality drops. |")
    lines.append("| 4. Memory capture + banking | `lib/memory_capture.py` + `lib/memory_banks.py` | user/tool events and payload text | bank entries and pending memory state | Low quality capture pollutes retrieval; over-filtering starves retrieval. |")
    lines.append("| 5. Meta-Ralph quality gate | `lib/meta_ralph.py` | candidate insights | roast history + scored verdicts | Strict gate improves quality but can reduce recall if thresholds are too high. |")
    lines.append("| 6. Cognitive + EIDOS stores | `lib/cognitive_learner.py`, `lib/eidos/*`, `chips/*.jsonl` | gated insights and episodic outcomes | cognitive/eidos/chip stores | Core retrieval substrate for advisory. |")
    lines.append("| 7. Mind write path | `lib/bridge_cycle.py -> lib/mind_bridge.py:sync_recent_insights` | recent high-readiness insights | Mind API + `mind_sync_state.json` + offline queue | If Mind service/auth fails, queue grows and cross-session memory value decays. |")
    lines.append("| 8. Pre-tool advisory runtime | `lib/advisory_engine_alpha.py:on_pre_tool` | session state + packet store + advisor | decision ledger + alpha engine log + advisory state | Packet hit/miss route determines latency and retrieval depth. |")
    lines.append("| 9. Retrieval fanout | `lib/advisor.py:advise` | bank, cognitive, chips, mind, tool, eidos, replay | in-memory advice bundle + advice log | Mind is optional and gated; no direct emit from memory without gate. |")
    lines.append("| 10. Gate + suppression | `lib/advisory_gate.py:evaluate` | phase, cooldown state, tool/input context | gate decisions (emitted/suppressed) | Main suppressors: shown TTL, global dedupe, tool cooldown, budget cap. |")
    lines.append("| 11. Dedupe + synth + emit | `lib/advisory_engine_alpha.py` + `lib/advisory_synthesizer.py` + emitter | emitted decisions and policy | stdout advisory, shown markers, packet updates | Text repeat and global dedupe can block even when gate emitted candidates. |")
    lines.append("| 12. Post-tool feedback loop | `lib/advisory_engine_alpha.py:on_post_tool` | execution success/failure + recent delivery | implicit feedback, outcome trackers, packet outcome stats | This loop tunes future ranking and effectiveness tracking. |")
    lines.append("")

    lines.append("## Mind: Actual Role In The Current System")
    lines.append("")
    lines.append("| Question | Current behavior in code |")
    lines.append("|---|---|")
    lines.append("| Does Mind store memory? | Yes. `lib/mind_bridge.py:sync_insight/sync_recent_insights` writes memory payloads to Mind and queues offline when unavailable. |")
    lines.append("| Does advisory emit directly from Mind memory? | Not directly. Mind memories become `Advice(source=\"mind\")` in `lib/advisor.py:_get_mind_advice`, then pass through gate/dedupe/synth/emitter. |")
    lines.append("| Does Mind affect input-side intelligence? | Yes, indirectly. Cross-session memories enrich pre-tool retrieval context when `include_mind=true` and stale/salience checks pass. |")
    lines.append("| What if Mind is down? | Retrieval degrades gracefully (Mind skipped). Core advisory still runs from bank/cognitive/eidos/chips/baseline sources. |")
    lines.append("| What is Mind's higher purpose today? | Durable cross-session memory with temporal metadata and salience, used to improve relevance on recurring patterns across sessions. |")
    lines.append("")

    lines.append("## Suppression Buckets (24h) and Control Surface")
    lines.append("")
    lines.append("| Bucket | Count | Share | Primary controls | Main code |")
    lines.append("|---|---:|---:|---|---|")
    bucket_total = sum(int(v or 0) for v in (runtime.get("suppression_buckets") or {}).values())
    for key, control, code in [
        ("shown_ttl", "advisory_gate.shown_advice_ttl_s + category_cooldown_multipliers", "lib/advisory_gate.py + lib/runtime_session_state.py"),
        ("global_dedupe", "advisory_engine.global_dedupe_cooldown_s", "lib/advisory_engine_alpha.py"),
        ("tool_cooldown", "advisory_gate.tool_cooldown_s", "lib/advisory_gate.py"),
        ("budget_exhausted", "advisory_gate.max_emit_per_call", "lib/advisory_gate.py"),
        ("context_phase_guard", "phase suppression rules + thresholds", "lib/advisory_gate.py:_check_obvious_suppression"),
        ("duplicate_repeat", "advisory_engine.advisory_text_repeat_cooldown_s", "lib/advisory_engine_alpha.py"),
        ("other", "reason-specific", "decision ledger reason text"),
    ]:
        count = int((runtime.get("suppression_buckets") or {}).get(key, 0) or 0)
        lines.append(f"| `{key}` | {count} | {_fmt_pct(count, max(bucket_total, 1))} | {control} | `{code}` |")
    lines.append("")

    lines.append("## Top Routes / Tools / Sources (24h)")
    lines.append("")
    lines.append("| Group | Top entries |")
    lines.append("|---|---|")
    lines.append(
        "| Routes | "
        + ", ".join([f"`{name}`={count}" for name, count in runtime.get("routes_top", [])])
        + " |"
    )
    lines.append(
        "| Tools | "
        + ", ".join([f"`{name}`={count}" for name, count in runtime.get("tools_top", [])])
        + " |"
    )
    lines.append(
        "| Sources | "
        + ", ".join([f"`{name}`={count}" for name, count in runtime.get("sources_top", [])])
        + " |"
    )
    lines.append("")

    if good_suppressed:
        lines.append("## Suppressed But Potentially Useful Advisories (Sample)")
        lines.append("")
        lines.append("| Advice ID | Source | Suppressed count | Top reasons |")
        lines.append("|---|---|---:|---|")
        for row in good_suppressed[:10]:
            advice_id = str(row.get("advice_id") or "")[:64]
            source = str(row.get("source") or "?")
            count = int(row.get("suppressed_count") or 0)
            reasons = "; ".join(
                [
                    str(row.get("top_reason_1") or "").strip(),
                    str(row.get("top_reason_2") or "").strip(),
                ]
            ).strip("; ")
            lines.append(f"| `{advice_id}` | `{source}` | {count} | {reasons or '-'} |")
        lines.append("")

    lines.append("## Priority Improvements (Evidence-Backed)")
    lines.append("")
    lines.append("| Priority | Focus | Evidence | Change | Where to implement |")
    lines.append("|---|---|---|---|---|")
    for row in improvements:
        lines.append(
            f"| {row['priority']} | {row['focus']} | {row['evidence']} | {row['change']} | `{row['where']}` |"
        )
    lines.append("")

    lines.append("## Current Tuneables Snapshot")
    lines.append("")
    lines.append("| Section | Key settings |")
    lines.append("|---|---|")
    engine = tune.get("engine") or {}
    gate = tune.get("gate") or {}
    advisor = tune.get("advisor") or {}
    prefetch = tune.get("prefetch") or {}
    packet = tune.get("packet") or {}
    lines.append(
        "| advisory_engine | "
        f"include_mind={engine.get('include_mind')}, "
        f"global_dedupe_cooldown_s={engine.get('global_dedupe_cooldown_s')}, "
        f"force_programmatic_synth={engine.get('force_programmatic_synth')} |"
    )
    lines.append(
        "| advisory_gate | "
        f"max_emit_per_call={gate.get('max_emit_per_call')}, tool_cooldown_s={gate.get('tool_cooldown_s')}, "
        f"shown_advice_ttl_s={gate.get('shown_advice_ttl_s')}, emit_whispers={gate.get('emit_whispers')} |"
    )
    lines.append(
        "| advisory_gate category multipliers | "
        f"{(gate.get('category_cooldown_multipliers') or {})} |"
    )
    lines.append(
        "| advisory_gate source TTL multipliers | "
        f"{(gate.get('source_ttl_multipliers') or {})} |"
    )
    lines.append(
        "| advisory_gate tool cooldown multipliers | "
        f"{(gate.get('tool_cooldown_multipliers') or {})} |"
    )
    lines.append(
        "| advisor (Mind) | "
        f"mind_max_stale_s={advisor.get('mind_max_stale_s')}, mind_min_salience={advisor.get('mind_min_salience')}, "
        f"mind_stale_allow_if_empty={advisor.get('mind_stale_allow_if_empty')} |"
    )
    lines.append(
        "| advisory_prefetch | "
        f"worker_enabled={prefetch.get('worker_enabled')}, max_jobs_per_run={prefetch.get('max_jobs_per_run')} |"
    )
    lines.append(
        "| advisory_packet_store | "
        f"packet_ttl_s={packet.get('packet_ttl_s')}, packet_lookup_candidates={packet.get('packet_lookup_candidates')}, "
        "lookup_backend=sqlite_canonical |"
    )
    lines.append("")

    lines.append("## Files To Inspect While Tuning")
    lines.append("")
    lines.append(f"- Ledger: `{runtime.get('ledger_file', '')}`")
    lines.append(f"- Implicit feedback: `{runtime.get('implicit_file', '')}`")
    lines.append("- Advisory state: `~/.spark/advisory_state/*.json`")
    lines.append("- Engine traces: `~/.spark/advisory_engine_alpha.jsonl` (primary)")
    lines.append("- Packet store: `~/.spark/advice_packets/*`")
    lines.append("- Good-but-suppressed sample: `reports/runtime/good_but_suppressed_24h.json`")
    lines.append("")

    return "\n".join(lines)
