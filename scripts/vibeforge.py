#!/usr/bin/env python3
"""VibeForge loop CLI.

Initial production slice:
- Goal lifecycle: init/status/pause/resume
- One-cycle run loop with oracle evaluation (production_gates + carmack_kpi)
- Tuneable proposal lane with schema validation and rollback
- Append-only ledger + regret tracking
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib.carmack_kpi import build_scorecard
from lib.production_gates import evaluate_gates, load_live_metrics
from lib.tuneables_schema import SCHEMA, validate_tuneables


EPSILON = 1e-9
GOAL_VERSION = 1
EVOLVE_START_RE = re.compile(r"^\s*#\s*---\s*EVOLVE-BLOCK-START:\s*([A-Za-z0-9_.\-]+)\s*---\s*$")
EVOLVE_END_RE = re.compile(r"^\s*#\s*---\s*EVOLVE-BLOCK-END\s*---\s*$")


PRESETS: Dict[str, Dict[str, Any]] = {
    "retrieval": {
        "goal": "Improve advisory retrieval rate to 85%",
        "optimize": "maximize",
        "metric": {"name": "retrieval_rate", "source": "production_gates", "field": "retrieval_rate"},
        "target": 0.85,
        "constraints": [
            {
                "name": "quality_rate",
                "source": "production_gates",
                "field": "quality_rate",
                "operator": ">=",
                "threshold": 0.30,
            },
            {
                "name": "effectiveness_rate",
                "source": "production_gates",
                "field": "effectiveness_rate",
                "operator": ">=",
                "threshold": 0.40,
            },
        ],
        "evolve_blocks": [
            "lib/advisory_engine.py",
            "lib/noise_classifier.py",
            "lib/cognitive_learner.py",
            "config/tuneables.json",
        ],
        "max_cycles": 20,
    },
    "latency": {
        "goal": "Reduce advisory queue depth to <= 5",
        "optimize": "minimize",
        "metric": {"name": "queue_depth", "source": "production_gates", "field": "queue_depth"},
        "target": 5.0,
        "constraints": [
            {
                "name": "retrieval_rate",
                "source": "production_gates",
                "field": "retrieval_rate",
                "operator": ">=",
                "threshold": 0.60,
            }
        ],
        "evolve_blocks": [
            "lib/advisory_engine.py",
            "lib/advisory_prefetch_worker.py",
            "config/tuneables.json",
        ],
        "max_cycles": 20,
    },
}


@dataclass
class TuneableProposal:
    section: str
    key: str
    from_value: Any
    to_value: Any
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "type": "tuneable",
            "section": self.section,
            "key": self.key,
            "from": self.from_value,
            "to": self.to_value,
            "reason": self.reason,
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _spark_dir() -> Path:
    raw = str(os.getenv("SPARK_FORGE_DIR", "")).strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".spark"


def _default_goal_path() -> Path:
    return _spark_dir() / "forge_goal.json"


def _default_ledger_path() -> Path:
    return _spark_dir() / "forge_ledger.jsonl"


def _default_blocks_inventory_path() -> Path:
    return _spark_dir() / "forge_evolve_blocks.json"


def _default_tuneables_path() -> Path:
    return _spark_dir() / "tuneables.json"


def _forge_backup_dir() -> Path:
    return _spark_dir() / "forge_backups"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return data


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=True) + "\n")


def _read_jsonl(path: Path, limit: int = 0) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except Exception:
        return []
    if limit > 0:
        lines = lines[-int(limit):]
    for line in lines:
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _dot_get(obj: Any, field: str) -> Any:
    parts = [p for p in str(field or "").split(".") if p]
    cur = obj
    for p in parts:
        if isinstance(cur, dict):
            if p not in cur:
                raise KeyError(f"missing key: {p}")
            cur = cur[p]
            continue
        if hasattr(cur, p):
            cur = getattr(cur, p)
            continue
        raise KeyError(f"missing attribute: {p}")
    return cur


def _infer_optimize(goal: Dict[str, Any]) -> str:
    explicit = str(goal.get("optimize", "")).strip().lower()
    if explicit in {"maximize", "minimize"}:
        return explicit
    metric_name = str((goal.get("metric") or {}).get("name", "")).lower()
    if any(token in metric_name for token in ("noise", "latency", "queue", "duplicate", "burden", "leakage")):
        return "minimize"
    return "maximize"


def _goal_reached(value: float, target: float, optimize: str) -> bool:
    if optimize == "minimize":
        return float(value) <= float(target) + EPSILON
    return float(value) >= float(target) - EPSILON


def _compare(left: float, operator: str, threshold: float) -> bool:
    op = str(operator or "").strip()
    if op == ">=":
        return float(left) >= float(threshold)
    if op == "<=":
        return float(left) <= float(threshold)
    if op == ">":
        return float(left) > float(threshold)
    if op == "<":
        return float(left) < float(threshold)
    if op in {"==", "="}:
        return abs(float(left) - float(threshold)) <= EPSILON
    raise ValueError(f"unsupported operator: {op}")


def _scan_evolve_blocks(paths: Iterable[str]) -> Dict[str, Any]:
    root = _repo_root()
    inventory: List[Dict[str, Any]] = []
    for raw in paths:
        item = str(raw or "").strip()
        if not item:
            continue
        if item.replace("\\", "/").endswith("config/tuneables.json"):
            inventory.append(
                {
                    "path": item,
                    "mode": "tuneables_all",
                    "exists": (root / "config" / "tuneables.json").exists(),
                    "blocks": [{"name": "__all__", "start_line": 1, "end_line": 0}],
                }
            )
            continue

        p = Path(item)
        if not p.is_absolute():
            p = root / item
        blocks: List[Dict[str, Any]] = []
        exists = p.exists()
        if exists:
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except Exception:
                lines = []
            current_name = ""
            current_start = 0
            for idx, line in enumerate(lines, start=1):
                m_start = EVOLVE_START_RE.match(line)
                if m_start:
                    current_name = str(m_start.group(1))
                    current_start = idx
                    continue
                if current_name and EVOLVE_END_RE.match(line):
                    blocks.append(
                        {
                            "name": current_name,
                            "start_line": int(current_start),
                            "end_line": int(idx),
                        }
                    )
                    current_name = ""
                    current_start = 0

        inventory.append(
            {
                "path": item,
                "mode": "code",
                "exists": exists,
                "blocks": blocks,
            }
        )
    return {"generated_at": _now_iso(), "inventory": inventory}


def _measure_sources() -> Dict[str, Any]:
    loop_metrics = load_live_metrics()
    loop_metrics_dict = dict(vars(loop_metrics))
    gates = evaluate_gates(loop_metrics)
    scorecard = build_scorecard(window_hours=4.0)
    return {
        "production_gates": {
            "metrics": loop_metrics_dict,
            "gates": gates,
        },
        "carmack_kpi": scorecard,
    }


def _resolve_metric(spec: Dict[str, Any], sources: Dict[str, Any]) -> float:
    source = str(spec.get("source", "")).strip().lower()
    field = str(spec.get("field", "")).strip()
    if not source or not field:
        raise ValueError("metric source/field missing")

    if source == "production_gates":
        payload = sources.get("production_gates") or {}
        metrics = payload.get("metrics") or {}
        for candidate in (
            field,
            f"metrics.{field}",
            f"gates.{field}",
        ):
            try:
                if candidate.startswith("metrics.") or candidate.startswith("gates."):
                    value = _dot_get(payload, candidate)
                else:
                    value = _dot_get(metrics, candidate)
                return float(value)
            except Exception:
                continue
        raise KeyError(f"production_gates field not found: {field}")

    if source == "carmack_kpi":
        value = _dot_get(sources.get("carmack_kpi") or {}, field)
        return float(value)

    if source == "benchmark":
        raise ValueError("benchmark source is not implemented in this initial slice")

    raise ValueError(f"unknown metric source: {source}")


def _evaluate_constraints(goal: Dict[str, Any], sources: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in list(goal.get("constraints") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "constraint"))
        operator = str(item.get("operator", ">="))
        threshold = float(item.get("threshold", 0.0) or 0.0)
        value = _resolve_metric(item, sources)
        ok = _compare(value, operator, threshold)
        out.append(
            {
                "name": name,
                "source": str(item.get("source", "")),
                "field": str(item.get("field", "")),
                "operator": operator,
                "threshold": threshold,
                "value": float(value),
                "ok": bool(ok),
            }
        )
    return out


def _measure_goal(goal: Dict[str, Any]) -> Dict[str, Any]:
    sources = _measure_sources()
    objective = _resolve_metric(goal.get("metric") or {}, sources)
    constraints = _evaluate_constraints(goal, sources)
    return {
        "objective": float(objective),
        "constraints": constraints,
        "all_constraints_ok": all(bool(x.get("ok")) for x in constraints),
        "gates_ready": bool(((sources.get("production_gates") or {}).get("gates") or {}).get("ready", False)),
        "sources": sources,
    }


def _load_tuneables(path: Path) -> Dict[str, Any]:
    base = _read_json(path, {})
    if not isinstance(base, dict):
        base = {}
    result = validate_tuneables(base)
    return result.data if isinstance(result.data, dict) else {}


def _write_tuneables(path: Path, tuneables: Dict[str, Any]) -> Dict[str, Any]:
    result = validate_tuneables(tuneables)
    _write_json(path, result.data)
    return {
        "warnings": list(result.warnings or []),
        "clamped": list(result.clamped or []),
        "defaults_applied": list(result.defaults_applied or []),
    }


def _candidate_pool(metric_name: str, optimize: str) -> List[Dict[str, Any]]:
    metric = str(metric_name or "").strip().lower()
    if metric == "retrieval_rate":
        return [
            {"section": "advisor", "key": "min_rank_score", "op": "add", "delta": -0.02, "reason": "Lower rank floor to improve recall."},
            {"section": "advisor", "key": "max_advice_items", "op": "add", "delta": 1, "reason": "Widen candidate set for retrieval coverage."},
            {"section": "advisory_gate", "key": "max_emit_per_call", "op": "add", "delta": 1, "reason": "Allow more surfaced candidates per call."},
            {"section": "advisory_engine", "key": "include_mind", "op": "set", "value": True, "reason": "Include mind memory to expand retrieval evidence."},
        ]
    if metric in {"quality_rate", "strict_trace_coverage"}:
        return [
            {"section": "advisor", "key": "min_rank_score", "op": "add", "delta": 0.02, "reason": "Tighten rank floor to reduce noisy retrievals."},
            {"section": "advisory_gate", "key": "note_threshold", "op": "add", "delta": 0.02, "reason": "Raise note threshold to reduce weak emissions."},
            {"section": "advisory_gate", "key": "warning_threshold", "op": "add", "delta": 0.02, "reason": "Raise warning threshold for higher precision."},
        ]
    if optimize == "minimize":
        return [
            {"section": "advisory_engine", "key": "prefetch_inline_enabled", "op": "set", "value": False, "reason": "Reduce inline contention."},
            {"section": "advisory_engine", "key": "prefetch_inline_max_jobs", "op": "add", "delta": -1, "reason": "Lower inline workload pressure."},
        ]
    return [
        {"section": "advisor", "key": "max_advice_items", "op": "add", "delta": 1, "reason": "General exploration candidate."},
        {"section": "advisor", "key": "min_rank_score", "op": "add", "delta": -0.01, "reason": "General recall expansion candidate."},
    ]


def _attempted_proposals(ledger_rows: List[Dict[str, Any]]) -> set[Tuple[str, str, str]]:
    seen: set[Tuple[str, str, str]] = set()
    for row in ledger_rows:
        prop = row.get("proposal") if isinstance(row, dict) else None
        if not isinstance(prop, dict):
            continue
        if str(prop.get("type")) != "tuneable":
            continue
        sec = str(prop.get("section", ""))
        key = str(prop.get("key", ""))
        to_value = json.dumps(prop.get("to"), sort_keys=True)
        seen.add((sec, key, to_value))
    return seen


def _default_for_key(section: str, key: str) -> Any:
    sec = SCHEMA.get(section) or {}
    spec = sec.get(key)
    if spec is not None:
        return spec.default
    return None


def _propose_tuneable(goal: Dict[str, Any], ledger_rows: List[Dict[str, Any]], tuneables: Dict[str, Any]) -> Optional[TuneableProposal]:
    metric_name = str((goal.get("metric") or {}).get("name", ""))
    optimize = _infer_optimize(goal)
    attempted = _attempted_proposals(ledger_rows[-40:])
    candidates = _candidate_pool(metric_name, optimize)

    for c in candidates:
        section = str(c.get("section", ""))
        key = str(c.get("key", ""))
        if not section or not key:
            continue
        section_dict = tuneables.setdefault(section, {})
        if not isinstance(section_dict, dict):
            section_dict = {}
            tuneables[section] = section_dict

        current = section_dict.get(key, _default_for_key(section, key))
        proposal_value = current
        op = str(c.get("op", "")).strip()

        if op == "set":
            proposal_value = c.get("value")
        elif op == "add":
            delta = c.get("delta", 0)
            if isinstance(current, bool):
                continue
            try:
                if isinstance(current, int):
                    proposal_value = int(current) + int(delta)
                else:
                    proposal_value = float(current) + float(delta)
            except Exception:
                continue
        else:
            continue

        sig = (section, key, json.dumps(proposal_value, sort_keys=True))
        if sig in attempted:
            continue
        if json.dumps(current, sort_keys=True) == json.dumps(proposal_value, sort_keys=True):
            continue

        return TuneableProposal(
            section=section,
            key=key,
            from_value=current,
            to_value=proposal_value,
            reason=str(c.get("reason", "VibeForge candidate change.")),
        )
    return None


def _create_tuneables_backup(path: Path, cycle: int) -> Path:
    backup_dir = _forge_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    backup_path = backup_dir / f"tuneables_cycle_{cycle:04d}_{stamp}.json"
    if path.exists():
        shutil.copyfile(path, backup_path)
    else:
        _write_json(backup_path, {})
    snapshots = sorted(backup_dir.glob("tuneables_cycle_*.json"))
    for old in snapshots[:-5]:
        try:
            old.unlink()
        except Exception:
            pass
    return backup_path


def _restore_tuneables(path: Path, backup_path: Path) -> None:
    if backup_path.exists():
        shutil.copyfile(backup_path, path)


def _reward(before: float, after: float, optimize: str) -> float:
    if optimize == "minimize":
        return float(before) - float(after)
    return float(after) - float(before)


def _gap(value: float, target: float, optimize: str) -> float:
    if optimize == "minimize":
        return max(0.0, float(value) - float(target))
    return max(0.0, float(target) - float(value))


def _update_regret(ledger_rows: List[Dict[str, Any]], reward: float, gap_before: float) -> Tuple[float, float, float]:
    del gap_before
    best_possible = max(float(reward), 0.01)
    cycle_regret = max(0.0, best_possible - float(reward))
    cumulative = float(sum(float(r.get("cycle_regret", 0.0) or 0.0) for r in ledger_rows)) + cycle_regret
    n = len(ledger_rows) + 1
    if cumulative <= 0.0 or n <= 1:
        rate = 0.0
    else:
        rate = math.log(cumulative + 1.0) / math.log(float(n) + 1.0)
    return cycle_regret, cumulative, rate


def _validate_goal(goal: Dict[str, Any]) -> None:
    required = {"goal", "metric", "target", "constraints", "evolve_blocks", "max_cycles", "status"}
    missing = [k for k in required if k not in goal]
    if missing:
        raise ValueError(f"goal missing required fields: {', '.join(missing)}")
    metric = goal.get("metric")
    if not isinstance(metric, dict):
        raise ValueError("goal.metric must be an object")
    for key in ("name", "source", "field"):
        if key not in metric:
            raise ValueError(f"goal.metric.{key} missing")


def _init_goal(preset: str, goal_path: Path, no_baseline: bool) -> Dict[str, Any]:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset: {preset}")
    base = dict(PRESETS[preset])
    goal: Dict[str, Any] = {
        "version": GOAL_VERSION,
        "goal": base["goal"],
        "metric": dict(base["metric"]),
        "baseline": None,
        "target": float(base["target"]),
        "constraints": list(base["constraints"]),
        "evolve_blocks": list(base["evolve_blocks"]),
        "max_cycles": int(base["max_cycles"]),
        "status": "active",
        "optimize": str(base.get("optimize", "maximize")),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "cycles_run": 0,
        "cycles_promoted": 0,
        "cycles_rolled_back": 0,
        "regret_cumulative": 0.0,
        "regret_rate": 0.0,
    }

    if not no_baseline:
        try:
            measured = _measure_goal(goal)
            goal["baseline"] = float(measured["objective"])
        except Exception:
            goal["baseline"] = None

    _write_json(goal_path, goal)
    inventory = _scan_evolve_blocks(goal.get("evolve_blocks") or [])
    _write_json(_default_blocks_inventory_path(), inventory)
    return goal


def _load_goal(goal_path: Path) -> Dict[str, Any]:
    goal = _read_json(goal_path, {})
    if not isinstance(goal, dict):
        raise ValueError("goal file is invalid")
    _validate_goal(goal)
    return goal


def _save_goal(goal_path: Path, goal: Dict[str, Any]) -> None:
    goal["updated_at"] = _now_iso()
    _write_json(goal_path, goal)


def _status_payload(goal: Dict[str, Any], ledger_rows: List[Dict[str, Any]], include_measure: bool) -> Dict[str, Any]:
    optimize = _infer_optimize(goal)
    current_value = None
    constraints: List[Dict[str, Any]] = []
    gates_ready = None
    if include_measure:
        try:
            measurement = _measure_goal(goal)
            current_value = float(measurement["objective"])
            constraints = list(measurement["constraints"])
            gates_ready = bool(measurement["gates_ready"])
        except Exception:
            current_value = None
            constraints = []
            gates_ready = None

    progress = None
    if current_value is not None:
        baseline = goal.get("baseline")
        target = float(goal.get("target", 0.0))
        if baseline is not None:
            try:
                b = float(baseline)
                if optimize == "minimize":
                    den = max(EPSILON, b - target)
                    progress = max(0.0, min(1.0, (b - current_value) / den))
                else:
                    den = max(EPSILON, target - b)
                    progress = max(0.0, min(1.0, (current_value - b) / den))
            except Exception:
                progress = None

    return {
        "goal": goal.get("goal"),
        "status": goal.get("status"),
        "optimize": optimize,
        "current": current_value,
        "target": float(goal.get("target", 0.0)),
        "baseline": goal.get("baseline"),
        "progress": progress,
        "cycles_run": int(goal.get("cycles_run", 0) or 0),
        "cycles_promoted": int(goal.get("cycles_promoted", 0) or 0),
        "cycles_rolled_back": int(goal.get("cycles_rolled_back", 0) or 0),
        "regret_cumulative": float(goal.get("regret_cumulative", 0.0) or 0.0),
        "regret_rate": float(goal.get("regret_rate", 0.0) or 0.0),
        "constraints": constraints,
        "gates_ready": gates_ready,
        "last_cycles": ledger_rows[-5:],
    }


def _print_status(payload: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    print("VIBEFORGE LOOP")
    print("=" * 50)
    print(f"Goal:     {payload.get('goal')}")
    print(f"Status:   {payload.get('status')}")
    current = payload.get("current")
    target = payload.get("target")
    if current is not None:
        print(f"Current:  {float(current):.4f}")
    print(f"Target:   {float(target):.4f}")
    progress = payload.get("progress")
    if progress is not None:
        print(f"Progress: {float(progress) * 100:.1f}%")
    print(
        f"Cycles:   {payload.get('cycles_run', 0)} run, "
        f"{payload.get('cycles_promoted', 0)} promoted, "
        f"{payload.get('cycles_rolled_back', 0)} rolled back"
    )
    print(
        f"Regret:   cumulative={float(payload.get('regret_cumulative', 0.0)):.4f}, "
        f"rate={float(payload.get('regret_rate', 0.0)):.4f}"
    )
    if payload.get("gates_ready") is not None:
        print(f"Gates:    {'READY' if payload.get('gates_ready') else 'NOT READY'}")
    constraints = list(payload.get("constraints") or [])
    if constraints:
        print("")
        print("Constraints:")
        for c in constraints:
            state = "OK" if c.get("ok") else "FAIL"
            print(
                f"  {c.get('name')}: {c.get('value')} {c.get('operator')} {c.get('threshold')} [{state}]"
            )


def _run_cycle(
    goal: Dict[str, Any],
    *,
    goal_path: Path,
    ledger_path: Path,
    tuneables_path: Path,
    dry_run: bool,
) -> Tuple[str, Dict[str, Any]]:
    optimize = _infer_optimize(goal)
    cycle = int(goal.get("cycles_run", 0) or 0) + 1
    before = _measure_goal(goal)
    before_value = float(before["objective"])
    target = float(goal.get("target", 0.0))
    gap_before = _gap(before_value, target, optimize)
    if _goal_reached(before_value, target, optimize):
        goal["status"] = "reached"
        _save_goal(goal_path, goal)
        return "reached", {"cycle": cycle, "before": before_value, "after": before_value}

    ledger_rows = _read_jsonl(ledger_path)
    tuneables = _load_tuneables(tuneables_path)
    proposal = _propose_tuneable(goal, ledger_rows, tuneables)
    if proposal is None:
        row = {
            "cycle": cycle,
            "timestamp": _now_iso(),
            "outcome": "no_proposal",
            "metric_before": before_value,
            "metric_after": before_value,
            "delta": 0.0,
            "proposal": None,
            "constraints_checked": before.get("constraints", []),
            "cycle_regret": 0.0,
            "cumulative_regret": float(goal.get("regret_cumulative", 0.0) or 0.0),
            "regret_rate": float(goal.get("regret_rate", 0.0) or 0.0),
        }
        _append_jsonl(ledger_path, row)
        goal["cycles_run"] = cycle
        goal["cycles_rolled_back"] = int(goal.get("cycles_rolled_back", 0) or 0) + 1
        _save_goal(goal_path, goal)
        return "no_proposal", row

    proposal_dict = proposal.as_dict()
    if dry_run:
        row = {
            "cycle": cycle,
            "timestamp": _now_iso(),
            "outcome": "dry_run",
            "metric_before": before_value,
            "metric_after": before_value,
            "delta": 0.0,
            "proposal": proposal_dict,
            "constraints_checked": before.get("constraints", []),
            "cycle_regret": 0.0,
            "cumulative_regret": float(goal.get("regret_cumulative", 0.0) or 0.0),
            "regret_rate": float(goal.get("regret_rate", 0.0) or 0.0),
        }
        _append_jsonl(ledger_path, row)
        return "dry_run", row

    backup = _create_tuneables_backup(tuneables_path, cycle)
    tuneables.setdefault(proposal.section, {})
    if not isinstance(tuneables[proposal.section], dict):
        tuneables[proposal.section] = {}
    tuneables[proposal.section][proposal.key] = proposal.to_value
    validation_meta = _write_tuneables(tuneables_path, tuneables)

    after = _measure_goal(goal)
    after_value = float(after["objective"])
    delta = _reward(before_value, after_value, optimize)
    improved = delta > EPSILON
    constraints_ok = bool(after.get("all_constraints_ok"))

    outcome = "promoted"
    if not (improved and constraints_ok):
        _restore_tuneables(tuneables_path, backup)
        outcome = "rolled_back"

    cycle_regret, cumulative_regret, regret_rate = _update_regret(
        _read_jsonl(ledger_path),
        reward=delta,
        gap_before=gap_before,
    )

    row = {
        "cycle": cycle,
        "timestamp": _now_iso(),
        "outcome": outcome,
        "metric_before": before_value,
        "metric_after": after_value,
        "delta": delta,
        "proposal": proposal_dict,
        "constraints_checked": after.get("constraints", []),
        "validation": validation_meta,
        "backup_path": str(backup),
        "cycle_regret": cycle_regret,
        "cumulative_regret": cumulative_regret,
        "regret_rate": regret_rate,
    }
    _append_jsonl(ledger_path, row)

    goal["cycles_run"] = cycle
    goal["regret_cumulative"] = cumulative_regret
    goal["regret_rate"] = regret_rate
    if outcome == "promoted":
        goal["cycles_promoted"] = int(goal.get("cycles_promoted", 0) or 0) + 1
    else:
        goal["cycles_rolled_back"] = int(goal.get("cycles_rolled_back", 0) or 0) + 1

    latest_value = after_value if outcome == "promoted" else before_value
    if _goal_reached(latest_value, target, optimize):
        goal["status"] = "reached"
    elif regret_rate > 1.0:
        goal["status"] = "paused"

    _save_goal(goal_path, goal)
    return outcome, row


def cmd_init(args: argparse.Namespace) -> int:
    goal_path = Path(args.goal).expanduser()
    goal = _init_goal(args.preset, goal_path, no_baseline=bool(args.no_baseline))
    print(f"Goal created: {goal_path}")
    print(f"  Goal: {goal.get('goal')}")
    print(f"  Target: {goal.get('target')}")
    print(f"  Baseline: {goal.get('baseline')}")
    print(f"  EVOLVE-BLOCK files: {len(goal.get('evolve_blocks') or [])}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    goal = _load_goal(Path(args.goal).expanduser())
    ledger = _read_jsonl(Path(args.ledger).expanduser())
    payload = _status_payload(goal, ledger, include_measure=not bool(args.no_measure))
    _print_status(payload, as_json=bool(args.json))
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    path = Path(args.goal).expanduser()
    goal = _load_goal(path)
    goal["status"] = "paused"
    _save_goal(path, goal)
    print("VibeForge paused.")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    path = Path(args.goal).expanduser()
    goal = _load_goal(path)
    goal["status"] = "active"
    _save_goal(path, goal)
    print("VibeForge resumed.")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    rows = _read_jsonl(Path(args.ledger).expanduser(), limit=max(0, int(args.limit)))
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No forge history yet.")
        return 0
    print("FORGE EVOLUTION HISTORY")
    print("=" * 70)
    for row in rows:
        cyc = int(row.get("cycle", 0) or 0)
        outcome = str(row.get("outcome", "unknown"))
        before = float(row.get("metric_before", 0.0) or 0.0)
        after = float(row.get("metric_after", 0.0) or 0.0)
        delta = float(row.get("delta", 0.0) or 0.0)
        proposal = row.get("proposal") if isinstance(row.get("proposal"), dict) else {}
        p_desc = f"{proposal.get('section', '')}.{proposal.get('key', '')}" if proposal else "-"
        print(f"Cycle {cyc:03d}  {outcome:11s}  {before:.4f} -> {after:.4f}  delta={delta:+.4f}  {p_desc}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    goal_path = Path(args.goal).expanduser()
    ledger_path = Path(args.ledger).expanduser()
    tuneables_path = Path(args.tuneables).expanduser()
    goal = _load_goal(goal_path)

    if str(goal.get("status", "active")) == "paused":
        print("Goal is paused. Use `resume` first.")
        return 2
    if str(goal.get("status", "active")) == "reached":
        print("Goal already reached.")
        return 3

    cycles = max(1, int(args.cycles))
    rc = 0
    for _ in range(cycles):
        outcome, row = _run_cycle(
            goal,
            goal_path=goal_path,
            ledger_path=ledger_path,
            tuneables_path=tuneables_path,
            dry_run=bool(args.dry_run),
        )
        goal = _load_goal(goal_path)
        print(
            f"Cycle {int(row.get('cycle', 0)):03d}: {outcome}  "
            f"{float(row.get('metric_before', 0.0)):.4f} -> {float(row.get('metric_after', 0.0)):.4f}  "
            f"delta={float(row.get('delta', 0.0)):+.4f}"
        )
        if outcome == "reached" or str(goal.get("status")) == "reached":
            rc = 3
            break
        if str(goal.get("status")) == "paused":
            rc = 2
            break
    return rc


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--goal", default=str(_default_goal_path()), help="Goal file path")
    parser.add_argument("--ledger", default=str(_default_ledger_path()), help="Ledger path")
    parser.add_argument("--tuneables", default=str(_default_tuneables_path()), help="Tuneables path")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VibeForge goal-directed self-improvement loop")
    p.set_defaults(fn=None)
    _add_common_args(p)

    sub = p.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Create a goal from preset")
    _add_common_args(p_init)
    p_init.add_argument("preset", choices=sorted(PRESETS.keys()))
    p_init.add_argument("--no-baseline", action="store_true", help="Skip baseline measurement")
    p_init.set_defaults(fn=cmd_init)

    p_status = sub.add_parser("status", help="Show goal progress")
    _add_common_args(p_status)
    p_status.add_argument("--json", action="store_true", help="JSON output")
    p_status.add_argument("--no-measure", action="store_true", help="Skip live measurement")
    p_status.set_defaults(fn=cmd_status)

    p_run_once = sub.add_parser("run-once", help="Run one improvement cycle")
    _add_common_args(p_run_once)
    p_run_once.add_argument("--dry-run", action="store_true", help="Do not apply proposal")
    p_run_once.set_defaults(fn=cmd_run, cycles=1)

    p_run = sub.add_parser("run", help="Run one or more cycles")
    _add_common_args(p_run)
    p_run.add_argument("--cycles", type=int, default=1)
    p_run.add_argument("--dry-run", action="store_true", help="Do not apply proposals")
    p_run.set_defaults(fn=cmd_run)

    p_hist = sub.add_parser("history", help="Show recent ledger rows")
    _add_common_args(p_hist)
    p_hist.add_argument("--limit", type=int, default=20)
    p_hist.add_argument("--json", action="store_true")
    p_hist.set_defaults(fn=cmd_history)

    p_pause = sub.add_parser("pause", help="Pause goal")
    _add_common_args(p_pause)
    p_pause.set_defaults(fn=cmd_pause)

    p_resume = sub.add_parser("resume", help="Resume goal")
    _add_common_args(p_resume)
    p_resume.set_defaults(fn=cmd_resume)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    fn = getattr(args, "fn", None)
    if fn is None:
        parser.print_help()
        return 1
    try:
        return int(fn(args))
    except Exception as exc:
        print(f"[vibeforge] error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
