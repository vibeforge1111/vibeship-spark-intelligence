#!/usr/bin/env python3
"""Context-first contradiction gate for Spark intelligence quality.

This script enforces a simple rule:
numbers are not accepted as quality evidence unless context-backed checks also pass.

It analyzes real runtime cohorts and writes:
  - docs/reports/<timestamp>_strict_contradiction_report.md
  - docs/reports/<timestamp>_last1000_antipattern_cohorts.json

Exit codes:
  0 -> all configured P0 gates pass (or enforcement disabled)
  2 -> one or more P0 gates fail with --enforce
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RAW_TELEMETRY_RE = re.compile(r"\b(exec_command failed|process exited with code|wall time:)\b", re.I)
CHUNK_ID_RE = re.compile(r"\bchunk id[:\s]*[a-f0-9]{4,}\b", re.I)
SESSION_WEATHER_RE = re.compile(r"\b(tool .* failed then recovered|session: \d+/\d+)\b", re.I)
SELF_REPLAY_RE = re.compile(r"\b(it worked|sounds good|let'?s do it|can we now run)\b", re.I)
NON_ACTIONABLE_RE = re.compile(r"\b(consider|might|maybe)\b", re.I)
TOKEN_RE = re.compile(r"[A-Za-z0-9_'-]+")

ACTION_WORDS = {
    "use",
    "verify",
    "validate",
    "check",
    "run",
    "trace",
    "compare",
    "retry",
    "gate",
    "split",
    "rewrite",
    "refactor",
    "avoid",
    "prefer",
    "must",
    "should",
    "always",
    "never",
}


@dataclass(frozen=True)
class Cohort:
    name: str
    source_path: Path
    rows: list[dict[str, Any]]


def _load_jsonl(path: Path, *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
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
    if limit > 0 and len(rows) > limit:
        rows = rows[-limit:]
    return rows


def _coerce_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_text(row: dict[str, Any]) -> str:
    return _coerce_text(
        row,
        ("text", "advice_text", "insight", "summary", "content", "message", "event"),
    )


def _semantic_thin(text: str) -> bool:
    words = TOKEN_RE.findall(text)
    if not words:
        return True
    if len(words) > 8:
        return False
    return not bool({w.lower() for w in words}.intersection(ACTION_WORDS))


def _analyze_tags(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tag_counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    tagged_rows = 0

    def add_tag(tag: str, text: str) -> None:
        tag_counts[tag] = int(tag_counts.get(tag, 0)) + 1
        bucket = examples.setdefault(tag, [])
        if len(bucket) < 5:
            snippet = " ".join((text or "").split())[:220]
            bucket.append(snippet)

    for row in rows:
        text = _extract_text(row)
        tags: set[str] = set()
        if text:
            if RAW_TELEMETRY_RE.search(text):
                tags.add("raw-telemetry-residue")
            if CHUNK_ID_RE.search(text):
                tags.add("chunk-hash-id")
            if SESSION_WEATHER_RE.search(text):
                tags.add("session-weather-memory")
            if SELF_REPLAY_RE.search(text):
                tags.add("self-replay-advice")
            if NON_ACTIONABLE_RE.search(text):
                tags.add("non-actionable-synthesis")
            if _semantic_thin(text):
                tags.add("semantic-thinness")
        if not _coerce_text(row, ("trace_id", "outcome_trace_id", "trace")):
            # Only require trace lineage on decision-like rows, not generic memory facts.
            if any(key in row for key in ("event", "advice_text", "tool", "route", "gate_reason", "outcome")):
                tags.add("trace-orphan")
        if tags:
            tagged_rows += 1
            evidence = text or _coerce_text(row, ("event", "outcome", "action")) or "(no text)"
            for tag in sorted(tags):
                add_tag(tag, evidence)

    return {
        "rows_available": len(rows),
        "rows_tagged": tagged_rows,
        "tag_counts": dict(sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "examples": examples,
    }


def _load_intake_cohort(queue_path: Path, limit: int) -> list[dict[str, Any]]:
    queue_rows = _load_jsonl(queue_path, limit=limit)
    normalized: list[dict[str, Any]] = []
    for row in queue_rows:
        text = ""
        if isinstance(row.get("tool_input"), str) and row.get("tool_input", "").strip():
            text = str(row.get("tool_input")).strip()
        elif isinstance(row.get("error"), str) and row.get("error", "").strip():
            text = str(row.get("error")).strip()
        elif isinstance(row.get("data"), dict):
            data = row["data"]
            if isinstance(data, dict):
                for key in ("text", "message", "summary", "content", "tool_input"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        text = value.strip()
                        break
        if not text:
            text = str(row.get("event_type") or "").strip()
        normalized.append(
            {
                "text": text,
                "event_type": row.get("event_type", ""),
                "tool_name": row.get("tool_name", ""),
                "session_id": row.get("session_id", ""),
                "timestamp": row.get("timestamp", ""),
                "source": "queue_events",
            }
        )
    return normalized


def _load_memory_cohort(memory_path: Path, limit: int) -> list[dict[str, Any]]:
    if not memory_path.exists():
        return []
    try:
        obj = json.loads(memory_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(value, dict):
                continue
            row = dict(value)
            row.setdefault("memory_key", key)
            if not isinstance(row.get("text"), str):
                row["text"] = str(row.get("insight") or row.get("summary") or key)
            rows.append(row)
    elif isinstance(obj, list):
        for value in obj:
            if not isinstance(value, dict):
                continue
            row = dict(value)
            if not isinstance(row.get("text"), str):
                row["text"] = str(row.get("insight") or row.get("summary") or "")
            rows.append(row)

    def score_ts(r: dict[str, Any]) -> float:
        for key in ("last_validated_at", "created_at", "updated_at", "timestamp", "ts"):
            value = r.get(key)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str) and value.strip():
                try:
                    return float(value)
                except Exception:
                    continue
        return 0.0

    rows = sorted(rows, key=score_ts)
    if limit > 0 and len(rows) > limit:
        rows = rows[-limit:]
    return rows


def _count_unknown_gate_reasons(engine_rows: list[dict[str, Any]]) -> int:
    total = 0
    for row in engine_rows:
        event = str(row.get("event") or row.get("outcome") or "").lower()
        if event not in {"gate_no_emit", "blocked", "suppressed"}:
            continue
        reason = str(row.get("gate_reason") or row.get("reason") or "").strip().lower()
        if reason in {"", "unknown", "none", "?"}:
            total += 1
    return total


def _ratio(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return float(numer) / float(denom)


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def build_report(
    spark_dir: Path,
    repo_root: Path,
    *,
    limit: int,
    max_non_actionable_ratio: float,
    max_memory_telemetry_ratio: float,
    max_session_weather_ratio: float,
) -> tuple[Path, Path, dict[str, Any], bool]:
    docs_reports = repo_root / "docs" / "reports"
    docs_reports.mkdir(parents=True, exist_ok=True)

    queue_path = spark_dir / "queue" / "events.jsonl"
    memory_path = spark_dir / "cognitive_insights.json"
    emit_path = spark_dir / "advisory_emit.jsonl"
    engine_path = spark_dir / "advisory_engine_alpha.jsonl"

    intake_rows = _load_intake_cohort(queue_path, limit)
    memory_rows = _load_memory_cohort(memory_path, limit)
    emission_rows = _load_jsonl(emit_path, limit=limit)
    engine_rows = _load_jsonl(engine_path, limit=limit)

    intake = Cohort("intake", queue_path, intake_rows)
    memory = Cohort("memory", memory_path, memory_rows)
    emission = Cohort("emission", emit_path, emission_rows)

    analyses = {
        intake.name: _analyze_tags(intake.rows),
        memory.name: _analyze_tags(memory.rows),
        emission.name: _analyze_tags(emission.rows),
    }

    intake_texts = [_extract_text(r) for r in intake.rows]
    memory_texts = [_extract_text(r) for r in memory.rows]
    emission_texts = [_extract_text(r) for r in emission.rows]

    intake_telemetry_rows = sum(1 for t in intake_texts if RAW_TELEMETRY_RE.search(t) or CHUNK_ID_RE.search(t))
    memory_telemetry_rows = sum(1 for t in memory_texts if RAW_TELEMETRY_RE.search(t) or CHUNK_ID_RE.search(t))
    emit_non_actionable_rows = sum(1 for t in emission_texts if NON_ACTIONABLE_RE.search(t))
    emit_self_replay_rows = sum(1 for t in emission_texts if SELF_REPLAY_RE.search(t))
    emit_session_weather_rows = sum(1 for t in emission_texts if SESSION_WEATHER_RE.search(t))
    unknown_gate_reason = _count_unknown_gate_reasons(engine_rows)

    intake_n = max(1, len(intake.rows))
    memory_n = max(1, len(memory.rows))
    emit_n = max(1, len(emission.rows))

    non_actionable_ratio = _ratio(emit_non_actionable_rows, emit_n)
    self_replay_ratio = _ratio(emit_self_replay_rows, emit_n)
    session_weather_ratio = _ratio(emit_session_weather_rows, emit_n)
    memory_telemetry_ratio = _ratio(memory_telemetry_rows, memory_n)
    intake_telemetry_ratio = _ratio(intake_telemetry_rows, intake_n)

    gates = {
        "unknown_gate_reason": {
            "condition": "unknown-gate-reason == 0",
            "current": unknown_gate_reason,
            "ok": unknown_gate_reason == 0,
        },
        "self_replay": {
            "condition": "self-replay-advice == 0",
            "current": emit_self_replay_rows,
            "ok": emit_self_replay_rows == 0,
        },
        "emission_actionability": {
            "condition": f"non-actionable ratio <= {max_non_actionable_ratio:.2f}",
            "current": non_actionable_ratio,
            "ok": non_actionable_ratio <= max_non_actionable_ratio,
        },
        "memory_residue": {
            "condition": f"memory telemetry/error ratio <= {max_memory_telemetry_ratio:.2f}",
            "current": memory_telemetry_ratio,
            "ok": memory_telemetry_ratio <= max_memory_telemetry_ratio,
        },
        "session_weather": {
            "condition": f"session-weather ratio <= {max_session_weather_ratio:.2f}",
            "current": session_weather_ratio,
            "ok": session_weather_ratio <= max_session_weather_ratio,
        },
    }
    all_ok = all(bool(g["ok"]) for g in gates.values())

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = docs_reports / f"{stamp}_last1000_antipattern_cohorts.json"
    md_path = docs_reports / f"{stamp}_strict_contradiction_report.md"

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_files": {
            "intake": str(intake.source_path),
            "memory": str(memory.source_path),
            "emission": str(emission.source_path),
            "engine": str(engine_path),
        },
        "row_counts": {
            "intake": len(intake.rows),
            "memory": len(memory.rows),
            "emission": len(emission.rows),
            "engine": len(engine_rows),
        },
        "analysis": analyses,
        "row_level_metrics": {
            "intake_telemetry_rows": intake_telemetry_rows,
            "memory_telemetry_rows": memory_telemetry_rows,
            "emit_non_actionable_rows": emit_non_actionable_rows,
            "emit_self_replay_rows": emit_self_replay_rows,
            "emit_session_weather_rows": emit_session_weather_rows,
            "unknown_gate_reason_rows": unknown_gate_reason,
            "intake_telemetry_ratio": intake_telemetry_ratio,
            "memory_telemetry_ratio": memory_telemetry_ratio,
            "emit_non_actionable_ratio": non_actionable_ratio,
            "emit_self_replay_ratio": self_replay_ratio,
            "emit_session_weather_ratio": session_weather_ratio,
        },
        "p0_gates": gates,
        "all_gates_ok": all_ok,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# Strict Contradiction Report (Context-First)")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}")
    lines.append("")
    lines.append("## Cohort Scope")
    lines.append("")
    lines.append(f"- Intake source: `{intake.source_path}` (rows analyzed: `{len(intake.rows)}`)")
    lines.append(f"- Memory source: `{memory.source_path}` (rows analyzed: `{len(memory.rows)}`)")
    lines.append(f"- Emission source: `{emission.source_path}` (rows analyzed: `{len(emission.rows)}`)")
    lines.append(f"- Gate diagnostics source: `{engine_path}` (rows analyzed: `{len(engine_rows)}`)")
    lines.append("")
    lines.append("## Core Reminder")
    lines.append("")
    lines.append("Numbers are not accepted as quality proof unless item-level context evidence agrees with them.")
    lines.append("")
    lines.append("## Socratic Contradictions")
    lines.append("")
    lines.append("| Assumption | Contradicting Evidence | Category Mistake | Confidence |")
    lines.append("|---|---|---|---:|")
    lines.append(
        f"| Emission activity implies utility | non-actionable emission `{emit_non_actionable_rows}/{emit_n}` (`{non_actionable_ratio:.3f}`), self-replay `{emit_self_replay_rows}/{emit_n}` (`{self_replay_ratio:.3f}`) | Throughput != usefulness | 94 |"
    )
    lines.append(
        f"| Memory reliability implies memory quality | telemetry/error memory `{memory_telemetry_rows}/{memory_n}` (`{memory_telemetry_ratio:.3f}`) | Exposure proxy != semantic value | 88 |"
    )
    lines.append(
        f"| Gate suppression is tunable | unknown gate reasons `{unknown_gate_reason}` over `{len(engine_rows)}` rows | Observability blind spot | 96 |"
    )
    lines.append(
        f"| Intake cleanliness guarantees downstream quality | intake telemetry `{intake_telemetry_ratio:.3f}` vs memory telemetry `{memory_telemetry_ratio:.3f}` | Stage-local success != end-to-end quality | 84 |"
    )
    lines.append("")
    lines.append("## Cohort Snapshot")
    lines.append("")
    lines.append("| Cohort | Rows | Tagged rows | Top tags |")
    lines.append("|---|---:|---:|---|")
    for cohort in (intake, memory, emission):
        data = analyses[cohort.name]
        top_items = list(data["tag_counts"].items())[:4]
        top_text = ", ".join(f"`{k}`={v}" for k, v in top_items) if top_items else "none"
        lines.append(f"| {cohort.name} | {len(cohort.rows)} | {int(data['rows_tagged'])} | {top_text} |")
    lines.append("")
    lines.append("## P0 Stop-Ship Gates")
    lines.append("")
    lines.append("| Gate | Condition | Current | Status |")
    lines.append("|---|---|---:|---|")
    lines.append(
        f"| Gate reason integrity | `{gates['unknown_gate_reason']['condition']}` | `{gates['unknown_gate_reason']['current']}` | **{_status(gates['unknown_gate_reason']['ok'])}** |"
    )
    lines.append(
        f"| No self-replay advice | `{gates['self_replay']['condition']}` | `{gates['self_replay']['current']}` | **{_status(gates['self_replay']['ok'])}** |"
    )
    lines.append(
        f"| Emission actionability floor | `{gates['emission_actionability']['condition']}` | `{gates['emission_actionability']['current']:.3f}` | **{_status(gates['emission_actionability']['ok'])}** |"
    )
    lines.append(
        f"| Memory residue cap | `{gates['memory_residue']['condition']}` | `{gates['memory_residue']['current']:.3f}` | **{_status(gates['memory_residue']['ok'])}** |"
    )
    lines.append(
        f"| No session-weather dominance | `{gates['session_weather']['condition']}` | `{gates['session_weather']['current']:.3f}` | **{_status(gates['session_weather']['ok'])}** |"
    )
    lines.append("")
    lines.append("## Required Actions (if any FAIL)")
    lines.append("")
    lines.append("1. Enforce non-empty reason enums on every suppression event (`unknown` forbidden).")
    lines.append("2. Block dialogue replay patterns from emission path.")
    lines.append("3. Add pre-emit actionability guard for vague synthesis.")
    lines.append("4. Quarantine telemetry/error memory rows from retrieval until rewritten.")
    lines.append("")
    lines.append("## Unknowns")
    lines.append("")
    lines.append("- If memory/emission rows are below 1000, all available rows were analyzed.")
    lines.append("- Queue normalization may under-capture nested semantic payloads in some events.")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path, payload, all_ok


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run context-first contradiction gate on Spark runtime artifacts.")
    ap.add_argument("--spark-dir", default=str(Path.home() / ".spark"))
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--limit", type=int, default=1000, help="Rows per cohort when available.")
    ap.add_argument("--max-non-actionable-ratio", type=float, default=0.25)
    ap.add_argument("--max-memory-telemetry-ratio", type=float, default=0.10)
    ap.add_argument("--max-session-weather-ratio", type=float, default=0.20)
    ap.add_argument("--enforce", action="store_true", help="Return non-zero exit code if any P0 gate fails.")
    return ap


def main() -> int:
    args = _build_parser().parse_args()
    spark_dir = Path(args.spark_dir).expanduser()
    repo_root = Path(args.repo_root).resolve()

    md_path, json_path, payload, all_ok = build_report(
        spark_dir,
        repo_root,
        limit=max(100, int(args.limit)),
        max_non_actionable_ratio=max(0.0, min(1.0, float(args.max_non_actionable_ratio))),
        max_memory_telemetry_ratio=max(0.0, min(1.0, float(args.max_memory_telemetry_ratio))),
        max_session_weather_ratio=max(0.0, min(1.0, float(args.max_session_weather_ratio))),
    )

    print(f"wrote_markdown={md_path}")
    print(f"wrote_json={json_path}")
    print(f"all_gates_ok={all_ok}")

    if bool(args.enforce) and not all_ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
