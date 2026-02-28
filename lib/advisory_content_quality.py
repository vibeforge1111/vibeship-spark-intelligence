"""Production content-quality regression audit for advisory intelligence.

This module inspects live Spark artifacts and evaluates whether the noise
classifier is catching the kinds of low-value content that actually pollute
advisory and promotion surfaces.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .noise_classifier import classify

_HARD_NOISE_PATTERNS = (
    ("chunk_id_telemetry", re.compile(r"\b(exec_command failed|chunk id)\b", re.I)),
    (
        "css_fragment",
        re.compile(
            r"\{[^{}]{0,320}\b(position|display|padding|margin|font|color|z-index|overflow)\b[^{}]*\}",
            re.I,
        ),
    ),
    (
        "conversational_directive",
        re.compile(
            r"^\s*(ok|okay|sure|sounds good|lets do it|let's do it)\b|"
            r"\b(can we now run|run localhost|it worked)\b",
            re.I,
        ),
    ),
    ("generic_sentiment", re.compile(r"\b(user expressed satisfaction|great response|nice work)\b", re.I)),
)

_SIGNAL_HINT_RE = re.compile(
    r"\b(use|enforce|validate|check|add|remove|fix|decompose|refactor|gate|benchmark|"
    r"regression|threshold|schema|token|retrieval|advisory|memory|trace|provider|config|"
    r"dedupe|cooldown|fallback|rerank|distillation)\b",
    re.I,
)


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_ts(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = _norm_text(value)
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return float(text)
    except Exception:
        pass
    try:
        return float(datetime.fromisoformat(text).timestamp())
    except Exception:
        return 0.0


def _extract_ts(row: Dict[str, Any], keys: Iterable[str]) -> float:
    for key in keys:
        ts = _safe_ts(row.get(key))
        if ts > 0:
            return ts
    return 0.0


def _tail_jsonl(path: Path, max_rows: int) -> List[Dict[str, Any]]:
    if not path.exists() or max_rows <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for raw in lines[-max_rows:]:
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _load_cognitive_rows(path: Path, max_rows: int) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    out: List[Dict[str, Any]] = []
    items = list(payload.items())[-max_rows:]
    for key, value in items:
        text = ""
        ts = 0.0
        if isinstance(value, dict):
            text = _norm_text(value.get("insight") or value.get("content") or value.get("text"))
            ts = _extract_ts(value, ("created_at", "created_ts", "last_seen", "updated_at", "ts"))
        else:
            text = _norm_text(value)
        out.append(
            {
                "source": "cognitive",
                "id": _norm_text(key) or "?",
                "text": text,
                "ts": ts,
            }
        )
    return out


def _extract_text(row: Dict[str, Any], fields: Iterable[str]) -> str:
    for key in fields:
        value = _norm_text(row.get(key))
        if value:
            return value
    return ""


def _load_jsonl_rows(
    *,
    path: Path,
    source: str,
    max_rows: int,
    text_fields: Iterable[str],
    id_fields: Iterable[str],
    ts_fields: Iterable[str],
) -> List[Dict[str, Any]]:
    rows = _tail_jsonl(path, max_rows=max_rows)
    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        text = _extract_text(row, text_fields)
        rec_id = _extract_text(row, id_fields) or f"{source}:{idx}"
        out.append(
            {
                "source": source,
                "id": rec_id,
                "text": text,
                "ts": _extract_ts(row, ts_fields),
            }
        )
    return out


def _hard_noise_reason(text: str) -> str:
    sample = _norm_text(text)
    if not sample:
        return "empty"
    for reason, rx in _HARD_NOISE_PATTERNS:
        if rx.search(sample):
            return reason
    return ""


def _expected_signal(text: str) -> bool:
    sample = _norm_text(text)
    if len(sample) < 30:
        return False
    if not _SIGNAL_HINT_RE.search(sample):
        return False
    if sample.endswith("?") and len(sample.split()) <= 20:
        return False
    return True


def _context_for_source(source: str) -> str:
    key = _norm_text(source).lower()
    if key == "promotion":
        return "promoter"
    if key in {"emit", "recent_advice"}:
        return "retrieval"
    return "generic"


def _snippet(text: str, limit: int = 220) -> str:
    sample = " ".join(_norm_text(text).split())
    if len(sample) <= limit:
        return sample
    return sample[:limit] + "..."


def build_production_noise_report(
    *,
    spark_dir: Path,
    max_rows_per_source: int = 1200,
    detail_rows: int = 600,
) -> Dict[str, Any]:
    now_ts = time.time()
    max_rows = max(50, int(max_rows_per_source))

    rows: List[Dict[str, Any]] = []
    rows.extend(_load_cognitive_rows(spark_dir / "cognitive_insights.json", max_rows=max_rows))
    rows.extend(
        _load_jsonl_rows(
            path=spark_dir / "promotion_log.jsonl",
            source="promotion",
            max_rows=max_rows,
            text_fields=("insight", "content", "text", "key", "reason"),
            id_fields=("key", "insight_key", "id"),
            ts_fields=("ts", "timestamp", "created_at"),
        )
    )
    rows.extend(
        _load_jsonl_rows(
            path=spark_dir / "advisory_emit.jsonl",
            source="emit",
            max_rows=max_rows,
            text_fields=("advice_text", "advice", "text", "message"),
            id_fields=("advice_id", "trace_id", "id"),
            ts_fields=("ts", "timestamp", "created_at", "emitted_ts"),
        )
    )
    rows.extend(
        _load_jsonl_rows(
            path=spark_dir / "advisor" / "recent_advice.jsonl",
            source="recent_advice",
            max_rows=max_rows,
            text_fields=("advice", "advice_text", "text"),
            id_fields=("trace_id", "advice_id", "id"),
            ts_fields=("ts", "timestamp", "created_at"),
        )
    )

    classifier_noise_rows = 0
    expected_noise_rows = 0
    expected_signal_rows = 0
    true_positive = 0
    false_negative = 0
    false_positive = 0

    by_source: Dict[str, int] = {}
    by_rule: Dict[str, int] = {}
    by_hard_reason: Dict[str, int] = {}
    evaluated: List[Dict[str, Any]] = []

    for row in rows:
        source = _norm_text(row.get("source")) or "unknown"
        text = _norm_text(row.get("text"))
        if not text:
            continue
        by_source[source] = by_source.get(source, 0) + 1

        hard_reason = _hard_noise_reason(text)
        hard_noise = bool(hard_reason)
        expected_signal = (not hard_noise) and _expected_signal(text)

        decision = classify(text, context=_context_for_source(source))
        is_noise = bool(decision.is_noise)
        if is_noise:
            classifier_noise_rows += 1
        by_rule[_norm_text(decision.rule) or "none"] = by_rule.get(_norm_text(decision.rule) or "none", 0) + 1

        if hard_noise:
            expected_noise_rows += 1
            by_hard_reason[hard_reason] = by_hard_reason.get(hard_reason, 0) + 1
            if is_noise:
                true_positive += 1
            else:
                false_negative += 1
        elif expected_signal:
            expected_signal_rows += 1
            if is_noise:
                false_positive += 1

        evaluated.append(
            {
                "source": source,
                "id": _norm_text(row.get("id")) or "?",
                "ts": float(row.get("ts") or 0.0),
                "text": text,
                "snippet": _snippet(text),
                "classifier_is_noise": is_noise,
                "classifier_rule": _norm_text(decision.rule) or "none",
                "hard_noise": hard_noise,
                "hard_noise_reason": hard_reason or "-",
                "expected_signal": expected_signal,
            }
        )

    recall = float(true_positive) / float(expected_noise_rows) if expected_noise_rows > 0 else 1.0
    fp_rate = float(false_positive) / float(expected_signal_rows) if expected_signal_rows > 0 else 0.0

    evaluated.sort(key=lambda r: float(r.get("ts") or 0.0), reverse=True)
    detail = evaluated[: max(80, int(detail_rows))]
    false_negatives = [r for r in evaluated if r.get("hard_noise") and not r.get("classifier_is_noise")][:120]
    false_positives = [
        r for r in evaluated if (not r.get("hard_noise")) and r.get("expected_signal") and r.get("classifier_is_noise")
    ][:120]

    return {
        "generated_at": now_ts,
        "spark_dir": str(spark_dir),
        "rows_analyzed": len(evaluated),
        "rows_by_source": by_source,
        "classifier_noise_rows": classifier_noise_rows,
        "expected_noise_rows": expected_noise_rows,
        "expected_signal_rows": expected_signal_rows,
        "true_positive": true_positive,
        "false_negative": false_negative,
        "false_positive": false_positive,
        "recall": round(recall, 4),
        "false_positive_rate": round(fp_rate, 4),
        "hard_noise_signature_counts": by_hard_reason,
        "classifier_rule_counts": by_rule,
        "false_negative_examples": false_negatives,
        "false_positive_examples": false_positives,
        "detailed_rows": detail,
    }
