"""Generate the main flow dashboard (flow.md) with Mermaid diagram + live metrics."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .linker import stage_link, fmt_ts, fmt_ago, fmt_num, fmt_size, health_badge

_ERA_FILE = Path.home() / ".spark" / "era.json"


def _read_era() -> dict | None:
    """Read ~/.spark/era.json if it exists."""
    try:
        if _ERA_FILE.exists():
            return json.loads(_ERA_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _frontmatter() -> str:
    lines = [
        "---",
        "title: Intelligence Flow Dashboard",
        "tags:",
        "  - observatory",
        "  - dashboard",
        "  - flow",
        "---",
        "",
    ]
    return "\n".join(lines)


def _health_status(data: dict[int, dict]) -> list[tuple[str, str, str]]:
    """Compute health rows from stage data."""
    rows = []
    # Queue
    q = data.get(2, {})
    pending = q.get("estimated_pending", 0)
    q_status = "healthy" if pending < 5000 else ("warning" if pending < 20000 else "critical")
    rows.append(("Queue depth", f"~{fmt_num(pending)} pending", q_status))

    # Pipeline
    p = data.get(3, {})
    last_ts = p.get("last_cycle_ts")
    ago = fmt_ago(last_ts)
    p_status = "healthy"
    if last_ts:
        diff = time.time() - last_ts
        if diff > 600:
            p_status = "critical"
        elif diff > 300:
            p_status = "warning"
    rows.append(("Last pipeline cycle", ago, p_status))
    rows.append(("Processing rate", f"{p.get('last_processing_rate', 0):.1f} ev/s", "healthy"))
    rows.append(("Events processed", fmt_num(p.get("total_events_processed", 0)), "healthy"))
    rows.append(("Insights created", fmt_num(p.get("total_insights_created", 0)), "healthy"))

    # Memory Capture
    mc = data.get(4, {})
    rows.append(("Pending memories", fmt_num(mc.get("pending_count", 0)), "healthy"))

    # Meta-Ralph
    mr = data.get(5, {})
    rows.append(("Meta-Ralph roasted", fmt_num(mr.get("total_roasted", 0)), "healthy"))
    pass_rate = mr.get("pass_rate", 0)
    rows.append(("Meta-Ralph pass rate", f"{pass_rate}%",
                 "healthy" if pass_rate > 30 else ("warning" if pass_rate > 15 else "critical")))
    rows.append(("Meta-Ralph avg score", str(mr.get("avg_total_score", 0)), "healthy"))

    # Cognitive
    cg = data.get(6, {})
    rows.append(("Cognitive insights", fmt_num(cg.get("total_insights", 0)), "healthy"))

    # EIDOS
    ei = data.get(7, {})
    rows.append(("EIDOS episodes", fmt_num(ei.get("episodes", 0)), "healthy" if ei.get("db_exists") else "warning"))
    rows.append(("EIDOS distillations", fmt_num(ei.get("distillations", 0)), "healthy"))

    # Advisory
    ad = data.get(8, {})
    rows.append(("Advisory given", fmt_num(ad.get("total_advice_given", 0)), "healthy"))
    rows.append(("Advisory followed", f"{ad.get('followed_rate', 0)}%", "healthy"))
    emit_rate = ad.get("decision_emit_rate", 0)
    rows.append(("Advisory emit rate", f"{emit_rate}%",
                 "healthy" if emit_rate > 20 else "warning"))
    fb_follow = ad.get("feedback_follow_rate", 0)
    rows.append(("Implicit follow rate", f"{fb_follow}%",
                 "healthy" if fb_follow > 40 else "warning"))

    # Promotion
    pr = data.get(9, {})
    rows.append(("Promotion log entries", fmt_num(pr.get("total_entries", 0)), "healthy"))

    # Chips
    ch = data.get(10, {})
    rows.append(("Active chips", fmt_num(ch.get("total_chips", 0)), "healthy"))

    # Learning-Systems Bridge
    bridge = data.get("bridge", {})
    if bridge.get("audit_exists"):
        rows.append(("External ingests", fmt_num(bridge.get("audit_count", 0)),
                     "healthy" if bridge.get("recent_store_rate", 0) > 50 else "warning"))
    if bridge.get("proposals_exists"):
        rows.append(("Tuneable proposals", fmt_num(bridge.get("proposals_count", 0)), "healthy"))

    # Onboarding
    onboard = data.get("onboarding", {})
    if onboard.get("completed"):
        rows.append(("Onboarding", "completed", "healthy"))
    elif onboard.get("started_at"):
        rows.append(("Onboarding", f"{onboard.get('progress_pct', 0)}% complete", "warning"))

    return rows


def _mermaid_diagram(data: dict[int, dict]) -> str:
    """Generate the Mermaid flowchart with live metrics."""
    p = data.get(3, {})
    q = data.get(2, {})
    mc = data.get(4, {})
    mr = data.get(5, {})
    cg = data.get(6, {})
    ei = data.get(7, {})
    ad = data.get(8, {})
    pr = data.get(9, {})
    ch = data.get(10, {})
    pk = data.get(11, {})

    elev = data.get("elevation", {})
    needs_work = elev.get("needs_work_verdicts", 0)

    lines = [
        "```mermaid",
        "flowchart TD",
        f'    A["`**Event Capture**',
        f'    hooks/observe.py',
        f'    _Last: {fmt_ago(data.get(1, {}).get("last_cycle_ts"))}_`"]',
        f'    --> B["`**Queue**',
        f'    ~{fmt_num(q.get("estimated_pending", 0))} pending',
        f'    _{fmt_size(q.get("events_file_size", 0))}_`"]',
        "",
        f'    B --> C["`**Pipeline**',
        f'    {fmt_num(p.get("total_events_processed", 0))} processed',
        f'    _{p.get("last_processing_rate", 0):.1f} ev/s_`"]',
        "",
        f'    C --> D["`**Memory Capture**',
        f'    {fmt_num(mc.get("pending_count", 0))} pending',
        f'    _Importance scoring_`"]',
        "",
        f'    D --> VS["`**validate_and_store**',
        f'    _Unified write gate_`"]',
        "",
        f'    VS --> E{{"`**Meta-Ralph**',
        f'    Quality Gate',
        f'    _{fmt_num(mr.get("total_roasted", 0))} roasted_`"}}',
        "",
        f'    E -->|pass| F["`**Cognitive Learner**',
        f'    {fmt_num(cg.get("total_insights", 0))} insights',
        f'    _{len(cg.get("category_distribution", {}))} categories_`"]',
        "",
        f'    E -->|needs_work| EL["`**Elevation**',
        f'    _12 text transforms_',
        f'    _{fmt_num(needs_work)} attempted_`"]',
        f'    EL -->|re-score| E',
        "",
        f'    E -->|reject| X["`**Rejected**',
        f'    _Below threshold_`"]',
        "",
        f'    E -->|exception| Q["`**Quarantine**',
        f'    _Fail-open: stored + logged_`"]',
        f'    Q --> F',
        "",
        f'    C --> G["`**EIDOS**',
        f'    {fmt_num(ei.get("episodes", 0))} episodes',
        f'    _{fmt_num(ei.get("distillations", 0))} distillations_`"]',
        "",
        f'    G --> GR["`**Distillation Refiner**',
        f'    _5-stage candidate ranking_`"]',
        "",
        f'    F --> H["`**Advisory**',
        f'    {fmt_num(ad.get("total_advice_given", 0))} given',
        f'    _{ad.get("followed_rate", 0)}% followed_`"]',
        "",
        f'    GR --> H',
        "",
        f'    H --> I["`**Promotion**',
        f'    {fmt_num(pr.get("total_entries", 0))} log entries',
        f'    _CLAUDE.md + targets_`"]',
        "",
        f'    C --> J["`**Chips**',
        f'    {fmt_num(ch.get("total_chips", 0))} active modules',
        f'    _{fmt_size(ch.get("total_size", 0))}_`"]',
        "",
        f'    J --> H',
        "",
        f'    C --> K["`**Predictions**',
        f'    {fmt_num(pk.get("outcomes_count", 0))} outcomes',
        f'    _Surprise tracking_`"]',
        "",
        f'    K --> G',
        "",
        f'    LS["`**Learning-Systems Bridge**',
        f'    _External insight ingress_`"]',
        f'    LS -->|validated| VS',
        "",
        f'    L["`**Config Authority**',
        f'    {len(data.get(12, {}).get("sections", {}))} sections',
        f'    _4-layer precedence + hot-reload_`"]',
        f'    -.->|configures| E',
        f'    L -.->|configures| H',
        f'    L -.->|configures| GR',
        "",
        '    style X fill:#4a2020,stroke:#ff6666,color:#ff9999',
        '    style E fill:#2a3a2a,stroke:#66cc66,color:#88ee88',
        '    style EL fill:#2a2a3a,stroke:#6688cc,color:#99bbee',
        '    style GR fill:#2a2a3a,stroke:#6688cc,color:#99bbee',
        '    style LS fill:#3a2a2a,stroke:#cc8866,color:#eebb99',
        "```",
    ]
    return "\n".join(lines)


def generate_flow_dashboard(data: dict[int, dict[str, Any]]) -> str:
    """Generate the full flow.md content."""
    now = fmt_ts(time.time())
    sections = []

    # Header
    sections.append(_frontmatter())
    sections.append(f"# Spark Intelligence Observatory\n")
    sections.append(f"> Last generated: {now}")
    p = data.get(3, {})
    sections.append(f"> Pipeline: {fmt_num(p.get('total_events_processed', 0))} events processed, {fmt_num(p.get('total_insights_created', 0))} insights created")

    # Era indicator
    era_info = _read_era()
    if era_info:
        era_name = era_info.get("current", "unknown")
        era_started = era_info.get("started_at", "?")[:19]
        sections.append(f"> **Era: {era_name}** (started {era_started})")
    sections.append("")

    # System Health table
    sections.append("## System Health\n")
    sections.append("| Metric | Value | Status |")
    sections.append("|--------|-------|--------|")
    for metric, value, status in _health_status(data):
        sections.append(f"| {metric} | {value} | {health_badge(status)} |")
    sections.append("")

    # Mermaid diagram
    sections.append("## Intelligence Flow\n")
    sections.append(_mermaid_diagram(data))
    sections.append("")

    # Stage links
    sections.append("## Stage Detail Pages\n")
    for i in range(1, 13):
        sd = data.get(i, {})
        name = sd.get("name", f"Stage {i}")
        desc = _stage_description(i)
        sections.append(f"{i}. {stage_link(i)} — {desc}")
    sections.append("")

    # Data flow narrative
    sections.append("## How Data Flows\n")
    sections.append(f"- An **event** enters via {stage_link(1)} and lands in the {stage_link(2)}")
    sections.append(f"- The {stage_link(3)} processes batches, feeding {stage_link(4)}")
    sections.append(f"- {stage_link(5)} gates every insight — NEEDS_WORK verdicts go through **Elevation Transforms** (12 text rewrites) before re-scoring")
    sections.append(f"- Passed insights enter {stage_link(6)}; {stage_link(7)} produces distillations refined through the **Distillation Refiner** (5-stage candidate ranking)")
    sections.append(f"- {stage_link(8)} retrieves from {stage_link(6)}, {stage_link(7)}, and {stage_link(10)}")
    sections.append(f"- High-confidence insights get {stage_link(9, 'promoted')} to CLAUDE.md")
    sections.append(f"- {stage_link(11)} close the loop: predict, observe, evaluate, learn")
    sections.append(f"- External systems feed insights via the **Learning-Systems Bridge** (validated ingress with audit trail)")
    sections.append(f"- All config resolves through **Config Authority** (4-layer precedence with hot-reload)")
    sections.append("")

    # Quick links to existing pages
    sections.append("## Quick Links\n")
    sections.append("- [[start_here|Start Here]] - guided 90-second orientation and reading path")
    sections.append("- [[topic_finder|Topic Finder]] - question-to-page index for fast navigation")
    sections.append("- [[glossary|Glossary]] - key terms across advisory, memory, EIDOS, and retrieval")
    sections.append("- [[troubleshooting_by_symptom|Troubleshooting by Symptom]] - diagnose issues by observed behavior")
    sections.append("- [[changes_since_last_regen|Changes Since Last Regen]] - track metric deltas after each regeneration")
    sections.append("- [[advisory_reverse_engineering|Advisory Reverse Engineering]] - full path map, suppressor diagnostics, and tuning plan")
    sections.append("- [[tuneables_deep_dive|Tuneables Deep Dive]] - config drift, hot-reload coverage, cooldown analysis, auto-tuner activity, recommendations")
    sections.append("- [[system_flow_comprehensive|System Flow Comprehensive]] - full human-readable reverse engineering with live examples, strengths, and gaps")
    sections.append("- [[system_flow_operator_playbook|System Flow Operator Playbook]] - threshold checks, run commands, immediate actions, and durable fixes")
    sections.append("- [[explore/_index|Explore Individual Items]] — browse cognitive insights, distillations, episodes, verdicts")
    sections.append("- [[../watchtower|Advisory Watchtower]] — existing advisory deep-dive")
    sections.append("- [[../packets/index|Advisory Packet Catalog]] — existing packet view")
    sections.append("")

    return "\n".join(sections)


def _stage_description(num: int) -> str:
    descs = {
        1: "Hook integration, session tracking, predictions",
        2: "Event buffering, overflow, compaction",
        3: "Batch processing, priority ordering, learning yield",
        4: "Importance scoring, domain detection, pending items",
        5: "Quality gate, roast verdicts, noise filtering, **elevation transforms**",
        6: "Insight store, categories, reliability tracking",
        7: "Episodes, steps, distillations, **distillation refiner pipeline**",
        8: "Retrieval, ranking, emission, effectiveness feedback",
        9: "Target files, criteria, promotion log",
        10: "Domain modules, per-chip activity",
        11: "Outcomes, links, surprise tracking",
        12: "**Config authority** (4-layer precedence), hot-reload, all sections",
    }
    return descs.get(num, "")
