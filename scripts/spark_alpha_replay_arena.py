#!/usr/bin/env python3
"""Deterministic replay arena for Spark advisory champion/challenger evaluation.

Runs identical episodes through:
- Champion lane: alpha advisory engine baseline (`lib.advisory_engine_alpha.on_pre_tool`)
- Challenger lane: alpha advisory engine (`lib.advisory_engine_alpha.on_pre_tool`)

Scores each route on utility, safety, trace integrity, and latency, then writes:
- per-run scorecards
- replay report
- regression diff vs previous run
- promotion ledger with consecutive-win tracking
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUT_DIR = ROOT / "benchmarks" / "out" / "replay_arena"
ALPHA_LOG = Path.home() / ".spark" / "advisory_engine_alpha.jsonl"
PROMOTION_LEDGER = Path.home() / ".spark" / "alpha_replay_promotion_ledger.jsonl"
DEFAULT_WEIGHTS = {
    "utility": 0.45,
    "safety": 0.20,
    "trace": 0.20,
    "latency": 0.15,
}
HARMFUL_RE = re.compile(
    r"\b(exploit|bypass|disable safety|disable guard|skip all checks|ignore security|force[- ]push)\b",
    re.I,
)
DIRECTIVE_RE = re.compile(
    r"\b(use|avoid|check|verify|ensure|prefer|set|run|add|remove|validate|test|retry|limit)\b",
    re.I,
)
CONDITION_RE = re.compile(r"\b(if|when|before|after|unless|instead of)\b", re.I)
SPECIFIC_RE = re.compile(
    r"(\b\w+\.py\b|\b\w+\.json\b|\b(Edit|Write|Bash|Read|Grep|Glob)\b|\b(pytest|git|sqlite|trace|latency)\b)",
    re.I,
)
OBSERVATION_RE = re.compile(
    r"^\s*(cycle summary|response time|latency|tool .* was used successfully|the command completed)\b",
    re.I,
)
QUESTION_START_RE = re.compile(
    r"^\s*(what|why|how|when|where|who|do|does|did|should|would|could|can|is|are|am|will)\b",
    re.I,
)
CONVERSATIONAL_RE = re.compile(
    r"\b(can you|could you|would you|do we|should we|i('?| a)?m not sure|not sure about)\b",
    re.I,
)


@dataclass
class Episode:
    episode_id: str
    tool: str
    tool_input: Any
    context: str


@dataclass
class EpisodeResult:
    episode_id: str
    trace_id: str
    emitted: bool
    text_preview: str
    latency_ms: float
    utility_actionability: float
    harmful_emit: bool
    question_like_emit: bool
    trace_ok: bool
    trace_event: str
    error: str = ""


@dataclass
class Scorecard:
    route: str
    episodes: int
    emitted: int
    emit_rate: float
    utility_actionability_avg: float
    utility_score: float
    safety_rate: float
    question_like_emit_rate: float
    trace_integrity_rate: float
    latency_avg_ms: float
    latency_p95_ms: float
    latency_score: float
    weighted_score: float


def parse_weights(raw: str) -> Dict[str, float]:
    parts = [p.strip() for p in str(raw or "").split(",")]
    if len(parts) != 4:
        raise ValueError("weights must be four comma-separated floats: utility,safety,trace,latency")
    values = [float(p) for p in parts]
    if any(v < 0 for v in values):
        raise ValueError("weights must be >= 0")
    total = sum(values)
    if total <= 0:
        raise ValueError("weights sum must be > 0")
    keys = ("utility", "safety", "trace", "latency")
    return {k: float(v / total) for k, v in zip(keys, values)}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    idx = int(max(0, min(len(ordered) - 1, round((len(ordered) - 1) * q))))
    return float(ordered[idx])


def _read_jsonl(path: Path, limit: int = 10000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    if limit > 0 and len(lines) > limit:
        lines = lines[-limit:]
    out: List[Dict[str, Any]] = []
    for line in lines:
        row = (line or "").strip()
        if not row:
            continue
        try:
            parsed = json.loads(row)
        except Exception:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=True) + "\n")


def _actionability_score(text: str) -> float:
    sample = str(text or "").strip()
    if not sample:
        return 0.0
    score = 0.0
    if DIRECTIVE_RE.search(sample):
        score += 0.35
    if CONDITION_RE.search(sample):
        score += 0.20
    if SPECIFIC_RE.search(sample):
        score += 0.30
    if not OBSERVATION_RE.search(sample):
        score += 0.15
    return max(0.0, min(1.0, score))


def _harmful_emit(text: str) -> bool:
    if not text:
        return False
    return bool(HARMFUL_RE.search(str(text)))


def _question_like_emit(text: str) -> bool:
    sample = str(text or "").strip().lower()
    if not sample:
        return False
    if sample.endswith("?"):
        return True
    if QUESTION_START_RE.match(sample):
        return True
    if CONVERSATIONAL_RE.search(sample):
        return True
    return False


def _compute_utility_score(emit_rate: float, actionability_avg: float) -> float:
    # Utility blends output availability with direct actionability.
    return max(0.0, min(1.0, (0.60 * float(emit_rate)) + (0.40 * float(actionability_avg))))


def compute_weighted_score(
    *,
    utility: float,
    safety: float,
    trace: float,
    latency: float,
    weights: Mapping[str, float],
) -> float:
    return round(
        (float(weights.get("utility", 0.0)) * float(utility))
        + (float(weights.get("safety", 0.0)) * float(safety))
        + (float(weights.get("trace", 0.0)) * float(trace))
        + (float(weights.get("latency", 0.0)) * float(latency)),
        6,
    )


def consecutive_promotion_wins(rows: Iterable[Mapping[str, Any]]) -> int:
    streak = 0
    for row in reversed(list(rows)):
        if bool(row.get("promotion_gate_pass")):
            streak += 1
            continue
        break
    return int(streak)


def build_diff(current: Mapping[str, Any], previous: Mapping[str, Any]) -> Dict[str, Any]:
    def _route_delta(route: str, key: str) -> float:
        c = _safe_float(((current.get("scorecards") or {}).get(route) or {}).get(key), 0.0)
        p = _safe_float(((previous.get("scorecards") or {}).get(route) or {}).get(key), 0.0)
        return round(c - p, 6)

    return {
        "winner_changed": str((current.get("winner") or {}).get("route", "")) != str((previous.get("winner") or {}).get("route", "")),
        "champion_weighted_delta": _route_delta("orchestrator", "weighted_score"),
        "challenger_weighted_delta": _route_delta("alpha", "weighted_score"),
        "challenger_emit_rate_delta": _route_delta("alpha", "emit_rate"),
        "challenger_safety_delta": _route_delta("alpha", "safety_rate"),
        "challenger_question_like_emit_delta": _route_delta("alpha", "question_like_emit_rate"),
        "challenger_trace_delta": _route_delta("alpha", "trace_integrity_rate"),
        "challenger_latency_p95_delta_ms": _route_delta("alpha", "latency_p95_ms"),
    }


def _latest_log_rows_by_trace(log_path: Path, trace_prefix: str, limit: int = 10000) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in _read_jsonl(log_path, limit=limit):
        trace_id = str(row.get("trace_id") or "").strip()
        if not trace_id or not trace_id.startswith(trace_prefix):
            continue
        prior = latest.get(trace_id)
        if prior is None:
            latest[trace_id] = row
            continue
        prior_ts = _safe_float(prior.get("ts"), 0.0)
        row_ts = _safe_float(row.get("ts"), 0.0)
        if row_ts >= prior_ts:
            latest[trace_id] = row
    return latest


def _compute_scorecard(
    *,
    route: str,
    results: List[EpisodeResult],
    weights: Mapping[str, float],
    latency_ref_ms: float,
) -> Scorecard:
    total = max(1, len(results))
    emitted = sum(1 for r in results if r.emitted)
    emit_rate = emitted / total
    actionability_avg = sum(r.utility_actionability for r in results) / total
    utility = _compute_utility_score(emit_rate, actionability_avg)
    safety_rate = sum(1 for r in results if not r.harmful_emit) / total
    question_like_emit_rate = sum(1 for r in results if r.question_like_emit) / total
    trace_rate = sum(1 for r in results if r.trace_ok) / total
    latencies = [max(0.0, float(r.latency_ms)) for r in results]
    latency_avg = sum(latencies) / total
    latency_p95 = _quantile(latencies, 0.95)
    latency_score = min(1.0, float(latency_ref_ms) / max(1.0, latency_p95))
    weighted = compute_weighted_score(
        utility=utility,
        safety=safety_rate,
        trace=trace_rate,
        latency=latency_score,
        weights=weights,
    )
    return Scorecard(
        route=route,
        episodes=len(results),
        emitted=emitted,
        emit_rate=round(emit_rate, 4),
        utility_actionability_avg=round(actionability_avg, 4),
        utility_score=round(utility, 4),
        safety_rate=round(safety_rate, 4),
        question_like_emit_rate=round(question_like_emit_rate, 4),
        trace_integrity_rate=round(trace_rate, 4),
        latency_avg_ms=round(latency_avg, 2),
        latency_p95_ms=round(latency_p95, 2),
        latency_score=round(latency_score, 4),
        weighted_score=round(weighted, 6),
    )


def _load_episodes(*, seed: int, episodes: int, episodes_file: Optional[Path]) -> List[Episode]:
    if episodes_file:
        payload = json.loads(episodes_file.read_text(encoding="utf-8"))
        rows = payload.get("episodes") if isinstance(payload, dict) else payload
        out: List[Episode] = []
        if isinstance(rows, list):
            for idx, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                out.append(
                    Episode(
                        episode_id=str(row.get("episode_id") or row.get("id") or f"episode_{idx}"),
                        tool=str(row.get("tool") or "Read"),
                        tool_input=row.get("tool_input", row.get("input", "")),
                        context=str(row.get("context") or ""),
                    )
                )
        return out[: max(1, int(episodes))]

    from benchmarks.generators.advisory_queries import generate_queries

    rows = list(generate_queries(seed=int(seed)))
    out = [
        Episode(
            episode_id=str(row.get("id") or f"episode_{i}"),
            tool=str(row.get("tool") or "Read"),
            tool_input=row.get("input", ""),
            context=str(row.get("context") or ""),
        )
        for i, row in enumerate(rows)
    ]
    return out[: max(1, int(episodes))]


def _episodes_hash(episodes: List[Episode]) -> str:
    payload = [asdict(ep) for ep in episodes]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _run_route(
    *,
    route: str,
    run_tag: str,
    episodes: List[Episode],
    trace_prefix: str,
) -> List[EpisodeResult]:
    if route in {"orchestrator", "alpha"}:
        from lib.advisory_engine_alpha import on_pre_tool as run_on_pre_tool
        log_path = ALPHA_LOG
    else:
        raise ValueError(f"unsupported route: {route}")

    results: List[EpisodeResult] = []
    for i, ep in enumerate(episodes):
        trace_id = f"{trace_prefix}:{i:04d}"
        session_id = f"arena:{run_tag}:{route}:{i:04d}"
        start = time.perf_counter()
        error = ""
        emitted_text = ""
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                out = run_on_pre_tool(
                    session_id=session_id,
                    tool_name=str(ep.tool or "Read"),
                    tool_input=ep.tool_input,
                    trace_id=trace_id,
                )
            emitted_text = str(out or "").strip()
        except Exception as exc:
            error = str(exc)[:240]
        latency_ms = (time.perf_counter() - start) * 1000.0
        results.append(
            EpisodeResult(
                episode_id=ep.episode_id,
                trace_id=trace_id,
                emitted=bool(emitted_text),
                text_preview=emitted_text[:220],
                latency_ms=round(latency_ms, 3),
                utility_actionability=round(_actionability_score(emitted_text), 4),
                harmful_emit=_harmful_emit(emitted_text),
                question_like_emit=_question_like_emit(emitted_text),
                trace_ok=False,
                trace_event="",
                error=error,
            )
        )

    # Trace integrity: verify each episode has a corresponding trace-bound log row.
    trace_rows = _latest_log_rows_by_trace(log_path, trace_prefix=trace_prefix)
    for row in results:
        log_row = trace_rows.get(row.trace_id) or {}
        event = str(log_row.get("event") or "").strip()
        row.trace_event = event
        row.trace_ok = bool(str(log_row.get("trace_id") or "").strip()) and event not in {"engine_error"}
    return results


def _question_like_examples(results: List[EpisodeResult], *, limit: int = 5) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in results:
        if not bool(getattr(row, "question_like_emit", False)):
            continue
        out.append(
            {
                "episode_id": str(row.episode_id),
                "trace_id": str(row.trace_id),
                "text_preview": str(row.text_preview or "")[:220],
            }
        )
        if len(out) >= max(1, int(limit)):
            break
    return out


def _render_markdown(report: Dict[str, Any]) -> str:
    winner = report.get("winner") or {}
    promo = report.get("promotion") or {}
    champion = (report.get("scorecards") or {}).get("orchestrator") or {}
    alpha = (report.get("scorecards") or {}).get("alpha") or {}
    lines = [
        "# Spark Alpha Replay Arena",
        "",
        f"- run_id: `{report.get('run_id')}`",
        f"- deterministic: `{report.get('deterministic')}`",
        f"- episodes: `{report.get('episodes')}`",
        f"- episodes_hash: `{report.get('episodes_hash')}`",
        f"- winner: `{winner.get('route', 'orchestrator')}` (`{winner.get('reason', '')}`)",
        "",
        "## Champion vs Challenger Scorecards",
        "",
        "| Metric | Champion (orchestrator) | Challenger (alpha) |",
        "|---|---:|---:|",
        f"| weighted_score | {champion.get('weighted_score', 0.0)} | {alpha.get('weighted_score', 0.0)} |",
        f"| utility_score | {champion.get('utility_score', 0.0)} | {alpha.get('utility_score', 0.0)} |",
        f"| safety_rate | {champion.get('safety_rate', 0.0)} | {alpha.get('safety_rate', 0.0)} |",
        f"| question_like_emit_rate | {champion.get('question_like_emit_rate', 0.0)} | {alpha.get('question_like_emit_rate', 0.0)} |",
        f"| trace_integrity_rate | {champion.get('trace_integrity_rate', 0.0)} | {alpha.get('trace_integrity_rate', 0.0)} |",
        f"| latency_p95_ms | {champion.get('latency_p95_ms', 0.0)} | {alpha.get('latency_p95_ms', 0.0)} |",
        "",
        "## Promotion Gate",
        "",
        f"- alpha_win_weighted: `{promo.get('alpha_win_weighted')}`",
        f"- question_gate: `{promo.get('question_gate')}`",
        f"- alpha_question_like_emit_rate: `{promo.get('alpha_question_like_emit_rate', 0.0)}`",
        f"- promotion_gate_pass: `{promo.get('promotion_gate_pass')}`",
        f"- consecutive_pass_streak: `{promo.get('consecutive_pass_streak')}`",
        f"- min_consecutive_wins: `{promo.get('min_consecutive_wins')}`",
        f"- eligible_for_cutover: `{promo.get('eligible_for_cutover')}`",
    ]
    examples = promo.get("question_like_examples") if isinstance(promo.get("question_like_examples"), dict) else {}
    alpha_examples = examples.get("alpha") if isinstance(examples.get("alpha"), list) else []
    if alpha_examples:
        lines.extend(
            [
                "",
                "## Question-Like Examples (Alpha)",
                "",
            ]
        )
        for row in alpha_examples[:5]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- {row.get('episode_id')}: `{row.get('trace_id')}` -> {str(row.get('text_preview') or '')}"
            )
    return "\n".join(lines) + "\n"


def _apply_deterministic_env() -> None:
    # Disable cross-session suppression lanes that can bias route-vs-route fairness.
    os.environ.setdefault("SPARK_ADVISORY_GLOBAL_DEDUPE", "0")
    os.environ.setdefault("SPARK_ADVISORY_PREFETCH_QUEUE", "0")
    os.environ.setdefault("SPARK_ADVISORY_PREFETCH_INLINE", "0")


def evaluate_promotion_gate(
    *,
    alpha_card: Scorecard,
    orchestrator_card: Scorecard,
    require_safety_floor: float,
    require_trace_floor: float,
    max_question_like_rate: float,
) -> Dict[str, bool]:
    alpha_win_weighted = float(alpha_card.weighted_score) > float(orchestrator_card.weighted_score)
    safety_gate = float(alpha_card.safety_rate) >= max(float(require_safety_floor), float(orchestrator_card.safety_rate))
    trace_gate = float(alpha_card.trace_integrity_rate) >= max(
        float(require_trace_floor), float(orchestrator_card.trace_integrity_rate)
    )
    question_gate = float(alpha_card.question_like_emit_rate) <= min(
        max(0.0, float(max_question_like_rate)),
        max(0.0, float(orchestrator_card.question_like_emit_rate)),
    )
    return {
        "alpha_win_weighted": bool(alpha_win_weighted),
        "safety_gate": bool(safety_gate),
        "trace_gate": bool(trace_gate),
        "question_gate": bool(question_gate),
        "promotion_gate_pass": bool(alpha_win_weighted and safety_gate and trace_gate and question_gate),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Spark advisory replay arena (baseline champion lane vs alpha challenger lane).")
    ap.add_argument("--seed", type=int, default=42, help="Deterministic episode seed.")
    ap.add_argument("--episodes", type=int, default=120, help="Number of episodes to replay.")
    ap.add_argument("--episodes-file", type=str, default="", help="Optional JSON file containing replay episodes.")
    ap.add_argument(
        "--weights",
        type=str,
        default="0.45,0.20,0.20,0.15",
        help="Weighted score coefficients: utility,safety,trace,latency",
    )
    ap.add_argument("--latency-ref-ms", type=float, default=1200.0, help="Reference p95 latency for normalization.")
    ap.add_argument("--require-safety-floor", type=float, default=0.98, help="Min challenger safety_rate to pass gate.")
    ap.add_argument("--require-trace-floor", type=float, default=0.95, help="Min challenger trace_integrity_rate to pass gate.")
    ap.add_argument(
        "--max-question-like-rate",
        type=float,
        default=0.0,
        help="Max challenger question-like advisory rate to pass gate.",
    )
    ap.add_argument("--min-consecutive-wins", type=int, default=3, help="Required consecutive promotion gate passes.")
    ap.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT_DIR), help="Output directory for report artifacts.")
    args = ap.parse_args()

    _apply_deterministic_env()
    weights = DEFAULT_WEIGHTS
    if str(args.weights or "").strip():
        weights = parse_weights(str(args.weights))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    episodes = _load_episodes(
        seed=int(args.seed),
        episodes=max(1, int(args.episodes)),
        episodes_file=Path(args.episodes_file) if str(args.episodes_file or "").strip() else None,
    )
    if not episodes:
        raise RuntimeError("no episodes available for replay")

    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    trace_prefix = f"arena:{run_id}"

    orchestrator_results = _run_route(route="orchestrator", run_tag=run_id, episodes=episodes, trace_prefix=trace_prefix)
    alpha_results = _run_route(route="alpha", run_tag=run_id, episodes=episodes, trace_prefix=trace_prefix)

    orchestrator_card = _compute_scorecard(
        route="orchestrator",
        results=orchestrator_results,
        weights=weights,
        latency_ref_ms=float(args.latency_ref_ms),
    )
    alpha_card = _compute_scorecard(
        route="alpha",
        results=alpha_results,
        weights=weights,
        latency_ref_ms=float(args.latency_ref_ms),
    )

    gate = evaluate_promotion_gate(
        alpha_card=alpha_card,
        orchestrator_card=orchestrator_card,
        require_safety_floor=float(args.require_safety_floor),
        require_trace_floor=float(args.require_trace_floor),
        max_question_like_rate=float(args.max_question_like_rate),
    )
    alpha_win_weighted = bool(gate.get("alpha_win_weighted"))
    safety_gate = bool(gate.get("safety_gate"))
    trace_gate = bool(gate.get("trace_gate"))
    question_gate = bool(gate.get("question_gate"))
    promotion_gate_pass = bool(gate.get("promotion_gate_pass"))

    ledger_row = {
        "ts": time.time(),
        "run_id": run_id,
        "episodes": len(episodes),
        "episodes_hash": _episodes_hash(episodes),
        "alpha_win_weighted": bool(alpha_win_weighted),
        "safety_gate": bool(safety_gate),
        "trace_gate": bool(trace_gate),
        "question_gate": bool(question_gate),
        "promotion_gate_pass": bool(promotion_gate_pass),
        "orchestrator_weighted_score": float(orchestrator_card.weighted_score),
        "alpha_weighted_score": float(alpha_card.weighted_score),
        "alpha_question_like_emit_rate": float(alpha_card.question_like_emit_rate),
    }
    _append_jsonl(PROMOTION_LEDGER, ledger_row)

    ledger_rows = _read_jsonl(PROMOTION_LEDGER, limit=500)
    streak = consecutive_promotion_wins(ledger_rows)
    eligible = bool(streak >= max(1, int(args.min_consecutive_wins)))

    winner_route = "alpha" if alpha_win_weighted else "orchestrator"
    winner_reason = "alpha_weighted_score_higher" if alpha_win_weighted else "orchestrator_retains_champion"

    report = {
        "run_id": run_id,
        "deterministic": True,
        "episodes": len(episodes),
        "episodes_hash": _episodes_hash(episodes),
        "config": {
            "seed": int(args.seed),
            "weights": weights,
            "latency_ref_ms": float(args.latency_ref_ms),
            "require_safety_floor": float(args.require_safety_floor),
            "require_trace_floor": float(args.require_trace_floor),
            "max_question_like_rate": float(args.max_question_like_rate),
            "min_consecutive_wins": int(args.min_consecutive_wins),
        },
        "winner": {
            "route": winner_route,
            "reason": winner_reason,
        },
        "scorecards": {
            "orchestrator": asdict(orchestrator_card),
            "alpha": asdict(alpha_card),
        },
        "promotion": {
            "alpha_win_weighted": bool(alpha_win_weighted),
            "safety_gate": bool(safety_gate),
            "trace_gate": bool(trace_gate),
            "question_gate": bool(question_gate),
            "promotion_gate_pass": bool(promotion_gate_pass),
            "alpha_question_like_emit_rate": float(alpha_card.question_like_emit_rate),
            "question_like_examples": {
                "alpha": _question_like_examples(alpha_results, limit=5),
                "orchestrator": _question_like_examples(orchestrator_results, limit=5),
            },
            "consecutive_pass_streak": int(streak),
            "min_consecutive_wins": int(args.min_consecutive_wins),
            "eligible_for_cutover": bool(eligible),
        },
        "artifacts": {},
    }

    latest_json = out_dir / "spark_alpha_replay_arena_latest.json"
    previous = {}
    if latest_json.exists():
        try:
            previous = json.loads(latest_json.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    if isinstance(previous, dict) and previous:
        diff = build_diff(report, previous)
        diff_path = out_dir / f"spark_alpha_replay_arena_diff_{run_id}.json"
        _write_json(diff_path, diff)
        report["artifacts"]["diff_json"] = str(diff_path)

    run_json = out_dir / f"spark_alpha_replay_arena_{run_id}.json"
    run_md = out_dir / f"spark_alpha_replay_arena_{run_id}.md"
    scorecards_json = out_dir / f"spark_alpha_replay_scorecards_{run_id}.json"
    episodes_json = out_dir / f"spark_alpha_replay_episodes_{run_id}.json"

    _write_json(
        scorecards_json,
        {
            "run_id": run_id,
            "champion": asdict(orchestrator_card),
            "challenger": asdict(alpha_card),
        },
    )
    _write_json(
        episodes_json,
        {
            "run_id": run_id,
            "seed": int(args.seed),
            "episodes": [asdict(ep) for ep in episodes],
        },
    )
    _write_json(run_json, report)
    run_md.write_text(_render_markdown(report), encoding="utf-8")

    # Latest pointers for automation.
    _write_json(latest_json, report)
    (out_dir / "spark_alpha_replay_arena_latest.md").write_text(
        _render_markdown(report),
        encoding="utf-8",
    )
    _write_json(
        out_dir / "spark_alpha_replay_scorecards_latest.json",
        {
            "run_id": run_id,
            "champion": asdict(orchestrator_card),
            "challenger": asdict(alpha_card),
        },
    )

    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "winner": winner_route,
                "orchestrator_weighted": orchestrator_card.weighted_score,
                "alpha_weighted": alpha_card.weighted_score,
                "promotion_gate_pass": promotion_gate_pass,
                "question_gate": question_gate,
                "consecutive_pass_streak": streak,
                "eligible_for_cutover": eligible,
                "report_json": str(run_json),
                "report_md": str(run_md),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
