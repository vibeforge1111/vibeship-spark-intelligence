"""Workflow evidence reader for advisory pipeline (Phase D1).

Reads workflow_summary JSON reports from all three providers (claude, codex, openclaw)
and converts them into high-signal advisory evidence. Also computes recovery effectiveness
metrics (Phase D2): failure -> advisory -> success chains by provider and tool.

Report directories:
  - Claude:  ~/.spark/workflow_reports/claude/
  - Codex:   ~/.spark/workflow_reports/codex/
  - OpenClaw: ~/.openclaw/workspace/spark_reports/workflow/
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config_authority import env_float, env_int, resolve_section

logger = logging.getLogger(__name__)

# ── Report directories ──────────────────────────────────────────────

WORKFLOW_REPORT_DIRS: Dict[str, Path] = {
    "claude": Path.home() / ".spark" / "workflow_reports" / "claude",
    "codex": Path.home() / ".spark" / "workflow_reports" / "codex",
    "openclaw": Path.home() / ".openclaw" / "workspace" / "spark_reports" / "workflow",
}
TUNEABLES_FILE = Path.home() / ".spark" / "tuneables.json"
BASELINE_TUNEABLES_FILE = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"

# ── Tuneable defaults (overridden from tuneables.json -> workflow_evidence) ──

MAX_SUMMARIES_PER_PROVIDER = 10
MAX_AGE_S = 3600  # 1 hour — only recent summaries matter for advisory
MIN_TOOL_FAILURES_FOR_ADVISORY = 1  # at least 1 failure to be worth surfacing
RECOVERY_BOOST = 0.20  # extra importance for recovered-tool patterns
WORKFLOW_SOURCE_QUALITY = 0.82  # between replay (0.85) and self_awareness (0.80)


def load_tuneables() -> None:
    """Reload workflow evidence tuneables from config authority."""
    global MAX_SUMMARIES_PER_PROVIDER, MAX_AGE_S, MIN_TOOL_FAILURES_FOR_ADVISORY
    global RECOVERY_BOOST, WORKFLOW_SOURCE_QUALITY
    try:
        cfg = resolve_section(
            "workflow_evidence",
            baseline_path=BASELINE_TUNEABLES_FILE,
            runtime_path=TUNEABLES_FILE,
            env_overrides={
                "max_summaries_per_provider": env_int("SPARK_WORKFLOW_EVIDENCE_MAX_SUMMARIES"),
                "max_age_s": env_int("SPARK_WORKFLOW_EVIDENCE_MAX_AGE_S"),
                "min_tool_failures_for_advisory": env_int("SPARK_WORKFLOW_EVIDENCE_MIN_TOOL_FAILURES"),
                "recovery_boost": env_float("SPARK_WORKFLOW_EVIDENCE_RECOVERY_BOOST"),
                "source_quality": env_float("SPARK_WORKFLOW_EVIDENCE_SOURCE_QUALITY"),
            },
        ).data
        if not isinstance(cfg, dict):
            return
        MAX_SUMMARIES_PER_PROVIDER = max(
            1,
            int(cfg.get("max_summaries_per_provider", MAX_SUMMARIES_PER_PROVIDER)),
        )
        MAX_AGE_S = max(60, int(cfg.get("max_age_s", MAX_AGE_S)))
        MIN_TOOL_FAILURES_FOR_ADVISORY = max(
            0,
            int(cfg.get("min_tool_failures_for_advisory", MIN_TOOL_FAILURES_FOR_ADVISORY)),
        )
        RECOVERY_BOOST = max(0.0, min(0.5, float(cfg.get("recovery_boost", RECOVERY_BOOST))))
        WORKFLOW_SOURCE_QUALITY = max(
            0.1,
            min(1.0, float(cfg.get("source_quality", WORKFLOW_SOURCE_QUALITY))),
        )
    except Exception as exc:
        logger.debug("workflow_evidence load_tuneables: %s", exc)


# ── Workflow summary reader ─────────────────────────────────────────

def _read_summaries(
    provider: str,
    report_dir: Path,
    *,
    max_age_s: float = 0,
    limit: int = 0,
) -> List[Dict[str, Any]]:
    """Read recent workflow_summary JSON files from a provider directory."""
    if not report_dir.exists():
        return []

    now = time.time()
    age_cutoff = now - (max_age_s or MAX_AGE_S)
    cap = limit or MAX_SUMMARIES_PER_PROVIDER
    results: List[Tuple[float, Dict[str, Any]]] = []

    try:
        for fp in report_dir.glob("workflow_*.json"):
            if not fp.is_file():
                continue
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            ts = float(data.get("ts") or 0)
            if ts < age_cutoff:
                continue
            data.setdefault("provider", provider)
            results.append((ts, data))
    except OSError as exc:
        logger.debug("workflow_evidence scan %s: %s", provider, exc)

    results.sort(key=lambda x: x[0], reverse=True)
    return [r[1] for r in results[:cap]]


def get_all_recent_summaries(
    *,
    max_age_s: float = 0,
    limit_per_provider: int = 0,
    providers: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Get recent workflow summaries from all (or specified) providers."""
    load_tuneables()
    targets = providers or list(WORKFLOW_REPORT_DIRS.keys())
    all_summaries: List[Dict[str, Any]] = []
    for prov in targets:
        rd = WORKFLOW_REPORT_DIRS.get(prov)
        if not rd:
            continue
        all_summaries.extend(
            _read_summaries(prov, rd, max_age_s=max_age_s, limit=limit_per_provider)
        )
    all_summaries.sort(key=lambda s: float(s.get("ts") or 0), reverse=True)
    return all_summaries


