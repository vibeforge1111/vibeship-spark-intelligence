"""Build EIDOS distillation training curriculum from live distillation data.

This module creates concrete "question cards" that can be used to train
distillation refinement loops (deterministic and optional runtime-LLM assist).
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_SPARK_DIR = Path.home() / ".spark"
_DEFAULT_DB = _SPARK_DIR / "eidos.db"
_LATEST_REPORT_FILE = _SPARK_DIR / "eidos_curriculum_latest.json"
_HISTORY_FILE = _SPARK_DIR / "eidos_curriculum_history.jsonl"

_SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def _llm_area_curriculum_gap_summarize(
    gap_counts: Dict[str, int],
    severity_counts: Dict[str, int],
    rows_scanned: int,
) -> str:
    """LLM area: generate narrative summary of curriculum gaps.

    When disabled (default), returns empty string.
    """
    try:
        from .llm_area_prompts import format_prompt
        from .llm_dispatch import llm_area_call

        prompt = format_prompt(
            "curriculum_gap_summarize",
            gap_counts=str(gap_counts),
            severity_counts=str(severity_counts),
            rows_scanned=str(rows_scanned),
        )
        result = llm_area_call("curriculum_gap_summarize", prompt, fallback="")
        if result.used_llm and result.text:
            return result.text
        return ""
    except Exception:
        return ""


@dataclass(frozen=True)
class DistillationRow:
    distillation_id: str
    dtype: str
    statement: str
    refined_statement: str
    advisory_quality: Dict[str, Any]
    times_used: int
    times_helped: int
    source: str = "distillations"
    archive_reason: str = ""


def _decode_quality(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            data = json.loads(s)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return float(default)


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return int(default)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception:
        return set()
    out: set[str] = set()
    for row in rows:
        # PRAGMA columns: cid, name, type, notnull, dflt_value, pk
        if len(row) >= 2 and row[1]:
            out.add(str(row[1]))
    return out


def _load_rows_from_distillations(conn: sqlite3.Connection, limit: int) -> List[DistillationRow]:
    cols = _table_columns(conn, "distillations")
    if not cols:
        return []

    wanted = [
        "distillation_id",
        "type",
        "statement",
        "refined_statement",
        "advisory_quality",
        "times_used",
        "times_helped",
    ]
    selected = [c for c in wanted if c in cols]
    if not selected:
        return []

    sql = f"SELECT {', '.join(selected)} FROM distillations ORDER BY rowid DESC LIMIT ?"  # noqa: S608 - columns are selected from schema introspection
    out: List[DistillationRow] = []
    try:
        rows = conn.execute(sql, (max(1, int(limit)),)).fetchall()
    except Exception:
        return out

    for row in rows:
        values = dict(zip(selected, row))
        out.append(
            DistillationRow(
                distillation_id=str(values.get("distillation_id") or ""),
                dtype=str(values.get("type") or ""),
                statement=str(values.get("statement") or ""),
                refined_statement=str(values.get("refined_statement") or ""),
                advisory_quality=_decode_quality(values.get("advisory_quality")),
                times_used=_safe_int(values.get("times_used"), 0),
                times_helped=_safe_int(values.get("times_helped"), 0),
                source="distillations",
            )
        )
    return out


def _load_rows_from_archive(conn: sqlite3.Connection, limit: int) -> List[DistillationRow]:
    cols = _table_columns(conn, "distillations_archive")
    if not cols:
        return []

    wanted = [
        "distillation_id",
        "type",
        "statement",
        "refined_statement",
        "advisory_quality",
        "times_used",
        "times_helped",
        "archive_reason",
    ]
    selected = [c for c in wanted if c in cols]
    if not selected:
        return []

    sql = f"SELECT {', '.join(selected)} FROM distillations_archive ORDER BY rowid DESC LIMIT ?"  # noqa: S608 - columns are selected from schema introspection
    out: List[DistillationRow] = []
    try:
        rows = conn.execute(sql, (max(1, int(limit)),)).fetchall()
    except Exception:
        return out

    for row in rows:
        values = dict(zip(selected, row))
        out.append(
            DistillationRow(
                distillation_id=str(values.get("distillation_id") or ""),
                dtype=str(values.get("type") or ""),
                statement=str(values.get("statement") or ""),
                refined_statement=str(values.get("refined_statement") or ""),
                advisory_quality=_decode_quality(values.get("advisory_quality")),
                times_used=_safe_int(values.get("times_used"), 0),
                times_helped=_safe_int(values.get("times_helped"), 0),
                source="distillations_archive",
                archive_reason=str(values.get("archive_reason") or ""),
            )
        )
    return out


def _card(
    row: DistillationRow,
    *,
    gap: str,
    severity: str,
    question: str,
    clear_answer: str,
    recommended_loop: str,
    why: str,
) -> Dict[str, Any]:
    return {
        "card_id": f"{row.source}:{row.distillation_id or 'unknown'}:{gap}",
        "distillation_id": row.distillation_id,
        "type": row.dtype,
        "source": row.source,
        "gap": gap,
        "severity": severity,
        "question": question,
        "clear_answer": clear_answer,
        "recommended_loop": recommended_loop,
        "llm_runtime_recommended": recommended_loop == "deterministic_then_llm",
        "answer_mode": (
            "single_plus_llm"
            if recommended_loop == "deterministic_then_llm"
            else "single_clear"
        ),
        "statement": (row.refined_statement or row.statement)[:300],
        "why": why,
        "archive_reason": row.archive_reason,
    }


def _derive_cards(row: DistillationRow) -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = []
    q = row.advisory_quality if isinstance(row.advisory_quality, dict) else {}

    suppressed = bool(q.get("suppressed", False))
    unified = _safe_float(q.get("unified_score"), 0.0)
    actionability = _safe_float(q.get("actionability"), 0.0)
    reasoning = _safe_float(q.get("reasoning"), 0.0)
    specificity = _safe_float(q.get("specificity"), 0.0)

    # Archived/suppressed rows are best candidates for targeted refinement drills.
    if suppressed or row.archive_reason.startswith("suppressed:"):
        cards.append(
            _card(
                row,
                gap="suppressed_statement",
                severity="high",
                question="What single action-first rewrite would remove suppression without changing meaning?",
                clear_answer="Rewrite to explicit 'When <condition>: <action> because <reason>' and keep it under 220 chars.",
                recommended_loop="deterministic_then_llm",
                why="Suppressed distillations are currently unusable in advisory retrieval.",
            )
        )

    if unified < 0.35 or row.archive_reason.startswith("unified_score_below_floor:"):
        cards.append(
            _card(
                row,
                gap="low_unified_score",
                severity="high",
                question="Which missing component (condition/action/reason) most directly raises unified quality above floor?",
                clear_answer="Fill the weakest missing component first, then re-score before any further edits.",
                recommended_loop="deterministic_then_llm" if unified < 0.25 else "deterministic_only",
                why=f"Unified score {unified:.2f} is below advisory floor.",
            )
        )

    if actionability < 0.40:
        cards.append(
            _card(
                row,
                gap="low_actionability",
                severity="medium",
                question="What exact operator action should be taken first?",
                clear_answer="Replace observations with a direct verb-led action and include scope.",
                recommended_loop="deterministic_only",
                why=f"Actionability is low ({actionability:.2f}).",
            )
        )

    if reasoning < 0.35:
        cards.append(
            _card(
                row,
                gap="low_reasoning",
                severity="medium",
                question="What causal 'because' clause is supported by episode evidence?",
                clear_answer="Attach one evidence-grounded reason; avoid speculative rationale.",
                recommended_loop="deterministic_then_llm",
                why=f"Reasoning is low ({reasoning:.2f}).",
            )
        )

    if specificity < 0.35:
        cards.append(
            _card(
                row,
                gap="low_specificity",
                severity="medium",
                question="Which concrete context (tool/file/constraint) should be named?",
                clear_answer="Name one concrete context anchor and remove vague terms.",
                recommended_loop="deterministic_only",
                why=f"Specificity is low ({specificity:.2f}).",
            )
        )

    if row.times_used >= 5:
        effectiveness = row.times_helped / max(row.times_used, 1)
        if effectiveness < 0.30:
            cards.append(
                _card(
                    row,
                    gap="low_effectiveness",
                    severity="high",
                    question="Why is this distillation retrieved often but helping rarely?",
                    clear_answer="Tighten trigger conditions or archive until stronger evidence exists.",
                    recommended_loop="deterministic_then_llm",
                    why=f"Usage effectiveness is low ({effectiveness:.2%}).",
                )
            )

    return cards


def build_curriculum(
    *,
    db_path: Optional[Path] = None,
    max_rows: int = 300,
    max_cards: int = 200,
    include_archive: bool = True,
) -> Dict[str, Any]:
    """Generate an EIDOS distillation curriculum from live database rows."""
    target_db = Path(db_path) if db_path else _DEFAULT_DB
    out: Dict[str, Any] = {
        "generated_at": int(time.time()),
        "db_path": str(target_db),
        "stats": {
            "rows_scanned": 0,
            "cards_generated": 0,
            "gaps": {},
            "severity": {},
        },
        "cards": [],
    }

    if not target_db.exists():
        return out

    rows: List[DistillationRow] = []
    try:
        conn = sqlite3.connect(str(target_db))
        rows.extend(_load_rows_from_distillations(conn, limit=max_rows))
        if include_archive:
            rows.extend(_load_rows_from_archive(conn, limit=max_rows // 2))
        conn.close()
    except Exception:
        return out

    cards: List[Dict[str, Any]] = []
    for row in rows:
        cards.extend(_derive_cards(row))

    def _priority(card: Dict[str, Any]) -> tuple[int, int]:
        sev = _SEVERITY_WEIGHT.get(str(card.get("severity") or "").lower(), 0)
        loop_bonus = 1 if str(card.get("recommended_loop")) == "deterministic_then_llm" else 0
        return sev, loop_bonus

    cards.sort(key=_priority, reverse=True)
    cards = cards[: max(1, int(max_cards))]

    gap_counts: Dict[str, int] = {}
    severity_counts: Dict[str, int] = {}
    for card in cards:
        gap = str(card.get("gap") or "unknown")
        sev = str(card.get("severity") or "unknown")
        gap_counts[gap] = gap_counts.get(gap, 0) + 1
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    out["stats"] = {
        "rows_scanned": len(rows),
        "cards_generated": len(cards),
        "gaps": gap_counts,
        "severity": severity_counts,
    }
    out["cards"] = cards

    # LLM area: curriculum_gap_summarize — generate narrative summary of gaps
    out["gap_summary"] = _llm_area_curriculum_gap_summarize(gap_counts, severity_counts, len(rows))

    return out


def save_curriculum_snapshot(
    report: Dict[str, Any],
    *,
    latest_path: Path = _LATEST_REPORT_FILE,
    history_path: Path = _HISTORY_FILE,
) -> Dict[str, Any]:
    """Persist latest curriculum report + append compact history row."""
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    payload = dict(report) if isinstance(report, dict) else {}
    payload["saved_at"] = int(time.time())
    latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    sev = stats.get("severity") if isinstance(stats.get("severity"), dict) else {}
    history_row = {
        "ts": int(time.time()),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "rows_scanned": int(stats.get("rows_scanned", 0) or 0),
        "cards_generated": int(stats.get("cards_generated", 0) or 0),
        "high": int(sev.get("high", 0) or 0),
        "medium": int(sev.get("medium", 0) or 0),
        "low": int(sev.get("low", 0) or 0),
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(history_row, ensure_ascii=True) + "\n")

    return history_row


def load_curriculum_latest(path: Path = _LATEST_REPORT_FILE) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def tail_curriculum_history(path: Path = _HISTORY_FILE, limit: int = 60) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    for line in lines[-max(1, int(limit)):]:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except Exception:
            continue
    return out


def render_curriculum_markdown(report: Dict[str, Any], *, max_cards: int = 30) -> str:
    """Render curriculum report as Markdown for runbooks or Obsidian."""
    stats = report.get("stats") if isinstance(report, dict) else {}
    cards = report.get("cards") if isinstance(report, dict) else []
    if not isinstance(stats, dict):
        stats = {}
    if not isinstance(cards, list):
        cards = []

    lines: List[str] = []
    lines.append("# EIDOS Distillation Curriculum")
    lines.append("")
    lines.append(f"- DB: `{report.get('db_path', '')}`")
    lines.append(f"- Rows scanned: `{stats.get('rows_scanned', 0)}`")
    lines.append(f"- Cards generated: `{stats.get('cards_generated', 0)}`")
    lines.append("")

    gaps = stats.get("gaps", {})
    if isinstance(gaps, dict) and gaps:
        lines.append("## Gap Summary")
        lines.append("")
        for k, v in sorted(gaps.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"- `{k}`: {v}")
        lines.append("")

    lines.append("## Top Question Cards")
    lines.append("")
    for idx, card in enumerate(cards[: max(1, int(max_cards))], start=1):
        lines.append(f"### {idx}. {card.get('gap', 'unknown')} ({card.get('severity', 'unknown')})")
        lines.append(f"- Distillation: `{card.get('distillation_id', '')}` ({card.get('source', '')})")
        lines.append(f"- Question: {card.get('question', '')}")
        lines.append(f"- Clear answer: {card.get('clear_answer', '')}")
        lines.append(f"- Recommended loop: `{card.get('recommended_loop', '')}`")
        lines.append(f"- Why: {card.get('why', '')}")
        lines.append("")

    return "\n".join(lines)
