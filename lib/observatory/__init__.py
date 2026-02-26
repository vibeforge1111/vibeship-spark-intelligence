"""Spark Intelligence Observatory — full pipeline visualization for Obsidian.

Public API:
    generate_observatory(force=False) — generate all observatory pages
    maybe_sync_observatory(stats=None) — cooldown-gated auto-sync (call from bridge_cycle)
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any

from .config import load_config

_last_sync_ts: float = 0.0


def _llm_area_operator_now_synth(data: dict) -> str:
    """LLM area: synthesize operator-facing system state summary.

    When disabled (default), returns empty string.
    """
    try:
        from ..llm_area_prompts import format_prompt
        from ..llm_dispatch import llm_area_call

        stage_keys = sorted(data.keys()) if isinstance(data, dict) else []
        prompt = format_prompt(
            "operator_now_synth",
            stage_count=str(len(stage_keys)),
            stages=str(stage_keys[:12]),
        )
        result = llm_area_call("operator_now_synth", prompt, fallback="")
        if result.used_llm and result.text:
            return result.text
        return ""
    except Exception:
        return ""


def _llm_area_canvas_enrich(canvas_content: str, data: dict) -> str:
    """LLM area: enrich canvas with annotations.

    When disabled (default), returns canvas_content unchanged.
    """
    try:
        from ..llm_area_prompts import format_prompt
        from ..llm_dispatch import llm_area_call

        prompt = format_prompt(
            "canvas_enrich",
            canvas_preview=canvas_content[:500],
            stage_count=str(len(data) if isinstance(data, dict) else 0),
        )
        result = llm_area_call("canvas_enrich", prompt, fallback=canvas_content)
        if result.used_llm and result.text and result.text != canvas_content:
            return result.text
        return canvas_content
    except Exception:
        return canvas_content


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _sync_eidos_curriculum(cfg, obs_dir: Path, *, verbose: bool = False) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "enabled": bool(getattr(cfg, "eidos_curriculum_enabled", False)),
        "rebuilt": False,
        "written": False,
        "reason": "disabled",
        "stats": {},
    }
    if not summary["enabled"]:
        return summary

    try:
        from ..eidos_distillation_curriculum import (
            build_curriculum,
            load_curriculum_latest,
            render_curriculum_markdown,
            save_curriculum_snapshot,
            tail_curriculum_history,
        )
    except Exception as exc:
        summary["reason"] = f"import_error:{exc.__class__.__name__}"
        return summary

    try:
        latest = load_curriculum_latest()
        now = time.time()
        latest_ts = 0.0
        if isinstance(latest, dict):
            for key in ("saved_at", "generated_at", "ts"):
                val = latest.get(key)
                if isinstance(val, (int, float)):
                    latest_ts = max(latest_ts, float(val))
        interval_s = max(600, _coerce_int(getattr(cfg, "eidos_curriculum_interval_s", 86400), 86400))
        should_rebuild = not isinstance(latest, dict) or not latest or latest_ts <= 0 or (now - latest_ts) >= interval_s

        if should_rebuild:
            report = build_curriculum(
                max_rows=max(20, _coerce_int(getattr(cfg, "eidos_curriculum_max_rows", 300), 300)),
                max_cards=max(10, _coerce_int(getattr(cfg, "eidos_curriculum_max_cards", 120), 120)),
                include_archive=bool(getattr(cfg, "eidos_curriculum_include_archive", True)),
            )
            save_curriculum_snapshot(report)
            latest = report
            summary["rebuilt"] = True

        report = latest if isinstance(latest, dict) else {}
        stats = report.get("stats", {}) if isinstance(report.get("stats"), dict) else {}
        severity = stats.get("severity", {}) if isinstance(stats.get("severity"), dict) else {}
        history = tail_curriculum_history(limit=60)
        current_high = _coerce_int(severity.get("high"), 0)
        high_delta = 0
        if history:
            high_delta = current_high - _coerce_int(history[0].get("high"), current_high)

        md = render_curriculum_markdown(
            report,
            max_cards=min(40, max(10, _coerce_int(getattr(cfg, "eidos_curriculum_max_cards", 120), 120))),
        )
        out_path = obs_dir / "eidos_curriculum.md"
        out_path.write_text(md, encoding="utf-8")

        summary["written"] = True
        summary["reason"] = "ok"
        summary["path"] = str(out_path)
        summary["stats"] = stats
        summary["history_points"] = len(history)
        summary["high_delta"] = high_delta

        if verbose:
            rows_scanned = _coerce_int(stats.get("rows_scanned"), 0)
            cards_generated = _coerce_int(stats.get("cards_generated"), 0)
            print(
                f"  [observatory] curriculum: rows={rows_scanned} cards={cards_generated} "
                f"rebuilt={summary['rebuilt']}"
            )
        return summary
    except Exception as exc:
        summary["reason"] = f"error:{exc.__class__.__name__}"
        return summary


def generate_observatory(*, force: bool = False, verbose: bool = False) -> dict:
    """Generate the full observatory (flow dashboard + 12 stage pages + canvas).

    Returns a summary dict with file counts and timing.
    """
    from .advisory_reverse_engineering import generate_advisory_reverse_engineering
    from .canvas_generator import generate_canvas
    from .explorer import generate_explorer
    from .flow_dashboard import generate_flow_dashboard
    from .llm_areas_status import generate_llm_areas_status
    from .readability_pack import (
        collect_metrics_snapshot,
        generate_readability_pack,
        load_previous_snapshot,
        save_snapshot,
    )
    from .readers import read_all_stages
    from .stage_pages import generate_all_stage_pages
    from .system_flow_comprehensive import generate_system_flow_comprehensive
    from .system_flow_operator_playbook import generate_system_flow_operator_playbook
    from .tuneables_deep_dive import generate_tuneables_deep_dive

    t0 = time.time()
    cfg = load_config()

    if not cfg.enabled and not force:
        return {"skipped": True, "reason": "disabled"}

    vault = Path(cfg.vault_dir).expanduser()
    obs_dir = vault / "_observatory"
    stages_dir = obs_dir / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)

    # Read all stage data
    data = read_all_stages(max_recent=cfg.max_recent_items)
    if verbose:
        print(f"  [observatory] read {len(data)} stages in {(time.time()-t0)*1000:.0f}ms")

    curriculum_summary = _sync_eidos_curriculum(cfg, obs_dir, verbose=verbose)
    curriculum_stats = (
        curriculum_summary.get("stats", {})
        if isinstance(curriculum_summary.get("stats"), dict)
        else {}
    )
    curriculum_severity = (
        curriculum_stats.get("severity", {})
        if isinstance(curriculum_stats.get("severity"), dict)
        else {}
    )
    stage7 = data.get(7)
    if isinstance(stage7, dict) and curriculum_stats:
        stage7["curriculum_rows_scanned"] = _coerce_int(curriculum_stats.get("rows_scanned"), 0)
        stage7["curriculum_cards_generated"] = _coerce_int(curriculum_stats.get("cards_generated"), 0)
        stage7["curriculum_high"] = _coerce_int(curriculum_severity.get("high"), 0)
        stage7["curriculum_medium"] = _coerce_int(curriculum_severity.get("medium"), 0)
        stage7["curriculum_low"] = _coerce_int(curriculum_severity.get("low"), 0)
        stage7["curriculum_gaps"] = (
            curriculum_stats.get("gaps", {}) if isinstance(curriculum_stats.get("gaps"), dict) else {}
        )
        stage7["curriculum_history_points"] = _coerce_int(curriculum_summary.get("history_points"), 0)
        stage7["curriculum_high_delta"] = _coerce_int(curriculum_summary.get("high_delta"), 0)

    # LLM area: operator_now_synth — synthesize system state summary
    operator_summary = _llm_area_operator_now_synth(data)
    if operator_summary:
        (obs_dir / "operator_now.md").write_text(
            f"---\ntags: [observatory, operator]\n---\n# Operator Now\n\n{operator_summary}\n",
            encoding="utf-8",
        )

    # Generate flow dashboard
    flow_path = obs_dir / "flow.md"
    flow_content = generate_flow_dashboard(data)
    flow_path.write_text(flow_content, encoding="utf-8")

    # Generate reverse-engineered advisory path page
    reverse_path = obs_dir / "advisory_reverse_engineering.md"
    reverse_content = generate_advisory_reverse_engineering(data)
    reverse_path.write_text(reverse_content, encoding="utf-8")

    # Generate tuneables deep dive page
    tuneables_dive_path = obs_dir / "tuneables_deep_dive.md"
    tuneables_dive_content = generate_tuneables_deep_dive(data)
    tuneables_dive_path.write_text(tuneables_dive_content, encoding="utf-8")

    # Generate LLM areas status page
    llm_areas_path = obs_dir / "llm_areas_status.md"
    llm_areas_content = generate_llm_areas_status(data)
    llm_areas_path.write_text(llm_areas_content, encoding="utf-8")

    # Generate comprehensive full-system reverse-engineering page
    comprehensive_path = obs_dir / "system_flow_comprehensive.md"
    comprehensive_content = generate_system_flow_comprehensive(data)
    comprehensive_path.write_text(comprehensive_content, encoding="utf-8")

    # Generate operator playbook page
    playbook_path = obs_dir / "system_flow_operator_playbook.md"
    playbook_content = generate_system_flow_operator_playbook(data)
    playbook_path.write_text(playbook_content, encoding="utf-8")

    # Generate readability/navigation pages
    previous_snapshot = load_previous_snapshot(obs_dir)
    current_snapshot = collect_metrics_snapshot(data)
    for filename, content in generate_readability_pack(
        data, current_snapshot=current_snapshot, previous_snapshot=previous_snapshot
    ):
        (obs_dir / filename).write_text(content, encoding="utf-8")
    save_snapshot(obs_dir, current_snapshot)

    # Generate stage pages
    files_written = 11  # flow + reverse + tuneables_dive + llm_areas + comprehensive + playbook + 5 readability pages
    if curriculum_summary.get("written"):
        files_written += 1  # eidos_curriculum.md
    for filename, content in generate_all_stage_pages(data):
        (stages_dir / filename).write_text(content, encoding="utf-8")
        files_written += 1

    # Generate canvas
    if cfg.generate_canvas:
        canvas_path = obs_dir / "flow.canvas"
        canvas_content = generate_canvas()
        # LLM area: canvas_enrich — add annotations to canvas
        canvas_content = _llm_area_canvas_enrich(canvas_content, data)
        canvas_path.write_text(canvas_content, encoding="utf-8")
        files_written += 1

    # Generate explorer (individual item detail pages)
    t_explore = time.time()
    explorer_counts = generate_explorer(cfg)
    explorer_total = sum(explorer_counts.values()) + 1  # +1 for master index
    files_written += explorer_total
    if verbose:
        print(f"  [observatory] explorer: {explorer_total} files in {(time.time()-t_explore)*1000:.0f}ms")
        for section, count in explorer_counts.items():
            print(f"    {section}: {count} pages")

    elapsed_ms = (time.time() - t0) * 1000
    if verbose:
        print(f"  [observatory] total: {files_written} files in {elapsed_ms:.0f}ms to {obs_dir}")

    return {
        "files_written": files_written,
        "elapsed_ms": round(elapsed_ms, 1),
        "vault_dir": str(vault),
        "explorer": explorer_counts,
        "eidos_curriculum": curriculum_summary,
    }


def maybe_sync_observatory(stats: dict | None = None) -> None:
    """Cooldown-gated sync — safe to call every bridge cycle."""
    global _last_sync_ts

    try:
        cfg = load_config()
        if not cfg.enabled or not cfg.auto_sync:
            return

        now = time.time()
        if (now - _last_sync_ts) < cfg.sync_cooldown_s:
            return

        _last_sync_ts = now
        generate_observatory()
    except Exception:
        # Non-critical — never crash the pipeline
        traceback.print_exc()
