"""
Spark Auto-Tuner: Data-Driven Source Boost Optimization

Reads advisor effectiveness data and adjusts source boosts in tuneables.json
so that high-performing sources get amplified and low-performing ones get demoted.

The auto-tuner runs periodically (default: every 24 hours) and makes bounded
adjustments (max 15% per run) to prevent wild swings.

Usage:
    from lib.auto_tuner import AutoTuner
    tuner = AutoTuner()
    report = tuner.run()
    print(report.summary)

CLI:
    python -m lib.auto_tuner [--dry-run] [--force]
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SPARK_DIR = Path.home() / ".spark"
TUNEABLES_PATH = SPARK_DIR / "tuneables.json"
EFFECTIVENESS_PATH = SPARK_DIR / "advisor" / "effectiveness.json"
COGNITIVE_INSIGHTS_PATH = SPARK_DIR / "cognitive_insights.json"
META_RALPH_PATH = SPARK_DIR / "meta_ralph.json"
EIDOS_DB_PATH = SPARK_DIR / "eidos.db"
TUNE_LOG_PATH = SPARK_DIR / "auto_tune_log.jsonl"
TUNEABLE_HISTORY_DIR = SPARK_DIR / "tuneable_history"


@dataclass
class BoostChange:
    """A single source boost adjustment."""
    source: str
    old_boost: float
    new_boost: float
    effectiveness: float
    sample_count: int
    reason: str

    @property
    def delta(self) -> float:
        return self.new_boost - self.old_boost


@dataclass
class TuningReport:
    """Result of an auto-tuner run."""
    timestamp: str
    changes: List[BoostChange]
    skipped: List[str]
    data_basis: str
    dry_run: bool = False

    @property
    def summary(self) -> str:
        lines = [f"Auto-Tuner Report ({self.timestamp})"]
        lines.append(f"Data: {self.data_basis}")
        if self.dry_run:
            lines.append("Mode: DRY RUN (no changes applied)")
        if not self.changes:
            lines.append("No changes needed — all boosts are within tolerance.")
        for c in self.changes:
            direction = "+" if c.delta > 0 else ""
            lines.append(
                f"  {c.source}: {c.old_boost:.2f} -> {c.new_boost:.2f} "
                f"({direction}{c.delta:.2f}) | {c.effectiveness:.1%} effective "
                f"({c.sample_count} samples) | {c.reason}"
            )
        if self.skipped:
            lines.append(f"Skipped (insufficient data): {', '.join(self.skipped)}")
        return "\n".join(lines)


@dataclass
class SystemHealth:
    """Comprehensive system health metrics."""
    advice_action_rate: float = 0.0
    distillation_rate: float = 0.0
    promotion_throughput: int = 0
    top_sources: List[str] = field(default_factory=list)
    weak_sources: List[str] = field(default_factory=list)
    cognitive_growth: float = 0.0
    feedback_loop_closure: float = 0.0
    total_advice_given: int = 0
    total_followed: int = 0
    total_helpful: int = 0


@dataclass
class TuneRecommendation:
    """A single tuneable adjustment recommendation."""
    section: str
    key: str
    current_value: Any
    recommended_value: Any
    reason: str
    confidence: float = 0.5
    impact: str = "medium"


def _values_equal(left: Any, right: Any) -> bool:
    """Best-effort equality for tune values with float tolerance."""
    try:
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return abs(float(left) - float(right)) < 1e-9
    except Exception:
        pass
    return left == right


def _read_json(path: Path) -> dict:
    """Read a JSON file, returning empty dict on error."""
    try:
        if path.exists():
            # Accept UTF-8 with BOM (common on Windows).
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically via temp file + replace.

    If this is the tuneables file, validates via schema (clamping out-of-bounds
    values) and records drift distance after write.
    """
    # Validate via schema before writing (soft import)
    try:
        from lib.tuneables_schema import validate_tuneables
        result = validate_tuneables(data)
        data = result.data  # Use cleaned/clamped version
    except ImportError:
        pass
    except Exception:
        pass  # Schema error should not block writes

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=4), encoding="utf-8")
    tmp.replace(path)

    # Record drift after writing tuneables
    try:
        from lib.tuneables_drift import check_drift
        check_drift()
    except ImportError:
        pass
    except Exception:
        pass


