"""
ChipStore: Per-chip insight and observation storage.

Each chip has its own namespace for:
- Observations (captured data)
- Insights (learned patterns)
- Predictions (future expectations)
- Outcomes (validated results)
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Default paths
SPARK_DIR = Path.home() / ".spark"
CHIP_INSIGHTS_DIR = SPARK_DIR / "chip_insights"


class ChipStore:
    """
    Storage for a single chip's data.

    Files:
    - observations.jsonl: Raw captured data
    - insights.json: Learned patterns
    - predictions.jsonl: Made predictions
    - outcomes.jsonl: Validated outcomes
    """

    def __init__(self, chip_id: str, base_dir: Optional[Path] = None):
        self.chip_id = chip_id
        self.base_dir = (base_dir or CHIP_INSIGHTS_DIR) / chip_id
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.observations_file = self.base_dir / "observations.jsonl"
        self.insights_file = self.base_dir / "insights.json"
        self.predictions_file = self.base_dir / "predictions.jsonl"
        self.outcomes_file = self.base_dir / "outcomes.jsonl"

        # In-memory cache
        self._insights: Dict[str, Any] = {}
        self._load_insights()

    def _load_insights(self):
        """Load insights from disk."""
        if self.insights_file.exists():
            try:
                with open(self.insights_file, "r", encoding="utf-8") as f:
                    self._insights = json.load(f)
            except Exception:
                self._insights = {}
        else:
            self._insights = {
                "chip_id": self.chip_id,
                "created_at": datetime.utcnow().isoformat(),
                "insights": [],
                "patterns": {},
                "correlations": {},
            }

    def _save_insights(self):
        """Save insights to disk."""
        self._insights["updated_at"] = datetime.utcnow().isoformat()
        with open(self.insights_file, "w", encoding="utf-8") as f:
            json.dump(self._insights, f, indent=2)

    # Max observation file size before rotation (5 MB per chip)
    OBS_MAX_BYTES = 5 * 1024 * 1024

    def add_observation(self, observation) -> None:
        """
        Add an observation (captured data).

        Args:
            observation: CapturedData or dict
        """
        if hasattr(observation, "__dict__"):
            data = {k: v for k, v in observation.__dict__.items() if not k.startswith("_")}
        else:
            data = observation

        data["stored_at"] = datetime.utcnow().isoformat()

        # Rotate if observations file is too large
        if self.observations_file.exists():
            try:
                if self.observations_file.stat().st_size > self.OBS_MAX_BYTES:
                    self._rotate_jsonl(self.observations_file)
            except Exception:
                pass

        with open(self.observations_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

    def _rotate_jsonl(self, path: Path) -> None:
        """Rotate a JSONL file by keeping only the last ~25% of data."""
        try:
            size = path.stat().st_size
            keep_bytes = self.OBS_MAX_BYTES // 4
            if size <= keep_bytes:
                return
            with open(path, 'rb') as f:
                f.seek(max(0, size - keep_bytes))
                f.readline()  # skip partial line
                tail = f.read()
            tmp = path.with_suffix('.jsonl.tmp')
            with open(tmp, 'wb') as f:
                f.write(tail)
            tmp.replace(path)
        except Exception:
            pass

    def get_observations(self, limit: int = 100, observer_name: Optional[str] = None) -> List[Dict]:
        """Get recent observations."""
        if not self.observations_file.exists():
            return []

        observations = []
        with open(self.observations_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obs = json.loads(line.strip())
                    if observer_name and obs.get("observer_name") != observer_name:
                        continue
                    observations.append(obs)
                except Exception:
                    pass

        # Return most recent
        return observations[-limit:]

    def add_insight(self, insight: str, category: str = "general", confidence: float = 0.7,
                    context: str = "", evidence: List[str] = None) -> Dict:
        """Add a learned insight."""
        insight_entry = {
            "id": f"{self.chip_id}_{len(self._insights.get('insights', []))}",
            "insight": insight,
            "category": category,
            "confidence": confidence,
            "context": context,
            "evidence": evidence or [],
            "created_at": datetime.utcnow().isoformat(),
            "validations": 0,
            "contradictions": 0,
        }

        if "insights" not in self._insights:
            self._insights["insights"] = []

        self._insights["insights"].append(insight_entry)
        self._save_insights()

        return insight_entry

    def get_insights(self, limit: int = 50, min_confidence: float = 0.0) -> List[Dict]:
        """Get insights above confidence threshold."""
        insights = self._insights.get("insights", [])
        filtered = [i for i in insights if i.get("confidence", 0) >= min_confidence]
        return filtered[-limit:]

    def add_pattern(self, pattern_name: str, pattern_data: Dict) -> None:
        """Add a learned pattern."""
        if "patterns" not in self._insights:
            self._insights["patterns"] = {}

        self._insights["patterns"][pattern_name] = {
            **pattern_data,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._save_insights()

    def get_pattern(self, pattern_name: str) -> Optional[Dict]:
        """Get a pattern by name."""
        return self._insights.get("patterns", {}).get(pattern_name)

    def add_correlation(self, name: str, input_fields: List[str], output_fields: List[str],
                        samples: int, correlation_data: Dict) -> None:
        """Add a learned correlation."""
        if "correlations" not in self._insights:
            self._insights["correlations"] = {}

        self._insights["correlations"][name] = {
            "input_fields": input_fields,
            "output_fields": output_fields,
            "samples": samples,
            "data": correlation_data,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._save_insights()

    def add_prediction(self, prediction: str, confidence: float, context: Dict = None) -> Dict:
        """Add a prediction."""
        pred_entry = {
            "id": f"pred_{datetime.utcnow().timestamp()}",
            "prediction": prediction,
            "confidence": confidence,
            "context": context or {},
            "created_at": datetime.utcnow().isoformat(),
            "outcome": None,
            "validated": False,
        }

        with open(self.predictions_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(pred_entry) + "\n")

        return pred_entry

    def add_outcome(self, outcome_type: str, insight: str, weight: float,
                    related_prediction_id: Optional[str] = None, data: Dict = None) -> Dict:
        """Add an outcome."""
        outcome_entry = {
            "type": outcome_type,
            "insight": insight,
            "weight": weight,
            "related_prediction_id": related_prediction_id,
            "data": data or {},
            "created_at": datetime.utcnow().isoformat(),
        }

        with open(self.outcomes_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(outcome_entry) + "\n")

        return outcome_entry

    def get_outcomes(self, limit: int = 100, outcome_type: Optional[str] = None) -> List[Dict]:
        """Get recent outcomes."""
        if not self.outcomes_file.exists():
            return []

        outcomes = []
        with open(self.outcomes_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    outcome = json.loads(line.strip())
                    if outcome_type and outcome.get("type") != outcome_type:
                        continue
                    outcomes.append(outcome)
                except Exception:
                    pass

        return outcomes[-limit:]

    def validate_insight(self, insight_id: str, positive: bool = True) -> bool:
        """Validate or contradict an insight."""
        insights = self._insights.get("insights", [])

        for insight in insights:
            if insight.get("id") == insight_id:
                if positive:
                    insight["validations"] = insight.get("validations", 0) + 1
                else:
                    insight["contradictions"] = insight.get("contradictions", 0) + 1

                # Recalculate confidence
                total = insight["validations"] + insight["contradictions"]
                if total > 0:
                    insight["confidence"] = insight["validations"] / total

                self._save_insights()
                return True

        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get store statistics."""
        obs_count = 0
        if self.observations_file.exists():
            with open(self.observations_file, "r", encoding="utf-8") as f:
                obs_count = sum(1 for _ in f)

        pred_count = 0
        if self.predictions_file.exists():
            with open(self.predictions_file, "r", encoding="utf-8") as f:
                pred_count = sum(1 for _ in f)

        outcome_count = 0
        if self.outcomes_file.exists():
            with open(self.outcomes_file, "r", encoding="utf-8") as f:
                outcome_count = sum(1 for _ in f)

        return {
            "chip_id": self.chip_id,
            "observations": obs_count,
            "insights": len(self._insights.get("insights", [])),
            "patterns": len(self._insights.get("patterns", {})),
            "correlations": len(self._insights.get("correlations", {})),
            "predictions": pred_count,
            "outcomes": outcome_count,
        }

    def clear(self) -> None:
        """Clear all data for this chip."""
        for f in [self.observations_file, self.predictions_file, self.outcomes_file]:
            if f.exists():
                f.unlink()

        self._insights = {
            "chip_id": self.chip_id,
            "created_at": datetime.utcnow().isoformat(),
            "insights": [],
            "patterns": {},
            "correlations": {},
        }
        self._save_insights()


# Cache of chip stores
_stores: Dict[str, ChipStore] = {}


def get_chip_store(chip_id: str) -> ChipStore:
    """Get or create a chip store."""
    if chip_id not in _stores:
        _stores[chip_id] = ChipStore(chip_id)
    return _stores[chip_id]
