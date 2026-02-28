"""Canonical intake path for EIDOS distillation updates.

This module centralizes validation, advisory-quality transformation,
dedupe, and persistence for EIDOS distillation rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .distillation_transformer import transform_for_advisory
from .noise_patterns import API_ERROR_STRINGS, GENERIC_ADVICE_STRINGS

DEFAULT_EIDOS_FILE = Path.home() / ".spark" / "eidos_distillations.jsonl"
_EIDOS_NOISE_PATTERNS = list(API_ERROR_STRINGS | GENERIC_ADVICE_STRINGS) + [
    "when repeated",
    "without progress",
]


@dataclass
class EidosIntakeResult:
    ok: bool
    reason: str
    entry: Optional[Dict[str, Any]] = None
    structured: Optional[Dict[str, Any]] = None
    advisory_quality: Dict[str, Any] = field(default_factory=dict)
    advisory_readiness: float = 0.0
    duplicate: bool = False
    spine_saved: int = 0


def _infer_distillation_type(action_text: str, insight_type: str):
    from .eidos.models import DistillationType

    action = str(action_text or "").strip().lower()
    kind = str(insight_type or "").strip().lower()
    if kind in {"failure", "anti_pattern", "anti-pattern"}:
        return DistillationType.ANTI_PATTERN
    if kind in {"workflow", "playbook", "procedure"}:
        return DistillationType.PLAYBOOK
    if kind in {"communication", "policy", "constraint"}:
        return DistillationType.POLICY
    if kind in {"sharp_edge", "gotcha", "pitfall"}:
        return DistillationType.SHARP_EDGE
    if action.startswith(("avoid ", "never ", "do not ", "don't ")):
        return DistillationType.ANTI_PATTERN
    return DistillationType.HEURISTIC


def _derive_domains(sample: str) -> List[str]:
    text = str(sample or "").strip().lower()
    if not text:
        return []
    mapping = {
        "api": "api",
        "auth": "auth",
        "token": "auth",
        "schema": "schema",
        "payload": "schema",
        "test": "testing",
        "pytest": "testing",
        "deploy": "deployment",
        "release": "deployment",
        "runtime": "runtime",
        "queue": "runtime",
        "memory": "memory",
        "advisory": "advisory",
        "sqlite": "data",
        "database": "data",
    }
    domains: List[str] = []
    for needle, domain in mapping.items():
        if needle in text and domain not in domains:
            domains.append(domain)
    return domains[:4]


def _build_spine_distillations(entry: Dict[str, Any], readiness: float):
    from .eidos.models import Distillation

    distillations = []
    insights = entry.get("insights") if isinstance(entry.get("insights"), list) else []
    if insights:
        for item in insights:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip()
            evidence = str(item.get("evidence") or "").strip()
            statement = action or evidence
            if len(statement) < 15:
                continue
            usage_context = str(item.get("usage_context") or "").strip()
            insight_type = str(item.get("insight_type") or "pattern")
            try:
                confidence = float(item.get("confidence") or readiness or 0.6)
            except Exception:
                confidence = float(readiness or 0.6)
            confidence = max(0.3, min(0.95, confidence))

            advisory_quality: Dict[str, Any] = {}
            refined_statement = ""
            try:
                transformed = transform_for_advisory(statement, source="eidos")
                if transformed.suppressed:
                    continue
                advisory_quality = transformed.to_dict()
                refined_statement = str(advisory_quality.get("advisory_text") or "").strip()
            except Exception:
                advisory_quality = {}
                refined_statement = ""

            distillations.append(
                Distillation(
                    distillation_id="",
                    type=_infer_distillation_type(statement, insight_type),
                    statement=statement[:1000],
                    domains=_derive_domains(usage_context or statement),
                    triggers=[usage_context[:180]] if usage_context else [],
                    anti_triggers=[],
                    confidence=confidence,
                    refined_statement=(
                        refined_statement
                        if refined_statement and refined_statement.lower() != statement.lower()
                        else ""
                    ),
                    advisory_quality=advisory_quality,
                )
            )

    if distillations:
        return distillations

    fallback_statement = str(
        entry.get("refined_statement")
        or entry.get("distillation_summary")
        or entry.get("distillation")
        or ""
    ).strip()
    if not fallback_statement:
        return []
    advisory_quality = entry.get("advisory_quality")
    if not isinstance(advisory_quality, dict):
        advisory_quality = {}
    return [
        Distillation(
            distillation_id="",
            type=_infer_distillation_type(fallback_statement, "pattern"),
            statement=fallback_statement[:1000],
            domains=_derive_domains(fallback_statement),
            confidence=max(0.3, min(0.95, float(readiness or 0.6))),
            refined_statement="",
            advisory_quality=advisory_quality,
        )
    ]


def _persist_to_spine(
    entry: Dict[str, Any],
    *,
    readiness: float,
    store_db_path: Optional[Path] = None,
) -> Tuple[int, Optional[str]]:
    try:
        from .eidos.store import EidosStore
    except Exception as exc:
        return 0, f"spine_import_failed:{exc}"

    distillations = _build_spine_distillations(entry, readiness)
    if not distillations:
        return 0, "spine_no_distillations"

    db_path = Path(store_db_path) if store_db_path else (Path.home() / ".spark" / "eidos.db")
    try:
        store = EidosStore(str(db_path))
        saved = 0
        for distillation in distillations:
            store.save_distillation(distillation)
            saved += 1
        return saved, None
    except Exception as exc:
        return 0, f"spine_write_failed:{exc}"


def parse_structured_eidos(text: str) -> Dict[str, Any] | None:
    try:
        obj = json.loads((text or "").strip())
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    insights = obj.get("insights")
    if not isinstance(insights, list) or not insights:
        return None
    return obj


def validate_eidos_distillation(text: str) -> Tuple[bool, str, Dict[str, Any] | None]:
    body = (text or "").strip()
    if len(body) < 24:
        return False, "too_short", None

    low = body.lower()
    for pattern in _EIDOS_NOISE_PATTERNS:
        if pattern in low:
            return False, f"noise:{pattern}", None

    structured = parse_structured_eidos(body)
    if structured is not None:
        kept = [
            item
            for item in (structured.get("insights") or [])
            if isinstance(item, dict) and str(item.get("decision", "keep")).lower() == "keep"
        ]
        if not kept:
            return False, "all_dropped", structured
        return True, "ok_structured", structured

    if not any(ch in body for ch in (".", "\n", ":", ";")):
        return False, "not_structured", None
    return True, "ok", None


def _normalize_entry_sig(entry: Dict[str, Any]) -> str:
    text = str(
        entry.get("refined_statement")
        or entry.get("distillation_summary")
        or entry.get("distillation")
        or ""
    ).strip().lower()
    return " ".join(text.split())


def _build_entry(
    update: str,
    *,
    structured: Dict[str, Any] | None,
    advisory_quality: Dict[str, Any],
    advisory_readiness: float,
) -> Tuple[Optional[Dict[str, Any]], str]:
    if structured is not None:
        kept = []
        for item in (structured.get("insights") or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("decision", "keep")).lower() != "keep":
                continue
            action = str(item.get("action") or "").strip()
            if len(action) < 15:
                continue
            low = action.lower()
            if any(pattern in low for pattern in _EIDOS_NOISE_PATTERNS):
                continue
            kept.append(item)
        if not kept:
            return None, "no_keep_actions"
        summary_parts = []
        for item in kept[:3]:
            action = str(item.get("action") or "").strip()
            context = str(item.get("usage_context") or "").strip()
            if action:
                summary_parts.append(f"{action} ({context})" if context else action)
        summary = " | ".join(summary_parts)[:1200]
        return (
            {
                "timestamp": datetime.now().isoformat(),
                "schema": structured.get("schema") or "spark.eidos.v1",
                "insights": kept[:3],
                "distillation_summary": summary,
                "refined_statement": advisory_quality.get("advisory_text") or summary,
                "advisory_quality": advisory_quality,
                "advisory_readiness": round(min(max(advisory_readiness, 0.0), 1.0), 4),
            },
            "ok_structured",
        )
    return (
        {
            "timestamp": datetime.now().isoformat(),
            "distillation": update,
            "refined_statement": advisory_quality.get("advisory_text") or update,
            "advisory_quality": advisory_quality,
            "advisory_readiness": round(min(max(advisory_readiness, 0.0), 1.0), 4),
        },
        "ok",
    )


def _is_duplicate_entry(entry: Dict[str, Any], eidos_file: Path) -> bool:
    sig = _normalize_entry_sig(entry)
    if not sig or not eidos_file.exists():
        return False
    try:
        tail = eidos_file.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]
    except Exception:
        return False
    for line in reversed(tail):
        try:
            prev = json.loads(line)
        except Exception:
            continue
        if isinstance(prev, dict) and _normalize_entry_sig(prev) == sig:
            return True
    return False


def _record_quarantine(
    fn: Optional[Callable[..., None]],
    *,
    stage: str,
    reason: str,
    text: str,
    advisory_quality: Optional[Dict[str, Any]] = None,
    advisory_readiness: Optional[float] = None,
) -> None:
    if fn is None:
        return
    try:
        fn(
            source="eidos",
            stage=stage,
            reason=reason,
            text=text,
            advisory_quality=advisory_quality,
            advisory_readiness=advisory_readiness,
        )
    except Exception:
        return


def ingest_eidos_update(
    update: str,
    *,
    eidos_file: Optional[Path] = None,
    store_db_path: Optional[Path] = None,
    quarantine_stage: str = "append_eidos_update",
    quarantine_fn: Optional[Callable[..., None]] = None,
) -> EidosIntakeResult:
    ok, reason, structured = validate_eidos_distillation(update)
    if not ok:
        _record_quarantine(
            quarantine_fn,
            stage=quarantine_stage,
            reason=f"validator:{reason}",
            text=update,
        )
        return EidosIntakeResult(ok=False, reason=reason, structured=structured)

    advisory_quality: Dict[str, Any] = {}
    try:
        transformed = transform_for_advisory(update, source="eidos")
        advisory_quality = transformed.to_dict()
        if transformed.suppressed:
            suppression = str(transformed.suppression_reason or "suppressed")
            _record_quarantine(
                quarantine_fn,
                stage=quarantine_stage,
                reason=f"transformer_suppressed:{suppression}",
                text=update,
                advisory_quality=advisory_quality,
                advisory_readiness=float(advisory_quality.get("unified_score") or 0.0),
            )
            return EidosIntakeResult(
                ok=False,
                reason=f"transformer_suppressed:{suppression}",
                structured=structured,
                advisory_quality=advisory_quality,
                advisory_readiness=float(advisory_quality.get("unified_score") or 0.0),
            )
    except Exception:
        advisory_quality = {}

    readiness = float((advisory_quality or {}).get("unified_score") or 0.0)
    entry, build_reason = _build_entry(
        update,
        structured=structured,
        advisory_quality=advisory_quality,
        advisory_readiness=readiness,
    )
    if entry is None:
        _record_quarantine(
            quarantine_fn,
            stage=quarantine_stage,
            reason=build_reason,
            text=update,
            advisory_quality=advisory_quality,
            advisory_readiness=readiness,
        )
        return EidosIntakeResult(
            ok=False,
            reason=build_reason,
            structured=structured,
            advisory_quality=advisory_quality,
            advisory_readiness=readiness,
        )

    spine_saved, spine_error = _persist_to_spine(
        entry,
        readiness=readiness,
        store_db_path=store_db_path,
    )
    if spine_error:
        _record_quarantine(
            quarantine_fn,
            stage=quarantine_stage,
            reason=spine_error,
            text=update,
            advisory_quality=advisory_quality,
            advisory_readiness=readiness,
        )
        return EidosIntakeResult(
            ok=False,
            reason=spine_error,
            entry=entry,
            structured=structured,
            advisory_quality=advisory_quality,
            advisory_readiness=readiness,
            spine_saved=0,
        )

    target_file = eidos_file or DEFAULT_EIDOS_FILE
    if _is_duplicate_entry(entry, target_file):
        return EidosIntakeResult(
            ok=True,
            reason="duplicate_skipped",
            entry=entry,
            structured=structured,
            advisory_quality=advisory_quality,
            advisory_readiness=readiness,
            duplicate=True,
            spine_saved=spine_saved,
        )

    try:
        with target_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:
        return EidosIntakeResult(
            ok=False,
            reason=f"append_failed:{exc}",
            entry=entry,
            structured=structured,
            advisory_quality=advisory_quality,
            advisory_readiness=readiness,
            spine_saved=spine_saved,
        )

    return EidosIntakeResult(
        ok=True,
        reason=build_reason,
        entry=entry,
        structured=structured,
        advisory_quality=advisory_quality,
        advisory_readiness=readiness,
        duplicate=False,
        spine_saved=spine_saved,
    )
