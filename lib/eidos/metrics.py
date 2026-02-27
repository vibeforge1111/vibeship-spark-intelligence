"""
EIDOS Metrics: Measuring Intelligence Compounding

The north star metric:
COMPOUNDING RATE = (Episodes where reused memory led to success) / (Total completed episodes)

If this number doesn't rise, we're not evolving.

Supporting Metrics:
- Reuse Rate: % of steps that cited retrieved memory
- Memory Effectiveness: Win rate with memory vs without
- Loop Suppression: Average retries before success
- Distillation Quality: Rules that proved useful when reused
"""

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CompoundingMetrics:
    """Core compounding metrics."""
    total_episodes: int
    episodes_using_memory: int
    successful_episodes: int
    memory_led_to_success: int
    compounding_rate_pct: float


@dataclass
class ReuseMetrics:
    """Memory reuse metrics."""
    total_steps: int
    steps_with_retrieval: int
    steps_citing_memory: int
    reuse_rate_pct: float


@dataclass
class EffectivenessMetrics:
    """Memory effectiveness comparison."""
    with_memory_episodes: int
    with_memory_successes: int
    with_memory_rate_pct: float
    without_memory_episodes: int
    without_memory_successes: int
    without_memory_rate_pct: float


@dataclass
class LoopMetrics:
    """Loop suppression metrics."""
    avg_retries: float
    max_retries: int
    episodes_over_threshold: int


@dataclass
class DistillationMetrics:
    """Distillation quality by type."""
    type: str
    total: int
    retrievals: int
    uses: int
    helped: int
    effectiveness_pct: float


@dataclass
class WeeklyReport:
    """Weekly intelligence report."""
    episodes: int
    success_rate_pct: float
    new_heuristics: int
    new_sharp_edges: int
    new_anti_patterns: int
    new_playbooks: int


def _sqlite_timeout_s() -> float:
    try:
        return max(0.5, float(os.getenv("SPARK_SQLITE_TIMEOUT_S", "5.0") or 5.0))
    except Exception:
        return 5.0


