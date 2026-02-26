"""Prediction -> outcome validation loop (semantic + lightweight).

Uses:
- Exposures (what was surfaced)
- Outcomes (user approvals/corrections, tool failures)
- Embeddings (optional) for semantic matching
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lib.queue import read_events, count_events, EventType, _tail_lines
from lib.cognitive_learner import get_cognitive_learner, _boost_confidence
from lib.aha_tracker import get_aha_tracker, SurpriseType
from lib.diagnostics import log_debug
from lib.exposure_tracker import read_recent_exposures
from lib.embeddings import embed_texts
from lib.outcome_log import OUTCOMES_FILE, append_outcomes, make_outcome_id, auto_link_outcomes, get_outcome_links
from lib.project_profile import list_profiles
from lib.primitive_filter import is_primitive_text


PREDICTIONS_FILE = Path.home() / ".spark" / "predictions.jsonl"
STATE_FILE = Path.home() / ".spark" / "prediction_state.json"

DEFAULT_SOURCE_BUDGETS = {
    "chip_merge": 80,
    "spark_inject": 60,
    "sync_context": 40,
}
DEFAULT_SOURCE_BUDGET = 30
DEFAULT_TOTAL_PREDICTION_BUDGET = 50


POSITIVE_OUTCOME = {
    "looks good", "ship it", "ship", "perfect", "great", "awesome", "thanks",
    "approved", "good", "works", "nice", "love it", "exactly",
}
NEGATIVE_OUTCOME = {
    "no", "wrong", "redo", "change", "fix", "not", "doesnt", "doesn't", "broken",
    "still", "bad", "failed", "issue", "bug",
}
SUCCESS_OUTCOME_TOOLS = {
    "Edit",
    "Write",
    "Bash",
    "Task",
    "NotebookEdit",
    "MultiEdit",
}
MATCH_WINDOW_BY_TYPE_S = {
    "failure_pattern": 12 * 3600,
    "workflow": 2 * 24 * 3600,
    "preference": 3 * 24 * 3600,
    "principle": 7 * 24 * 3600,
    "project_milestone": 30 * 24 * 3600,
    "project_done": 30 * 24 * 3600,
    "general": 24 * 3600,
}
TEST_NAMESPACE_PATTERN = re.compile(
    r"(^|[\\/_:\-\s])(test|tests|pytest|unittest|integration|ci|smoke)([\\/_:\-\s]|$)"
)


def _load_state() -> Dict:
    if not STATE_FILE.exists():
        return {"offset": 0, "matched_ids": []}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"offset": 0, "matched_ids": []}


def _save_state(state: Dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _hash_id(*parts: str) -> str:
    raw = "|".join(p or "" for p in parts).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def _normalize(text: str) -> str:
    return (text or "").lower().strip()


def _expected_polarity(insight_text: str) -> str:
    t = _normalize(insight_text)
    if any(w in t for w in ("struggle", "fails", "error", "timeout", "broken")):
        return "neg"
    return "pos"


def _prediction_type(category: str, insight_text: str) -> str:
    t = _normalize(insight_text)
    if any(w in t for w in ("struggle", "fails", "error", "timeout")):
        return "failure_pattern"
    if "sequence" in t or "pattern" in t:
        return "workflow"
    if category in ("communication", "user_understanding"):
        return "preference"
    if category in ("wisdom", "reasoning", "meta_learning"):
        return "principle"
    return "general"


def _looks_like_test_namespace(value: Optional[str]) -> bool:
    if not value:
        return False
    text = _normalize(str(value))
    if not text:
        return False
    if text in {"test", "tests", "pytest", "unittest", "integration", "ci", "smoke"}:
        return True
    if text.startswith("test-") or text.startswith("test_") or text.startswith("pytest"):
        return True
    return bool(TEST_NAMESPACE_PATTERN.search(text))


def _resolve_namespace(*values: Optional[str]) -> str:
    forced = str(os.environ.get("SPARK_NAMESPACE", "")).strip().lower()
    if forced in {"prod", "production"}:
        return "prod"
    if forced in {"test", "testing", "ci"}:
        return "test"
    for value in values:
        if _looks_like_test_namespace(value):
            return "test"
    return "prod"


def _row_namespace(row: Dict) -> str:
    explicit = row.get("namespace")
    if explicit:
        return "test" if str(explicit).strip().lower() == "test" else "prod"
    return _resolve_namespace(
        row.get("session_id"),
        row.get("source"),
        row.get("trace_id"),
        row.get("project_key"),
        row.get("tool"),
    )


def _load_prediction_budget_config() -> Tuple[int, int, Dict[str, int]]:
    total_budget = DEFAULT_TOTAL_PREDICTION_BUDGET
    default_source_budget = DEFAULT_SOURCE_BUDGET
    source_budgets = dict(DEFAULT_SOURCE_BUDGETS)

    try:
        from lib.config_authority import resolve_section, env_int, env_str
        cfg = resolve_section(
            "prediction",
            env_overrides={
                "total_budget": env_int("SPARK_PREDICTION_TOTAL_BUDGET"),
                "default_source_budget": env_int("SPARK_PREDICTION_DEFAULT_SOURCE_BUDGET"),
                "source_budgets": env_str("SPARK_PREDICTION_SOURCE_BUDGETS"),
            },
        ).data
        total_budget = int(cfg.get("total_budget", total_budget))
        default_source_budget = int(cfg.get("default_source_budget", default_source_budget))
        raw_csv = str(cfg.get("source_budgets", "") or "").strip()
    except Exception:
        raw_csv = os.environ.get("SPARK_PREDICTION_SOURCE_BUDGETS", "").strip()

    if not raw_csv:
        return total_budget, default_source_budget, source_budgets

    for part in raw_csv.split(","):
        token = part.strip()
        if not token or "=" not in token:
            continue
        source, raw_value = token.split("=", 1)
        source = source.strip()
        if not source:
            continue
        try:
            value = int(raw_value.strip())
            if value <= 0:
                continue
            source_budgets[source] = min(value, 2000)
        except Exception:
            continue
    return total_budget, default_source_budget, source_budgets


def _load_jsonl(path: Path, limit: int = 300) -> List[Dict]:
    """Load last N lines from JSONL file using memory-efficient tail read."""
    if not path.exists():
        return []

    # Use tail read to avoid loading entire file into memory
    lines = _tail_lines(path, limit)
    if not lines:
        return []

    out: List[Dict] = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _append_jsonl(path: Path, rows: List[Dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_predictions(max_age_s: float = 6 * 3600) -> int:
    """Generate predictions for recently surfaced insights."""
    total_budget, default_source_budget, source_budgets = _load_prediction_budget_config()
    scan_limit = max(200, min(2000, total_budget * 4))
    exposures = read_recent_exposures(limit=scan_limit, max_age_s=max_age_s)
    if not exposures:
        return 0

    existing = {p.get("prediction_id") for p in _load_jsonl(PREDICTIONS_FILE, limit=500)}
    cog = get_cognitive_learner()
    preds: List[Dict] = []
    source_counts: Dict[str, int] = {}
    now = time.time()

    for ex in exposures:
        if len(preds) >= total_budget:
            break
        key = ex.get("insight_key")
        text = ex.get("text") or ""
        category = ex.get("category") or ""
        source = ex.get("source") or "exposure"
        session_id = ex.get("session_id")
        if not text:
            continue
        if is_primitive_text(text):
            continue
        pred_id = _hash_id(key or "", text, source)
        if pred_id in existing:
            continue
        # In-cycle dedup: skip if >80% token overlap with already-batched prediction
        text_norm = _normalize(text)
        is_dupe = False
        for prev in preds:
            if _token_overlap(text_norm, _normalize(prev.get("text", ""))) > 0.80:
                is_dupe = True
                break
        if is_dupe:
            continue
        source_cap = int(source_budgets.get(source, default_source_budget))
        if source_counts.get(source, 0) >= source_cap:
            continue

        pred = {
            "prediction_id": pred_id,
            "insight_key": key,
            "category": category,
            "type": _prediction_type(category, text),
            "text": text,
            "expected_polarity": _expected_polarity(text),
            "created_at": now,
            "expires_at": now + max_age_s,
            "source": source,
            "session_id": session_id,
            "namespace": _resolve_namespace(session_id, source, ex.get("trace_id")),
        }
        trace_id = ex.get("trace_id")
        if trace_id:
            pred["trace_id"] = trace_id
        preds.append(pred)
        source_counts[source] = source_counts.get(source, 0) + 1

    _append_jsonl(PREDICTIONS_FILE, preds)
    return len(preds)


def build_project_predictions(max_age_s: float = 14 * 24 * 3600) -> int:
    """Generate predictions from project profiles (done + milestones)."""
    profiles = list_profiles()
    if not profiles:
        return 0
    existing = {p.get("prediction_id") for p in _load_jsonl(PREDICTIONS_FILE, limit=800)}
    now = time.time()
    preds: List[Dict] = []

    for profile in profiles:
        project_key = profile.get("project_key") or "project"
        domain = profile.get("domain") or "general"
        done_text = profile.get("done") or ""
        if done_text:
            pred_id = _hash_id("project_done", project_key, done_text[:120])
            if pred_id not in existing:
                preds.append({
                    "prediction_id": pred_id,
                    "insight_key": f"project:done:{project_key}",
                    "category": "project_done",
                    "type": "project_done",
                    "text": f"Project done: {done_text}",
                    "expected_polarity": "pos",
                    "created_at": now,
                    "expires_at": now + max_age_s,
                    "source": "project_profile",
                    "project_key": project_key,
                    "domain": domain,
                    "entity_id": _hash_id(project_key, "done"),
                    "namespace": _resolve_namespace(project_key, "project_profile"),
                })

        for m in profile.get("milestones") or []:
            text = (m.get("text") or "").strip()
            if not text:
                continue
            status = (m.get("meta") or {}).get("status") or ""
            if str(status).lower() in ("done", "complete", "completed"):
                continue
            entity_id = m.get("entry_id") or _hash_id(project_key, "milestone", text[:120])
            pred_id = _hash_id("project_milestone", project_key, entity_id)
            if pred_id in existing:
                continue
            preds.append({
                "prediction_id": pred_id,
                "insight_key": f"project:milestone:{project_key}:{entity_id}",
                "category": "project_milestone",
                "type": "project_milestone",
                "text": f"Milestone pending: {text}",
                "expected_polarity": "pos",
                "created_at": now,
                "expires_at": now + max_age_s,
                "source": "project_profile",
                "project_key": project_key,
                "domain": domain,
                "entity_id": entity_id,
                "namespace": _resolve_namespace(project_key, "project_profile"),
            })

    _append_jsonl(PREDICTIONS_FILE, preds)
    return len(preds)


def _outcome_polarity(text: str) -> Optional[str]:
    t = _normalize(text)
    if any(w in t for w in POSITIVE_OUTCOME):
        return "pos"
    if any(w in t for w in NEGATIVE_OUTCOME):
        return "neg"
    return None


def collect_outcomes(limit: int = 200) -> Dict[str, int]:
    """Collect outcomes from recent events."""
    state = _load_state()
    offset = int(state.get("offset", 0))

    total = count_events()
    if total < offset:
        offset = max(0, total - limit)

    events = read_events(limit=limit, offset=offset)
    if not events:
        return {"processed": 0, "outcomes": 0}

    rows: List[Dict] = []
    processed = 0
    for ev in events:
        processed += 1
        trace_id = (ev.data or {}).get("trace_id")
        namespace = _resolve_namespace(ev.session_id, ev.tool_name, trace_id, (ev.data or {}).get("cwd"))
        if ev.event_type == EventType.USER_PROMPT:
            payload = (ev.data or {}).get("payload") or {}
            role = payload.get("role") or "user"
            if role != "user":
                continue
            text = str(payload.get("text") or "").strip()
            if not text:
                continue
            polarity = _outcome_polarity(text)
            if not polarity:
                continue
            row = {
                "outcome_id": make_outcome_id(str(ev.timestamp), text[:100]),
                "event_type": "user_prompt",
                "tool": None,
                "text": text,
                "polarity": polarity,
                "created_at": ev.timestamp,
                "session_id": ev.session_id,
                "namespace": namespace,
            }
            if trace_id:
                row["trace_id"] = trace_id
            rows.append(row)
        elif ev.event_type in (EventType.POST_TOOL_FAILURE,):
            tool = ev.tool_name or ""
            error = ev.error or ""
            if not error:
                payload = (ev.data or {}).get("payload") or {}
                error = payload.get("error") or payload.get("stderr") or payload.get("message") or ""
            if not error:
                continue
            text = f"{tool} error: {str(error)[:200]}"
            row = {
                "outcome_id": make_outcome_id(str(ev.timestamp), tool, "error"),
                "event_type": "tool_error",
                "tool": tool,
                "text": text,
                "polarity": "neg",
                "created_at": ev.timestamp,
                "session_id": ev.session_id,
                "namespace": namespace,
            }
            if trace_id:
                row["trace_id"] = trace_id
            rows.append(row)
        elif ev.event_type == EventType.POST_TOOL:
            tool = ev.tool_name or ""
            if tool not in SUCCESS_OUTCOME_TOOLS:
                continue
            detail = ""
            tool_input = ev.tool_input or {}
            if isinstance(tool_input, dict):
                for key in ("command", "path", "file_path", "query"):
                    value = tool_input.get(key)
                    if value:
                        detail = str(value).strip()
                        break
            if not detail:
                payload = (ev.data or {}).get("payload") or {}
                if isinstance(payload, dict):
                    detail = str(payload.get("summary") or payload.get("text") or "").strip()
            text = f"{tool} success"
            if detail:
                text = f"{tool} success: {detail[:180]}"
            row = {
                "outcome_id": make_outcome_id(str(ev.timestamp), tool, "success", text[:120]),
                "event_type": "tool_success",
                "tool": tool,
                "text": text,
                "polarity": "pos",
                "created_at": ev.timestamp,
                "session_id": ev.session_id,
                "namespace": namespace,
            }
            if trace_id:
                row["trace_id"] = trace_id
            rows.append(row)

    append_outcomes(rows)
    state["offset"] = offset + len(events)
    _save_state(state)
    return {"processed": processed, "outcomes": len(rows)}


def _load_auto_link_config() -> Tuple[bool, float, int, float]:
    enabled = True
    interval_s = 60.0
    limit = 200
    min_similarity = 0.20

    try:
        from lib.config_authority import resolve_section, env_bool, env_int, env_float
        cfg = resolve_section(
            "prediction",
            env_overrides={
                "auto_link_enabled": env_bool("SPARK_PREDICTION_AUTO_LINK"),
                "auto_link_interval_s": env_float("SPARK_PREDICTION_AUTO_LINK_INTERVAL_S"),
                "auto_link_limit": env_int("SPARK_PREDICTION_AUTO_LINK_LIMIT"),
                "auto_link_min_sim": env_float("SPARK_PREDICTION_AUTO_LINK_MIN_SIM"),
            },
        ).data
        enabled = bool(cfg.get("auto_link_enabled", True))
        interval_s = float(cfg.get("auto_link_interval_s", 60.0))
        limit = int(cfg.get("auto_link_limit", 200))
        min_similarity = float(cfg.get("auto_link_min_sim", 0.20))
    except Exception:
        pass  # keep defaults

    return enabled, interval_s, limit, min_similarity


def _token_overlap(a: str, b: str) -> float:
    a_t = set(_normalize(a).split())
    b_t = set(_normalize(b).split())
    if not a_t or not b_t:
        return 0.0
    return len(a_t & b_t) / max(1, len(a_t | b_t))


def _cleanup_expired_predictions(max_age_s: float = 7 * 24 * 3600) -> int:
    """Remove predictions older than max_age_s or past their expires_at to prevent unbounded growth."""
    if not PREDICTIONS_FILE.exists():
        return 0
    now = time.time()
    kept: List[Dict] = []
    removed = 0
    for pred in _load_jsonl(PREDICTIONS_FILE, limit=25000):
        expires = float(pred.get("expires_at") or 0.0)
        created = float(pred.get("created_at") or 0.0)
        if expires and now > expires:
            removed += 1
            continue
        if created and (now - created) > max_age_s:
            removed += 1
            continue
        kept.append(pred)
    if removed > 0:
        tmp = PREDICTIONS_FILE.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for row in kept:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp.replace(PREDICTIONS_FILE)
        log_debug("prediction", f"Cleaned {removed} expired predictions, kept {len(kept)}", None)
    return removed


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / ((na ** 0.5) * (nb ** 0.5))))


def _match_window_s(pred_type: str, default_window_s: float) -> float:
    specific = float(MATCH_WINDOW_BY_TYPE_S.get(pred_type or "general", 0.0))
    return max(float(default_window_s or 0.0), specific)


def match_predictions(
    *,
    max_age_s: float = 6 * 3600,
    sim_threshold: float = 0.72,
) -> Dict[str, int]:
    """Match predictions to outcomes and update insight reliability."""
    preds = _load_jsonl(PREDICTIONS_FILE, limit=1200)
    outcomes = _load_jsonl(OUTCOMES_FILE, limit=1200)
    if not preds or not outcomes:
        return {"matched": 0, "validated": 0, "contradicted": 0, "surprises": 0}

    state = _load_state()
    matched_ids = set(state.get("matched_ids") or [])
    match_history = list(state.get("match_history") or [])
    now = time.time()

    max_window = max(float(max_age_s or 0.0), max(MATCH_WINDOW_BY_TYPE_S.values()))
    filtered_preds: List[Dict] = []
    for pred in preds:
        if (now - float(pred.get("created_at") or 0.0)) > max_window:
            continue
        pred_ns = _row_namespace(pred)
        pred["namespace"] = pred_ns
        if pred_ns == "test":
            continue
        filtered_preds.append(pred)
    preds = filtered_preds

    filtered_outcomes: List[Dict] = []
    for outcome in outcomes:
        if (now - float(outcome.get("created_at") or 0.0)) > max_window:
            continue
        out_ns = _row_namespace(outcome)
        outcome["namespace"] = out_ns
        if out_ns == "test":
            continue
        filtered_outcomes.append(outcome)
    outcomes = filtered_outcomes

    pred_texts = [p.get("text") or "" for p in preds]
    outcome_texts = [o.get("text") or "" for o in outcomes]
    pred_vecs = embed_texts(pred_texts) or []
    out_vecs = embed_texts(outcome_texts) or []

    outcome_link_map: Dict[str, set] = {}
    try:
        for link in get_outcome_links(limit=5000):
            outcome_id = link.get("outcome_id")
            insight_key = link.get("insight_key")
            if not outcome_id or not insight_key:
                continue
            if outcome_id not in outcome_link_map:
                outcome_link_map[outcome_id] = set()
            outcome_link_map[outcome_id].add(insight_key)
    except Exception:
        outcome_link_map = {}

    def similarity(i: int, j: int) -> float:
        if pred_vecs and out_vecs:
            return _cosine(pred_vecs[i], out_vecs[j])
        return _token_overlap(pred_texts[i], outcome_texts[j])

    cog = get_cognitive_learner()
    stats = {"matched": 0, "validated": 0, "contradicted": 0, "surprises": 0}

    for i, pred in enumerate(preds):
        pred_id = pred.get("prediction_id")
        if not pred_id or pred_id in matched_ids:
            continue
        expires = float(pred.get("expires_at") or 0.0)
        if expires and now > expires:
            continue
        pred_pol = pred.get("expected_polarity")
        pred_type = pred.get("type") or "general"
        pred_created = float(pred.get("created_at") or 0.0)
        window_s = _match_window_s(pred_type, max_age_s)
        if pred_created and (now - pred_created) > window_s:
            continue
        window_end = (pred_created + window_s) if pred_created else now
        if expires:
            window_end = min(window_end, expires)
        insight_key = pred.get("insight_key")
        insight = cog.insights.get(insight_key) if insight_key else None

        best = None
        best_sim = 0.0
        hard_hits: Dict[str, Tuple[int, float, Dict]] = {}

        def _add_hard_hit(outcome: Dict, rank: int) -> None:
            oid = str(outcome.get("outcome_id") or f"anon:{id(outcome)}")
            ts = float(outcome.get("created_at") or 0.0)
            current = hard_hits.get(oid)
            if not current or rank > current[0] or (rank == current[0] and ts > current[1]):
                hard_hits[oid] = (rank, ts, outcome)

        # Hard link by entity_id (project milestones/done)
        entity_id = pred.get("entity_id")
        if entity_id:
            for outcome in outcomes:
                if outcome.get("entity_id") == entity_id:
                    _add_hard_hit(outcome, rank=4)
        if insight_key:
            for outcome in outcomes:
                links = outcome.get("linked_insights") or []
                if isinstance(links, list) and insight_key in links:
                    _add_hard_hit(outcome, rank=3)
                oid = outcome.get("outcome_id")
                linked_insights = outcome_link_map.get(str(oid)) if oid else None
                if linked_insights and insight_key in linked_insights:
                    _add_hard_hit(outcome, rank=3)
        pred_trace = pred.get("trace_id")
        if pred_trace:
            for outcome in outcomes:
                if outcome.get("trace_id") == pred_trace:
                    _add_hard_hit(outcome, rank=2)

        if hard_hits:
            ranked_hits = sorted(hard_hits.values(), key=lambda item: (item[0], item[1]), reverse=True)
            best = ranked_hits[0][2]
            best_sim = 1.0

        pred_sid = pred.get("session_id")
        cand_indices = list(range(len(outcomes)))
        if pred_sid:
            same = [idx for idx, o in enumerate(outcomes) if o.get("session_id") == pred_sid]
            if same:
                cand_indices = same

        for j in cand_indices:
            outcome = outcomes[j]
            if best is not None:
                break
            outcome_created = float(outcome.get("created_at") or 0.0)
            if pred_created:
                if outcome_created and outcome_created < pred_created:
                    continue
                if outcome_created and outcome_created > window_end:
                    continue
            sim = similarity(i, j)
            if sim > best_sim:
                best_sim = sim
                best = outcome

        if not best or best_sim < sim_threshold:
            continue

        stats["matched"] += 1
        matched_ids.add(pred_id)

        out_pol = best.get("polarity")
        if out_pol not in ("pos", "neg"):
            continue
        if pred_type == "failure_pattern":
            validated = True
        else:
            validated = (pred_pol == out_pol)

        if validated:
            stats["validated"] += 1
        else:
            stats["contradicted"] += 1

        match_history.append(
            {
                "prediction_id": pred_id,
                "prediction_created_at": pred_created,
                "matched_at": now,
                "namespace": pred.get("namespace") or "prod",
                "validated": bool(validated),
            }
        )

        if not insight:
            continue

        if validated:
            cog._touch_validation(insight, validated_delta=1)
            insight.confidence = _boost_confidence(insight.confidence, 1)
            insight.evidence.append(best.get("text", "")[:200])
            insight.evidence = insight.evidence[-10:]
        else:
            cog._touch_validation(insight, contradicted_delta=1)
            insight.counter_examples.append(best.get("text", "")[:200])
            insight.counter_examples = insight.counter_examples[-10:]

            if insight.reliability >= 0.7 and insight.times_validated >= 2:
                try:
                    tracker = get_aha_tracker()
                    tracker.capture_surprise(
                        surprise_type=SurpriseType.UNEXPECTED_FAILURE,
                        predicted=f"Expected: {insight.insight}",
                        actual=f"Outcome: {best.get('text', '')[:120]}",
                        confidence_gap=min(1.0, insight.reliability),
                        context={"tool": "prediction", "insight": insight.insight},
                        lesson=f"Prediction contradicted: {insight.insight[:60]}",
                    )
                    stats["surprises"] += 1
                except Exception as e:
                    log_debug("prediction", "surprise capture failed", e)

    if stats["validated"] or stats["contradicted"]:
        cog._save_insights()

    state["matched_ids"] = list(matched_ids)[-500:]
    state["match_history"] = match_history[-5000:]
    state["last_run_ts"] = time.time()
    state["last_stats"] = stats
    _save_state(state)
    return stats


def process_prediction_cycle(limit: int = 200) -> Dict[str, int]:
    """Full prediction cycle: build -> outcomes -> match."""
    stats = {
        "predictions": 0,
        "outcomes": 0,
        "auto_link_processed": 0,
        "auto_link_linked": 0,
        "auto_link_skipped": 0,
        "matched": 0,
        "validated": 0,
        "contradicted": 0,
        "surprises": 0,
    }
    try:
        stats["predictions"] = build_predictions()
    except Exception as e:
        log_debug("prediction", "build_predictions failed", e)
    try:
        stats["predictions"] += build_project_predictions()
    except Exception as e:
        log_debug("prediction", "build_project_predictions failed", e)
    try:
        outcome_stats = collect_outcomes(limit=limit)
        stats["outcomes"] = outcome_stats.get("outcomes", 0)
    except Exception as e:
        log_debug("prediction", "collect_outcomes failed", e)
    try:
        enabled, interval_s, auto_link_limit, min_similarity = _load_auto_link_config()
        if enabled:
            state = _load_state()
            last_ts = float(state.get("last_auto_link_ts") or 0.0)
            now = time.time()
            if (now - last_ts) >= interval_s:
                auto_stats = auto_link_outcomes(
                    min_similarity=min_similarity,
                    limit=min(limit, auto_link_limit),
                    dry_run=False,
                )
                stats["auto_link_processed"] = int(auto_stats.get("processed", 0) or 0)
                stats["auto_link_linked"] = int(auto_stats.get("linked", 0) or 0)
                stats["auto_link_skipped"] = int(auto_stats.get("skipped", 0) or 0)
                state["last_auto_link_ts"] = now
                state["last_auto_link_stats"] = {
                    "processed": stats["auto_link_processed"],
                    "linked": stats["auto_link_linked"],
                    "skipped": stats["auto_link_skipped"],
                }
                _save_state(state)
    except Exception as e:
        log_debug("prediction", "auto_link_outcomes failed", e)
    try:
        match_stats = match_predictions()
        stats.update({k: match_stats.get(k, 0) for k in ("matched", "validated", "contradicted", "surprises")})
    except Exception as e:
        log_debug("prediction", "match_predictions failed", e)
    try:
        removed = _cleanup_expired_predictions()
        if removed:
            stats["expired_cleaned"] = removed
    except Exception as e:
        log_debug("prediction", "cleanup_expired failed", e)
    return stats


def _compute_loop_kpis(window_s: float = 7 * 24 * 3600) -> Dict[str, float]:
    now = time.time()
    since = now - float(window_s or 0.0)

    preds = _load_jsonl(PREDICTIONS_FILE, limit=5000)
    outcomes = _load_jsonl(OUTCOMES_FILE, limit=5000)
    preds = [
        p
        for p in preds
        if float(p.get("created_at") or 0.0) >= since and _row_namespace(p) == "prod"
    ]
    outcomes = [
        o
        for o in outcomes
        if float(o.get("created_at") or 0.0) >= since and _row_namespace(o) == "prod"
    ]

    pred_count = len(preds)
    outcome_count = len(outcomes)
    ratio = (pred_count / outcome_count) if outcome_count > 0 else float(pred_count)

    linked_ids = set()
    try:
        for link in get_outcome_links(limit=5000):
            created_at = float(link.get("created_at") or 0.0)
            if created_at and created_at < since:
                continue
            oid = link.get("outcome_id")
            if oid:
                linked_ids.add(str(oid))
    except Exception:
        linked_ids = set()

    unlinked = 0
    for outcome in outcomes:
        links = outcome.get("linked_insights") or []
        if isinstance(links, list) and len(links) > 0:
            continue
        oid = outcome.get("outcome_id")
        if oid and str(oid) in linked_ids:
            continue
        unlinked += 1

    state = _load_state()
    history = list(state.get("match_history") or [])
    history = [
        h
        for h in history
        if float(h.get("matched_at") or 0.0) >= since
        and str(h.get("namespace") or "prod") == "prod"
    ]
    matched_count = len(history)
    validated_count = sum(1 for h in history if bool(h.get("validated")))
    coverage = (matched_count / pred_count) if pred_count > 0 else 0.0
    validated_per_100 = (validated_count * 100.0 / pred_count) if pred_count > 0 else 0.0

    return {
        "window_days": round(window_s / (24 * 3600), 2),
        "predictions": pred_count,
        "outcomes": outcome_count,
        "prediction_to_outcome_ratio": round(ratio, 3),
        "unlinked_outcomes": int(unlinked),
        "coverage": round(coverage, 3),
        "validated_per_100_predictions": round(validated_per_100, 2),
        "matched_predictions": int(matched_count),
        "validated_predictions": int(validated_count),
    }


def get_prediction_state() -> Dict:
    state = _load_state()
    kpis = _compute_loop_kpis()
    return {
        "last_run_ts": state.get("last_run_ts"),
        "last_stats": state.get("last_stats") or {},
        "offset": state.get("offset", 0),
        "matched_count": len(state.get("matched_ids") or []),
        "kpis": kpis,
    }
