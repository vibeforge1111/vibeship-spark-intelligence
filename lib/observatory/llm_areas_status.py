"""Generate an LLM Areas status page for Obsidian Observatory.

Shows per-area enabled/disabled status, provider, timeout, max_chars,
and host module for all 30 configurable LLM-assisted areas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def generate_llm_areas_status(data: Dict[int, Any] | None = None) -> str:
    """Generate the LLM Areas status markdown page.

    Args:
        data: Stage data dict (unused here, kept for generator signature compat).

    Returns:
        Full markdown page content.
    """
    try:
        from ..llm_area_prompts import AREA_PROMPTS
        from ..llm_dispatch import (
            ALL_AREAS,
            ARCHITECTURE_AREAS,
            LEARNING_AREAS,
            get_all_area_configs,
        )
    except Exception:
        return _fallback_page("import error: llm_dispatch or llm_area_prompts unavailable")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    configs = get_all_area_configs()

    # Compute summary stats
    total = len(ALL_AREAS)
    enabled_count = sum(1 for c in configs.values() if c.get("enabled"))
    disabled_count = total - enabled_count
    providers_used = {}
    for area_id, cfg in configs.items():
        if cfg.get("enabled"):
            p = cfg.get("provider", "minimax")
            providers_used[p] = providers_used.get(p, 0) + 1

    lines = [
        "---",
        "tags: [observatory, llm-areas, config]",
        "---",
        "# LLM Areas Status",
        "",
        f"> Auto-generated {now} by Observatory",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Total areas | **{total}** |",
        f"| Enabled | **{enabled_count}** |",
        f"| Disabled | **{disabled_count}** |",
    ]
    for prov, cnt in sorted(providers_used.items(), key=lambda x: -x[1]):
        lines.append(f"| Provider: `{prov}` | {cnt} area(s) |")
    lines.append("")

    # Provider distribution bar (visual)
    if enabled_count > 0:
        lines.append("### Provider Distribution")
        lines.append("")
        for prov, cnt in sorted(providers_used.items(), key=lambda x: -x[1]):
            bar = "#" * cnt + "." * (enabled_count - cnt)
            pct = 100.0 * cnt / enabled_count
            lines.append(f"- `{prov}`: {bar} {cnt}/{enabled_count} ({pct:.0f}%)")
        lines.append("")

    # Host module mapping
    host_modules = {
        "archive_rewrite": "lib/distillation_refiner.py",
        "archive_rescue": "lib/distillation_refiner.py",
        "system28_reformulate": "lib/distillation_transformer.py",
        "conflict_resolve": "lib/cognitive_learner.py",
        "evidence_compress": "lib/cognitive_learner.py",
        "novelty_score": "lib/memory_capture.py",
        "missed_signal_detect": "lib/memory_capture.py",
        "retrieval_rewrite": "lib/advisor.py",
        "retrieval_explain": "lib/advisor.py",
        "generic_demotion": "lib/cognitive_learner.py",
        "meta_ralph_remediate": "lib/meta_ralph.py",
        "actionability_boost": "lib/distillation_transformer.py",
        "specificity_augment": "lib/distillation_transformer.py",
        "reasoning_patch": "lib/distillation_transformer.py",
        "unsuppression_score": "lib/meta_ralph.py",
        "soft_promotion_triage": "lib/promoter.py",
        "outcome_link_reconstruct": "lib/eidos/distillation_engine.py",
        "implicit_feedback_interpret": "lib/advisory_engine.py",
        "curriculum_gap_summarize": "lib/eidos_distillation_curriculum.py",
        "policy_autotuner_recommend": "lib/auto_tuner.py",
        "suppression_triage": "lib/advisory_engine.py",
        "dedupe_optimize": "lib/advisory_engine.py",
        "packet_rerank": "lib/advisory_packet_store.py",
        "operator_now_synth": "lib/observatory/__init__.py",
        "drift_diagnose": "scripts/cross_surface_drift_checker.py",
        "dead_widget_plan": "lib/observatory/stage_pages.py",
        "error_translate": "lib/error_translator.py",
        "config_advise": "lib/observatory/tuneables_deep_dive.py",
        "canary_decide": "lib/canary_assistant.py",
        "canvas_enrich": "lib/observatory/__init__.py",
    }

    # Learning System Areas table
    lines.append("## Learning System Areas (20)")
    lines.append("")
    lines.append("| # | Area ID | Status | Provider | Timeout | Max Chars | Host Module |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for i, area_id in enumerate(LEARNING_AREAS, 1):
        cfg = configs.get(area_id, {})
        status = "ON" if cfg.get("enabled") else "OFF"
        provider = cfg.get("provider", "minimax")
        timeout = cfg.get("timeout_s", 6.0)
        max_chars = cfg.get("max_chars", 300)
        host = host_modules.get(area_id, "?")
        lines.append(
            f"| {i} | `{area_id}` | {status} | `{provider}` | {timeout}s | {max_chars} | `{host}` |"
        )
    lines.append("")

    # Architecture Areas table
    lines.append("## Architecture Areas (10)")
    lines.append("")
    lines.append("| # | Area ID | Status | Provider | Timeout | Max Chars | Host Module |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for i, area_id in enumerate(ARCHITECTURE_AREAS, 1):
        cfg = configs.get(area_id, {})
        status = "ON" if cfg.get("enabled") else "OFF"
        provider = cfg.get("provider", "minimax")
        timeout = cfg.get("timeout_s", 6.0)
        max_chars = cfg.get("max_chars", 300)
        host = host_modules.get(area_id, "?")
        lines.append(
            f"| {i} | `{area_id}` | {status} | `{provider}` | `{timeout}s` | {max_chars} | `{host}` |"
        )
    lines.append("")

    # Quick-enable guide
    lines.append("## Configuration")
    lines.append("")
    lines.append("All areas are configured in `~/.spark/tuneables.json` under the `llm_areas` section.")
    lines.append("")
    lines.append("### Enable a single area")
    lines.append("```json")
    lines.append('{')
    lines.append('  "llm_areas": {')
    lines.append('    "archive_rewrite_enabled": true,')
    lines.append('    "archive_rewrite_provider": "minimax"')
    lines.append('  }')
    lines.append('}')
    lines.append("```")
    lines.append("")
    lines.append("### Enable all areas at once (via CLI)")
    lines.append("```python")
    lines.append("from lib.intelligence_llm_preferences import apply_runtime_llm_preferences")
    lines.append('apply_runtime_llm_preferences(llm_areas_enable=True, provider="minimax")')
    lines.append("```")
    lines.append("")

    # Prompt previews section
    lines.append("## Prompt Previews")
    lines.append("")
    lines.append("Each area has a system prompt and template. Below are the system prompts:")
    lines.append("")
    for area_id in ALL_AREAS:
        prompts = AREA_PROMPTS.get(area_id, {})
        sys_prompt = prompts.get("system", "(none)")
        if len(sys_prompt) > 120:
            sys_prompt = sys_prompt[:117] + "..."
        lines.append(f"- **`{area_id}`**: {sys_prompt}")
    lines.append("")

    # Config keys reference
    lines.append("## Config Keys Reference")
    lines.append("")
    lines.append("Each area has 4 config keys in the `llm_areas` tuneable section:")
    lines.append("")
    lines.append("| Key Pattern | Type | Default | Description |")
    lines.append("| --- | --- | --- | --- |")
    lines.append("| `{area_id}_enabled` | bool | `false` | Enable/disable this LLM area |")
    lines.append("| `{area_id}_provider` | string | `minimax` | LLM provider to use |")
    lines.append("| `{area_id}_timeout_s` | float | varies | Max wait for LLM response |")
    lines.append("| `{area_id}_max_chars` | int | varies | Max chars in LLM response |")
    lines.append("")
    lines.append("Valid providers: `auto`, `minimax`, `ollama`, `gemini`, `openai`, `anthropic`, `claude`")
    lines.append("")

    # Links
    lines.append("---")
    lines.append("")
    lines.append("[[flow|← Flow Dashboard]] · [[tuneables_deep_dive|Tuneables Deep Dive]] · [[advisory_reverse_engineering|Advisory Analysis]]")
    lines.append("")

    return "\n".join(lines)


def _fallback_page(reason: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    return (
        "---\ntags: [observatory, llm-areas]\n---\n"
        f"# LLM Areas Status\n\n"
        f"> Generated {now}\n\n"
        f"WARNING: Could not generate status page: {reason}\n"
    )
