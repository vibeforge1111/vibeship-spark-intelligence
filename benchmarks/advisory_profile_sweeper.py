"""Advisory profile parameter sweeper.

Generates a grid of candidate advisory configurations, evaluates them against
a case set, and selects the best-performing profiles using a weighted objective
function.

Usage:
    python benchmarks/advisory_profile_sweeper.py [--cases-path PATH] [--repeats N]
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import benchmarks.advisory_quality_ab as aq


# ---------------------------------------------------------------------------
# Weights for multi-objective scoring
# ---------------------------------------------------------------------------

@dataclass
class SweepWeights:
    """Weights applied to each metric when computing objective score."""
    score_weight: float = 1.0
    no_emit_penalty: float = 1.5
    repetition_penalty: float = 1.2
    actionability_bonus: float = 0.4
    trace_bound_bonus: float = 0.3


# ---------------------------------------------------------------------------
# Objective scoring
# ---------------------------------------------------------------------------

def objective_score(summary: Dict[str, Any], weights: SweepWeights) -> float:
    """Compute a scalar objective score from a profile summary dict.

    Higher is better. Penalises high no_emit_rate and repetition_penalty_rate;
    rewards high actionability_rate and trace_bound_rate.
    """
    base = float(summary.get("score", 0.0))
    no_emit = float(summary.get("no_emit_rate", 0.0))
    repeat = float(summary.get("repetition_penalty_rate", 0.0))
    actionability = float(summary.get("actionability_rate", 0.0))
    trace_bound = float(summary.get("trace_bound_rate", 0.0))

    return (
        weights.score_weight * base
        - weights.no_emit_penalty * no_emit
        - weights.repetition_penalty * repeat
        + weights.actionability_bonus * actionability
        + weights.trace_bound_bonus * trace_bound
    )


# ---------------------------------------------------------------------------
# Candidate profile generation
# ---------------------------------------------------------------------------

def build_candidate_profiles(
    *,
    advisory_text_repeat_grid: List[int],
    tool_cooldown_grid: List[int],
    advice_repeat_grid: List[int],
    min_rank_score_grid: List[float],
    max_items_grid: List[int],
    max_emit_per_call: int = 1,
) -> List[Dict[str, Any]]:
    """Generate the full Cartesian product of advisory config parameters.

    Returns a list of candidate profile dicts. Each dict has at minimum a
    ``name`` key plus nested ``advisory_engine``, ``advisory_gate``, and
    ``advisor`` config sub-dicts.
    """
    candidates: List[Dict[str, Any]] = []
    combos = itertools.product(
        advisory_text_repeat_grid,
        tool_cooldown_grid,
        advice_repeat_grid,
        min_rank_score_grid,
        max_items_grid,
    )
    for atr, tc, ar, mrs, mi in combos:
        name = (
            f"atr{atr}_tc{tc}_ar{ar}_mrs{str(mrs).replace('.', '')}_mi{mi}"
            f"_emit{max_emit_per_call}"
        )
        candidates.append(
            {
                "name": name,
                "advisory_engine": {
                    "advisory_text_repeat_window": atr,
                    "tool_cooldown_window": tc,
                    "advice_repeat_window": ar,
                    "min_rank_score": mrs,
                    "max_items": mi,
                },
                "advisory_gate": {
                    "actionability_min": mrs,
                },
                "advisor": {
                    "max_emit_per_call": max_emit_per_call,
                },
            }
        )
    return candidates


def select_candidate_subset(
    candidates: List[Dict[str, Any]],
    max_candidates: int = 8,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Return a random subset of at most *max_candidates* profiles.

    Always returns at least 1 candidate (or the full list if it is smaller).
    """
    if len(candidates) <= max_candidates:
        return list(candidates)
    rng = random.Random(seed)
    return rng.sample(candidates, max_candidates)


# ---------------------------------------------------------------------------
# Profile sweeper
# ---------------------------------------------------------------------------

def sweep_profiles(
    *,
    cases_path: Path,
    repeats: int = 1,
    force_live: bool = False,
    suppress_emit_output: bool = True,
    candidates: List[Dict[str, Any]],
    weights: SweepWeights,
) -> Dict[str, Any]:
    """Run all candidate profiles against *cases_path* and rank by objective score.

    Returns a summary dict containing the ranked results and the winning profile.
    """
    cases = aq.load_cases(cases_path)

    results = []
    for candidate in candidates:
        profile_name = candidate["name"]
        profile_cfg = {
            k: v for k, v in candidate.items() if k != "name"
        }
        result = aq.run_profile(
            profile_name=profile_name,
            profile_cfg=profile_cfg,
            cases=cases,
            repeats=repeats,
            force_live=force_live,
            suppress_emit_output=suppress_emit_output,
        )
        obj = objective_score(result.get("summary", {}), weights)
        results.append({**result, "objective": obj, "profile_name": profile_name})

    results.sort(key=lambda r: r["objective"], reverse=True)

    return {
        "suppress_emit_output": suppress_emit_output,
        "ranked": results,
        "winner": results[0] if results else None,
        "total_candidates": len(candidates),
    }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Advisory profile parameter sweeper")
    parser.add_argument("--cases-path", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--force-live", action="store_true")
    parser.add_argument("--max-candidates", type=int, default=16)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    all_candidates = build_candidate_profiles(
        advisory_text_repeat_grid=[1800, 3600],
        tool_cooldown_grid=[90, 120],
        advice_repeat_grid=[1800, 3600],
        min_rank_score_grid=[0.45, 0.5],
        max_items_grid=[4, 5],
        max_emit_per_call=1,
    )
    subset = select_candidate_subset(all_candidates, max_candidates=args.max_candidates)
    out = sweep_profiles(
        cases_path=args.cases_path,
        repeats=args.repeats,
        force_live=args.force_live,
        suppress_emit_output=True,
        candidates=subset,
        weights=SweepWeights(),
    )

    if args.out:
        args.out.write_text(json.dumps(out, indent=2))
        print(f"Results written to {args.out}")
    else:
        print(json.dumps(out, indent=2))
