"""Generate a comprehensive tuneables deep-dive page for Obsidian Observatory.

Analyzes both config files, identifies drift, checks hot-reload coverage,
maps cooldown redundancy, reports auto-tuner activity, and generates
actionable recommendations.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import spark_dir

_SPARK_DIR = spark_dir()
_REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Helpers ──────────────────────────────────────────────────────────

def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return data if isinstance(data, dict) else {}


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _fmt_pct(part: float, whole: float) -> str:
    if whole <= 0:
        return "0.0%"
    return f"{(100.0 * float(part) / float(whole)):.1f}%"


def _trunc(val: Any, max_len: int = 80) -> str:
    s = str(val)
    if len(s) > max_len:
        return s[:max_len - 3] + "..."
    return s


def _val_repr(val: Any) -> str:
    """Compact representation for table cells."""
    if isinstance(val, dict):
        if len(val) == 0:
            return "`{}`"
        keys = list(val.keys())[:4]
        summary = ", ".join(f"{k}: ..." for k in keys)
        if len(val) > 4:
            summary += f", +{len(val)-4}"
        return f"`{{{summary}}}`"
    if isinstance(val, list):
        if len(val) == 0:
            return "`[]`"
        return f"`[{len(val)} items]`"
    return f"`{_trunc(val, 50)}`"


# ── Data Collectors ──────────────────────────────────────────────────

# Which sections have register_reload() calls in code
KNOWN_RELOAD_SECTIONS = {
    "flow": ["lib/validate_and_store.py"],
    "advisory_engine": ["lib/advisory_engine.py"],
    "advisory_gate": ["lib/advisory_gate.py"],
    "advisory_packet_store": ["lib/advisory_packet_store.py"],
    "advisory_state": ["lib/advisory_state.py"],
    "advisor": ["lib/advisor.py"],
    "bridge_worker": ["lib/bridge_cycle.py"],
    "meta_ralph": ["lib/meta_ralph.py"],
    "eidos": ["lib/eidos/models.py"],
    "values": ["lib/pipeline.py"],
    "queue": ["lib/queue.py"],
}

# Schema sections from tuneables_schema.py
SCHEMA_SECTIONS = [
    "values", "pipeline", "semantic", "triggers", "promotion", "synthesizer",
    "flow", "advisory_engine", "advisory_gate", "advisory_packet_store",
    "advisory_prefetch", "advisor", "retrieval", "meta_ralph", "eidos",
    "auto_tuner", "chip_merge",
    "advisory_quality", "advisory_preferences", "memory_emotion",
    "memory_learning", "memory_retrieval_guard", "bridge_worker",
    "memory_capture", "observatory", "production_gates",
]

# Impact rating for each section
SECTION_IMPACT = {
    "flow": "HIGH",
    "advisory_engine": "CRITICAL",
    "advisory_gate": "CRITICAL",
    "advisor": "HIGH",
    "meta_ralph": "HIGH",
    "auto_tuner": "HIGH",
    "semantic": "HIGH",
    "advisory_packet_store": "MEDIUM",
    "retrieval": "MEDIUM",
    "promotion": "MEDIUM",
    "bridge_worker": "MEDIUM",
    "eidos": "MEDIUM",
    "production_gates": "MEDIUM",
    "values": "LOW",
    "synthesizer": "LOW",
    "triggers": "LOW",
    "advisory_prefetch": "LOW",
    "pipeline": "MEDIUM",
    "chip_merge": "LOW",
    "advisory_quality": "LOW",
    "advisory_preferences": "LOW",
    "memory_emotion": "LOW",
    "memory_learning": "LOW",
    "memory_retrieval_guard": "LOW",
    "memory_capture": "LOW",
    "observatory": "LOW",
}

# Consumer map (from tuneables_schema.py SECTION_CONSUMERS)
SECTION_CONSUMERS = {
    "values": ["lib/pipeline.py", "lib/advisor.py", "lib/eidos/models.py"],
    "semantic": ["lib/semantic_retriever.py", "lib/advisor.py"],
    "triggers": ["lib/advisor.py"],
    "promotion": ["lib/promoter.py", "lib/auto_promote.py"],
    "synthesizer": ["lib/advisory_synthesizer.py"],
    "advisory_engine": ["lib/advisory_engine.py"],
    "advisory_gate": ["lib/advisory_gate.py", "lib/advisory_state.py"],
    "advisory_packet_store": ["lib/advisory_packet_store.py"],
    "advisory_prefetch": ["lib/advisory_prefetch_worker.py"],
    "advisor": ["lib/advisor.py"],
    "retrieval": ["lib/advisor.py", "lib/semantic_retriever.py"],
    "meta_ralph": ["lib/meta_ralph.py"],
    "eidos": ["lib/eidos/models.py"],
    "pipeline": ["lib/pipeline.py"],
    "auto_tuner": ["lib/auto_tuner.py"],
    "chip_merge": ["lib/chips/runtime.py"],
    "advisory_quality": ["lib/advisory_synthesizer.py"],
    "advisory_preferences": ["lib/advisory_preferences.py"],
    "memory_emotion": ["lib/memory_store.py"],
    "memory_learning": ["lib/memory_store.py"],
    "memory_retrieval_guard": ["lib/memory_store.py"],
    "bridge_worker": ["lib/bridge_cycle.py"],
    "memory_capture": ["lib/memory_capture.py"],
    "production_gates": ["lib/production_gates.py"],
    "observatory": ["lib/observatory/*"],
}


def _load_configs() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Load live (~/.spark/) and version-controlled (config/) tuneables."""
    live = _read_json(_SPARK_DIR / "tuneables.json")
    versioned = _read_json(_REPO_ROOT / "config" / "tuneables.json")
    return live, versioned


