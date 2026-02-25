"""
Meta-Ralph: The quality gate for Spark's self-evolution.

Philosophy: "Evolve, don't disable. Roast until it's good."

Core responsibilities:
1. ROAST: Question any proposed learning before storage
2. SCORE: Multi-dimensional quality scoring (not just "useful vs primitive")
3. TRACK: Follow outcomes, not just outputs
4. TEST: Adversarial testing of learning systems
5. META: Question itself periodically

Integration points:
- hooks/observe.py: Roast cognitive signals from user prompts
- lib/pattern_detection/: Roast distillations before storage
- lib/cognitive_learner.py: Roast insights before persistence

The Ralph Loop:
PROPOSE → ROAST → REFINE → TEST → VERIFY → META-ROAST → repeat
"""

import json
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re

# Tuneables — defaults overridden by ~/.spark/tuneables.json → "meta_ralph" section.
QUALITY_THRESHOLD = 4
NEEDS_WORK_THRESHOLD = 2
NEEDS_WORK_CLOSE_DELTA = 0.5
MIN_OUTCOME_SAMPLES = 5
MIN_TUNEABLE_SAMPLES = 50
MIN_NEEDS_WORK_SAMPLES = 5
MIN_SOURCE_SAMPLES = 15
ATTRIBUTION_WINDOW_S = 1200
STRICT_ATTRIBUTION_REQUIRE_TRACE = True
# Dual-gate advisory promotion/suppression tuneables.
# 1) Require weak coverage first (warm-up)
# 2) Then enforce strict quality floor when strict samples are sufficient.
INSIGHT_WARMUP_WEAK_SAMPLES = 3
INSIGHT_MIN_STRICT_SAMPLES = 2
INSIGHT_STRICT_QUALITY_FLOOR = 0.45
# If an insight has poor strict quality but no recent strict outcomes,
# allow resurfacing for periodic re-test instead of permanent suppression.
INSIGHT_SUPPRESSION_RETEST_AFTER_S = 6 * 3600
QUALITY_WINDOW_TRACE_REPEAT_CAP = 6
QUALITY_WINDOW_EXCLUDE_TRACE_PREFIXES = [
    "pipeline",
    "bench",
    "benchmark",
    "smoke",
    "test",
    "qa",
    "ci",
    "calibration",
]
QUALITY_WINDOW_EXCLUDE_TEXT_PREFIXES = [
    "scope:operation op:",
    "said it like this:",
    "another reply is:",
    "[hook_smoke_test]",
]


def _load_meta_ralph_config() -> None:
    """Load meta_ralph tuneables via config_authority resolve_section."""
    try:
        from .config_authority import resolve_section
        tuneables = Path.home() / ".spark" / "tuneables.json"
        cfg = resolve_section("meta_ralph", runtime_path=tuneables).data
        if isinstance(cfg, dict):
            reload_meta_ralph_from(cfg)
    except Exception:
        pass


def reload_meta_ralph_from(cfg: Dict[str, Any]) -> None:
    """Reload meta_ralph tuneables from a validated section dict.

    Called by tuneables_reload coordinator when meta_ralph section changes.
    """
    if not isinstance(cfg, dict):
        return
    global QUALITY_THRESHOLD, NEEDS_WORK_THRESHOLD, NEEDS_WORK_CLOSE_DELTA
    global MIN_OUTCOME_SAMPLES, MIN_TUNEABLE_SAMPLES, MIN_NEEDS_WORK_SAMPLES
    global MIN_SOURCE_SAMPLES, ATTRIBUTION_WINDOW_S, STRICT_ATTRIBUTION_REQUIRE_TRACE
    global INSIGHT_WARMUP_WEAK_SAMPLES, INSIGHT_MIN_STRICT_SAMPLES
    global INSIGHT_STRICT_QUALITY_FLOOR, INSIGHT_SUPPRESSION_RETEST_AFTER_S
    global QUALITY_WINDOW_TRACE_REPEAT_CAP
    global QUALITY_WINDOW_EXCLUDE_TRACE_PREFIXES, QUALITY_WINDOW_EXCLUDE_TEXT_PREFIXES
    if "quality_threshold" in cfg:
        QUALITY_THRESHOLD = float(cfg["quality_threshold"])
    if "needs_work_threshold" in cfg:
        NEEDS_WORK_THRESHOLD = float(cfg["needs_work_threshold"])
    if "needs_work_close_delta" in cfg:
        NEEDS_WORK_CLOSE_DELTA = float(cfg["needs_work_close_delta"])
    if "min_outcome_samples" in cfg:
        MIN_OUTCOME_SAMPLES = int(cfg["min_outcome_samples"])
    if "min_tuneable_samples" in cfg:
        MIN_TUNEABLE_SAMPLES = int(cfg["min_tuneable_samples"])
    if "min_needs_work_samples" in cfg:
        MIN_NEEDS_WORK_SAMPLES = int(cfg["min_needs_work_samples"])
    if "min_source_samples" in cfg:
        MIN_SOURCE_SAMPLES = int(cfg["min_source_samples"])
    if "attribution_window_s" in cfg:
        ATTRIBUTION_WINDOW_S = int(cfg["attribution_window_s"])
    if "strict_attribution_require_trace" in cfg:
        STRICT_ATTRIBUTION_REQUIRE_TRACE = bool(cfg["strict_attribution_require_trace"])
    if "insight_warmup_weak_samples" in cfg:
        INSIGHT_WARMUP_WEAK_SAMPLES = int(cfg["insight_warmup_weak_samples"])
    if "insight_min_strict_samples" in cfg:
        INSIGHT_MIN_STRICT_SAMPLES = int(cfg["insight_min_strict_samples"])
    if "insight_strict_quality_floor" in cfg:
        INSIGHT_STRICT_QUALITY_FLOOR = float(cfg["insight_strict_quality_floor"])
    if "insight_suppression_retest_after_s" in cfg:
        INSIGHT_SUPPRESSION_RETEST_AFTER_S = int(cfg["insight_suppression_retest_after_s"])
    if "quality_rate_trace_repeat_cap" in cfg:
        QUALITY_WINDOW_TRACE_REPEAT_CAP = max(1, int(cfg["quality_rate_trace_repeat_cap"]))
    if "quality_rate_exclude_trace_prefixes" in cfg:
        raw = cfg["quality_rate_exclude_trace_prefixes"]
        if isinstance(raw, list):
            QUALITY_WINDOW_EXCLUDE_TRACE_PREFIXES = [
                str(item).strip().lower() for item in raw if str(item).strip()
            ]
    if "quality_rate_exclude_text_prefixes" in cfg:
        raw = cfg["quality_rate_exclude_text_prefixes"]
        if isinstance(raw, list):
            QUALITY_WINDOW_EXCLUDE_TEXT_PREFIXES = [
                str(item).strip().lower() for item in raw if str(item).strip()
            ]


try:
    from .tuneables_reload import register_reload as _register_reload
    _register_reload("meta_ralph", reload_meta_ralph_from, label="meta_ralph.reload_from")
except ImportError:
    pass

_load_meta_ralph_config()


class QualityDimension(Enum):
    """Concrete scoring dimensions - not fuzzy "useful vs primitive"."""
    ACTIONABILITY = "actionability"    # Can I act on this?
    NOVELTY = "novelty"                # Is this new information?
    REASONING = "reasoning"            # Does it have a "why"?
    SPECIFICITY = "specificity"        # Is it specific or generic?
    OUTCOME_LINKED = "outcome_linked"  # Is it tied to real outcomes?


class RoastVerdict(Enum):
    """Verdict after roasting a learning."""
    QUALITY = "quality"          # Score >= 4, worth storing
    NEEDS_WORK = "needs_work"    # Score 2-3, refine before storing
    PRIMITIVE = "primitive"      # Score < 2, don't store
    DUPLICATE = "duplicate"      # Already have this


@dataclass
class QualityScore:
    """Multi-dimensional quality score for a learning."""
    actionability: int = 0      # 0-2: Can't act / Vague guidance / Specific action
    novelty: int = 0            # 0-2: Already obvious / Somewhat new / Genuine insight
    reasoning: int = 0          # 0-2: No "why" / Implied "why" / Explicit "because"
    specificity: int = 0        # 0-2: Generic / Domain-specific / Context-specific
    outcome_linked: int = 0     # 0-2: No outcome / Implied outcome / Validated outcome
    ethics: int = 1             # 0-2: Harmful/exploitative / Neutral / Positive-sum

    @property
    def total(self) -> int:
        """Total score out of 12."""
        return self.actionability + self.novelty + self.reasoning + self.specificity + self.outcome_linked + self.ethics

    @property
    def verdict(self) -> RoastVerdict:
        """Get verdict based on total score.

        Thresholds tuned 2026-02-03:
        - quality_threshold: 4 (lowered from 7 to reduce over-filtering)
        - needs_work_threshold: 2
        """
        if self.total >= QUALITY_THRESHOLD:
            return RoastVerdict.QUALITY
        elif self.total >= NEEDS_WORK_THRESHOLD:
            return RoastVerdict.NEEDS_WORK
        else:
            return RoastVerdict.PRIMITIVE

    def to_dict(self) -> Dict:
        return {
            "actionability": self.actionability,
            "novelty": self.novelty,
            "reasoning": self.reasoning,
            "specificity": self.specificity,
            "outcome_linked": self.outcome_linked,
            "ethics": self.ethics,
            "total": self.total,
            "verdict": self.verdict.value
        }


@dataclass
class RoastResult:
    """Result of roasting a proposed learning."""
    original: str
    score: QualityScore
    verdict: RoastVerdict
    roast_questions: List[str]
    issues_found: List[str]
    refinement_suggestions: List[str]
    refined_version: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "original": self.original,
            "score": self.score.to_dict(),
            "verdict": self.verdict.value,
            "roast_questions": self.roast_questions,
            "issues_found": self.issues_found,
            "refinement_suggestions": self.refinement_suggestions,
            "refined_version": self.refined_version
        }


@dataclass
class OutcomeRecord:
    """Track what happened when a learning was used."""
    learning_id: str
    learning_content: str
    retrieved_at: str
    insight_key: Optional[str] = None
    source: Optional[str] = None
    trace_id: Optional[str] = None
    acted_on: bool = False
    outcome: Optional[str] = None  # "good", "bad", "neutral"
    outcome_evidence: Optional[str] = None
    outcome_at: Optional[str] = None
    outcome_trace_id: Optional[str] = None
    # If an outcome is reported under a different trace than retrieval, keep the reported
    # value for debugging while keeping strict attribution trace-bound to retrieval.
    reported_outcome_trace_id: Optional[str] = None
    outcome_latency_s: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "learning_id": self.learning_id,
            "learning_content": self.learning_content[:100],
            "retrieved_at": self.retrieved_at,
            "insight_key": self.insight_key,
            "source": self.source,
            "trace_id": self.trace_id,
            "acted_on": self.acted_on,
            "outcome": self.outcome,
            "outcome_evidence": self.outcome_evidence,
            "outcome_at": self.outcome_at,
            "outcome_trace_id": self.outcome_trace_id,
            "reported_outcome_trace_id": self.reported_outcome_trace_id,
            "outcome_latency_s": self.outcome_latency_s,
        }