# ── Advisory evidence conversion ────────────────────────────────────

def summaries_to_advisory_evidence(
    summaries: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Convert workflow summaries into advisory evidence items.

    Each item has: text, source, confidence, context_match, insight_key, provider.
    High-signal items: tool failures, recovery tools, low success rates.
    """
    if summaries is None:
        summaries = get_all_recent_summaries()

    evidence: List[Dict[str, Any]] = []
    seen_keys: set = set()

    for s in summaries:
        provider = s.get("provider", "unknown")
        failures = int(s.get("tool_failures") or 0)
        successes = int(s.get("tool_successes") or 0)
        results_total = int(s.get("tool_results") or 0)
        recovery_tools = s.get("recovery_tools") or []
        top_tools = s.get("top_tools") or []
        session_key = s.get("session_key", "")[:16]

        if failures < MIN_TOOL_FAILURES_FOR_ADVISORY and not recovery_tools:
            continue

        # Recovery evidence (highest signal)
        for tool_name in recovery_tools:
            key = f"workflow:recovery:{provider}:{tool_name}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            text = (
                f"Tool '{tool_name}' failed then recovered in {provider} session. "
                f"Recovery pattern detected — prior failures for this tool may be transient."
            )
            evidence.append({
                "text": text,
                "source": "workflow",
                "confidence": 0.85,
                "context_match": 0.0,  # filled by advisor context matching
                "insight_key": key,
                "provider": provider,
                "signal_type": "recovery",
                "tool_name": tool_name,
            })

        # Failure-rate evidence
        if failures >= MIN_TOOL_FAILURES_FOR_ADVISORY and results_total > 0:
            rate = failures / results_total
            if rate >= 0.20:  # 20%+ failure rate is notable
                key = f"workflow:failure_rate:{provider}:{session_key}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    # List failed tools
                    tool_list = ", ".join(t.get("tool_name", "?") for t in top_tools[:5])
                    text = (
                        f"{provider} session: {failures}/{results_total} tool results failed "
                        f"({rate:.0%} failure rate). Top tools: {tool_list}. "
                        f"Consider checking environment or inputs before retrying."
                    )
                    evidence.append({
                        "text": text,
                        "source": "workflow",
                        "confidence": min(0.90, 0.60 + rate),
                        "context_match": 0.0,
                        "insight_key": key,
                        "provider": provider,
                        "signal_type": "failure_rate",
                    })

    return evidence


# ── Recovery effectiveness metric (Phase D2) ────────────────────────

def compute_recovery_metrics(
    summaries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute recovery effectiveness metrics from workflow summaries.

    Returns breakdown by provider and tool:
      - total_sessions: sessions with any tool results
      - sessions_with_failures: sessions where failures occurred
      - sessions_with_recovery: sessions where a tool both failed and succeeded
      - recovery_rate: sessions_with_recovery / sessions_with_failures
      - per_provider: {provider: {sessions, failures, recoveries, rate}}
      - per_tool: {tool_name: {failures_total, recoveries_total, rate}}
    """
    if summaries is None:
        summaries = get_all_recent_summaries(max_age_s=86400)  # 24h window for metrics

    total_sessions = 0
    sessions_with_failures = 0
    sessions_with_recovery = 0

    per_provider: Dict[str, Dict[str, int]] = {}
    per_tool: Dict[str, Dict[str, int]] = {}

    for s in summaries:
        results_total = int(s.get("tool_results") or 0)
        if results_total == 0:
            continue

        total_sessions += 1
        provider = s.get("provider", "unknown")
        failures = int(s.get("tool_failures") or 0)
        recovery_tools = s.get("recovery_tools") or []

        # Provider stats
        prov = per_provider.setdefault(provider, {
            "sessions": 0, "failures": 0, "recoveries": 0,
        })
        prov["sessions"] += 1

        has_failure = failures > 0
        has_recovery = len(recovery_tools) > 0

        if has_failure:
            sessions_with_failures += 1
            prov["failures"] += 1
        if has_recovery:
            sessions_with_recovery += 1
            prov["recoveries"] += 1

        # Tool-level stats from recovery_tools
        for tool_name in recovery_tools:
            t = per_tool.setdefault(tool_name, {"failures_total": 0, "recoveries_total": 0})
            t["recoveries_total"] += 1
            t["failures_total"] += 1  # recovered implies at least 1 failure

    # Compute rates
    for prov_stats in per_provider.values():
        f = prov_stats["failures"]
        prov_stats["rate"] = round(prov_stats["recoveries"] / f, 3) if f > 0 else 0.0

    for tool_stats in per_tool.values():
        f = tool_stats["failures_total"]
        tool_stats["rate"] = round(tool_stats["recoveries_total"] / f, 3) if f > 0 else 0.0

    overall_rate = 0.0
    if sessions_with_failures > 0:
        overall_rate = round(sessions_with_recovery / sessions_with_failures, 3)

    return {
        "total_sessions": total_sessions,
        "sessions_with_failures": sessions_with_failures,
        "sessions_with_recovery": sessions_with_recovery,
        "recovery_rate": overall_rate,
        "per_provider": per_provider,
        "per_tool": per_tool,
        "computed_at": time.time(),
        "window_s": 86400,
    }