def _compute_drift(live: Dict[str, Any], versioned: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compare live vs versioned and return list of drifted items."""
    drifts: List[Dict[str, Any]] = []

    all_sections = sorted(set(list(live.keys()) + list(versioned.keys())) - {"updated_at"})

    for section in all_sections:
        live_sec = live.get(section)
        ver_sec = versioned.get(section)

        if live_sec is None and ver_sec is not None:
            drifts.append({
                "section": section, "key": "(entire section)",
                "live": "MISSING", "versioned": f"{len(ver_sec) if isinstance(ver_sec, dict) else 1} keys",
                "severity": "HIGH",
            })
            continue
        if ver_sec is None and live_sec is not None:
            drifts.append({
                "section": section, "key": "(entire section)",
                "live": f"{len(live_sec) if isinstance(live_sec, dict) else 1} keys",
                "versioned": "MISSING",
                "severity": "MEDIUM",
            })
            continue

        if not isinstance(live_sec, dict) or not isinstance(ver_sec, dict):
            if live_sec != ver_sec:
                drifts.append({
                    "section": section, "key": "(value)",
                    "live": _trunc(live_sec, 40), "versioned": _trunc(ver_sec, 40),
                    "severity": "LOW",
                })
            continue

        # Key-level drift
        all_keys = sorted(set(list(live_sec.keys()) + list(ver_sec.keys())))
        for key in all_keys:
            if key.startswith("_"):
                continue
            live_val = live_sec.get(key)
            ver_val = ver_sec.get(key)

            if live_val is None and ver_val is not None:
                drifts.append({
                    "section": section, "key": key,
                    "live": "MISSING", "versioned": _trunc(ver_val, 40),
                    "severity": "MEDIUM",
                })
            elif ver_val is None and live_val is not None:
                drifts.append({
                    "section": section, "key": key,
                    "live": _trunc(live_val, 40), "versioned": "MISSING",
                    "severity": "LOW",
                })
            elif live_val != ver_val:
                # Skip auto-tuner runtime state that's expected to drift
                if section == "auto_tuner" and key in ("source_boosts", "source_effectiveness",
                                                        "tuning_log", "last_run"):
                    continue
                if key == "updated_at":
                    continue
                drifts.append({
                    "section": section, "key": key,
                    "live": _trunc(live_val, 40), "versioned": _trunc(ver_val, 40),
                    "severity": "MEDIUM" if section in ("advisory_engine", "advisory_gate", "advisor") else "LOW",
                })

    return drifts


def _detect_anomalies(live: Dict[str, Any]) -> List[Dict[str, str]]:
    """Find float artifacts, suspicious values, etc."""
    anomalies: List[Dict[str, str]] = []

    for section, sec_data in live.items():
        if not isinstance(sec_data, dict):
            continue
        for key, val in sec_data.items():
            if key.startswith("_"):
                continue

            # Float artifact check
            if isinstance(val, float):
                s = str(val)
                if len(s) > 8 and "." in s and len(s.split(".")[-1]) > 4:
                    anomalies.append({
                        "section": section, "key": key,
                        "value": s, "issue": "Float precision artifact",
                        "suggestion": f"Round to `{round(val, 4)}`",
                    })

    return anomalies


def _auto_tuner_analysis(live: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze auto-tuner state for concerning patterns."""
    auto = live.get("auto_tuner", {})
    if not isinstance(auto, dict):
        return {"available": False}

    boosts = auto.get("source_boosts", {})
    effectiveness = auto.get("source_effectiveness", {})
    tuning_log = auto.get("tuning_log", [])

    # Find dampened high-performers
    dampened = []
    for source, eff in sorted(effectiveness.items(), key=lambda x: x[1], reverse=True):
        boost = boosts.get(source, 1.0)
        if eff > 0.10 and boost < 0.8:
            dampened.append({
                "source": source,
                "effectiveness": f"{eff:.1%}",
                "boost": f"{boost:.3f}",
                "concern": "High effectiveness but low boost",
            })

    # Recent tuning trend
    recent_changes = []
    for entry in (tuning_log or [])[-5:]:
        if isinstance(entry, dict) and entry.get("action") != "auto_tune_noop":
            recent_changes.append({
                "ts": entry.get("timestamp", "?"),
                "changes": len(entry.get("changes", {})),
                "basis": entry.get("data_basis", "?"),
            })

    return {
        "available": True,
        "boosts": boosts,
        "effectiveness": effectiveness,
        "dampened": dampened,
        "recent_changes": recent_changes,
        "total_log_entries": len(tuning_log or []),
    }


# ── Page Generator ───────────────────────────────────────────────────

def generate_tuneables_deep_dive(data: Dict[int, Dict[str, Any]]) -> str:
    """Build the comprehensive tuneables deep-dive page for Obsidian."""
    live, versioned = _load_configs()
    drifts = _compute_drift(live, versioned)
    anomalies = _detect_anomalies(live)
    tuner = _auto_tuner_analysis(live)

    lines: List[str] = []

    # ── Frontmatter ──
    lines.append("---")
    lines.append("title: Tuneables Deep Dive")
    lines.append("tags:")
    lines.append("  - observatory")
    lines.append("  - tuneables")
    lines.append("  - configuration")
    lines.append("  - diagnostics")
    lines.append("---")
    lines.append("")

    # ── 1. Executive Summary ──
    lines.append("# Tuneables Deep Dive")
    lines.append("")
    lines.append(f"> Generated: {_fmt_ts(time.time())}")
    lines.append("> Comprehensive analysis of all tuneable configuration across the Spark Intelligence pipeline.")
    lines.append("")

    live_sections = [k for k in live.keys() if k != "updated_at"]
    ver_sections = [k for k in versioned.keys() if k != "updated_at"]
    all_sections = sorted(set(live_sections + ver_sections))
    total_keys_live = sum(len(v) for v in live.values() if isinstance(v, dict))
    total_keys_ver = sum(len(v) for v in versioned.values() if isinstance(v, dict))

    reload_count = len(KNOWN_RELOAD_SECTIONS)
    schema_count = len(SCHEMA_SECTIONS)
    reload_pct = _fmt_pct(reload_count, schema_count)

    drift_count = len(drifts)
    anomaly_count = len(anomalies)
    health = "GREEN" if drift_count < 5 and anomaly_count == 0 else ("YELLOW" if drift_count < 15 else "RED")

    lines.append("## Executive Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Health | **{health}** |")
    lines.append(f"| Total sections | {len(all_sections)} (live: {len(live_sections)}, versioned: {len(ver_sections)}) |")
    lines.append(f"| Total keys | live: {total_keys_live}, versioned: {total_keys_ver} |")
    lines.append(f"| Schema sections | {schema_count} |")
    lines.append(f"| Hot-reload coverage | {reload_count}/{schema_count} ({reload_pct}) |")
    lines.append(f"| Config drifts detected | {drift_count} |")
    lines.append(f"| Value anomalies | {anomaly_count} |")
    lines.append(f"| Auto-tuner entries | {tuner.get('total_log_entries', 0)} |")
    lines.append("")

    # ── 2. Hot-Reload Coverage Map ──
    lines.append("## Hot-Reload Coverage Map")
    lines.append("")
    lines.append("Sections with `register_reload()` get updated at runtime when `tuneables.json` changes.")
    lines.append("Sections WITHOUT hot-reload require a full restart to pick up changes.")
    lines.append("")
    lines.append("| Section | Hot-Reload | Impact | Registered In | Consumers |")
    lines.append("|---|---|---|---|---|")

    for section in SCHEMA_SECTIONS:
        has_reload = section in KNOWN_RELOAD_SECTIONS
        reload_str = "YES" if has_reload else "**NO**"
        impact = SECTION_IMPACT.get(section, "LOW")
        impact_str = f"**{impact}**" if impact in ("CRITICAL", "HIGH") else impact
        registered = ", ".join(f"`{f}`" for f in KNOWN_RELOAD_SECTIONS.get(section, []))
        consumers = ", ".join(f"`{c}`" for c in SECTION_CONSUMERS.get(section, []))
        lines.append(f"| `{section}` | {reload_str} | {impact_str} | {registered or '-'} | {consumers or '-'} |")

    lines.append("")

    # Flag critical gaps
    critical_gaps = [s for s in SCHEMA_SECTIONS
                     if s not in KNOWN_RELOAD_SECTIONS
                     and SECTION_IMPACT.get(s) in ("CRITICAL", "HIGH")]
    if critical_gaps:
        lines.append("> **CRITICAL GAPS**: The following high-impact sections have NO hot-reload:")
        for s in critical_gaps:
            lines.append(f"> - `{s}` ({SECTION_IMPACT.get(s)}) — consumed by {', '.join(SECTION_CONSUMERS.get(s, []))}")
        lines.append("")

    # ── 3. Config Drift Analysis ──
    lines.append("## Config Drift Analysis")
    lines.append("")
    lines.append("Comparison of `~/.spark/tuneables.json` (live) vs `config/tuneables.json` (version-controlled).")
    lines.append("Auto-tuner state (`source_boosts`, `tuning_log`, `last_run`) is expected to drift and excluded.")
    lines.append("")

    if drifts:
        lines.append(f"**{len(drifts)} drifts detected:**")
        lines.append("")
        lines.append("| Severity | Section | Key | Live Value | Versioned Value |")
        lines.append("|---|---|---|---|---|")
        for d in sorted(drifts, key=lambda x: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(x["severity"], 3)):
            sev = f"**{d['severity']}**" if d["severity"] == "HIGH" else d["severity"]
            lines.append(f"| {sev} | `{d['section']}` | `{d['key']}` | {d['live']} | {d['versioned']} |")
        lines.append("")
    else:
        lines.append("No config drift detected (configs are in sync).")
        lines.append("")

    # ── 4. Cooldown Redundancy Report ──
    lines.append("## Cooldown Redundancy Report")
    lines.append("")
    lines.append("Three overlapping cooldown mechanisms control advisory suppression:")
    lines.append("")
    lines.append("| Cooldown | Section | Live Value | Scope | Effect |")
    lines.append("|---|---|---|---|---|")

    ae = live.get("advisory_engine", {})
    ag = live.get("advisory_gate", {})

    text_cd = ae.get("advisory_text_repeat_cooldown_s", "?")
    advice_cd = ag.get("advice_repeat_cooldown_s", "?")
    shown_ttl = ag.get("shown_advice_ttl_s", "?")
    global_cd = ae.get("global_dedupe_cooldown_s", "?")

    lines.append(f"| `advisory_text_repeat_cooldown_s` | advisory_engine | `{text_cd}s` | "
                 f"Exact text match | Prevents emitting identical text within window |")
    lines.append(f"| `advice_repeat_cooldown_s` | advisory_gate | `{advice_cd}s` | "
                 f"Same advice_id | Prevents re-emitting same advice item within window |")
    lines.append(f"| `shown_advice_ttl_s` | advisory_gate | `{shown_ttl}s` | "
                 f"Shown-state marker | Marks advice as \"shown\" for TTL duration; source TTL multipliers scale this per-source |")
    lines.append(f"| `global_dedupe_cooldown_s` | advisory_engine | `{global_cd}s` | "
                 f"Cross-session dedup | Prevents same insight from emitting across sessions |")
    lines.append("")

    lines.append("**Interaction pattern:**")
    lines.append("1. Gate `shown_advice_ttl_s` fires first (per-source scaled)")
    lines.append("2. Gate `advice_repeat_cooldown_s` catches same-id repeats")
    lines.append("3. Engine `advisory_text_repeat_cooldown_s` catches text-level duplicates")
    lines.append("4. Engine `global_dedupe_cooldown_s` catches cross-session duplicates")
    lines.append("")

    if isinstance(text_cd, (int, float)) and isinstance(advice_cd, (int, float)):
        if text_cd >= advice_cd:
            lines.append(f"> Note: `advisory_text_repeat_cooldown_s` ({text_cd}s) >= `advice_repeat_cooldown_s` "
                         f"({advice_cd}s). The text cooldown may shadow the advice cooldown for exact-match cases.")
        lines.append("")

    # ── 5. Source TTL & Tool Cooldown Multipliers ──
    lines.append("## Source TTL & Tool Cooldown Multipliers")
    lines.append("")

    source_ttl = ag.get("source_ttl_multipliers", {})
    tool_cd_mult = ag.get("tool_cooldown_multipliers", {})

    if source_ttl:
        base_ttl = shown_ttl if isinstance(shown_ttl, (int, float)) else 420
        lines.append("### Source TTL Multipliers")
        lines.append("")
        lines.append("| Source | Multiplier | Effective TTL |")
        lines.append("|---|---|---|")
        for source, mult in sorted(source_ttl.items(), key=lambda x: x[1]):
            effective = round(float(base_ttl) * float(mult))
            lines.append(f"| `{source}` | {mult}x | ~{effective}s |")
        lines.append("")

    if tool_cd_mult:
        base_cd = ag.get("tool_cooldown_s", 15)
        if not isinstance(base_cd, (int, float)):
            base_cd = 15
        lines.append("### Tool Cooldown Multipliers")
        lines.append("")
        lines.append("| Tool | Multiplier | Effective Cooldown |")
        lines.append("|---|---|---|")
        for tool, mult in sorted(tool_cd_mult.items(), key=lambda x: x[1]):
            effective = round(float(base_cd) * float(mult))
            lines.append(f"| `{tool}` | {mult}x | ~{effective}s |")
        lines.append("")

    # ── 6. Auto-Tuner Activity ──
    lines.append("## Auto-Tuner Activity")
    lines.append("")

    if not tuner.get("available"):
        lines.append("Auto-tuner data not available.")
        lines.append("")
    else:
        # Source boosts table
        boosts = tuner.get("boosts", {})
        effectiveness = tuner.get("effectiveness", {})
        if boosts:
            lines.append("### Current Source Boosts vs Effectiveness")
            lines.append("")
            lines.append("| Source | Boost | Effectiveness | Status |")
            lines.append("|---|---|---|---|")
            for source in sorted(boosts.keys()):
                boost = boosts[source]
                eff = effectiveness.get(source, 0)
                if eff > 0.10 and boost < 0.8:
                    status = "DAMPENED (high eff, low boost)"
                elif eff < 0.03 and boost > 0.5:
                    status = "over-weighted"
                elif eff > 0.50:
                    status = "TOP PERFORMER"
                else:
                    status = "normal"
                lines.append(f"| `{source}` | {boost:.3f} | {eff:.1%} | {status} |")
            lines.append("")

        # Dampened warnings
        dampened = tuner.get("dampened", [])
        if dampened:
            lines.append("> **AUTO-TUNER CONCERN**: The following sources have high effectiveness but are being dampened:")
            for d in dampened:
                lines.append(f"> - `{d['source']}`: effectiveness={d['effectiveness']}, boost={d['boost']}")
            lines.append("> min_boost floor is now 0.8 (tightened from 0.2 in Batch 5). Boosts are clamped on load.")
            lines.append("")

        # Recent changes
        recent = tuner.get("recent_changes", [])
        if recent:
            lines.append("### Recent Tuning Activity")
            lines.append("")
            lines.append("| Timestamp | Changes | Data Basis |")
            lines.append("|---|---|---|")
            for r in recent:
                lines.append(f"| {r['ts']} | {r['changes']} | {r['basis']} |")
            lines.append("")

    # ── 7. Value Anomalies ──
    lines.append("## Value Anomalies")
    lines.append("")

    if anomalies:
        lines.append(f"**{len(anomalies)} anomalies detected:**")
        lines.append("")
        lines.append("| Section | Key | Current Value | Issue | Suggestion |")
        lines.append("|---|---|---|---|---|")
        for a in anomalies:
            lines.append(f"| `{a['section']}` | `{a['key']}` | `{a['value']}` | {a['issue']} | {a['suggestion']} |")
        lines.append("")
    else:
        lines.append("No value anomalies detected.")
        lines.append("")

    # ── 8. Live Values Table ──
    lines.append("## Live Values (All Sections)")
    lines.append("")
    lines.append("Complete dump of `~/.spark/tuneables.json` organized by section.")
    lines.append("")

    for section in sorted(live.keys()):
        if section == "updated_at":
            continue
        sec_data = live[section]
        if not isinstance(sec_data, dict):
            lines.append(f"### `{section}`")
            lines.append(f"Value: `{_trunc(sec_data, 60)}`")
            lines.append("")
            continue

        has_reload = section in KNOWN_RELOAD_SECTIONS
        reload_badge = " (hot-reload)" if has_reload else " (restart-only)"
        impact = SECTION_IMPACT.get(section, "?")

        lines.append(f"### `{section}`{reload_badge} — Impact: {impact}")
        lines.append("")

        # Skip massive nested structures for readability
        flat_keys = {k: v for k, v in sec_data.items() if not k.startswith("_")}
        if not flat_keys:
            lines.append("(empty section)")
            lines.append("")
            continue

        lines.append("| Key | Value |")
        lines.append("|---|---|")
        for key in sorted(flat_keys.keys()):
            val = flat_keys[key]
            lines.append(f"| `{key}` | {_val_repr(val)} |")
        lines.append("")

    # ── 9. Advisory Pipeline Impact Map ──
    lines.append("## Advisory Pipeline Impact Map")
    lines.append("")
    lines.append("Which tuneables control which stage of the advisory path.")
    lines.append("")
    lines.append("| Pipeline Stage | Controlling Sections | Key Tuneables |")
    lines.append("|---|---|---|")
    lines.append("| 1. Hook ingress | - | (no tuneables; config in `settings.json`) |")
    lines.append("| 2. Queue ingest | `values` | `queue_batch_size` |")
    lines.append("| 3. Bridge cycle | `bridge_worker` | `enabled`, `mind_sync_*` |")
    lines.append("| 4. Memory capture | `memory_capture`, `values` | `auto_save_threshold`, importance scoring |")
    lines.append("| 5. Meta-Ralph gate | `meta_ralph` | `quality_threshold`, `needs_work_threshold` |")
    lines.append("| 6. Cognitive/EIDOS | `eidos`, `semantic` | `max_steps`, `min_fusion_score`, `dedupe_similarity` |")
    lines.append("| 7. Mind sync | `bridge_worker`, `advisor` | `mind_sync_*`, `mind_max_stale_s`, `mind_min_salience` |")
    lines.append("| 5.5. Unified write gate | `flow` | `validate_and_store_enabled` (bypass Meta-Ralph if false) |")
    lines.append("| 8. Pre-tool orchestrator | `advisory_engine` | `max_ms`, `include_mind`, `delivery_stale_s`, `fallback_budget_cap/window` |")
    lines.append("| 9. Retrieval fanout | `advisor`, `retrieval`, `semantic` | `min_rank_score`, `level` |")
    lines.append("| 10. Gate + suppression | `advisory_gate` | `max_emit_per_call`, `*_cooldown_*`, `*_threshold` |")
    lines.append("| 11. Synth + emit | `synthesizer`, `advisory_quality` | `mode`, `preferred_provider` |")
    lines.append("| 12. Post-tool feedback | `advisory_engine` | `advisory_text_repeat_cooldown_s`, `global_dedupe_cooldown_s` |")
    lines.append("")

    # ── 10. Cross-Section Dependencies ──
    lines.append("## Cross-Section Dependencies")
    lines.append("")
    lines.append("| From Section | To Section | Dependency |")
    lines.append("|---|---|---|")
    lines.append("| `auto_tuner` | `advisor` | `source_boosts` affect `_rank_score()` in advisor |")
    lines.append("| `advisory_gate` | `advisory_state` | Gate writes shown markers; state tracks cooldowns |")
    lines.append("| `advisory_engine` | `advisory_gate` | Engine sets budget; gate enforces it |")
    lines.append("| `advisory_engine` | `advisory_packet_store` | Engine routes through packet cache |")
    lines.append("| `advisor` | `semantic` | Advisor uses semantic retrieval config for ranking |")
    lines.append("| `bridge_worker` | `advisor` | Mind sync feeds advisor's mind source |")
    lines.append("| `meta_ralph` | `advisor` | Quality gate affects what's available for advisory |")
    lines.append("| `retrieval` | `semantic` | Retrieval overrides semantic parameters |")
    lines.append("| `production_gates` | `meta_ralph` | Production gates check quality band from Meta-Ralph |")
    lines.append("")

    # ── 11. Recommendations ──
    lines.append("## Recommendations")
    lines.append("")
    lines.append("| Priority | Issue | Current | Recommended | Rationale |")
    lines.append("|---|---|---|---|---|")

    # Float artifact
    if anomalies:
        for a in anomalies:
            lines.append(f"| LOW | Float artifact | `{a['section']}.{a['key']}={a['value']}` | {a['suggestion']} | Precision noise |")

    # Critical hot-reload gaps
    for section in critical_gaps:
        lines.append(f"| **HIGH** | No hot-reload | `{section}` (restart-only) | Add `register_reload()` | "
                     f"{SECTION_IMPACT.get(section, '?')} impact section, tuning requires restart |")

    # Drift items
    high_drifts = [d for d in drifts if d["severity"] == "HIGH"]
    for d in high_drifts:
        lines.append(f"| **HIGH** | Config drift | `{d['section']}.{d['key']}` live={d['live']} | Sync with versioned: {d['versioned']} | Configs diverged |")

    medium_drifts = [d for d in drifts if d["severity"] == "MEDIUM"]
    for d in medium_drifts[:8]:  # Cap at 8 to avoid huge table
        lines.append(f"| MEDIUM | Config drift | `{d['section']}.{d['key']}` | Evaluate if live or versioned is correct | Intentional tuning or accidental? |")
    if len(medium_drifts) > 8:
        lines.append(f"| MEDIUM | Config drift | +{len(medium_drifts)-8} more | Review all drifts | See drift table above |")

    # Auto-tuner dampening
    dampened = tuner.get("dampened", [])
    if dampened:
        for d in dampened:
            lines.append(f"| MEDIUM | Auto-tuner dampening | `{d['source']}` boost={d['boost']} | "
                         f"min_boost floor is 0.8 (clamped on load) | {d['effectiveness']} effective but being reduced |")

    # Schema missing keys
    gate_schema_missing = []
    for key in ("shown_advice_ttl_s", "source_ttl_multipliers", "tool_cooldown_multipliers"):
        if key not in []:  # These were added to schema already, but check
            pass
    # Check if schema has the Phase 7 keys
    try:
        from ..tuneables_schema import SCHEMA
        gate_schema = SCHEMA.get("advisory_gate", {})
        for key in ("source_ttl_multipliers", "tool_cooldown_multipliers"):
            if key not in gate_schema:
                gate_schema_missing.append(key)
    except Exception:
        pass

    for key in gate_schema_missing:
        lines.append(f"| MEDIUM | Schema gap | `advisory_gate.{key}` | Add to `tuneables_schema.py` | "
                     f"Phase 7 key missing from schema validation |")

    lines.append("")

    # ── 12. Self-Audit Questions ──
    lines.append("## Self-Audit Questions")
    lines.append("")
    lines.append("Use these when reviewing tuneable changes:")
    lines.append("")
    lines.append("1. **Is every suppression justified by data?** Check the suppression buckets in [[Advisory Reverse Engineering]].")
    lines.append("2. **Are any high-value sources being penalized?** Compare auto-tuner `source_boosts` vs `source_effectiveness`.")
    lines.append("3. **Could reducing cooldowns improve emit rate without harming follow rate?** "
                 "Follow rate (96.8%) is very high — there may be room to emit more without quality loss.")
    lines.append("4. **Are there tuneables nobody has ever changed from default?** "
                 "Any key matching its schema default and never appearing in tuning_log is a candidate for removal.")
    lines.append("5. **Is the auto-tuner converging or oscillating?** Check if source boosts are moving in consistent directions across runs.")
    lines.append("6. **Are the 3 cooldown mechanisms (text, advice, shown) stepping on each other?** "
                 "If text_repeat > advice_repeat, the text cooldown is the binding constraint and advice_repeat may be dead weight.")
    lines.append("7. **Does the advisory_engine section need hot-reload?** "
                 "It's the most frequently tweaked section but requires a full restart for changes to take effect.")
    lines.append("8. **Are production_gates thresholds still appropriate?** "
                 "As the system matures, quality floors may need adjustment.")
    lines.append("")

    # ── 13. Change History ──
    lines.append("## Change History (Auto-Tuner Log)")
    lines.append("")

    auto = live.get("auto_tuner", {})
    tuning_log = auto.get("tuning_log", []) if isinstance(auto, dict) else []
    if tuning_log:
        lines.append(f"Last {min(len(tuning_log), 5)} auto-tuner runs:")
        lines.append("")
        for entry in tuning_log[-5:]:
            if not isinstance(entry, dict):
                continue
            ts = entry.get("timestamp", "?")
            action = entry.get("action", "?")
            changes = entry.get("changes", {})
            basis = entry.get("data_basis", "?")
            lines.append(f"### {ts} — `{action}`")
            lines.append(f"Data basis: {basis}")
            lines.append("")
            if changes:
                for source, detail in sorted(changes.items()):
                    lines.append(f"- `{source}`: {detail}")
            else:
                lines.append("- (no changes)")
            lines.append("")
    else:
        lines.append("No auto-tuner log entries available.")
        lines.append("")

    # ── 14. Related Pages ──
    lines.append("## Related Pages")
    lines.append("")
    lines.append("- [[Advisory Reverse Engineering]] — Suppression analysis and improvement tracking")
    lines.append("- [[Stage 12 - Tuneables]] — Basic tuneable overview")
    lines.append("- [[System Flow Comprehensive]] — Full pipeline reverse engineering")
    lines.append("- [[System Flow Operator Playbook]] — Operational procedures")
    lines.append("")

    return "\n".join(lines)
