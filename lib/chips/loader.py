"""
Chip Loader - Parse chip YAML files into usable objects.

Supports:
- Single file chips (`*.chip.yaml`)
- Multi-file chips (`<dir>/chip.yaml` + modular components)
- Hybrid chips (`*.chip.yaml` with `includes:`)
"""

import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .schema import validate_chip_spec

log = logging.getLogger("spark.chips")

# Default chips directory (relative to this package)
CHIPS_DIR = Path(__file__).parent.parent.parent / "chips"

MULTIFILE_COMPONENTS = (
    "triggers.yaml",
    "observers.yaml",
    "outcomes.yaml",
    "questions.yaml",
    "learners.yaml",
    "evolution.yaml",
    "context.yaml",
)

CHIP_ENABLED_VALUES = {"1", "true", "yes", "on"}


def chips_enabled() -> bool:
    """Return True unless explicitly disabled via env."""
    raw = os.getenv("SPARK_CHIPS_ENABLED", "").strip().lower()
    if not raw:
        return True
    return raw in CHIP_ENABLED_VALUES


@dataclass
class ChipObserver:
    """An observer that captures domain-specific data."""

    name: str
    description: str
    triggers: List[str]
    capture_required: Dict[str, str] = field(default_factory=dict)
    capture_optional: Dict[str, str] = field(default_factory=dict)
    extraction: List[Dict[str, Any]] = field(default_factory=list)
    insight_template: str = ""


@dataclass
class LoadMetrics:
    """Loading metrics for diagnostics and benchmark comparisons."""

    format_type: str = "single"
    load_time_ms: float = 0.0
    file_count: int = 0
    total_bytes: int = 0
    merge_operations: int = 0
    validation_errors: List[str] = field(default_factory=list)
    parse_success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format_type": self.format_type,
            "load_time_ms": self.load_time_ms,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "merge_operations": self.merge_operations,
            "validation_errors": list(self.validation_errors),
            "parse_success": self.parse_success,
        }


@dataclass
class Chip:
    """A loaded chip definition."""

    id: str
    name: str
    version: str
    description: str
    domains: List[str]
    triggers: List[str]  # All triggers (patterns + events + observer triggers)
    observers: List[ChipObserver]
    learners: List[Dict[str, Any]]
    outcomes_positive: List[Dict]
    outcomes_negative: List[Dict]
    outcomes_neutral: List[Dict]
    questions: List[Dict]
    trigger_patterns: List[str] = field(default_factory=list)
    trigger_events: List[str] = field(default_factory=list)
    trigger_tools: List[Dict[str, Any]] = field(default_factory=list)
    activation: str = "auto"
    load_format: str = "single"
    source_path: Optional[Path] = None
    raw_yaml: Dict[str, Any] = field(default_factory=dict)
    load_metrics: Dict[str, Any] = field(default_factory=dict)
    _compiled_pattern_triggers: Dict[str, re.Pattern] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self):
        self._compiled_pattern_triggers = {}
        for trigger in self.trigger_patterns:
            trigger_str = str(trigger or "").strip().lower()
            if not trigger_str:
                continue
            try:
                self._compiled_pattern_triggers[trigger_str] = re.compile(
                    r"(?<!\w)" + re.escape(trigger_str) + r"(?!\w)",
                    re.IGNORECASE,
                )
            except re.error:
                continue

    def _matches_trigger(self, trigger: str, content_lower: str) -> bool:
        trigger_lower = str(trigger or "").strip().lower()
        if not trigger_lower:
            return False

        pattern = self._compiled_pattern_triggers.get(trigger_lower)
        if pattern and pattern.search(content_lower):
            return True

        # Allow partial matching for longer phrases when boundary match fails.
        if len(trigger_lower) >= 4 and trigger_lower in content_lower:
            return True

        return False

    def matches_content(self, content: str) -> List[str]:
        """Check which pattern triggers match the content (exclude event triggers)."""
        content_lower = (content or "").lower()
        matched: List[str] = []
        for trigger in self.trigger_patterns:
            if self._matches_trigger(trigger, content_lower):
                matched.append(trigger)
        return matched

    def get_matching_observers(self, content: str) -> List[ChipObserver]:
        """Get observers whose triggers match the content."""
        content_lower = (content or "").lower()
        matched: List[ChipObserver] = []
        for obs in self.observers:
            for trigger in obs.triggers:
                if self._matches_trigger(trigger, content_lower):
                    matched.append(obs)
                    break
        return matched