class AutoTuner:
    """Data-driven source boost optimizer for the Spark advisor."""

    # Minimum samples before a source's boost can be adjusted
    MIN_SAMPLES = 20

    # How far from the "ideal" boost a source must be before we adjust
    TOLERANCE = 0.05

    # Boost floor and ceiling
    BOOST_MIN = 0.2
    BOOST_MAX = 2.0

    def __init__(self, tuneables_path: Path = TUNEABLES_PATH) -> None:
        self.tuneables_path = tuneables_path
        self._tuneables = _read_json(tuneables_path)
        self._config = self._tuneables.get("auto_tuner", {})

    @property
    def enabled(self) -> bool:
        return self._config.get("enabled", False)

    @property
    def max_change(self) -> float:
        return self._config.get("max_change_per_run", 0.15)

    @property
    def run_interval(self) -> int:
        return self._config.get("run_interval_s", 86400)

    def should_run(self) -> bool:
        """Check if enough time has passed since last run."""
        if not self.enabled:
            return False
        last_run = self._config.get("last_run")
        if not last_run:
            return True
        try:
            last_ts = datetime.fromisoformat(last_run).timestamp()
            return (time.time() - last_ts) >= self.run_interval
        except (ValueError, TypeError):
            return True

    def get_effectiveness_data(self) -> Dict[str, Dict[str, int]]:
        """Read per-source effectiveness from the advisor."""
        data = _read_json(EFFECTIVENESS_PATH)
        return data.get("by_source", {})

    def measure_system_health(self) -> SystemHealth:
        """Read all data sources and compute comprehensive system health."""
        health = SystemHealth()

        # --- Advisor effectiveness ---
        eff = _read_json(EFFECTIVENESS_PATH)
        health.total_advice_given = int(eff.get("total_advice_given", 0))
        health.total_followed = int(eff.get("total_followed", 0))
        health.total_helpful = int(eff.get("total_helpful", 0))
        health.advice_action_rate = (
            health.total_followed / max(health.total_advice_given, 1)
        )

        by_source = eff.get("by_source", {})
        source_rates: Dict[str, float] = {}
        for src, stats in by_source.items():
            total = int(stats.get("total", 0))
            helpful = int(stats.get("helpful", 0))
            if total >= self.MIN_SAMPLES:
                source_rates[src] = helpful / total

        if source_rates:
            ranked = sorted(source_rates.items(), key=lambda x: x[1], reverse=True)
            avg_rate = sum(v for _, v in ranked) / len(ranked)
            health.top_sources = [s for s, r in ranked if r > avg_rate][:5]
            health.weak_sources = [s for s, r in ranked if r < avg_rate * 0.5][:5]

        # --- Cognitive insights ---
        try:
            cog = _read_json(COGNITIVE_INSIGHTS_PATH)
            insights = cog.get("insights", [])
            if isinstance(insights, list):
                health.cognitive_growth = float(len(insights))
                validated = sum(
                    1 for i in insights
                    if isinstance(i, dict) and i.get("times_validated", 0) > 0
                )
                if insights:
                    health.feedback_loop_closure = validated / len(insights)
        except Exception:
            pass

        # --- EIDOS distillation rate ---
        try:
            if EIDOS_DB_PATH.exists():
                import sqlite3
                conn = sqlite3.connect(str(EIDOS_DB_PATH))
                cur = conn.cursor()
                try:
                    cur.execute("SELECT COUNT(*) FROM distillations")
                    dist_count = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM episodes")
                    ep_count = cur.fetchone()[0]
                    health.distillation_rate = dist_count / max(ep_count, 1)
                except Exception:
                    pass
                finally:
                    conn.close()
        except Exception:
            pass

        # --- Meta-Ralph ---
        try:
            mr = _read_json(META_RALPH_PATH)
            promotions = mr.get("promotions", [])
            if isinstance(promotions, list):
                # Count promotions in last 24h
                cutoff = time.time() - 86400
                recent = [
                    p for p in promotions
                    if isinstance(p, dict) and p.get("ts", 0) > cutoff
                ]
                health.promotion_throughput = len(recent)
        except Exception:
            pass

        return health

    def compute_recommendations(self, health: SystemHealth) -> List[TuneRecommendation]:
        """Compute tuning recommendations based on system health."""
        recs: List[TuneRecommendation] = []
        tuneables = _read_json(self.tuneables_path)
        advisor_cfg = tuneables.get("advisor", {})
        promotion_cfg = tuneables.get("promotion", {})

        # --- Advisor: MIN_RANK_SCORE ---
        current_mrs = float(advisor_cfg.get("min_rank_score", 0.35))
        if health.advice_action_rate < 0.05 and health.total_advice_given > 50:
            recs.append(TuneRecommendation(
                section="advisor", key="min_rank_score",
                current_value=current_mrs, recommended_value=0.25,
                reason=f"Action rate {health.advice_action_rate:.1%} < 5% — lower threshold to surface more advice",
                confidence=0.7, impact="medium",
            ))
        elif health.advice_action_rate > 0.20 and health.total_advice_given > 50:
            recs.append(TuneRecommendation(
                section="advisor", key="min_rank_score",
                current_value=current_mrs, recommended_value=0.45,
                reason=f"Action rate {health.advice_action_rate:.1%} > 20% — tighten filtering",
                confidence=0.7, impact="low",
            ))

        # --- Advisor: MAX_ADVICE_ITEMS ---
        current_mai = int(advisor_cfg.get("max_advice_items", 8))
        if health.advice_action_rate < 0.05 and current_mai > 5:
            recs.append(TuneRecommendation(
                section="advisor", key="max_advice_items",
                current_value=current_mai, recommended_value=5,
                reason="Most advice ignored — reduce count for focus",
                confidence=0.6, impact="low",
            ))
        elif health.advice_action_rate > 0.15 and current_mai < 10:
            recs.append(TuneRecommendation(
                section="advisor", key="max_advice_items",
                current_value=current_mai, recommended_value=10,
                reason="User follows most advice — allow more items",
                confidence=0.6, impact="low",
            ))

        # --- Promotion tuning ---
        current_pt = float(promotion_cfg.get("threshold", 0.7))
        if health.promotion_throughput < 2:
            recs.append(TuneRecommendation(
                section="promotion", key="threshold",
                current_value=current_pt, recommended_value=max(0.5, current_pt - 0.1),
                reason=f"Only {health.promotion_throughput} promotions/day — lower threshold",
                confidence=0.6, impact="medium",
            ))
        elif health.promotion_throughput > 20:
            recs.append(TuneRecommendation(
                section="promotion", key="threshold",
                current_value=current_pt, recommended_value=min(0.9, current_pt + 0.1),
                reason=f"{health.promotion_throughput} promotions/day — raise threshold to reduce noise",
                confidence=0.6, impact="medium",
            ))

        # --- Meta-Ralph quality threshold ---
        mr_cfg = tuneables.get("meta_ralph", {})
        current_qt = int(mr_cfg.get("quality_threshold", 4))
        if health.feedback_loop_closure < 0.3 and health.cognitive_growth > 50:
            recs.append(TuneRecommendation(
                section="meta_ralph", key="quality_threshold",
                current_value=current_qt, recommended_value=min(6, current_qt + 1),
                reason=f"Low feedback closure ({health.feedback_loop_closure:.0%}) with many insights — raise quality bar",
                confidence=0.5, impact="medium",
            ))

        return recs

    def apply_recommendations(
        self,
        recs: List[TuneRecommendation],
        mode: str = "suggest",
    ) -> List[TuneRecommendation]:
        """Apply recommendations with safety constraints.

        Modes:
            suggest: Log only, don't apply.
            conservative: Apply only high-confidence (>0.8), low-impact changes.
            moderate: Apply medium+ confidence (>0.5) changes.
            aggressive: Apply all recommendations.
        """
        max_changes = int(self._config.get("max_changes_per_cycle", 3))

        if mode == "suggest":
            selected: List[TuneRecommendation] = []
        elif mode == "conservative":
            selected = [r for r in recs if r.confidence > 0.8 and r.impact == "low"]
        elif mode == "moderate":
            selected = [r for r in recs if r.confidence > 0.5]
        else:  # aggressive
            selected = list(recs)

        selected = selected[:max_changes]
        tuneables = _read_json(self.tuneables_path)
        applied: List[TuneRecommendation] = []
        for rec in selected:
            section = tuneables.setdefault(rec.section, {})
            current_value = section.get(rec.key, rec.current_value)
            if _values_equal(current_value, rec.recommended_value):
                continue
            applied.append(
                TuneRecommendation(
                    section=rec.section,
                    key=rec.key,
                    current_value=current_value,
                    recommended_value=rec.recommended_value,
                    reason=rec.reason,
                    confidence=rec.confidence,
                    impact=rec.impact,
                )
            )

        if applied:
            # Snapshot current tuneables for rollback
            try:
                TUNEABLE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                snapshot_path = TUNEABLE_HISTORY_DIR / f"tuneables_{ts}.json"
                current = dict(tuneables)
                snapshot_path.write_text(
                    json.dumps(current, indent=2), encoding="utf-8"
                )
                # Keep only last 5 snapshots
                snapshots = sorted(TUNEABLE_HISTORY_DIR.glob("tuneables_*.json"))
                for old in snapshots[:-5]:
                    try:
                        old.unlink()
                    except Exception:
                        pass
            except Exception:
                pass

            # Apply changes
            for rec in applied:
                section = tuneables.setdefault(rec.section, {})
                section[rec.key] = rec.recommended_value

            tuneables["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _write_json_atomic(self.tuneables_path, tuneables)

            # Log to auto_tune_log.jsonl
            try:
                with open(TUNE_LOG_PATH, "a", encoding="utf-8") as f:
                    for rec in applied:
                        entry = {
                            "ts": time.time(),
                            "section": rec.section,
                            "key": rec.key,
                            "old": rec.current_value,
                            "new": rec.recommended_value,
                            "reason": rec.reason,
                            "confidence": rec.confidence,
                        }
                        f.write(json.dumps(entry) + "\n")
            except Exception:
                pass

        return applied

    def compute_ideal_boost(self, effectiveness: float, global_avg: float) -> float:
        """Compute the ideal boost for a source based on its effectiveness.

        Sources above the global average get boosted, below get demoted.
        The boost scales linearly between BOOST_MIN and BOOST_MAX,
        centered at 1.0 for global-average effectiveness.
        """
        if global_avg <= 0:
            return 1.0

        # Ratio of source effectiveness to global average
        ratio = effectiveness / global_avg

        # Map ratio to boost: ratio=0 -> 0.3, ratio=1 -> 1.0, ratio=2 -> 1.7
        ideal = 0.3 + ratio * 0.7

        return max(self.BOOST_MIN, min(self.BOOST_MAX, round(ideal, 3)))

    def run(self, dry_run: bool = False, force: bool = False) -> TuningReport:
        """Execute an auto-tuning cycle.

        Args:
            dry_run: If True, compute changes but don't apply them.
            force: If True, ignore the run interval check.
        """
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if not force and not self.should_run():
            return TuningReport(
                timestamp=now, changes=[], skipped=[],
                data_basis="Skipped: interval not reached", dry_run=dry_run
            )

        # Read effectiveness data
        by_source = self.get_effectiveness_data()
        current_boosts = self._config.get("source_boosts", {})

        # Compute global average effectiveness (weighted by sample count)
        total_helpful = sum(s.get("helpful", 0) for s in by_source.values())
        total_samples = sum(s.get("total", 0) for s in by_source.values())
        global_avg = total_helpful / max(total_samples, 1)

        changes: List[BoostChange] = []
        skipped: List[str] = []
        new_effectiveness: Dict[str, float] = {}

        # All known sources (union of effectiveness data and current boosts)
        all_sources = set(by_source.keys()) | set(current_boosts.keys())

        for source in sorted(all_sources):
            stats = by_source.get(source, {})
            total = stats.get("total", 0)
            helpful = stats.get("helpful", 0)

            # Skip sources with insufficient data
            if total < self.MIN_SAMPLES:
                skipped.append(f"{source} ({total} samples)")
                continue

            effectiveness = helpful / total
            new_effectiveness[source] = effectiveness

            ideal = self.compute_ideal_boost(effectiveness, global_avg)
            current = current_boosts.get(source, 1.0)

            # Check if change is needed (beyond tolerance)
            delta = ideal - current
            if abs(delta) < self.TOLERANCE:
                continue

            # Cap the change per run
            capped_delta = max(-self.max_change, min(self.max_change, delta))
            new_boost = round(current + capped_delta, 3)
            new_boost = max(self.BOOST_MIN, min(self.BOOST_MAX, new_boost))
            if _values_equal(new_boost, current):
                continue

            # Determine reason
            if effectiveness > global_avg:
                reason = f"Above avg ({global_avg:.1%}), boosting"
            elif effectiveness < global_avg * 0.5:
                reason = f"Well below avg ({global_avg:.1%}), demoting"
            else:
                reason = f"Below avg ({global_avg:.1%}), slight demotion"

            changes.append(BoostChange(
                source=source,
                old_boost=current,
                new_boost=new_boost,
                effectiveness=effectiveness,
                sample_count=total,
                reason=reason,
            ))

        data_basis = f"{total_samples:,} advisor outcomes across {len(by_source)} sources"

        # Apply changes if not dry run
        if not dry_run:
            if changes:
                self._apply_changes(changes, new_effectiveness, now, data_basis)
            else:
                self._record_noop_run(new_effectiveness, now, data_basis)

        return TuningReport(
            timestamp=now,
            changes=changes,
            skipped=skipped,
            data_basis=data_basis,
            dry_run=dry_run,
        )

    def _apply_changes(
        self,
        changes: List[BoostChange],
        new_effectiveness: Dict[str, float],
        timestamp: str,
        data_basis: str,
    ) -> None:
        """Write boost changes to tuneables.json atomically."""
        effective_changes = [c for c in changes if not _values_equal(c.old_boost, c.new_boost)]
        if not effective_changes:
            return

        tuneables = _read_json(self.tuneables_path)
        auto_tuner = tuneables.setdefault("auto_tuner", {})

        # Update boosts
        boosts = auto_tuner.setdefault("source_boosts", {})
        for c in effective_changes:
            boosts[c.source] = c.new_boost

        # Update effectiveness snapshot
        auto_tuner["source_effectiveness"] = {
            k: round(v, 4) for k, v in new_effectiveness.items()
        }

        # Update metadata
        auto_tuner["last_run"] = timestamp

        # Append to tuning log (keep last 50 entries)
        log = auto_tuner.setdefault("tuning_log", [])
        log.append({
            "timestamp": timestamp,
            "action": "auto_tune",
            "changes": {
                c.source: f"{c.old_boost} -> {c.new_boost} ({c.effectiveness:.1%} effective, {c.sample_count} samples)"
                for c in effective_changes
            },
            "data_basis": data_basis,
        })
        if len(log) > 50:
            auto_tuner["tuning_log"] = log[-50:]

        tuneables["updated_at"] = timestamp
        _write_json_atomic(self.tuneables_path, tuneables)
        self._tuneables = tuneables
        self._config = auto_tuner

    def _record_noop_run(
        self,
        new_effectiveness: Dict[str, float],
        timestamp: str,
        data_basis: str,
    ) -> None:
        """Persist run metadata even when no boost changes are required."""
        tuneables = _read_json(self.tuneables_path)
        auto_tuner = tuneables.setdefault("auto_tuner", {})
        auto_tuner["source_effectiveness"] = {
            k: round(v, 4) for k, v in new_effectiveness.items()
        }
        auto_tuner["last_run"] = timestamp

        log = auto_tuner.setdefault("tuning_log", [])
        log.append(
            {
                "timestamp": timestamp,
                "action": "auto_tune_noop",
                "changes": {},
                "data_basis": data_basis,
            }
        )
        if len(log) > 50:
            auto_tuner["tuning_log"] = log[-50:]

        tuneables["updated_at"] = timestamp
        _write_json_atomic(self.tuneables_path, tuneables)
        self._tuneables = tuneables
        self._config = auto_tuner

    def get_status(self) -> Dict[str, Any]:
        """Get current auto-tuner status for dashboards."""
        by_source = self.get_effectiveness_data()
        current_boosts = self._config.get("source_boosts", {})

        status = {
            "enabled": self.enabled,
            "last_run": self._config.get("last_run"),
            "run_interval_s": self.run_interval,
            "max_change_per_run": self.max_change,
            "sources": {},
        }

        for source in sorted(set(by_source.keys()) | set(current_boosts.keys())):
            stats = by_source.get(source, {})
            total = stats.get("total", 0)
            helpful = stats.get("helpful", 0)
            status["sources"][source] = {
                "boost": current_boosts.get(source, 1.0),
                "effectiveness": round(helpful / max(total, 1), 4),
                "samples": total,
                "sufficient_data": total >= self.MIN_SAMPLES,
            }

        return status


# CLI entry point
if __name__ == "__main__":
    import sys

    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    tuner = AutoTuner()

    if "--status" in sys.argv:
        status = tuner.get_status()
        print(json.dumps(status, indent=2))
        sys.exit(0)

    report = tuner.run(dry_run=dry_run, force=force)
    print(report.summary)

    if not dry_run and report.changes:
        print(f"\nApplied {len(report.changes)} changes to {TUNEABLES_PATH}")
    elif dry_run and report.changes:
        print(f"\nDry run: {len(report.changes)} changes would be applied")
