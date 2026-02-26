"""Auto-refinement worker for high-priority EIDOS curriculum cards."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .distillation_refiner import refine_distillation
from .eidos_distillation_curriculum import build_curriculum

_SPARK_DIR = Path.home() / ".spark"
_DEFAULT_DB = _SPARK_DIR / "eidos.db"
_SUPPORTED_TABLES = {"distillations", "distillations_archive"}


def _table_info(conn: sqlite3.Connection, table: str) -> List[tuple[Any, ...]]:
    if table not in _SUPPORTED_TABLES:
        return []
    try:
        return conn.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception:
        return []


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    out: set[str] = set()
    for row in _table_info(conn, table):
        if len(row) >= 2 and row[1]:
            out.add(str(row[1]))
    return out


def _table_pk_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    ranked: List[Tuple[int, str]] = []
    for row in _table_info(conn, table):
        if len(row) < 6 or not row[1]:
            continue
        try:
            pk_rank = int(row[5] or 0)
        except Exception:
            pk_rank = 0
        if pk_rank > 0:
            ranked.append((pk_rank, str(row[1])))
    ranked.sort(key=lambda item: item[0])
    return [name for _, name in ranked]


def _decode_quality(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _rank(quality: Dict[str, Any]) -> tuple[int, float, float]:
    q = quality if isinstance(quality, dict) else {}
    suppressed = bool(q.get("suppressed", False))
    unified = _safe_float(q.get("unified_score"), 0.0)
    combo = _quality_combo(q)
    return (0 if suppressed else 1, unified, combo)


def _quality_combo(quality: Dict[str, Any]) -> float:
    q = quality if isinstance(quality, dict) else {}
    return (
        _safe_float(q.get("actionability"), 0.0)
        + _safe_float(q.get("reasoning"), 0.0)
        + _safe_float(q.get("specificity"), 0.0)
    )


def _is_improved(old_q: Dict[str, Any], new_q: Dict[str, Any], *, min_gain: float) -> bool:
    old_unified = _safe_float((old_q or {}).get("unified_score"), 0.0)
    new_unified = _safe_float((new_q or {}).get("unified_score"), 0.0)
    if _rank(new_q) > _rank(old_q):
        if new_unified >= old_unified:
            return True
    return (new_unified - old_unified) >= max(0.0, float(min_gain))


def _load_distillation_row(
    conn: sqlite3.Connection,
    *,
    table: str,
    distillation_id: str,
) -> Optional[Dict[str, Any]]:
    if table not in _SUPPORTED_TABLES:
        return None
    cols = _table_columns(conn, table)
    if not cols or "distillation_id" not in cols:
        return None

    selected = [
        c
        for c in ("distillation_id", "statement", "refined_statement", "advisory_quality")
        if c in cols
    ]
    if not selected:
        return None

    row = conn.execute(
        f"SELECT {', '.join(selected)} FROM {table} "  # noqa: S608 - table is allowlisted above
        "WHERE distillation_id = ? ORDER BY rowid DESC LIMIT 1",
        (distillation_id,),
    ).fetchone()
    if not row:
        return None

    return dict(zip(selected, row))


def _persist_refinement(
    conn: sqlite3.Connection,
    *,
    table: str,
    distillation_id: str,
    statement: str,
    refined_text: str,
    quality_payload: str,
) -> bool:
    if table not in _SUPPORTED_TABLES:
        return False
    cols = _table_columns(conn, table)
    if not cols or "distillation_id" not in cols:
        return False

    sets: List[str] = []
    args: List[Any] = []

    if "refined_statement" in cols:
        persisted_refined = refined_text
        if persisted_refined == statement:
            persisted_refined = ""
        sets.append("refined_statement = ?")
        args.append(persisted_refined)

    if "advisory_quality" in cols:
        sets.append("advisory_quality = ?")
        args.append(quality_payload)

    if not sets:
        return False

    conn.execute(
        f"UPDATE {table} SET {', '.join(sets)} WHERE distillation_id = ?",  # noqa: S608 - table is allowlisted above
        tuple(args + [distillation_id]),
    )
    return True


def _promote_archive_row(
    conn: sqlite3.Connection,
    *,
    distillation_id: str,
    refined_text: str,
    quality_payload: str,
) -> bool:
    archive_cols = _table_columns(conn, "distillations_archive")
    target_cols = _table_columns(conn, "distillations")
    if not archive_cols or not target_cols:
        return False
    if "distillation_id" not in archive_cols or "distillation_id" not in target_cols:
        return False

    archive_row = conn.execute(
        "SELECT * FROM distillations_archive WHERE distillation_id = ? ORDER BY rowid DESC LIMIT 1",
        (distillation_id,),
    ).fetchone()
    if not archive_row:
        return False

    source_data = dict(archive_row)

    payload: Dict[str, Any] = {}
    for col in sorted(target_cols.intersection(archive_cols)):
        if col in source_data:
            payload[col] = source_data[col]

    if "distillation_id" not in payload:
        payload["distillation_id"] = distillation_id
    if "refined_statement" in target_cols:
        payload["refined_statement"] = refined_text
    if "advisory_quality" in target_cols:
        payload["advisory_quality"] = quality_payload

    pk_cols = _table_pk_columns(conn, "distillations")
    if not pk_cols:
        pk_cols = ["distillation_id"] if "distillation_id" in payload else []
    if not pk_cols or any(col not in payload for col in pk_cols):
        return False

    where_clause = " AND ".join([f"{col} = ?" for col in pk_cols])
    where_values = [payload[col] for col in pk_cols]
    exists = conn.execute(
        f"SELECT 1 FROM distillations WHERE {where_clause} LIMIT 1",  # noqa: S608 - where clause is derived from validated PK cols
        tuple(where_values),
    ).fetchone()

    if exists:
        update_cols = [col for col in payload.keys() if col not in pk_cols]
        if update_cols:
            set_clause = ", ".join([f"{col} = ?" for col in update_cols])
            conn.execute(
                f"UPDATE distillations SET {set_clause} WHERE {where_clause}",  # noqa: S608 - set/where clauses are derived from validated column names
                tuple([payload[col] for col in update_cols] + where_values),
            )
        return True

    insert_cols = list(payload.keys())
    placeholders = ", ".join(["?"] * len(insert_cols))
    try:
        conn.execute(
            f"INSERT INTO distillations ({', '.join(insert_cols)}) VALUES ({placeholders})",  # noqa: S608 - insert cols derived from validated schema columns
            tuple(payload[col] for col in insert_cols),
        )
        return True
    except sqlite3.IntegrityError:
        # Last-resort upsert fallback for schemas with non-pk uniqueness constraints.
        if "distillation_id" not in payload:
            return False
        conn.execute(
            "UPDATE distillations SET refined_statement = ?, advisory_quality = ? WHERE distillation_id = ?",
            (refined_text, quality_payload, distillation_id),
        )
        return True


def run_curriculum_autofix(
    *,
    db_path: Optional[Path] = None,
    max_cards: int = 5,
    min_gain: float = 0.03,
    apply: bool = False,
    include_archive: bool = False,
    promote_on_success: bool = False,
    promote_min_unified: float = 0.60,
    archive_fallback_llm: bool = True,
    soft_promote_on_success: bool = False,
    soft_promote_min_unified: float = 0.35,
) -> Dict[str, Any]:
    """Run curriculum-driven refinement attempts on top priority cards."""
    target_db = Path(db_path) if db_path else _DEFAULT_DB
    report: Dict[str, Any] = {
        "ts": int(time.time()),
        "db_path": str(target_db),
        "max_cards": max(1, int(max_cards)),
        "min_gain": float(min_gain),
        "apply": bool(apply),
        "include_archive": bool(include_archive),
        "promote_on_success": bool(promote_on_success),
        "promote_min_unified": float(promote_min_unified),
        "archive_fallback_llm": bool(archive_fallback_llm),
        "soft_promote_on_success": bool(soft_promote_on_success),
        "soft_promote_min_unified": float(soft_promote_min_unified),
        "mode_used": "deterministic_plus_fallback" if bool(archive_fallback_llm) else "deterministic_only",
        "candidates": 0,
        "attempted": 0,
        "updated": 0,
        "archive_attempted": 0,
        "archive_updated": 0,
        "archive_promoted": 0,
        "archive_stagnation_detected": False,
        "archive_update_rate": 0.0,
        "suppression_recovery_rate": 0.0,
        "rows": [],
    }
    if not target_db.exists():
        report["error"] = "db_missing"
        return report

    curriculum = build_curriculum(
        db_path=target_db,
        max_rows=300,
        max_cards=max(20, int(max_cards) * 6),
        include_archive=bool(include_archive),
    )
    cards = curriculum.get("cards") if isinstance(curriculum, dict) else []
    if not isinstance(cards, list):
        cards = []

    ordered_targets: List[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for card in cards:
        if not isinstance(card, dict):
            continue
        source = str(card.get("source") or "").strip()
        if source not in _SUPPORTED_TABLES:
            continue
        if source == "distillations_archive" and not bool(include_archive):
            continue
        dist_id = str(card.get("distillation_id") or "").strip()
        key = (source, dist_id)
        if not dist_id or key in seen:
            continue
        seen.add(key)
        ordered_targets.append(key)

    report["candidates"] = len(ordered_targets)
    targets = ordered_targets[: max(1, int(max_cards))]

    conn = sqlite3.connect(str(target_db), timeout=5)
    conn.row_factory = sqlite3.Row
    suppressed_attempted = 0
    suppressed_recovered = 0
    try:
        for source, dist_id in targets:
            row = _load_distillation_row(conn, table=source, distillation_id=dist_id)
            if not isinstance(row, dict):
                continue

            statement = str(row.get("statement") or "").strip()
            refined_statement = str(row.get("refined_statement") or "").strip()
            input_text = refined_statement or statement
            if not input_text:
                continue

            old_q = _decode_quality(row.get("advisory_quality"))
            old_unified = _safe_float(old_q.get("unified_score"), 0.0)
            refine_context = {"curriculum_autofix": True, "distillation_id": dist_id, "source": source}
            new_text, new_q = refine_distillation(
                input_text,
                source="eidos",
                context=refine_context,
                min_unified_score=0.60,
            )
            if source == "distillations_archive" and bool(archive_fallback_llm):
                pass_a_suppressed = bool((new_q or {}).get("suppressed", False))
                pass_a_unified = _safe_float((new_q or {}).get("unified_score"), 0.0)
                pass_a_gain = pass_a_unified - old_unified
                if pass_a_suppressed or pass_a_gain < float(min_gain):
                    fallback_context = dict(refine_context)
                    fallback_context["archive_fallback_pass"] = True
                    fallback_input = str(new_text or "").strip() or input_text
                    fallback_text, fallback_q = refine_distillation(
                        fallback_input,
                        source="eidos",
                        context=fallback_context,
                        min_unified_score=0.60,
                    )
                    if _rank(fallback_q) > _rank(new_q):
                        new_text, new_q = fallback_text, fallback_q
            improved = _is_improved(old_q, new_q, min_gain=float(min_gain))
            changed_text = str(new_text or "").strip() and str(new_text).strip() != input_text

            old_suppressed = bool(old_q.get("suppressed", False))
            new_suppressed = bool((new_q or {}).get("suppressed", False))
            if old_suppressed:
                suppressed_attempted += 1
                if not new_suppressed:
                    suppressed_recovered += 1

            action = "noop"
            new_quality_payload = json.dumps(new_q, ensure_ascii=True)
            if improved:
                action = "improved"
                if apply:
                    persisted_refined = str(new_text or "").strip()
                    persisted = _persist_refinement(
                        conn,
                        table=source,
                        distillation_id=dist_id,
                        statement=statement,
                        refined_text=persisted_refined,
                        quality_payload=new_quality_payload,
                    )
                    if persisted:
                        report["updated"] += 1
                        action = "updated"
                        if source == "distillations_archive":
                            report["archive_updated"] += 1

                    hard_promoted = False
                    promote_candidate = (
                        source == "distillations_archive"
                        and bool(promote_on_success)
                        and not new_suppressed
                        and _safe_float((new_q or {}).get("unified_score"), 0.0) >= float(promote_min_unified)
                        and _quality_combo(new_q) >= _quality_combo(old_q)
                    )
                    if promote_candidate and _promote_archive_row(
                        conn,
                        distillation_id=dist_id,
                        refined_text=persisted_refined,
                        quality_payload=new_quality_payload,
                    ):
                        report["archive_promoted"] += 1
                        hard_promoted = True
                        action = "promoted"

                    soft_promote_candidate = (
                        source == "distillations_archive"
                        and bool(soft_promote_on_success)
                        and not promote_candidate
                        and not hard_promoted
                        and not new_suppressed
                        and _safe_float((new_q or {}).get("unified_score"), 0.0) >= float(soft_promote_min_unified)
                        and _quality_combo(new_q) >= _quality_combo(old_q)
                    )
                    if soft_promote_candidate:
                        soft_quality = dict(new_q or {})
                        soft_quality["soft_promoted"] = True
                        soft_quality_payload = json.dumps(soft_quality, ensure_ascii=True)
                        soft_persisted = _persist_refinement(
                            conn,
                            table=source,
                            distillation_id=dist_id,
                            statement=statement,
                            refined_text=persisted_refined,
                            quality_payload=soft_quality_payload,
                        )
                        if soft_persisted:
                            new_q = soft_quality
                            new_quality_payload = soft_quality_payload
                            action = "soft_promoted"

            report["attempted"] += 1
            if source == "distillations_archive":
                report["archive_attempted"] += 1
                rate = report["archive_updated"] / report["archive_attempted"]
                report["archive_update_rate"] = round(rate, 4)
                report["archive_stagnation_detected"] = report["archive_update_rate"] < 0.05

            report["rows"].append(
                {
                    "distillation_id": dist_id,
                    "source": source,
                    "old_unified": round(_safe_float(old_q.get("unified_score"), 0.0), 4),
                    "new_unified": round(_safe_float(new_q.get("unified_score"), 0.0), 4),
                    "old_suppressed": old_suppressed,
                    "new_suppressed": new_suppressed,
                    "changed_text": bool(changed_text),
                    "action": action,
                }
            )

        if apply:
            conn.commit()
    finally:
        conn.close()

    report["suppression_recovery_rate"] = (
        round(suppressed_recovered / suppressed_attempted, 4) if suppressed_attempted > 0 else 0.0
    )
    if report["archive_attempted"] > 0:
        report["archive_update_rate"] = round(report["archive_updated"] / report["archive_attempted"], 4)
    else:
        report["archive_update_rate"] = 0.0
    report["archive_stagnation_detected"] = (
        bool(report["archive_attempted"] > 0 and report["archive_update_rate"] < 0.05)
    )
    return report