class ChipLoader:
    """Loads chip definitions from YAML files."""

    def __init__(self, chips_dir: Path = None, preferred_format: Optional[str] = None):
        self.chips_dir = Path(chips_dir or CHIPS_DIR)
        self._cache: Dict[str, Chip] = {}
        self._metrics: Dict[str, LoadMetrics] = {}
        if preferred_format:
            preferred = preferred_format.lower()
        else:
            try:
                from lib.config_authority import resolve_section, env_str
                _cc = resolve_section("chips_runtime", env_overrides={"preferred_format": env_str("SPARK_CHIP_PREFERRED_FORMAT")}).data
                preferred = str(_cc.get("preferred_format", "multifile")).lower()
            except Exception:
                preferred = os.getenv("SPARK_CHIP_PREFERRED_FORMAT", "multifile").lower()
        self.preferred_format = preferred if preferred in {"single", "multifile", "hybrid"} else "multifile"
        self._disabled = not chips_enabled()
        self._warned_disabled = False

    def _check_enabled(self, operation: str = "chip operations") -> bool:
        """Short-circuit runtime behavior when chips are disabled by default."""
        if self._disabled:
            if not self._warned_disabled:
                log.warning(
                    "Chips runtime is disabled in Spark OSS default mode. Set SPARK_CHIPS_ENABLED=1 "
                    "to enable chip processing."
                )
                self._warned_disabled = True
            log.debug("Skipping %s because SPARK_CHIPS_ENABLED is not enabled", operation)
            return False
        return True

    def refresh_enabled_state(self) -> None:
        """Refresh cached enabled state from environment."""
        self._disabled = not chips_enabled()
        if not self._disabled:
            self._warned_disabled = False

    def get_metrics(self, chip_id: str) -> Optional[LoadMetrics]:
        """Get load metrics for a chip, if available."""
        return self._metrics.get(chip_id)

    def _format_priority(self, format_type: str) -> int:
        order = [self.preferred_format] + [
            fmt for fmt in ("single", "multifile", "hybrid") if fmt != self.preferred_format
        ]
        return len(order) - order.index(format_type) if format_type in order else 0

    def _read_yaml_with_metrics(self, path: Path, metrics: LoadMetrics) -> Any:
        content = path.read_text(encoding="utf-8")
        metrics.file_count += 1
        metrics.total_bytes += len(content.encode("utf-8"))
        return yaml.safe_load(content)

    def _deep_merge(self, base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries, with overlay taking precedence."""
        result = dict(base)
        for key, value in overlay.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            elif key in result and isinstance(result[key], list) and isinstance(value, list):
                result[key] = result[key] + value
            else:
                result[key] = value
        return result

    def _is_hybrid(self, raw: Any) -> bool:
        return isinstance(raw, dict) and "includes" in raw

    def _load_multifile(self, dir_path: Path, metrics: LoadMetrics) -> Dict[str, Any]:
        metrics.format_type = "multifile"
        chip_file = dir_path / "chip.yaml"
        if not chip_file.exists():
            raise FileNotFoundError(f"Missing chip.yaml in {dir_path}")

        raw = self._read_yaml_with_metrics(chip_file, metrics) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid chip.yaml format in {dir_path}")

        for component_name in MULTIFILE_COMPONENTS:
            component_path = dir_path / component_name
            if not component_path.exists():
                continue
            component_data = self._read_yaml_with_metrics(component_path, metrics) or {}
            if isinstance(component_data, dict):
                raw = self._deep_merge(raw, component_data)
                metrics.merge_operations += 1

        return raw

    def _load_hybrid(self, file_path: Path, raw: Dict[str, Any], metrics: LoadMetrics) -> Dict[str, Any]:
        metrics.format_type = "hybrid"
        merged = dict(raw)
        includes = merged.pop("includes", [])
        if not isinstance(includes, list):
            raise ValueError(f"Invalid includes format in {file_path}: expected list")

        for include_item in includes:
            include_path = file_path.parent / str(include_item)
            if not include_path.exists():
                metrics.validation_errors.append(f"missing include: {include_item}")
                continue
            include_data = self._read_yaml_with_metrics(include_path, metrics) or {}
            if isinstance(include_data, dict):
                merged = self._deep_merge(merged, include_data)
                metrics.merge_operations += 1

        return merged

    def _load_raw_chip_data(self, path: Path) -> Tuple[Dict[str, Any], Path, LoadMetrics]:
        start = time.perf_counter()
        metrics = LoadMetrics()
        resolved_path = Path(path)

        try:
            if resolved_path.is_dir():
                raw_data = self._load_multifile(resolved_path, metrics)
                source_path = resolved_path / "chip.yaml"
            else:
                raw_data = self._read_yaml_with_metrics(resolved_path, metrics)
                if self._is_hybrid(raw_data):
                    raw_data = self._load_hybrid(resolved_path, raw_data, metrics)
                else:
                    metrics.format_type = "single"
                source_path = resolved_path

            if not isinstance(raw_data, dict):
                raise ValueError(f"Invalid chip payload in {resolved_path}")

            metrics.parse_success = True
            return raw_data, source_path, metrics
        finally:
            metrics.load_time_ms = (time.perf_counter() - start) * 1000.0

    def load_chip(self, path: Path) -> Optional[Chip]:
        """Load a chip from supported formats (single, multifile, hybrid)."""
        self.refresh_enabled_state()
        if not self._check_enabled("load_chip"):
            return None

        path = Path(path)
        try:
            data, source_path, metrics = self._load_raw_chip_data(path)
        except Exception as e:
            log.error(f"Failed to load chip {path}: {e}")
            return None

        try:
            # Validate spec (warn-only by default)
            spec_for_validation = data if isinstance(data, dict) and "chip" in data else {"chip": data}
            errors = validate_chip_spec(spec_for_validation)
            if errors:
                try:
                    from lib.config_authority import resolve_section, env_str as _es
                    _vc = resolve_section("chips_runtime", env_overrides={"schema_validation": _es("SPARK_CHIP_SCHEMA_VALIDATION")}).data
                    validation_mode = str(_vc.get("schema_validation", "warn")).strip().lower()
                except Exception:
                    validation_mode = os.getenv("SPARK_CHIP_SCHEMA_VALIDATION", "warn").strip().lower()
                if validation_mode in ("block", "strict", "error"):
                    log.error(f"Chip spec validation failed for {source_path}: {errors}")
                    return None
                log.warning(f"Chip spec validation failed for {source_path}: {errors}")

            # Handle nested 'chip' key
            chip_data = data.get("chip", data)

            # Parse triggers from multiple sources
            trigger_patterns, trigger_events, trigger_tools = self._parse_triggers(data)

            # Parse observers
            observers = self._parse_observers(data.get("observers", []))

            # Add observer triggers to chip triggers
            observer_triggers: List[str] = []
            for obs in observers:
                observer_triggers.extend(obs.triggers)

            trigger_patterns = list(dict.fromkeys(trigger_patterns + observer_triggers))
            triggers = list(dict.fromkeys(trigger_patterns + trigger_events))

            # Parse outcomes
            outcomes = data.get("outcomes", {})
            if not isinstance(outcomes, dict):
                outcomes = {}

            default_id = chip_data.get("id")
            if not default_id:
                default_id = source_path.parent.name if source_path.name == "chip.yaml" else source_path.stem
                default_id = str(default_id).replace(".chip", "")

            chip = Chip(
                id=default_id,
                name=chip_data.get("name", chip_data.get("id", "Unknown")),
                version=chip_data.get("version", "0.1.0"),
                description=chip_data.get("description", ""),
                domains=chip_data.get("domains", []),
                activation=chip_data.get("activation", "auto"),
                triggers=triggers,
                trigger_patterns=trigger_patterns,
                trigger_events=trigger_events,
                trigger_tools=trigger_tools,
                observers=observers,
                learners=data.get("learners", []),
                outcomes_positive=outcomes.get("positive", []),
                outcomes_negative=outcomes.get("negative", []),
                outcomes_neutral=outcomes.get("neutral", []),
                questions=data.get("questions", []),
                load_format=metrics.format_type,
                source_path=source_path,
                raw_yaml=data,
                load_metrics=metrics.to_dict(),
            )

            self._cache[chip.id] = chip
            self._metrics[chip.id] = metrics
            log.info(
                "Loaded chip: %s (%s) with %d triggers, %d observers in %.2fms",
                chip.id,
                chip.load_format,
                len(triggers),
                len(observers),
                metrics.load_time_ms,
            )
            return chip
        except Exception as e:
            log.error(f"Failed to parse chip {path}: {e}")
            return None

    def _parse_triggers(self, data: Dict[str, Any]) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
        """Parse triggers from chip data."""
        patterns: List[str] = []
        events: List[str] = []
        tools: List[Dict[str, Any]] = []
        triggers_data = data.get("triggers", {})

        if isinstance(triggers_data, dict):
            patterns.extend([str(p) for p in (triggers_data.get("patterns", []) or []) if p is not None])
            events.extend([str(e) for e in (triggers_data.get("events", []) or []) if e is not None])
            raw_tools = triggers_data.get("tools", []) or []
            for tool in raw_tools:
                if isinstance(tool, dict):
                    tools.append(tool)
                elif tool:
                    tools.append({"name": str(tool), "context_contains": ["*"]})
        elif isinstance(triggers_data, list):
            patterns = [str(p) for p in triggers_data if p is not None]

        return patterns, events, tools

    def _parse_observers(self, observers_data: List[Any]) -> List[ChipObserver]:
        """Parse observer definitions."""
        observers: List[ChipObserver] = []
        for obs in observers_data or []:
            if not isinstance(obs, dict):
                continue
            capture = obs.get("capture", {})
            capture = capture if isinstance(capture, dict) else {}
            required = capture.get("required", {})
            optional = capture.get("optional", {})
            observers.append(
                ChipObserver(
                    name=str(obs.get("name", "")),
                    description=str(obs.get("description", "")),
                    triggers=[str(t) for t in (obs.get("triggers", []) or []) if t is not None],
                    capture_required=required if isinstance(required, dict) else {},
                    capture_optional=optional if isinstance(optional, dict) else {},
                    extraction=obs.get("extraction", []) or [],
                    insight_template=str(obs.get("insight_template", "") or ""),
                )
            )
        return observers

    def _discover_candidates(self) -> List[Tuple[str, Path]]:
        """Discover all chip candidate paths across supported formats."""
        candidates: List[Tuple[str, Path]] = []
        if not self.chips_dir.exists():
            return candidates

        # Single file chips in root.
        for path in sorted(self.chips_dir.glob("*.chip.yaml")):
            candidates.append(("single", path))

        # Multi-file chips: chips/multifile/<chip>/chip.yaml
        multifile_root = self.chips_dir / "multifile"
        if multifile_root.exists() and multifile_root.is_dir():
            for path in sorted(multifile_root.iterdir()):
                if path.is_dir() and (path / "chip.yaml").exists():
                    candidates.append(("multifile", path))

        # Hybrid chips: chips/hybrid/*.chip.yaml
        hybrid_root = self.chips_dir / "hybrid"
        if hybrid_root.exists() and hybrid_root.is_dir():
            for path in sorted(hybrid_root.glob("*.chip.yaml")):
                candidates.append(("hybrid", path))

        return candidates

    def discover_chips(self) -> List[Chip]:
        """Discover all chips in the chips directory."""
        self.refresh_enabled_state()
        if not self._check_enabled("discover_chips"):
            return []

        if not self.chips_dir.exists():
            log.warning(f"Chips directory not found: {self.chips_dir}")
            return []

        selected: Dict[str, Tuple[Chip, int]] = {}
        for format_type, path in self._discover_candidates():
            chip = self.load_chip(path)
            if not chip:
                continue

            priority = self._format_priority(format_type)
            existing = selected.get(chip.id)
            if existing and existing[1] > priority:
                log.info(
                    "Skipping chip variant %s (%s) in favor of higher-priority loaded format",
                    chip.id,
                    format_type,
                )
                continue
            selected[chip.id] = (chip, priority)

        chips = [entry[0] for entry in selected.values()]
        log.info("Discovered %d chips", len(chips))
        return chips

    def get_chip(self, chip_id: str) -> Optional[Chip]:
        """Get a cached chip by ID."""
        return self._cache.get(chip_id)

    def get_all_chips(self) -> List[Chip]:
        """Get all cached chips."""
        return list(self._cache.values())

    def get_active_chips(self, context: str = "", threshold: float = None) -> List[Chip]:
        """
        Get chips that are active for the given context.

        Improvement #10: Chips Auto-Activation.
        """
        self.refresh_enabled_state()
        if not self._check_enabled("get_active_chips"):
            return []

        if threshold is None:
            try:
                from ..metalearning.strategist import get_strategist

                threshold = get_strategist().strategy.auto_activate_threshold
            except Exception:
                threshold = 0.5  # Fallback

        if not self._cache:
            self.discover_chips()

        if not context:
            return [c for c in self._cache.values() if c.activation == "auto"]

        active_chips: List[Tuple[Chip, float, int]] = []
        for chip in self._cache.values():
            match_count = len(chip.matches_content(context))
            trigger_count = len(chip.trigger_patterns)
            match_score = (match_count / trigger_count) if trigger_count else 0.0
            if match_score >= threshold or match_count > 0:
                active_chips.append((chip, match_score, match_count))

        active_chips.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return [c[0] for c in active_chips]


# ============= Singleton and Convenience Functions =============

_loader: Optional[ChipLoader] = None


def get_chip_loader() -> ChipLoader:
    """Get the singleton chip loader."""
    global _loader
    if _loader is None:
        _loader = ChipLoader()
        _loader.discover_chips()
    return _loader


def get_active_chips(context: str = "", threshold: float = None) -> List[Chip]:
    """
    Get chips that are active for the given context.

    Convenience function for Improvement #10: Chips Auto-Activation.
    """
    return get_chip_loader().get_active_chips(context, threshold)