class MetricsCalculator:
    """
    Calculate EIDOS intelligence metrics from the database.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path.home() / ".spark" / "eidos.db")
        self.db_path = db_path

    def compounding_rate(self) -> CompoundingMetrics:
        """
        Calculate the COMPOUNDING RATE - the north star metric.

        (Episodes where reused memory led to success) / (Total completed episodes)
        """
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            row = conn.execute("""
                WITH episode_memory_usage AS (
                    SELECT
                        e.episode_id,
                        e.outcome,
                        COALESCE(SUM(s.memory_cited), 0) > 0 as used_memory,
                        COALESCE(SUM(CASE WHEN s.memory_useful = 1 THEN 1 ELSE 0 END), 0) > 0 as memory_was_useful
                    FROM episodes e
                    LEFT JOIN steps s ON s.episode_id = e.episode_id
                    WHERE e.outcome IS NOT NULL
                    AND e.outcome != 'in_progress'
                    GROUP BY e.episode_id, e.outcome
                )
                SELECT
                    COUNT(*) as total_episodes,
                    SUM(CASE WHEN used_memory THEN 1 ELSE 0 END) as episodes_using_memory,
                    SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successful_episodes,
                    SUM(CASE WHEN used_memory AND memory_was_useful AND outcome = 'success' THEN 1 ELSE 0 END) as memory_led_to_success
                FROM episode_memory_usage
            """).fetchone()

            total = row[0] or 0
            using_memory = row[1] or 0
            successful = row[2] or 0
            memory_success = row[3] or 0

            rate = (100.0 * memory_success / total) if total > 0 else 0.0

            return CompoundingMetrics(
                total_episodes=total,
                episodes_using_memory=using_memory,
                successful_episodes=successful,
                memory_led_to_success=memory_success,
                compounding_rate_pct=round(rate, 1)
            )

    def reuse_rate(self) -> ReuseMetrics:
        """
        Calculate REUSE RATE - % of steps that cited retrieved memory.
        """
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_steps,
                    SUM(CASE WHEN retrieved_memories IS NOT NULL AND retrieved_memories != '[]' THEN 1 ELSE 0 END) as steps_with_retrieval,
                    SUM(memory_cited) as steps_citing_memory
                FROM steps
                WHERE episode_id IN (
                    SELECT episode_id FROM episodes
                    WHERE outcome IS NOT NULL AND outcome != 'in_progress'
                )
            """).fetchone()

            total = row[0] or 0
            with_retrieval = row[1] or 0
            citing = row[2] or 0

            rate = (100.0 * citing / total) if total > 0 else 0.0

            return ReuseMetrics(
                total_steps=total,
                steps_with_retrieval=with_retrieval,
                steps_citing_memory=citing,
                reuse_rate_pct=round(rate, 1)
            )

    def memory_effectiveness(self) -> EffectivenessMetrics:
        """
        Calculate MEMORY EFFECTIVENESS - win rate with memory vs without.
        """
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            # With memory
            with_row = conn.execute("""
                SELECT
                    COUNT(*) as episodes,
                    SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes
                FROM episodes e
                WHERE EXISTS (
                    SELECT 1 FROM steps s
                    WHERE s.episode_id = e.episode_id AND s.memory_cited = 1
                )
                AND e.outcome IS NOT NULL
                AND e.outcome != 'in_progress'
            """).fetchone()

            # Without memory
            without_row = conn.execute("""
                SELECT
                    COUNT(*) as episodes,
                    SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes
                FROM episodes e
                WHERE NOT EXISTS (
                    SELECT 1 FROM steps s
                    WHERE s.episode_id = e.episode_id AND s.memory_cited = 1
                )
                AND e.outcome IS NOT NULL
                AND e.outcome != 'in_progress'
            """).fetchone()

            with_ep = with_row[0] or 0
            with_succ = with_row[1] or 0
            without_ep = without_row[0] or 0
            without_succ = without_row[1] or 0

            with_rate = (100.0 * with_succ / with_ep) if with_ep > 0 else 0.0
            without_rate = (100.0 * without_succ / without_ep) if without_ep > 0 else 0.0

            return EffectivenessMetrics(
                with_memory_episodes=with_ep,
                with_memory_successes=with_succ,
                with_memory_rate_pct=round(with_rate, 1),
                without_memory_episodes=without_ep,
                without_memory_successes=without_succ,
                without_memory_rate_pct=round(without_rate, 1)
            )

    def loop_suppression(self) -> LoopMetrics:
        """
        Calculate LOOP SUPPRESSION - average retries before success.
        """
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            row = conn.execute("""
                SELECT
                    ROUND(AVG(retry_count), 1) as avg_retries,
                    MAX(retry_count) as max_retries,
                    COUNT(CASE WHEN retry_count > 3 THEN 1 END) as episodes_over_threshold
                FROM (
                    SELECT
                        e.episode_id,
                        COUNT(CASE WHEN s.evaluation = 'fail' THEN 1 END) as retry_count
                    FROM episodes e
                    JOIN steps s ON s.episode_id = e.episode_id
                    WHERE e.outcome = 'success'
                    GROUP BY e.episode_id
                )
            """).fetchone()

            return LoopMetrics(
                avg_retries=row[0] or 0.0,
                max_retries=row[1] or 0,
                episodes_over_threshold=row[2] or 0
            )

    def distillation_quality(self) -> List[DistillationMetrics]:
        """
        Calculate DISTILLATION QUALITY by type.
        """
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            rows = conn.execute("""
                SELECT
                    d.type,
                    COUNT(*) as total_distillations,
                    SUM(d.times_retrieved) as total_retrievals,
                    SUM(d.times_used) as total_uses,
                    SUM(d.times_helped) as total_helped
                FROM distillations d
                GROUP BY d.type
            """).fetchall()

            results = []
            for row in rows:
                dtype = row[0]
                total = row[1] or 0
                retrievals = row[2] or 0
                uses = row[3] or 0
                helped = row[4] or 0
                effectiveness = (100.0 * helped / uses) if uses > 0 else 0.0

                results.append(DistillationMetrics(
                    type=dtype,
                    total=total,
                    retrievals=retrievals,
                    uses=uses,
                    helped=helped,
                    effectiveness_pct=round(effectiveness, 1)
                ))

            return results

    def weekly_report(self) -> WeeklyReport:
        """
        Generate WEEKLY INTELLIGENCE REPORT.
        """
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            # Episodes this week
            ep_row = conn.execute("""
                SELECT
                    COUNT(*) as episodes,
                    SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes
                FROM episodes
                WHERE start_ts > strftime('%s', 'now') - 604800
            """).fetchone()

            episodes = ep_row[0] or 0
            successes = ep_row[1] or 0
            success_rate = (100.0 * successes / episodes) if episodes > 0 else 0.0

            # New distillations by type
            dist_rows = conn.execute("""
                SELECT type, COUNT(*) as count
                FROM distillations
                WHERE created_at > strftime('%s', 'now') - 604800
                GROUP BY type
            """).fetchall()

            dist_counts = {row[0]: row[1] for row in dist_rows}

            return WeeklyReport(
                episodes=episodes,
                success_rate_pct=round(success_rate, 1),
                new_heuristics=dist_counts.get('heuristic', 0),
                new_sharp_edges=dist_counts.get('sharp_edge', 0),
                new_anti_patterns=dist_counts.get('anti_pattern', 0),
                new_playbooks=dist_counts.get('playbook', 0)
            )

    def all_metrics(self) -> Dict[str, Any]:
        """Get all metrics in a single call."""
        compounding = self.compounding_rate()
        reuse = self.reuse_rate()
        effectiveness = self.memory_effectiveness()
        loops = self.loop_suppression()
        distillations = self.distillation_quality()
        weekly = self.weekly_report()

        return {
            "north_star": {
                "compounding_rate_pct": compounding.compounding_rate_pct,
                "target": 40.0,
                "status": "on_track" if compounding.compounding_rate_pct >= 40 else "below_target"
            },
            "compounding": {
                "total_episodes": compounding.total_episodes,
                "episodes_using_memory": compounding.episodes_using_memory,
                "successful_episodes": compounding.successful_episodes,
                "memory_led_to_success": compounding.memory_led_to_success,
            },
            "reuse": {
                "total_steps": reuse.total_steps,
                "steps_with_retrieval": reuse.steps_with_retrieval,
                "steps_citing_memory": reuse.steps_citing_memory,
                "reuse_rate_pct": reuse.reuse_rate_pct,
            },
            "effectiveness": {
                "with_memory": {
                    "episodes": effectiveness.with_memory_episodes,
                    "successes": effectiveness.with_memory_successes,
                    "rate_pct": effectiveness.with_memory_rate_pct,
                },
                "without_memory": {
                    "episodes": effectiveness.without_memory_episodes,
                    "successes": effectiveness.without_memory_successes,
                    "rate_pct": effectiveness.without_memory_rate_pct,
                },
                "memory_advantage_pct": round(
                    effectiveness.with_memory_rate_pct - effectiveness.without_memory_rate_pct, 1
                )
            },
            "loop_suppression": {
                "avg_retries": loops.avg_retries,
                "max_retries": loops.max_retries,
                "episodes_over_threshold": loops.episodes_over_threshold,
                "target_max": 3,
            },
            "distillation_quality": [
                {
                    "type": d.type,
                    "total": d.total,
                    "retrievals": d.retrievals,
                    "uses": d.uses,
                    "helped": d.helped,
                    "effectiveness_pct": d.effectiveness_pct,
                }
                for d in distillations
            ],
            "weekly": {
                "episodes": weekly.episodes,
                "success_rate_pct": weekly.success_rate_pct,
                "new_heuristics": weekly.new_heuristics,
                "new_sharp_edges": weekly.new_sharp_edges,
                "new_anti_patterns": weekly.new_anti_patterns,
                "new_playbooks": weekly.new_playbooks,
            }
        }


# Singleton instance
_calculator: Optional[MetricsCalculator] = None


def get_metrics_calculator(db_path: Optional[str] = None) -> MetricsCalculator:
    """Get the singleton metrics calculator."""
    global _calculator
    if _calculator is None or (db_path and _calculator.db_path != db_path):
        _calculator = MetricsCalculator(db_path)
    return _calculator

