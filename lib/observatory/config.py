"""Observatory configuration — loads from tuneables.json."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config_authority import resolve_section

_SPARK_DIR = Path.home() / ".spark"
_BASELINE_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "tuneables.json"
_DEFAULT_VAULT = str(Path.home() / "Documents" / "Obsidian Vault" / "Spark-Intelligence-Observatory")


def _to_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _to_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    try:
        out = int(value)  # type: ignore[arg-type]
    except Exception:
        out = int(default)
    return max(int(minimum), min(int(maximum), int(out)))


@dataclass
class ObservatoryConfig:
    enabled: bool = True
    auto_sync: bool = True
    sync_cooldown_s: int = 120
    vault_dir: str = _DEFAULT_VAULT
    generate_canvas: bool = True
    max_recent_items: int = 20
    # Explorer limits (configurable per data type)
    explore_cognitive_max: int = 200
    explore_distillations_max: int = 200
    explore_episodes_max: int = 100
    explore_verdicts_max: int = 100
    explore_promotions_max: int = 200
    explore_advice_max: int = 200
    explore_routing_max: int = 100
    explore_tuning_max: int = 200
    explore_decisions_max: int = 200
    explore_feedback_max: int = 200
    # EIDOS curriculum export settings
    eidos_curriculum_enabled: bool = True
    eidos_curriculum_interval_s: int = 86400
    eidos_curriculum_max_rows: int = 300
    eidos_curriculum_max_cards: int = 120
    eidos_curriculum_include_archive: bool = True


def load_config() -> ObservatoryConfig:
    """Load observatory config via canonical config authority."""
    section = resolve_section(
        "observatory",
        baseline_path=_BASELINE_FILE,
        runtime_path=_SPARK_DIR / "tuneables.json",
    ).data
    if not isinstance(section, dict):
        return ObservatoryConfig()
    return ObservatoryConfig(
        enabled=_to_bool(section.get("enabled", True), True),
        auto_sync=_to_bool(section.get("auto_sync", True), True),
        sync_cooldown_s=_to_int(section.get("sync_cooldown_s", 120), 120, minimum=10, maximum=3600),
        vault_dir=str(section.get("vault_dir") or _DEFAULT_VAULT),
        generate_canvas=_to_bool(section.get("generate_canvas", True), True),
        max_recent_items=_to_int(section.get("max_recent_items", 20), 20, minimum=5, maximum=100),
        explore_cognitive_max=_to_int(section.get("explore_cognitive_max", 200), 200, minimum=1, maximum=5000),
        explore_distillations_max=_to_int(section.get("explore_distillations_max", 200), 200, minimum=1, maximum=5000),
        explore_episodes_max=_to_int(section.get("explore_episodes_max", 100), 100, minimum=1, maximum=2000),
        explore_verdicts_max=_to_int(section.get("explore_verdicts_max", 100), 100, minimum=1, maximum=5000),
        explore_promotions_max=_to_int(section.get("explore_promotions_max", 200), 200, minimum=1, maximum=5000),
        explore_advice_max=_to_int(section.get("explore_advice_max", 200), 200, minimum=1, maximum=5000),
        explore_routing_max=_to_int(section.get("explore_routing_max", 100), 100, minimum=1, maximum=5000),
        explore_tuning_max=_to_int(section.get("explore_tuning_max", 200), 200, minimum=1, maximum=5000),
        explore_decisions_max=_to_int(section.get("explore_decisions_max", 200), 200, minimum=1, maximum=5000),
        explore_feedback_max=_to_int(section.get("explore_feedback_max", 200), 200, minimum=1, maximum=5000),
        eidos_curriculum_enabled=_to_bool(section.get("eidos_curriculum_enabled", True), True),
        eidos_curriculum_interval_s=_to_int(section.get("eidos_curriculum_interval_s", 86400), 86400, minimum=600, maximum=604800),
        eidos_curriculum_max_rows=_to_int(section.get("eidos_curriculum_max_rows", 300), 300, minimum=20, maximum=5000),
        eidos_curriculum_max_cards=_to_int(section.get("eidos_curriculum_max_cards", 120), 120, minimum=10, maximum=1000),
        eidos_curriculum_include_archive=_to_bool(section.get("eidos_curriculum_include_archive", True), True),
    )


def spark_dir() -> Path:
    """Return the ~/.spark/ directory."""
    return _SPARK_DIR


# ---------------------------------------------------------------------------
# Hot-reload registration
# ---------------------------------------------------------------------------

def _reload_observatory_from(_cfg) -> None:
    """Hot-reload callback — config is read fresh each call, no cached state."""
    pass


try:
    from ..tuneables_reload import register_reload as _obs_register
    _obs_register("observatory", _reload_observatory_from, label="observatory.config.reload")
except Exception:
    pass