class MetaRalph:
    """
    Meta-Ralph: Quality gate for Spark's self-evolution.

    "Roast until it's good. Track outcomes, not outputs. Question everything."
    """

    # Patterns that indicate primitive/operational learning (auto-reject)
    # NOTE: All patterns are matched case-insensitively via re.IGNORECASE
    # NOTE: Overlaps with lib.noise_patterns shared patterns (Batch 6).
    #        Kept in-class for self-contained MetaRalph scoring.
    PRIMITIVE_PATTERNS = [
        r"tasks? succeed with",           # "read tasks succeed with Read"
        r"pattern using \w+\.",           # "Successful write pattern using Write"
        r"pattern found",                 # "Pattern found: X"
        r"over \d+ uses",                 # "Success rate: 100% over 1794 uses"
        r"success rate: \d+%",            # Pure stats
        r"tool sequence",                 # Tool sequences
        r"\b(?:read|edit|write|bash|glob|grep)\b\s*->\s*\b(?:read|edit|write|bash|glob|grep)\b",  # "Read -> Edit"
        r"\b\w+\s*->\s*\w+\b",             # Generic arrows
        r"generation: \d+",               # Generation counts
        r"accumulated \d+ learnings",     # Meta counts
        r"pattern distribution",          # Stats
        r"events processed",              # Processing stats
        r"for \w+ tasks,? use standard",  # "For read tasks, use standard approach"
        r"recurring \w+ errors? \(\d+x\)",  # "Recurring other errors (2x)"
        r"file modified:",                # "File modified: config.json"
        r"tool timeout",                  # Tool timeout stats
        r"validation count",              # Validation counts
    ]

    # Patterns that indicate quality learning (boost score)
    QUALITY_SIGNALS = [
        r"because",                       # Reasoning
        r"prefer[s]?",                    # Preferences
        r"when .+ then",                  # Conditional wisdom
        r"avoid",                         # Anti-patterns
        r"instead of",                    # Alternatives
        r"the reason",                    # Explanation
        r"user wants",                    # User understanding
        r"mistake",                       # Learning from errors
        r"actually",                      # Corrections
        r"remember",                      # Explicit memory requests
        r"critical",                      # Critical insight marker
        r"insight",                       # Explicit insight marker
        r"principle",                     # Design principle
        r"balance",                       # Balance decision
        r"sweet spot",                    # Optimal value found
        r"data shows",                    # Evidence-based
        r"consistently",                  # Validated pattern
        r"outperforms?",                  # Comparative evidence
        r"\d{3,}\s*(avg|likes|views)",    # Numeric engagement evidence
        r"strategy",                      # Strategic insight
    ]

    # File paths
    DATA_DIR = Path.home() / ".spark" / "meta_ralph"
    ROAST_HISTORY_FILE = DATA_DIR / "roast_history.json"
    OUTCOME_TRACKING_FILE = DATA_DIR / "outcome_tracking.json"
    LEARNINGS_STORE_FILE = DATA_DIR / "learnings_store.json"
    SELF_ROAST_FILE = DATA_DIR / "self_roast.json"

    def __init__(self, mind_client=None):
        self.mind = mind_client
        self.roast_history: List[Dict] = []
        self.outcome_records: Dict[str, OutcomeRecord] = {}
        # Track last loaded mtime so we only merge when another process updated disk.
        self._outcome_loaded_mtime: float = 0.0
        self.learnings_stored: Dict[str, Dict] = {}
        self.self_roast_results: List[Dict] = []

        # Stats
        self.total_roasted = 0
        self.quality_passed = 0
        self.primitive_rejected = 0
        self.duplicates_caught = 0
        self.refinements_made = 0

        # Deferred save support - avoids writing 3 files on every roast
        self._dirty = False
        self._defer_saves = False

        self._ensure_data_dir()
        self._load_state()

    def _ensure_data_dir(self):
        """Ensure data directory exists."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _read_json_safe(self, path: Path) -> Optional[Dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Possible concurrent write; retry once.
            time.sleep(0.05)
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
        except Exception:
            return None

    def _atomic_write_json(self, path: Path, payload: Dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _recompute_totals_from_history(self, history: List[Dict]) -> Dict[str, int]:
        totals = {
            "total_roasted": 0,
            "quality_passed": 0,
            "primitive_rejected": 0,
            "duplicates_caught": 0,
            "refinements_made": 0,
        }
        for rec in history or []:
            result = rec.get("result", {}) if isinstance(rec, dict) else {}
            verdict = result.get("verdict")
            totals["total_roasted"] += 1
            if verdict == "quality":
                totals["quality_passed"] += 1
            elif verdict == "primitive":
                totals["primitive_rejected"] += 1
            elif verdict == "duplicate":
                totals["duplicates_caught"] += 1
            if result.get("refined_version"):
                totals["refinements_made"] += 1
        return totals

    def _load_state(self):
        """Load persisted state."""
        if self.ROAST_HISTORY_FILE.exists():
            try:
                data = self._read_json_safe(self.ROAST_HISTORY_FILE) or {}
                self.roast_history = data.get("history", [])[-1000:]
                self.total_roasted = data.get("total_roasted", 0)
                self.quality_passed = data.get("quality_passed", 0)
                self.primitive_rejected = data.get("primitive_rejected", 0)
                self.duplicates_caught = data.get("duplicates_caught", 0)
                self.refinements_made = data.get("refinements_made", 0)
                if self.roast_history and self.total_roasted == 0:
                    totals = self._recompute_totals_from_history(self.roast_history)
                    self.total_roasted = totals["total_roasted"]
                    if self.quality_passed == 0:
                        self.quality_passed = totals["quality_passed"]
                    if self.primitive_rejected == 0:
                        self.primitive_rejected = totals["primitive_rejected"]
                    if self.duplicates_caught == 0:
                        self.duplicates_caught = totals["duplicates_caught"]
                    if self.refinements_made == 0:
                        self.refinements_made = totals["refinements_made"]
            except Exception:
                pass

        if self.OUTCOME_TRACKING_FILE.exists():
            try:
                data = self._read_json_safe(self.OUTCOME_TRACKING_FILE) or {}
                for rec_data in data.get("records", []):
                    rec = OutcomeRecord(**rec_data)
                    self.outcome_records[rec.learning_id] = rec
                try:
                    self._outcome_loaded_mtime = float(self.OUTCOME_TRACKING_FILE.stat().st_mtime or 0.0)
                except Exception:
                    self._outcome_loaded_mtime = 0.0
            except Exception:
                pass

        if self.LEARNINGS_STORE_FILE.exists():
            try:
                data = self._read_json_safe(self.LEARNINGS_STORE_FILE) or {}
                self.learnings_stored = data.get("learnings", {})
            except Exception:
                self.learnings_stored = {}

        # If learnings store is empty but we have roast history, rebuild a small cache.
        if not self.learnings_stored and self.roast_history:
            for roast in self.roast_history:
                result = roast.get("result", {})
                if result.get("verdict") != "quality":
                    continue
                content = result.get("refined_version") or result.get("original") or ""
                if not content:
                    continue
                h = self._hash_learning(content)
                self.learnings_stored[h] = {
                    "content": content[:200],
                    "stored_at": roast.get("timestamp"),
                    "source": roast.get("source", "unknown"),
                    "was_refined": bool(result.get("refined_version")),
                    "outcomes": {"good": 0, "bad": 0, "neutral": 0},
                }

    def begin_batch(self):
        """Start a batch operation - defer all saves until flush()."""
        self._defer_saves = True

    def end_batch(self):
        """End batch operation and flush if dirty."""
        self._defer_saves = False
        if self._dirty:
            self._save_state_now()

    def flush(self):
        """Flush any pending changes to disk."""
        if self._dirty:
            self._save_state_now()

    def _save_state(self):
        """Persist state to disk (deferred if in batch mode)."""
        if self._defer_saves:
            self._dirty = True
            return
        self._save_state_now()

    def _record_recency_ts(self, record: OutcomeRecord) -> float:
        """Best-effort monotonic timestamp for ordering/merge precedence."""
        preferred = self._parse_iso_timestamp(record.outcome_at) or self._parse_iso_timestamp(
            record.retrieved_at
        )
        if preferred is None:
            return 0.0
        try:
            return float(preferred.timestamp())
        except Exception:
            return 0.0

    def _merge_outcome_record(self, current: OutcomeRecord, incoming: OutcomeRecord) -> OutcomeRecord:
        """Merge two records for the same learning_id without mixing trace cycles."""
        cur_ts = self._record_recency_ts(current)
        inc_ts = self._record_recency_ts(incoming)
        newer, older = (incoming, current) if inc_ts >= cur_ts else (current, incoming)

        # Keep the newest cycle intact (retrieved_at/trace_id/outcome_*). Only backfill
        # metadata fields from the older record.
        learning_id = newer.learning_id or older.learning_id
        learning_content = (
            newer.learning_content
            if len(str(newer.learning_content or "")) >= len(str(older.learning_content or ""))
            else older.learning_content
        )
        return OutcomeRecord(
            learning_id=learning_id,
            learning_content=learning_content,
            retrieved_at=newer.retrieved_at or older.retrieved_at,
            insight_key=newer.insight_key or older.insight_key,
            source=newer.source or older.source,
            trace_id=newer.trace_id or older.trace_id,
            acted_on=bool(newer.acted_on),
            outcome=newer.outcome,
            outcome_evidence=newer.outcome_evidence,
            outcome_at=newer.outcome_at,
            outcome_trace_id=newer.outcome_trace_id,
            reported_outcome_trace_id=(
                newer.reported_outcome_trace_id or older.reported_outcome_trace_id
            ),
            outcome_latency_s=newer.outcome_latency_s,
        )

    def _merge_outcome_records_from_disk(self) -> None:
        """Merge current in-memory outcome records with latest on-disk snapshot."""
        if not self.OUTCOME_TRACKING_FILE.exists():
            return
        # Only merge when another process has updated the file since we last loaded/wrote it.
        try:
            disk_mtime = float(self.OUTCOME_TRACKING_FILE.stat().st_mtime or 0.0)
            if disk_mtime and disk_mtime <= float(self._outcome_loaded_mtime or 0.0):
                return
        except Exception:
            disk_mtime = None
        data = self._read_json_safe(self.OUTCOME_TRACKING_FILE) or {}
        records = data.get("records", [])
        if not isinstance(records, list):
            return
        for rec_data in records:
            try:
                disk_record = OutcomeRecord(**rec_data)
            except Exception:
                continue
            existing = self.outcome_records.get(disk_record.learning_id)
            if existing is None:
                self.outcome_records[disk_record.learning_id] = disk_record
            else:
                self.outcome_records[disk_record.learning_id] = self._merge_outcome_record(
                    existing, disk_record
                )
        try:
            if disk_mtime is not None:
                self._outcome_loaded_mtime = float(disk_mtime)
        except Exception:
            pass

    def _save_state_now(self):
        """Actually persist state to disk."""
        self._dirty = False
        history = self.roast_history[-1000:]
        # Keep in-memory and on-disk retention aligned.
        self.roast_history = history
        total_roasted = self.total_roasted
        quality_passed = self.quality_passed
        primitive_rejected = self.primitive_rejected
        duplicates_caught = self.duplicates_caught
        refinements_made = self.refinements_made

        if not history and self.ROAST_HISTORY_FILE.exists():
            try:
                data = self._read_json_safe(self.ROAST_HISTORY_FILE) or {}
                history = data.get("history", [])[-1000:] or history
                if total_roasted == 0:
                    total_roasted = data.get("total_roasted", 0)
                if quality_passed == 0:
                    quality_passed = data.get("quality_passed", 0)
                if primitive_rejected == 0:
                    primitive_rejected = data.get("primitive_rejected", 0)
                if duplicates_caught == 0:
                    duplicates_caught = data.get("duplicates_caught", 0)
                if refinements_made == 0:
                    refinements_made = data.get("refinements_made", 0)
                if total_roasted == 0 and history:
                    totals = self._recompute_totals_from_history(history)
                    total_roasted = totals["total_roasted"]
                    if quality_passed == 0:
                        quality_passed = totals["quality_passed"]
                    if primitive_rejected == 0:
                        primitive_rejected = totals["primitive_rejected"]
                    if duplicates_caught == 0:
                        duplicates_caught = totals["duplicates_caught"]
                    if refinements_made == 0:
                        refinements_made = totals["refinements_made"]
            except Exception:
                pass

        self._atomic_write_json(self.ROAST_HISTORY_FILE, {
            "history": history,
            "total_roasted": total_roasted,
            "quality_passed": quality_passed,
            "primitive_rejected": primitive_rejected,
            "duplicates_caught": duplicates_caught,
            "refinements_made": refinements_made,
            "last_updated": datetime.now().isoformat()
        })

        # Merge latest persisted records first so concurrent hook writers do not
        # drop actionable attribution samples (last-writer-wins clobbering).
        self._merge_outcome_records_from_disk()

        # Bound in-memory outcome records for long-running processes.
        if len(self.outcome_records) > 500:
            all_records = list(self.outcome_records.values())
            # Keep actionable records first so task-only advisory noise does
            # not evict real attribution history.
            actionable_acted_on = [
                r
                for r in all_records
                if r.acted_on and not self._is_non_actionable_record(r)
            ]
            actionable_pending = [
                r
                for r in all_records
                if (not r.acted_on) and not self._is_non_actionable_record(r)
            ]
            non_actionable_acted_on = [
                r
                for r in all_records
                if r.acted_on and self._is_non_actionable_record(r)
            ]
            non_actionable_pending = [
                r
                for r in all_records
                if (not r.acted_on) and self._is_non_actionable_record(r)
            ]

            for bucket in (
                actionable_acted_on,
                actionable_pending,
                non_actionable_acted_on,
                non_actionable_pending,
            ):
                bucket.sort(key=self._record_recency_ts, reverse=True)

            keep: List[OutcomeRecord] = []
            for bucket in (
                actionable_acted_on,
                actionable_pending,
                non_actionable_acted_on,
                non_actionable_pending,
            ):
                if len(keep) >= 500:
                    break
                keep.extend(bucket[: 500 - len(keep)])
            self.outcome_records = {r.learning_id: r for r in keep}

        self._atomic_write_json(self.OUTCOME_TRACKING_FILE, {
            "records": [r.to_dict() for r in list(self.outcome_records.values())[-500:]],
            "last_updated": datetime.now().isoformat()
        })
        try:
            if self.OUTCOME_TRACKING_FILE.exists():
                self._outcome_loaded_mtime = float(self.OUTCOME_TRACKING_FILE.stat().st_mtime or 0.0)
        except Exception:
            pass

        # Keep last N learnings for dedupe (oldest trimmed)
        if self.learnings_stored:
            items = list(self.learnings_stored.items())
            items.sort(key=lambda kv: kv[1].get("stored_at") or "")
            items = items[-5000:]
            self.learnings_stored = {k: v for k, v in items}

        self._atomic_write_json(self.LEARNINGS_STORE_FILE, {
            "learnings": self.learnings_stored,
            "last_updated": datetime.now().isoformat()
        })

    # =========================================================================
    # CORE: ROAST A LEARNING
    # =========================================================================

    def roast(self, learning: str, source: str = "unknown", context: Dict = None) -> RoastResult:
        """
        Roast a proposed learning before it gets stored.

        Args:
            learning: The proposed learning content
            source: Where it came from (observe_hook, pattern_detection, etc.)
            context: Additional context (signals, importance_score, etc.)

        Returns:
            RoastResult with verdict and suggestions
        """
        self.total_roasted += 1
        context = context or {}

        roast_questions = []
        issues_found = []
        refinement_suggestions = []

        # Step 1: Check for primitive patterns (auto-reject)
        if self._is_primitive(learning):
            issues_found.append("Matches primitive pattern - operational noise, not cognitive insight")
            self.primitive_rejected += 1

            result = RoastResult(
                original=learning,
                score=QualityScore(),
                verdict=RoastVerdict.PRIMITIVE,
                roast_questions=["Is this something a human would find useful?"],
                issues_found=issues_found,
                refinement_suggestions=["Extract the cognitive insight, not the operational pattern"]
            )
            self._record_roast(result, source, context)
            return result

        # Step 2: Check for duplicates
        learning_hash = self._hash_learning(learning)
        if learning_hash in self.learnings_stored:
            self.duplicates_caught += 1
            result = RoastResult(
                original=learning,
                score=QualityScore(),
                verdict=RoastVerdict.DUPLICATE,
                roast_questions=[],
                issues_found=["This learning already exists"],
                refinement_suggestions=[]
            )
            self._record_roast(result, source, context)
            return result

        # Step 3: Score on each dimension
        score = self._score_learning(learning, context)

        # Step 4: Ask roast questions based on low scores
        roast_questions, issues_found = self._generate_roast_questions(learning, score)

        # Step 5: Generate refinement suggestions
        refinement_suggestions = self._generate_refinements(learning, score, issues_found)

        # Step 6: Attempt auto-refinement if score is close
        refined_version = None
        final_score = score
        final_learning = learning

        if score.verdict == RoastVerdict.NEEDS_WORK:
            refined_version = self._attempt_refinement(learning, issues_found)
            if refined_version:
                # Re-score the refined version
                refined_score = self._score_learning(refined_version, context)
                if refined_score.verdict == RoastVerdict.QUALITY:
                    # Refinement successful - use the refined version
                    self.refinements_made += 1
                    final_score = refined_score
                    final_learning = refined_version
                    # Clear the issues since refinement fixed them
                    issues_found = [f"Refined from: {learning[:50]}..."]
                elif refined_score.total > score.total:
                    # Partial improvement - note it but keep needs_work
                    self.refinements_made += 1

        # Step 7: Update stats
        if final_score.verdict == RoastVerdict.QUALITY:
            self.quality_passed += 1
            final_hash = self._hash_learning(final_learning)
            self.learnings_stored[final_hash] = {
                "content": final_learning,
                "stored_at": datetime.now().isoformat(),
                "source": source,
                "was_refined": refined_version is not None,
                "outcomes": {"good": 0, "bad": 0, "neutral": 0},
            }

        result = RoastResult(
            original=learning,
            score=final_score,
            verdict=final_score.verdict,
            roast_questions=roast_questions,
            issues_found=issues_found,
            refinement_suggestions=refinement_suggestions,
            refined_version=refined_version if refined_version != learning else None
        )

        self._record_roast(result, source, context)
        return result

    def _is_primitive(self, learning: str) -> bool:
        """Check if learning matches primitive patterns."""
        for pattern in self.PRIMITIVE_PATTERNS:
            if re.search(pattern, learning or "", flags=re.IGNORECASE):
                return True
        return False

    def _hash_learning(self, learning: str) -> str:
        """Create semantic hash for deduplication."""
        normalized = re.sub(r'\d+', 'N', learning.lower())
        normalized = ' '.join(normalized.split())
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def _score_learning(self, learning: str, context: Dict) -> QualityScore:
        """Score a learning on each quality dimension.

        Enhanced with priority/decision boosts and importance scorer integration.
        """
        score = QualityScore()
        learning_lower = (learning or "").lower()
        project_key = context.get("project") or context.get("project_key")
        domain = context.get("domain")

        # PRIORITY BOOST: "Remember this" or explicit instructions
        # Reduced from +2 to +0.5 to prevent gaming the scoring system.
        # A "Remember this:" prefix alone should not bypass quality gates.
        priority_boost = 0
        if any(phrase in learning_lower for phrase in [
            "remember this", "remember:", "important:", "note:",
            "always remember", "don't forget", "key insight"
        ]):
            priority_boost = 0.5

        # DECISION/CORRECTION BOOST: User made a decision or correction
        decision_boost = 0
        decision_patterns = [
            r"\bdecided to\b",
            r"\bchose to\b",
            r"\bchose\b",
            r"\bwent with\b",
            r"\bswitched to\b",
            r"\bopted to\b",
            r"\bopted for\b",
            r"\binstead of\b",
            r"\brather than\b",
            r"\bcorrected me\b",
            r"\bcorrection:\b",
            r"\bactually want",
            r"\bthey want\b",
        ]
        if any(re.search(p, learning_lower) for p in decision_patterns):
            decision_boost = 1

        # Check context for importance scorer result
        importance_score = context.get("importance_score")
        is_priority = context.get("is_priority", False)
        if is_priority:
            priority_boost = max(priority_boost, 1.0)

        # ACTIONABILITY: Can I act on this?
        if any(word in learning_lower for word in ["always", "never", "use", "avoid", "prefer", "should", "must", "set", "allows", "cap"]):
            score.actionability = 2
        elif any(word in learning_lower for word in [
            "consider", "try", "might", "could", "optimal", "sweet spot", "balance",
            # Data-backed action words (present + past tense)
            "drives", "increases", "decreases", "reduces", "outperforms",
            "increased", "decreased", "reduced", "dropped", "moved",
            "eliminated", "achieved", "measured",
            # Strategy/approach patterns
            "strategy", "approach", "pattern", "technique", "prioritize",
        ]):
            score.actionability = 1
        # Numeric evidence implies actionability (e.g., "2729 avg likes")
        if score.actionability == 0 and re.search(r"\d{2,}", learning_lower):
            if any(w in learning_lower for w in ["avg", "likes", "engagement", "%", "score", "rate", "count"]):
                score.actionability = 1

        # NOVELTY: Is this new information?
        quality_matches = sum(1 for pattern in self.QUALITY_SIGNALS if re.search(pattern, learning_lower))
        # Data-backed claims with numbers are inherently novel
        has_numeric_evidence = bool(re.search(r"\d{2,}", learning_lower))
        if quality_matches >= 2 or priority_boost > 0 or (has_numeric_evidence and quality_matches >= 1):
            score.novelty = 2
        elif quality_matches >= 1 or decision_boost > 0 or has_numeric_evidence:
            score.novelty = 1

        # REASONING: Does it have a "why"?
        if any(word in learning_lower for word in ["because", "the reason", "due to", "since", "as a result"]):
            score.reasoning = 2
        elif any(phrase in learning_lower for phrase in [
            "so that", "in order to", "helps", "prevents",
            "for better", "for easier", "for safer", "for faster",
            "to avoid", "to ensure", "to prevent", "to improve",
            "which means", "which allows", "which prevents",
            # Causal/temporal reasoning
            "after", "resulted", "caused", "led to", "when",
            # Data-backed reasoning
            "data shows", "evidence", "correlates", "consistently",
        ]):
            score.reasoning = 1
        elif decision_boost > 0:
            score.reasoning = 1
        # Numeric data with comparative language implies reasoning
        elif has_numeric_evidence and any(w in learning_lower for w in ["vs", "over", "compared", "avg", "outperforms"]):
            score.reasoning = 1

        # SPECIFICITY: Is it specific or generic?
        if domain and project_key:
            score.specificity = 2
        elif domain or project_key or any(word in learning_lower for word in [
            "user", "this project", "here", "our", "my",
            "typescript", "javascript", "python", "react",
            "postgresql", "mysql", "oauth", "api",
            # Game dev terms
            "player", "health", "damage", "spawn", "enemy", "balance",
            # Architecture terms
            "queue", "worker", "bridge", "pipeline", "flow",
        ]):
            score.specificity = 1
        elif any(tok in learning_lower for tok in ["/", "\\", ".py", ".js", ".ts", ".md", ".json"]):
            score.specificity = 1

        # OUTCOME_LINKED: Is it tied to real outcomes?
        if any(word in learning_lower for word in ["worked", "failed", "resulted in", "led to", "fixed", "broke"]):
            score.outcome_linked = 2
        elif any(phrase in learning_lower for phrase in [
            "helps", "improves", "prevents", "causes",
            "better", "safer", "faster", "easier",
            "type safety", "security", "performance",
            # Past-tense outcomes
            "reduced", "dropped", "increased", "decreased",
            "improved", "eliminated", "measured", "achieved",
            # Game feel outcomes
            "feels fair", "feels good", "feels right", "punishing", "boring", "satisfying",
            # Architecture outcomes
            "persisting", "processing", "captured", "stored",
            # Engagement/metric outcomes
            "likes", "engagement", "views", "clicks", "conversion", "retention",
            "drives", "outperforms", "increases",
        ]):
            score.outcome_linked = 1
        elif context.get("has_outcome"):
            score.outcome_linked = max(score.outcome_linked, 1)
        # Numeric evidence with engagement metrics = strong outcome link
        elif has_numeric_evidence and any(w in learning_lower for w in ["avg", "rate", "%", "score"]):
            score.outcome_linked = 1

        # Apply boosts
        if priority_boost > 0:
            if score.novelty < 2:
                score.novelty = 2
            if score.specificity < 1:
                score.specificity = 1

        if decision_boost > 0:
            if score.novelty < 1:
                score.novelty = 1

        # ETHICS: Does this promote positive-sum outcomes?
        # Default is 1 (neutral). Reward positive-sum patterns, penalize harmful ones.
        from .promoter import is_unsafe_insight
        if is_unsafe_insight(learning):
            score.ethics = 0  # Harmful patterns detected
        elif any(phrase in learning_lower for phrase in [
            "guardrail", "safety", "responsible", "transparent",
            "collaborate", "positive-sum", "ethical", "fair",
            "user trust", "privacy", "consent", "inclusive",
            "help avoid", "prevent harm", "protect user",
        ]):
            score.ethics = 2  # Explicitly positive-sum

        # GARBAGE PENALTIES: Reduce scores for known garbage patterns.
        # These patterns inflate individual dimensions but aren't real learning.

        # Tool sequences: "Bash -> Edit -> verify" have action verbs but no insight
        if re.search(r"(->|-->|then run|then use|then check|execute)\s+\w+", learning_lower):
            arrow_count = learning_lower.count("->") + learning_lower.count("-->")
            if arrow_count >= 2:
                score.actionability = 0
                score.novelty = 0
        # Also catch "Used X tool to Y" patterns
        if re.search(r"\bused\s+(bash|edit|read|write|glob|grep|task)\s+(tool\s+)?(to|for)\b", learning_lower):
            score.actionability = 0
            score.novelty = 0

        # Platitudes: "Good code should be well-tested" - sounds wise but teaches nothing
        platitude_patterns = [
            r"^(good|best|proper|clean|quality)\s+(code|software|practice)",
            r"\b(best practice|industry standard|common sense|goes without saying)\b",
            r"^(it.s important|you should|one should|we should)\s+(to|always|never)\b",
            r"^(code should|testing helps|security is|architecture should|good design)\b",
            r"\b(well.?written|well.?maintained|well.?tested|well.?documented)\b",
            r"\b(is valuable|is important|should be addressed|should be managed|should be prioritized)\b",
            r"\b(feedback is|debt should|practices are|communication is|documentation is)\b",
            r"\b(horizontal scaling adds|vertical scaling adds|load balancing distributes)\b",
        ]
        if any(re.search(p, learning_lower) for p in platitude_patterns):
            if not has_numeric_evidence and not re.search(r"\b(because|due to|causes)\b", learning_lower):
                score.reasoning = 0
                score.novelty = 0
                score.specificity = 0

        # System noise: operational status, health checks, metrics dumps
        if re.search(r"\b(status|health|heartbeat|uptime|process(es)?)\s*[:=]", learning_lower):
            score.actionability = 0
            score.specificity = 0
        # Queue/bridge/pipeline telemetry
        if re.search(r"\b(queue depth|processed|bridge.?cycle|pipeline|heartbeat)\s*[:=\d]", learning_lower):
            score.actionability = 0
            score.specificity = 0

        # Cycle summaries / tool telemetry
        if learning_lower.startswith("cycle summary:") or re.search(r"\b\d+\s*times?\s*\(\d+%\s*success\)", learning_lower):
            score.actionability = 0
            score.novelty = 0
            score.reasoning = 0

        # Timing metrics: "Response time: 342ms", "latency p95: 89ms"
        if re.search(r"\b(response time|latency|elapsed|cold start|warm start|boot time)\s*[:=]\s*\d+", learning_lower):
            score.actionability = 0
            score.novelty = 0

        # Raw code without explanation (just code, no surrounding prose)
        code_indicators = learning_lower.count("(") + learning_lower.count("{") + learning_lower.count(";")
        if code_indicators >= 3 and len(learning) < 200:
            word_count = len(learning.split())
            # If more than 40% of content looks like code syntax
            if code_indicators / max(word_count, 1) > 0.3:
                score.reasoning = 0
                score.novelty = 0

        # Sophisticated garbage: circular reasoning
        # "We need X because X isn't good" pattern
        if re.search(r"\bneed\s+(\w+).{5,30}\b\1\b", learning_lower):
            if not has_numeric_evidence:
                score.reasoning = 0

        # Tautology: same 4-char fragment appears in 3+ separate words
        # "reliability...unreliable...reliable" all contain "reli"
        tautology_words = re.findall(r"[a-z]{5,}", learning_lower)
        seen_fragments: dict = {}  # fragment -> set of word indices
        for idx, w in enumerate(tautology_words):
            frag = w[:4]
            seen_fragments.setdefault(frag, set()).add(idx)
            # Also check if this word CONTAINS a previous fragment
            for prev_frag in list(seen_fragments.keys()):
                if prev_frag in w:
                    seen_fragments[prev_frag].add(idx)
        for frag, indices in seen_fragments.items():
            if len(indices) >= 3 and not has_numeric_evidence:
                score.reasoning = 0
                score.novelty = 0
                score.actionability = 0
                break

        # Broader circular reasoning: same root word appears in both halves
        # of a because/by/since split (e.g. "reliable...because...not reliable")
        def _strip_prefix(w):
            for pfx in ("un", "in", "im", "ir", "non", "dis", "re"):
                if w.startswith(pfx) and len(w) - len(pfx) >= 5:
                    return w[len(pfx):]
            return w

        for splitter in [" because ", " since ", " by ", " due to "]:
            if splitter in learning_lower:
                parts = learning_lower.split(splitter, 1)
                if len(parts) == 2:
                    left_stems = set(_strip_prefix(w)[:6] for w in parts[0].split() if len(w) >= 5)
                    right_stems = set(_strip_prefix(w)[:6] for w in parts[1].split() if len(w) >= 5)
                    shared_stems = left_stems & right_stems
                    # >= 2 shared stems is strong tautology signal
                    if len(shared_stems) >= 2 and not has_numeric_evidence:
                        score.reasoning = 0
                        score.novelty = 0
                        score.actionability = 0
                        break
                    # 1 shared stem in short text is suspicious
                    if shared_stems and len(learning) < 80 and not has_numeric_evidence:
                        score.reasoning = 0
                        score.novelty = 0
                        break

        # Sophisticated garbage: decisions without reasoning
        # "We decided to use X" with no because/why
        if re.search(r"\b(decided to|chose to|went with|selected)\b", learning_lower):
            if not re.search(r"\b(because|since|due to|reason|for|over|instead|rather|vs|compared)\b", learning_lower):
                score.reasoning = 0

        # Short reactions: "lgtm", "nice", "ok", "ship it"
        stripped = learning.strip()
        if len(stripped) < 20 and not re.search(r"\b(always|never|use|avoid)\b", learning_lower):
            score.actionability = 0
            score.novelty = 0
            score.reasoning = 0
            score.specificity = 0

        # Edge cases: empty, whitespace-only, special chars only
        if not stripped or not re.search(r"[a-zA-Z]{3,}", stripped):
            score.actionability = 0
            score.novelty = 0
            score.reasoning = 0
            score.specificity = 0
            score.outcome_linked = 0

        return score

    def _generate_roast_questions(self, learning: str, score: QualityScore) -> Tuple[List[str], List[str]]:
        """Generate roast questions based on low scores."""
        questions = []
        issues = []

        if score.actionability < 2:
            questions.append("What specific action should I take based on this?")
            if score.actionability == 0:
                issues.append("No actionable guidance")

        if score.novelty < 2:
            questions.append("Is this something I didn't already know?")
            if score.novelty == 0:
                issues.append("This seems obvious or already known")

        if score.reasoning < 2:
            questions.append("WHY is this true? What's the reasoning?")
            if score.reasoning == 0:
                issues.append("No reasoning provided")

        if score.specificity < 2:
            questions.append("When does this apply vs not apply?")
            if score.specificity == 0:
                issues.append("Too generic")

        if score.outcome_linked < 2:
            questions.append("What outcome does this lead to?")
            if score.outcome_linked == 0:
                issues.append("Not linked to any outcome")

        if score.ethics == 0:
            questions.append("Does this learning promote harmful or exploitative behavior?")
            issues.append("Contains potentially harmful patterns — blocked by safety filter")

        return questions, issues

    def _generate_refinements(self, learning: str, score: QualityScore, issues: List[str]) -> List[str]:
        """Generate suggestions for how to improve the learning."""
        suggestions = []

        if score.actionability < 2:
            suggestions.append("Add specific action: 'When X, do Y'")
        if score.reasoning < 2:
            suggestions.append("Add reasoning: '...because Z'")
        if score.specificity < 2:
            suggestions.append("Add context: 'In [domain/situation], ...'")
        if score.outcome_linked < 2:
            suggestions.append("Add outcome: '...which leads to [result]'")

        return suggestions

    def _attempt_refinement(self, learning: str, issues: List[str]) -> Optional[str]:
        """Attempt to auto-refine a learning that needs work.

        Only performs structural cleanup (whitespace, prefix dedup).
        Does NOT add fake reasoning or boilerplate — if the original
        learning lacks reasoning, it should score low honestly rather
        than get synthetic text appended.
        """
        refined = learning.strip()
        made_changes = False

        # Structural fix: collapse excessive whitespace
        import re as _re
        collapsed = _re.sub(r"\s{2,}", " ", refined)
        if collapsed != refined:
            refined = collapsed
            made_changes = True

        # Structural fix: deduplicate redundant prefixes
        #   e.g. "CRITICAL: CRITICAL: do X" → "CRITICAL: do X"
        for prefix in ("CRITICAL:", "REMEMBER:", "RULE:", "NOTE:", "INSIGHT:"):
            double = f"{prefix} {prefix}"
            if refined.upper().startswith(double.upper()):
                refined = f"{prefix} {refined[len(double):].strip()}"
                made_changes = True
                break

        return refined if made_changes else None

    def _record_roast(self, result: RoastResult, source: str, context: Optional[Dict] = None):
        """Record roast for history and learning."""
        trace_id = None
        if context and isinstance(context, dict):
            trace_id = context.get("trace_id")
        record = {
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "trace_id": trace_id,
            "result": result.to_dict()
        }
        self.roast_history.append(record)
        if len(self.roast_history) > 1000:
            self.roast_history = self.roast_history[-1000:]
        self._save_state()

    # =========================================================================
    # OUTCOME TRACKING
    # =========================================================================

    def track_retrieval(
        self,
        learning_id: str,
        learning_content: str,
        insight_key: Optional[str] = None,
        source: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        """Track when a learning is retrieved.

        Only creates a new record if one doesn't exist.
        This preserves acted_on status from previous retrievals.
        """
        if not self.roast_history and self.ROAST_HISTORY_FILE.exists():
            self._load_state()
        now_iso = datetime.now().isoformat()
        if learning_id not in self.outcome_records:
            self.outcome_records[learning_id] = OutcomeRecord(
                learning_id=learning_id,
                learning_content=learning_content,
                retrieved_at=now_iso,
                insight_key=insight_key,
                source=source,
                trace_id=trace_id,
            )
            self._save_state()
            return

        # Refresh the attribution sample on every retrieval. Advice IDs are reused across
        # sessions; keeping the first-seen trace_id causes systematic trace mismatches when
        # the same advice is delivered and scored again later.
        rec = self.outcome_records[learning_id]
        try:
            if learning_content and len(str(learning_content)) > len(str(rec.learning_content or "")):
                rec.learning_content = str(learning_content)
        except Exception:
            pass
        if insight_key and not rec.insight_key:
            rec.insight_key = insight_key
        if source and (not rec.source or rec.source == "auto_created"):
            rec.source = source

        rec.retrieved_at = now_iso
        if trace_id:
            rec.trace_id = trace_id

        # Start a fresh "attempt" for strict attribution in this window.
        rec.acted_on = False
        rec.outcome = None
        rec.outcome_evidence = None
        rec.outcome_at = None
        rec.outcome_trace_id = None
        rec.outcome_latency_s = None
        self._save_state()

    def track_outcome(
        self,
        learning_id: str,
        outcome: str,
        evidence: str = "",
        trace_id: Optional[str] = None,
        insight_key: Optional[str] = None,
        source: Optional[str] = None,
    ):
        """Track the outcome of acting on a learning.

        Args:
            learning_id: The advice ID or tool-level ID
            outcome: "good", "bad", or "neutral"
            evidence: Description of what happened
            trace_id: Trace ID for linking
            insight_key: The insight key from the advice entry (critical for
                closing the feedback loop to cognitive insight reliability)
            source: The advice source type (e.g., "cognitive", "semantic")
        """
        if not self.roast_history and self.ROAST_HISTORY_FILE.exists():
            self._load_state()
        # Create record if it doesn't exist (for tool-level outcomes)
        if learning_id not in self.outcome_records:
            effective_source = source or "unattributed"
            self.outcome_records[learning_id] = OutcomeRecord(
                learning_id=learning_id,
                learning_content=learning_id,  # Use ID as content for tool-level
                retrieved_at=datetime.now().isoformat(),
                source=effective_source,
                trace_id=trace_id,
                insight_key=insight_key,
            )

        rec = self.outcome_records[learning_id]
        if trace_id and not rec.trace_id:
            rec.trace_id = trace_id
        # Propagate insight_key if not already set (critical for feedback loop)
        if insight_key and not rec.insight_key:
            rec.insight_key = insight_key
        if source and rec.source in ("auto_created", "unattributed"):
            rec.source = source
        outcome_now = datetime.now().isoformat()
        rec.acted_on = True
        rec.outcome = outcome
        rec.outcome_evidence = evidence
        rec.outcome_at = outcome_now
        if trace_id:
            rec.outcome_trace_id = trace_id
            try:
                if rec.trace_id and str(rec.trace_id).strip() and str(trace_id).strip():
                    if str(rec.trace_id).strip() != str(trace_id).strip():
                        rec.reported_outcome_trace_id = str(trace_id).strip()
            except Exception:
                pass
        elif not rec.outcome_trace_id and rec.trace_id:
            rec.outcome_trace_id = rec.trace_id
        latency_s = self._compute_outcome_latency_s(rec)
        if latency_s is not None:
            rec.outcome_latency_s = latency_s
        self._update_learning_outcomes(rec)
        self._apply_outcome_to_cognitive(rec)
        self._save_state()

    def _normalize_outcome(self, outcome: Optional[str]) -> str:
        if not outcome:
            return "neutral"
        o = outcome.strip().lower()
        if o in ("good", "bad", "neutral"):
            return o
        return "neutral"

    @staticmethod
    def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None

    def _compute_outcome_latency_s(self, record: OutcomeRecord) -> Optional[float]:
        if record.outcome_latency_s is not None:
            try:
                cached = float(record.outcome_latency_s)
                if cached >= 0:
                    return cached
            except Exception:
                pass
        started = self._parse_iso_timestamp(record.retrieved_at)
        ended = self._parse_iso_timestamp(record.outcome_at)
        if not started or not ended:
            return None
        try:
            delta = ended.timestamp() - started.timestamp()
        except Exception:
            return None
        if delta < 0:
            return None
        return float(delta)

    def _is_trace_bound(self, record: OutcomeRecord, require_trace: bool = True) -> bool:
        retrieve_trace = (record.trace_id or "").strip()
        outcome_trace = (record.outcome_trace_id or "").strip()
        if not outcome_trace and retrieve_trace:
            outcome_trace = retrieve_trace

        if require_trace:
            return bool(retrieve_trace and outcome_trace and retrieve_trace == outcome_trace)
        if retrieve_trace and outcome_trace:
            return retrieve_trace == outcome_trace
        return bool(retrieve_trace or outcome_trace)

    def _is_strictly_attributable(
        self,
        record: OutcomeRecord,
        *,
        window_s: int,
        require_trace: bool,
    ) -> bool:
        if not record.acted_on:
            return False
        if require_trace and not self._is_trace_bound(record, require_trace=True):
            return False
        latency_s = self._compute_outcome_latency_s(record)
        if latency_s is None:
            return False
        return latency_s <= max(0, int(window_s))

    def _is_non_actionable_record(self, record: OutcomeRecord) -> bool:
        """Return True for retrieval records that should not count in acted-on rate.

        Task-orchestration cautions (`tool:task`) are surfaced as context but are
        not direct actionable advice items, so they should not dilute utilization.
        """
        insight_key = (record.insight_key or "").strip().lower()
        learning_id = (record.learning_id or "").strip().lower()
        if insight_key == "tool:task" or learning_id == "tool:task":
            return True

        # Legacy task caution pattern from self-awareness telemetry.
        content = (record.learning_content or "").strip().lower()
        if (
            (record.source or "").strip().lower() == "self_awareness"
            and content.startswith("[caution] i struggle with tool_")
            and content.endswith(" tasks")
        ):
            return True

        return False

    def _update_learning_outcomes(self, record: OutcomeRecord) -> None:
        """Update stored learning outcome stats for dedupe and tuning."""
        outcome = self._normalize_outcome(record.outcome)
        if not record.learning_content:
            return
        # Skip effectiveness stats for unattributed records — they inflate scores
        if record.source in ("unattributed", "auto_created"):
            return
        h = self._hash_learning(record.learning_content)
        entry = self.learnings_stored.get(h)
        if not entry:
            return
        outcomes = entry.setdefault("outcomes", {"good": 0, "bad": 0, "neutral": 0})
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        entry["last_outcome"] = outcome
        entry["last_outcome_at"] = datetime.now().isoformat()

    def _apply_outcome_to_cognitive(self, record: OutcomeRecord) -> None:
        """Apply outcome feedback to cognitive insights or EIDOS distillations."""
        outcome = self._normalize_outcome(record.outcome)
        if outcome not in ("good", "bad"):
            return

        # Route EIDOS outcomes to the EIDOS store (not cognitive).
        ik = (record.insight_key or "").strip()
        if ik.startswith("eidos:"):
            try:
                from lib.eidos.store import EidosStore
                store = EidosStore()
                parts = ik.split(":")
                if len(parts) >= 3:
                    id_prefix = parts[2]
                    full_id = store.find_distillation_by_prefix(id_prefix)
                    if full_id:
                        store.record_distillation_usage(
                            full_id, helped=(outcome == "good")
                        )
            except Exception:
                pass
            return

        try:
            from lib.cognitive_learner import get_cognitive_learner
            cog = get_cognitive_learner()
        except Exception:
            return

        # Prefer explicit insight key when available.
        if record.insight_key and record.insight_key in cog.insights:
            cog.apply_outcome(record.insight_key, outcome, record.outcome_evidence or "")
            return

        # Fallback: try to match by text.
        target = (record.learning_content or "").strip().lower()
        if not target:
            return
        # Remove bracketed prefixes (e.g., [Caution]).
        target = re.sub(r"^\[[^\]]+\]\s*", "", target)
        matches = []
        for key, ins in cog.insights.items():
            text = (ins.insight or "").strip().lower()
            if not text:
                continue
            if text == target:
                matches.append(key)
            elif len(target) > 30 and (target in text or text in target):
                matches.append(key)

        if len(matches) == 1:
            cog.apply_outcome(matches[0], outcome, record.outcome_evidence or "")

    def _extract_tool_name(self, record: OutcomeRecord) -> str:
        """Best-effort tool name extraction for attribution analytics."""
        learning_id = (record.learning_id or "").strip()
        if learning_id.startswith("tool:"):
            return learning_id[5:]

        evidence = (record.outcome_evidence or "").strip()
        if evidence:
            for token in evidence.split():
                if token.startswith("tool="):
                    return token.split("=", 1)[1]
        return ""

    def get_source_attribution(
        self,
        limit: int = 8,
        *,
        window_s: Optional[int] = None,
        require_trace: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Return source -> action -> outcome attribution rollups.

        Includes:
        - weak attribution: any actionable acted-on outcome,
        - strict attribution: acted-on outcomes that are trace-bound and within
          a bounded retrieval->outcome time window.
        """
        resolved_window_s = int(window_s if window_s is not None else ATTRIBUTION_WINDOW_S)
        resolved_require_trace = (
            STRICT_ATTRIBUTION_REQUIRE_TRACE if require_trace is None else bool(require_trace)
        )

        records = [r for r in self.outcome_records.values() if not self._is_non_actionable_record(r)]
        by_source: Dict[str, Dict[str, Any]] = {}
        totals = {
            "retrieved": 0,
            "acted_on": 0,
            "good": 0,
            "bad": 0,
            "unknown": 0,
            "strict_acted_on": 0,
            "strict_good": 0,
            "strict_bad": 0,
            "strict_unknown": 0,
        }

        for rec in records:
            source = (rec.source or "unknown").strip() or "unknown"
            row = by_source.setdefault(
                source,
                {
                    "source": source,
                    "retrieved": 0,
                    "acted_on": 0,
                    "good": 0,
                    "bad": 0,
                    "unknown": 0,
                    "strict_acted_on": 0,
                    "strict_good": 0,
                    "strict_bad": 0,
                    "strict_unknown": 0,
                    "_tools": {},
                    "_strict_tools": {},
                },
            )

            row["retrieved"] += 1
            totals["retrieved"] += 1

            if not rec.acted_on:
                continue

            row["acted_on"] += 1
            totals["acted_on"] += 1
            outcome = self._normalize_outcome(rec.outcome)
            if outcome == "good":
                row["good"] += 1
                totals["good"] += 1
            elif outcome == "bad":
                row["bad"] += 1
                totals["bad"] += 1
            else:
                row["unknown"] += 1
                totals["unknown"] += 1

            tool_name = self._extract_tool_name(rec)
            if tool_name:
                tool_bucket = row["_tools"].setdefault(
                    tool_name,
                    {"name": tool_name, "acted_on": 0, "good": 0, "bad": 0},
                )
                tool_bucket["acted_on"] += 1
                if outcome == "good":
                    tool_bucket["good"] += 1
                elif outcome == "bad":
                    tool_bucket["bad"] += 1

            strict_ok = self._is_strictly_attributable(
                rec,
                window_s=resolved_window_s,
                require_trace=resolved_require_trace,
            )
            if not strict_ok:
                continue

            row["strict_acted_on"] += 1
            totals["strict_acted_on"] += 1
            if outcome == "good":
                row["strict_good"] += 1
                totals["strict_good"] += 1
            elif outcome == "bad":
                row["strict_bad"] += 1
                totals["strict_bad"] += 1
            else:
                row["strict_unknown"] += 1
                totals["strict_unknown"] += 1

            if tool_name:
                strict_tool_bucket = row["_strict_tools"].setdefault(
                    tool_name,
                    {"name": tool_name, "acted_on": 0, "good": 0, "bad": 0},
                )
                strict_tool_bucket["acted_on"] += 1
                if outcome == "good":
                    strict_tool_bucket["good"] += 1
                elif outcome == "bad":
                    strict_tool_bucket["bad"] += 1

        rows: List[Dict[str, Any]] = []
        for row in by_source.values():
            explicit = int(row["good"]) + int(row["bad"])
            strict_explicit = int(row["strict_good"]) + int(row["strict_bad"])

            tool_values = list(row["_tools"].values())
            top_tool: Optional[Dict[str, Any]] = None
            if tool_values:
                tool_values.sort(key=lambda x: (x["acted_on"], x["good"]), reverse=True)
                top_tool = tool_values[0]
                top_explicit = int(top_tool["good"]) + int(top_tool["bad"])
                top_tool = {
                    **top_tool,
                    "effectiveness_rate": (
                        int(top_tool["good"]) / max(top_explicit, 1)
                        if top_explicit > 0
                        else None
                    ),
                }

            strict_tool_values = list(row["_strict_tools"].values())
            strict_top_tool: Optional[Dict[str, Any]] = None
            if strict_tool_values:
                strict_tool_values.sort(key=lambda x: (x["acted_on"], x["good"]), reverse=True)
                strict_top_tool = strict_tool_values[0]
                strict_top_explicit = int(strict_top_tool["good"]) + int(strict_top_tool["bad"])
                strict_top_tool = {
                    **strict_top_tool,
                    "effectiveness_rate": (
                        int(strict_top_tool["good"]) / max(strict_top_explicit, 1)
                        if strict_top_explicit > 0
                        else None
                    ),
                }

            rows.append(
                {
                    "source": row["source"],
                    "retrieved": int(row["retrieved"]),
                    "acted_on": int(row["acted_on"]),
                    "good": int(row["good"]),
                    "bad": int(row["bad"]),
                    "unknown": int(row["unknown"]),
                    "with_explicit_outcome": explicit,
                    "action_rate": int(row["acted_on"]) / max(int(row["retrieved"]), 1),
                    "effectiveness_rate": (
                        int(row["good"]) / max(explicit, 1) if explicit > 0 else None
                    ),
                    "strict_acted_on": int(row["strict_acted_on"]),
                    "strict_good": int(row["strict_good"]),
                    "strict_bad": int(row["strict_bad"]),
                    "strict_unknown": int(row["strict_unknown"]),
                    "strict_with_explicit_outcome": strict_explicit,
                    "strict_action_rate": int(row["strict_acted_on"]) / max(int(row["retrieved"]), 1),
                    "strict_effectiveness_rate": (
                        int(row["strict_good"]) / max(strict_explicit, 1)
                        if strict_explicit > 0
                        else None
                    ),
                    "top_tool": top_tool,
                    "strict_top_tool": strict_top_tool,
                }
            )

        rows.sort(key=lambda x: (x["strict_acted_on"], x["acted_on"], x["good"]), reverse=True)
        limited = rows[: max(int(limit), 0)]

        totals_explicit = totals["good"] + totals["bad"]
        strict_totals_explicit = totals["strict_good"] + totals["strict_bad"]
        return {
            "attribution_mode": {
                "window_s": resolved_window_s,
                "require_trace": resolved_require_trace,
            },
            "total_sources": len(rows),
            "rows": limited,
            "totals": {
                **totals,
                "with_explicit_outcome": totals_explicit,
                "action_rate": totals["acted_on"] / max(totals["retrieved"], 1),
                "effectiveness_rate": (
                    totals["good"] / max(totals_explicit, 1)
                    if totals_explicit > 0
                    else None
                ),
                "strict_with_explicit_outcome": strict_totals_explicit,
                "strict_action_rate": totals["strict_acted_on"] / max(totals["retrieved"], 1),
                "strict_effectiveness_rate": (
                    totals["strict_good"] / max(strict_totals_explicit, 1)
                    if strict_totals_explicit > 0
                    else None
                ),
            },
        }

    def get_outcome_stats(self) -> Dict:
        """Get aggregate outcome statistics."""
        records = list(self.outcome_records.values())
        actionable = [r for r in records if not self._is_non_actionable_record(r)]
        acted_on = [r for r in actionable if r.acted_on]
        acted_on_all = [r for r in records if r.acted_on]
        with_explicit = [
            r for r in acted_on if self._normalize_outcome(r.outcome) in ("good", "bad")
        ]
        unknown_outcomes = len(
            [r for r in acted_on if self._normalize_outcome(r.outcome) == "neutral"]
        )

        good_outcomes = len(
            [r for r in with_explicit if self._normalize_outcome(r.outcome) == "good"]
        )
        bad_outcomes = len(
            [r for r in with_explicit if self._normalize_outcome(r.outcome) == "bad"]
        )

        return {
            "total_tracked": len(records),
            "actionable_tracked": len(actionable),
            "ignored_non_actionable": max(0, len(records) - len(actionable)),
            "acted_on": len(acted_on),
            "acted_on_all": len(acted_on_all),
            "actionable_acted_on": len(acted_on),
            "with_outcome": len(with_explicit),
            "unknown_outcomes": unknown_outcomes,
            "good_outcomes": good_outcomes,
            "bad_outcomes": bad_outcomes,
            "effectiveness_rate": good_outcomes / max(len(with_explicit), 1)
        }

    def get_insight_effectiveness(self, insight_key: str) -> float:
        """Get effectiveness rate for a specific insight (0.0 to 1.0).

        Dual-gate policy:
        1) Warm-up on weak coverage first (acted-on + explicit outcome),
        2) Enforce strict quality floor once strict attribution samples are sufficient.

        Returns 0.5 (neutral) if no usable outcome data is available.
        Used by Advisor for outcome-based ranking.
        """
        if not insight_key:
            return 0.5

        # Weak coverage set: acted-on records with explicit good/bad outcomes.
        weak = [
            r
            for r in self.outcome_records.values()
            if r.insight_key == insight_key
            and r.acted_on
            and self._normalize_outcome(r.outcome) in ("good", "bad")
        ]
        if not weak:
            return 0.5

        weak_good = len([r for r in weak if self._normalize_outcome(r.outcome) == "good"])
        weak_total = len(weak)
        weak_rate = weak_good / max(weak_total, 1)

        warmup_min = max(1, int(INSIGHT_WARMUP_WEAK_SAMPLES))
        if weak_total < warmup_min:
            # Do not over-suppress new/low-volume advisories.
            return weak_rate

        strict = [
            r
            for r in weak
            if self._is_strictly_attributable(
                r,
                window_s=int(ATTRIBUTION_WINDOW_S),
                require_trace=bool(STRICT_ATTRIBUTION_REQUIRE_TRACE),
            )
        ]
        strict_good = len([r for r in strict if self._normalize_outcome(r.outcome) == "good"])
        strict_total = len(strict)
        strict_rate = strict_good / max(strict_total, 1) if strict_total > 0 else 0.0

        strict_min = max(1, int(INSIGHT_MIN_STRICT_SAMPLES))
        if strict_total < strict_min:
            # Coverage-first: keep advisory eligible until we have enough strict evidence.
            return weak_rate

        strict_floor = max(0.0, min(1.0, float(INSIGHT_STRICT_QUALITY_FLOOR)))
        if strict_rate < strict_floor:
            # Periodic re-test path: after a cooldown, stop hard-suppressing and let
            # weak evidence (or neutral baseline) resurface the advisory for re-evaluation.
            last_strict_at = None
            for rec in strict:
                ts = self._parse_iso_timestamp(rec.outcome_at)
                if ts and (last_strict_at is None or ts > last_strict_at):
                    last_strict_at = ts

            if last_strict_at is not None:
                age_s = max(0.0, datetime.now().timestamp() - last_strict_at.timestamp())
                if age_s >= max(0, int(INSIGHT_SUPPRESSION_RETEST_AFTER_S)):
                    return max(0.5, weak_rate)

            # Suppression path while strict evidence is fresh and below floor.
            return max(0.05, min(weak_rate, strict_rate * 0.5))

        # Promotion path: strict is primary signal, weak still contributes stability.
        return (0.35 * weak_rate) + (0.65 * strict_rate)

    # =========================================================================
    # STATS AND REPORTING
    # =========================================================================

    def get_stats(self) -> Dict:
        """Get Meta-Ralph statistics."""
        # Quality-rate gate should reflect the *current* stream of meaningful learning candidates.
        # The roast history can be polluted by synthetic pipeline tests; exclude those from the
        # quality-band metric used by production gates.
        window = self.roast_history[-1000:]
        effective = []
        filtered_pipeline_tests = 0
        filtered_duplicates = 0
        filtered_trace_prefix = 0
        filtered_trace_churn = 0
        filtered_text_artifacts = 0
        trace_kept: Dict[str, int] = {}
        for r in window:
            res = r.get("result") or {}
            verdict = (res.get("verdict") or "").strip()
            # Duplicates are a dedupe/retention artifact, not a quality signal for the stream.
            # Exclude them from the quality-band denominator to avoid false "low quality" gating.
            if verdict == "duplicate":
                filtered_duplicates += 1
                continue

            trace_id_raw = str(r.get("trace_id") or "").strip()
            trace_id = trace_id_raw.lower()
            if trace_id:
                if any(
                    trace_id.startswith(prefix)
                    for prefix in QUALITY_WINDOW_EXCLUDE_TRACE_PREFIXES
                ):
                    filtered_trace_prefix += 1
                    continue
                per_trace_cap = max(1, int(QUALITY_WINDOW_TRACE_REPEAT_CAP))
                kept_for_trace = trace_kept.get(trace_id_raw, 0)
                if kept_for_trace >= per_trace_cap:
                    filtered_trace_churn += 1
                    continue
                trace_kept[trace_id_raw] = kept_for_trace + 1

            original = res.get("original") or ""
            if isinstance(original, str) and "[PIPELINE_TEST" in original:
                filtered_pipeline_tests += 1
                continue
            original_lower = str(original).strip().lower()
            if any(
                original_lower.startswith(prefix)
                for prefix in QUALITY_WINDOW_EXCLUDE_TEXT_PREFIXES
            ):
                filtered_text_artifacts += 1
                continue
            effective.append(r)

        effective_total = len(effective)
        effective_quality = 0
        for r in effective:
            res = r.get("result") or {}
            if (res.get("verdict") or "") == "quality":
                effective_quality += 1

        quality_rate_window = effective_quality / max(effective_total, 1)
        quality_rate_all_time = self.quality_passed / max(self.total_roasted, 1)

        return {
            "total_roasted": self.total_roasted,
            "quality_passed": self.quality_passed,
            "primitive_rejected": self.primitive_rejected,
            "duplicates_caught": self.duplicates_caught,
            "refinements_made": self.refinements_made,
            "pass_rate": quality_rate_all_time,
            # Used by production loop gates: windowed, excludes synthetic pipeline test pollution.
            "quality_rate": quality_rate_window,
            "quality_rate_window_samples": effective_total,
            "quality_rate_window_filtered_pipeline_tests": filtered_pipeline_tests,
            "quality_rate_window_filtered_duplicates": filtered_duplicates,
            "quality_rate_window_filtered_trace_prefix": filtered_trace_prefix,
            "quality_rate_window_filtered_trace_churn": filtered_trace_churn,
            "quality_rate_window_filtered_text_artifacts": filtered_text_artifacts,
            "quality_rate_all_time": quality_rate_all_time,
            "reject_rate": self.primitive_rejected / max(self.total_roasted, 1),
            "outcome_stats": self.get_outcome_stats(),
            "learnings_stored": len(self.learnings_stored),
        }

    def get_recent_roasts(self, limit: int = 10) -> List[Dict]:
        """Get recent roast results."""
        return self.roast_history[-limit:]

    def get_session_summary(self, last_n: int = 50) -> Dict:
        """
        Generate end-of-session summary with suggestions.

        Call this at session end to surface:
        - What was learned (quality items)
        - What could be improved (needs_work with suggestions)
        - Patterns to watch out for (primitives seen)
        - Recommendations for next session
        """
        recent = self.roast_history[-last_n:]

        if not recent:
            return {"message": "No activity this session"}

        # Categorize
        quality = []
        needs_work_with_suggestions = []
        primitives = []

        for roast in recent:
            result = roast.get("result", {})
            verdict = result.get("verdict", "")
            original = result.get("original", "")[:100]
            suggestions = result.get("refinement_suggestions", [])
            refined = result.get("refined_version")

            if verdict == "quality":
                quality.append(original)
            elif verdict == "needs_work":
                needs_work_with_suggestions.append({
                    "learning": original,
                    "suggestions": suggestions,
                    "refined": refined
                })
            elif verdict == "primitive":
                primitives.append(original[:60])

        # Generate recommendations
        recommendations = []

        if len(needs_work_with_suggestions) > 3:
            recommendations.append(
                "Many borderline items detected. Try adding 'because...' to explain reasoning."
            )

        if len(primitives) > len(quality):
            recommendations.append(
                "More primitives than quality items. Focus on capturing 'why' not 'what'."
            )

        if not quality:
            recommendations.append(
                "No quality learnings captured. Try explicit statements like 'Remember this:' or 'I prefer X because Y'."
            )

        # Build summary
        summary = {
            "session_stats": {
                "total_roasted": len(recent),
                "quality_learned": len(quality),
                "needs_improvement": len(needs_work_with_suggestions),
                "primitives_filtered": len(primitives)
            },
            "quality_items": quality[:5],  # Top 5 learned
            "improvement_opportunities": needs_work_with_suggestions[:3],  # Top 3 to improve
            "recommendations": recommendations,
            "next_session_tips": [
                "Add reasoning with 'because' to boost quality scores",
                "Be specific about context (project, domain, technology)",
                "Use 'Remember this:' for critical insights"
            ] if not quality else []
        }

        return summary

    def print_session_summary(self) -> str:
        """Print a human-readable session summary."""
        summary = self.get_session_summary()

        lines = [
            "",
            "=" * 60,
            " META-RALPH SESSION SUMMARY",
            "=" * 60,
            "",
            f"Quality learned: {summary['session_stats']['quality_learned']}",
            f"Needs improvement: {summary['session_stats']['needs_improvement']}",
            f"Primitives filtered: {summary['session_stats']['primitives_filtered']}",
            "",
        ]

        if summary.get("quality_items"):
            lines.append("LEARNED THIS SESSION:")
            for item in summary["quality_items"]:
                lines.append(f"  + {item}...")
            lines.append("")

        if summary.get("improvement_opportunities"):
            lines.append("COULD BE IMPROVED:")
            for opp in summary["improvement_opportunities"]:
                lines.append(f"  - {opp['learning']}...")
                if opp.get("suggestions"):
                    lines.append(f"    Tip: {opp['suggestions'][0]}")
            lines.append("")

        if summary.get("recommendations"):
            lines.append("RECOMMENDATIONS:")
            for rec in summary["recommendations"]:
                lines.append(f"  > {rec}")
            lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)

    def deep_analysis(self) -> Dict:
        """
        Comprehensive analysis of Spark's learning evolution.

        Analyzes:
        - Skill domain coverage
        - Learning pattern quality
        - User resonance signals
        - Evolution trajectory
        - Improvement opportunities
        """
        analysis = {
            "timestamp": datetime.now().isoformat(),
            "skill_domains": {},
            "learning_patterns": {},
            "user_resonance": {},
            "evolution_trajectory": {},
            "improvement_opportunities": [],
            "meta_insights": []
        }

        if len(self.roast_history) < 10:
            analysis["meta_insights"].append("Need more data for deep analysis")
            return analysis

        # Skill domain detection patterns
        skill_domains = {
            "orchestration": ["workflow", "pipeline", "sequence", "parallel", "coordinate"],
            "ui_ux": ["layout", "component", "responsive", "accessibility", "design"],
            "debugging": ["error", "trace", "root cause", "hypothesis", "debug"],
            "architecture": ["pattern", "tradeoff", "scalability", "interface", "module"],
            "agent_coordination": ["agent", "handoff", "routing", "capability"],
            "team_management": ["delegation", "blocker", "review", "sprint"],
            "game_dev": ["balance", "feel", "gameplay", "physics", "player"],
            "fintech": ["compliance", "security", "transaction", "risk"],
            "product": ["user", "feature", "roadmap", "priority"],
        }

        # Learning pattern types
        pattern_types = {
            "preferences": ["prefer", "like", "want", "love", "hate"],
            "decisions": ["decided", "chose", "choosing", "went with", "switched"],
            "corrections": ["actually", "no,", "not ", "wrong", "instead"],
            "reasoning": ["because", "since", "the reason", "due to"],
            "rules": ["always", "never", "must", "should"],
            "context": ["this project", "here", "our", "my"],
        }

        # User resonance signals
        resonance_signals = {
            "explicit_memory": ["remember this", "don't forget", "important"],
            "style_preference": ["prefer", "style", "approach", "way"],
            "domain_expertise": ["experience", "learned", "found that"],
            "constraint": ["constraint", "requirement", "must have"],
        }

        # Count occurrences
        for roast in self.roast_history:
            result = roast.get("result", {})
            content = result.get("original", "").lower()
            verdict = result.get("verdict", "")

            if verdict != "quality":
                continue

            # Check skill domains
            for domain, keywords in skill_domains.items():
                if any(kw in content for kw in keywords):
                    analysis["skill_domains"][domain] = analysis["skill_domains"].get(domain, 0) + 1

            # Check learning patterns
            for pattern, keywords in pattern_types.items():
                if any(kw in content for kw in keywords):
                    analysis["learning_patterns"][pattern] = analysis["learning_patterns"].get(pattern, 0) + 1

            # Check user resonance
            for signal, keywords in resonance_signals.items():
                if any(kw in content for kw in keywords):
                    analysis["user_resonance"][signal] = analysis["user_resonance"].get(signal, 0) + 1

        # Evolution trajectory
        total_quality = sum(1 for r in self.roast_history if r.get("result", {}).get("verdict") == "quality")
        total_primitive = sum(1 for r in self.roast_history if r.get("result", {}).get("verdict") == "primitive")
        total_needs_work = sum(1 for r in self.roast_history if r.get("result", {}).get("verdict") == "needs_work")

        analysis["evolution_trajectory"] = {
            "quality_rate": total_quality / max(len(self.roast_history), 1),
            "primitive_rate": total_primitive / max(len(self.roast_history), 1),
            "needs_work_rate": total_needs_work / max(len(self.roast_history), 1),
            "trend": "improving" if self.quality_passed > self.primitive_rejected else "needs_attention"
        }

        # Generate improvement opportunities
        covered_domains = set(analysis["skill_domains"].keys())
        all_domains = set(skill_domains.keys())
        missing_domains = all_domains - covered_domains

        if missing_domains:
            analysis["improvement_opportunities"].append({
                "area": "skill_coverage",
                "issue": f"No learnings in: {', '.join(missing_domains)}",
                "suggestion": "Ask about these domains when relevant to capture expertise"
            })

        if analysis["learning_patterns"].get("reasoning", 0) < 5:
            analysis["improvement_opportunities"].append({
                "area": "reasoning_depth",
                "issue": "Few reasoned learnings (with 'because')",
                "suggestion": "Prompt for explanations: 'Why did that work?'"
            })

        if analysis["user_resonance"].get("explicit_memory", 0) < 3:
            analysis["improvement_opportunities"].append({
                "area": "user_engagement",
                "issue": "Few explicit memory requests from user",
                "suggestion": "User may not know about 'Remember this:' feature"
            })

        # Meta insights
        if analysis["evolution_trajectory"]["quality_rate"] > 0.3:
            analysis["meta_insights"].append("Good quality rate - system is capturing valuable insights")

        if len(covered_domains) >= 5:
            analysis["meta_insights"].append(f"Broad skill coverage across {len(covered_domains)} domains")

        dominant_pattern = max(analysis["learning_patterns"].items(), key=lambda x: x[1], default=("none", 0))
        if dominant_pattern[1] > 0:
            analysis["meta_insights"].append(f"Strongest learning pattern: {dominant_pattern[0]} ({dominant_pattern[1]} instances)")

        return analysis

    def print_deep_analysis(self) -> str:
        """Print human-readable deep analysis."""
        analysis = self.deep_analysis()

        lines = [
            "",
            "=" * 70,
            " META-RALPH DEEP ANALYSIS: SPARK INTELLIGENCE EVOLUTION",
            "=" * 70,
            "",
        ]

        # Skill domains
        lines.append("SKILL DOMAIN COVERAGE:")
        if analysis["skill_domains"]:
            for domain, count in sorted(analysis["skill_domains"].items(), key=lambda x: -x[1]):
                bar = "#" * min(count, 20)
                lines.append(f"  {domain:20} {bar} ({count})")
        else:
            lines.append("  No domain-specific learnings yet")
        lines.append("")

        # Learning patterns
        lines.append("LEARNING PATTERN DISTRIBUTION:")
        if analysis["learning_patterns"]:
            for pattern, count in sorted(analysis["learning_patterns"].items(), key=lambda x: -x[1]):
                bar = "#" * min(count, 20)
                lines.append(f"  {pattern:20} {bar} ({count})")
        lines.append("")

        # User resonance
        lines.append("USER RESONANCE SIGNALS:")
        if analysis["user_resonance"]:
            for signal, count in sorted(analysis["user_resonance"].items(), key=lambda x: -x[1]):
                lines.append(f"  {signal}: {count}")
        else:
            lines.append("  Limited user resonance signals detected")
        lines.append("")

        # Evolution trajectory
        traj = analysis["evolution_trajectory"]
        lines.append("EVOLUTION TRAJECTORY:")
        lines.append(f"  Quality rate: {traj.get('quality_rate', 0):.1%}")
        lines.append(f"  Trend: {traj.get('trend', 'unknown')}")
        lines.append("")

        # Improvement opportunities
        if analysis["improvement_opportunities"]:
            lines.append("IMPROVEMENT OPPORTUNITIES:")
            for opp in analysis["improvement_opportunities"]:
                lines.append(f"  [{opp['area']}]")
                lines.append(f"    Issue: {opp['issue']}")
                lines.append(f"    Action: {opp['suggestion']}")
            lines.append("")

        # Meta insights
        if analysis["meta_insights"]:
            lines.append("META INSIGHTS:")
            for insight in analysis["meta_insights"]:
                lines.append(f"  > {insight}")
            lines.append("")

        lines.append("=" * 70)

        return "\n".join(lines)

    def analyze_tuneables(self) -> Dict:
        """Analyze current learning patterns and recommend tuneable adjustments."""
        analysis = {
            "timestamp": datetime.now().isoformat(),
            "current_state": {},
            "issues_detected": [],
            "recommendations": []
        }

        if len(self.roast_history) < MIN_TUNEABLE_SAMPLES:
            analysis["issues_detected"].append(
                f"Not enough data yet - need {MIN_TUNEABLE_SAMPLES}+ roasted items"
            )
            return analysis

        # Categorize roasts
        quality_items = []
        primitive_items = []
        needs_work_items = []
        source_stats: Dict[str, Dict[str, Any]] = {}

        for roast in self.roast_history:
            result = roast.get("result", {})
            verdict = result.get("verdict", "")
            original = result.get("original", "")
            score_total = result.get("score", {}).get("total", 0)
            source = roast.get("source", "unknown")

            if source not in source_stats:
                source_stats[source] = {
                    "total": 0,
                    "quality": 0,
                    "needs_work": 0,
                    "primitive": 0,
                }
            source_stats[source]["total"] += 1

            if verdict == "quality":
                quality_items.append({"content": original, "score": score_total})
                source_stats[source]["quality"] += 1
            elif verdict == "primitive":
                primitive_items.append({"content": original, "score": score_total})
                source_stats[source]["primitive"] += 1
            elif verdict == "needs_work":
                needs_work_items.append({"content": original, "score": score_total})
                source_stats[source]["needs_work"] += 1

        total = max(len(self.roast_history), 1)
        pass_rate = len(quality_items) / total
        needs_work_rate = len(needs_work_items) / total

        for stats in source_stats.values():
            stats["pass_rate"] = stats["quality"] / max(stats["total"], 1)

        analysis["current_state"] = {
            "quality_count": len(quality_items),
            "primitive_count": len(primitive_items),
            "needs_work_count": len(needs_work_items),
            "pass_rate": pass_rate,
            "needs_work_rate": needs_work_rate,
            "quality_threshold": QUALITY_THRESHOLD,
            "needs_work_threshold": NEEDS_WORK_THRESHOLD,
            "samples": {
                "total_roasts": len(self.roast_history),
                "needs_work": len(needs_work_items),
            },
            "source_quality": source_stats,
        }

        # Analyze and recommend
        avg_needs_work: Optional[float] = None
        if len(needs_work_items) >= MIN_NEEDS_WORK_SAMPLES:
            avg_needs_work = (
                sum(i["score"] for i in needs_work_items) / max(len(needs_work_items), 1)
            )
        outcome_stats = self.get_outcome_stats()
        effectiveness = outcome_stats.get("effectiveness_rate", 0.0)
        with_outcome = outcome_stats.get("with_outcome", 0)

        # Decision tree aligned with META_RALPH.md
        if pass_rate < 0.1:
            if avg_needs_work is None:
                analysis["issues_detected"].append(
                    "Low pass rate but insufficient needs-work samples to tune thresholds"
                )
                analysis["recommendations"].append({
                    "tuneable": "quality_threshold",
                    "action": "KEEP",
                    "reason": f"Collect {MIN_NEEDS_WORK_SAMPLES}+ needs-work samples first"
                })
            elif avg_needs_work >= (QUALITY_THRESHOLD - 1):
                analysis["issues_detected"].append(
                    f"OVER-FILTERING: {pass_rate:.1%} passing, needs-work avg {avg_needs_work:.1f}"
                )
                analysis["recommendations"].append({
                    "tuneable": "quality_threshold",
                    "action": "LOWER",
                    "reason": "Valuable items being blocked"
                })
            else:
                analysis["issues_detected"].append(
                    f"LOW QUALITY INPUT: {pass_rate:.1%} passing, needs-work avg {avg_needs_work:.1f}"
                )
                analysis["recommendations"].append({
                    "tuneable": "quality_threshold",
                    "action": "KEEP",
                    "reason": "Input is genuinely low-value"
                })

        elif pass_rate > 0.8:
            if with_outcome >= MIN_OUTCOME_SAMPLES and effectiveness < 0.5:
                analysis["issues_detected"].append(
                    f"NOISE LEAK: pass_rate {pass_rate:.1%} with effectiveness {effectiveness:.0%}"
                )
                analysis["recommendations"].append({
                    "tuneable": "quality_threshold",
                    "action": "RAISE",
                    "reason": "Letting through noise"
                })
            elif with_outcome < MIN_OUTCOME_SAMPLES:
                analysis["issues_detected"].append(
                    f"INSUFFICIENT OUTCOME DATA: only {with_outcome} outcomes, need {MIN_OUTCOME_SAMPLES}+"
                )
                analysis["recommendations"].append({
                    "tuneable": "quality_threshold",
                    "action": "KEEP",
                    "reason": "Need more outcome validation"
                })

        elif needs_work_rate > 0.5:
            if avg_needs_work is None:
                analysis["issues_detected"].append(
                    "Needs-work rate high but insufficient samples to judge threshold proximity"
                )
                analysis["recommendations"].append({
                    "tuneable": "quality_threshold",
                    "action": "KEEP",
                    "reason": f"Collect {MIN_NEEDS_WORK_SAMPLES}+ needs-work samples first"
                })
            elif avg_needs_work >= (QUALITY_THRESHOLD - NEEDS_WORK_CLOSE_DELTA):
                analysis["issues_detected"].append(
                    f"BORDERLINE HEAVY: needs-work rate {needs_work_rate:.1%}, avg {avg_needs_work:.1f}"
                )
                analysis["recommendations"].append({
                    "tuneable": "quality_threshold",
                    "action": "CONSIDER_LOWERING",
                    "reason": "Borderline items are close to threshold"
                })
            else:
                analysis["issues_detected"].append(
                    f"NEEDS_WORK ITEMS LOW QUALITY: avg {avg_needs_work:.1f}"
                )
                analysis["recommendations"].append({
                    "tuneable": "quality_threshold",
                    "action": "KEEP",
                    "reason": "Items are genuinely low-value"
                })

        # Source-level quality: flag consistently low-quality sources
        for source, stats in source_stats.items():
            if stats["total"] < MIN_SOURCE_SAMPLES:
                continue
            if stats["pass_rate"] < 0.1:
                analysis["issues_detected"].append(
                    f"LOW QUALITY SOURCE: {source} pass_rate {stats['pass_rate']:.1%} over {stats['total']} items"
                )
                analysis["recommendations"].append({
                    "tuneable": "source_pipeline",
                    "action": "AUDIT",
                    "reason": f"Improve {source} signals before changing global thresholds"
                })

        return analysis


# Singleton
_meta_ralph: Optional[MetaRalph] = None

def get_meta_ralph(mind_client=None) -> MetaRalph:
    """Get the global Meta-Ralph instance."""
    global _meta_ralph
    if _meta_ralph is None:
        _meta_ralph = MetaRalph(mind_client)
    return _meta_ralph
