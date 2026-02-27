"""Map advisory recommendations to observed actions/evidence."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

JSONL_EXT = ".jsonl"
FEEDBACK_FILE = Path.home() / ".spark" / f"advice_feedback{JSONL_EXT}"
REPORTS_DIR = Path.home() / ".openclaw" / "workspace" / "spark_reports"
OUTCOMES_FILE = Path.home() / ".spark" / f"outcomes{JSONL_EXT}"

_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    t = str(text or "").strip().lower()
    return _WS_RE.sub(" ", t)


def _text_sim(a: str, b: str) -> float:
    aa = _norm(a)
    bb = _norm(b)
    if not aa or not bb:
        return 0.0
    if aa in bb or bb in aa:
        return 1.0
    return float(SequenceMatcher(a=aa, b=bb).ratio())


def _parse_ts(row: Dict[str, Any]) -> float:
    for key in ("created_at", "ts", "timestamp"):
        val = row.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except Exception:
            continue
    return 0.0


def _read_jsonl(path: Path) -> List[tuple[int, Dict[str, Any]]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: List[tuple[int, Dict[str, Any]]] = []
    for idx, line in enumerate(lines, start=1):
        try:
            row = json.loads(line)
        except Exception:
            continue
        rows.append((idx, row))
    return rows


def _load_reports(path: Path) -> List[tuple[str, Dict[str, Any]]]:
    if not path.exists():
        return []
    out: List[tuple[str, Dict[str, Any]]] = []
    for fp in sorted(path.glob("*.json")):
        try:
            row = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        out.append((str(fp), row))
    return out


def _match_explicit_feedback(
    advisory: Dict[str, Any],
    feedback_rows: List[tuple[int, Dict[str, Any]]],
    max_match_window_s: float,
) -> Optional[Dict[str, Any]]:
    advisory_id = str(advisory.get("advisory_id") or "")
    advisory_created = float(advisory.get("created_at") or 0.0)
    if not advisory_id or not advisory_created:
        return None
    best: Optional[Dict[str, Any]] = None
    for line_no, row in feedback_rows:
        advice_ids = [str(x) for x in (row.get("advice_ids") or [])]
        if advisory_id not in advice_ids:
            continue
        ts = _parse_ts(row)
        if ts < advisory_created:
            continue
        if max_match_window_s > 0 and ts - advisory_created > max_match_window_s:
            continue
        followed = bool(row.get("followed"))
        helpful = row.get("helpful")
        status = "acted" if followed else "skipped"
        hint = "neutral"
        if helpful is True:
            hint = "positive"
        elif helpful is False:
            hint = "negative"
        cur = {
            "status": status,
            "matched_at": ts,
            "latency_s": max(0.0, ts - advisory_created),
            "match_type": "explicit_feedback",
            "effect_hint": hint,
            "confidence_hint": 0.96,
            "evidence_refs": [f"{FEEDBACK_FILE}:{line_no}"],
            "evidence_excerpt": str(row.get("notes") or "")[:240],
        }
        if best is None or ts < float(best.get("matched_at") or 0.0):
            best = cur
    return best


def _match_reports(
    advisory: Dict[str, Any],
    report_rows: List[tuple[str, Dict[str, Any]]],
    max_match_window_s: float,
) -> Optional[Dict[str, Any]]:
    rec = str(advisory.get("recommendation") or "")
    advisory_created = float(advisory.get("created_at") or 0.0)
    if not rec or not advisory_created:
        return None
    best: Optional[Dict[str, Any]] = None
    for fp, row in report_rows:
        source = str(row.get("source") or "").strip().lower()
        if "spark_advisory" not in source:
            continue
        ts = _parse_ts(row)
        if ts < advisory_created:
            continue
        if max_match_window_s > 0 and ts - advisory_created > max_match_window_s:
            continue
        kind = str(row.get("kind") or "").strip().lower()
        advisory_ref = str(row.get("advisory_ref") or "")
        reasoning = str(row.get("reasoning") or "")
        lesson = str(row.get("lesson") or "")
        result = str(row.get("result") or "")
        haystack = " ".join([advisory_ref, reasoning, lesson, result]).strip()
        is_match = _text_sim(rec, haystack) >= 0.58
        if not is_match:
            continue
        if kind == "outcome":
            success = row.get("success")
            hint = "neutral"
            if success is True:
                hint = "positive"
            elif success is False:
                hint = "negative"
            cur = {
                "status": "acted",
                "matched_at": ts,
                "latency_s": max(0.0, ts - advisory_created),
                "match_type": "report_outcome",
                "effect_hint": hint,
                "confidence_hint": 0.86,
                "evidence_refs": [fp],
                "evidence_excerpt": haystack[:240],
            }
        elif kind == "decision":
            cur = {
                "status": "skipped",
                "matched_at": ts,
                "latency_s": max(0.0, ts - advisory_created),
                "match_type": "report_decision",
                "effect_hint": "neutral",
                "confidence_hint": 0.84,
                "evidence_refs": [fp],
                "evidence_excerpt": haystack[:240],
            }
        else:
            continue
        if best is None or ts < float(best.get("matched_at") or 0.0):
            best = cur
    return best


def _match_implicit_outcome(
    advisory: Dict[str, Any],
    outcome_rows: List[tuple[int, Dict[str, Any]]],
    max_match_window_s: float,
) -> Optional[Dict[str, Any]]:
    advisory_created = float(advisory.get("created_at") or 0.0)
    session_id = str(advisory.get("session_id") or "")
    tool = str(advisory.get("tool") or "")
    if advisory_created <= 0.0 or not (session_id and tool):
        return None
    best: Optional[Dict[str, Any]] = None
    for line_no, row in outcome_rows:
        ts = _parse_ts(row)
        if ts < advisory_created:
            continue
        if max_match_window_s > 0 and ts - advisory_created > max_match_window_s:
            continue
        if str(row.get("session_id") or "") != session_id:
            continue
        if str(row.get("tool") or "").lower() != tool.lower():
            continue
        et = str(row.get("event_type") or "").strip().lower()
        polarity = str(row.get("polarity") or "").strip().lower()
        hint = "neutral"
        if et.endswith("success") or polarity == "pos":
            hint = "positive"
        elif et.endswith("failure") or polarity == "neg":
            hint = "negative"
        cur = {
            "status": "acted",
            "matched_at": ts,
            "latency_s": max(0.0, ts - advisory_created),
            "match_type": "implicit_outcome",
            "effect_hint": hint,
            "confidence_hint": 0.55,
            "evidence_refs": [f"{OUTCOMES_FILE}:{line_no}"],
            "evidence_excerpt": str(row.get("text") or "")[:240],
        }
        if best is None or ts < float(best.get("matched_at") or 0.0):
            best = cur
    return best


def match_actions(
    advisories: List[Dict[str, Any]],
    *,
    feedback_file: Path = FEEDBACK_FILE,
    reports_dir: Path = REPORTS_DIR,
    outcomes_file: Path = OUTCOMES_FILE,
    max_match_window_s: float = 6 * 3600,
) -> List[Dict[str, Any]]:
    feedback_rows = _read_jsonl(feedback_file)
    report_rows = _load_reports(reports_dir)
    outcome_rows = _read_jsonl(outcomes_file)

    matches: List[Dict[str, Any]] = []
    for advisory in advisories:
        advisory_instance_id = str(advisory.get("advisory_instance_id") or "")
        match = (
            _match_explicit_feedback(advisory, feedback_rows, max_match_window_s)
            or _match_reports(advisory, report_rows, max_match_window_s)
            or _match_implicit_outcome(advisory, outcome_rows, max_match_window_s)
        )
        if match is None:
            match = {
                "status": "unresolved",
                "matched_at": None,
                "latency_s": None,
                "match_type": "none",
                "effect_hint": "neutral",
                "confidence_hint": 0.35,
                "evidence_refs": [],
                "evidence_excerpt": "",
            }
        match["advisory_instance_id"] = advisory_instance_id
        matches.append(match)
    return matches
