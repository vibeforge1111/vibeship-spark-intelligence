"""LLM interface for Spark Intelligence.

Uses Claude Code CLI (OAuth) — no API keys needed.
Claude Max subscription provides the backing model.

Usage:
    from lib.llm import ask_claude
    result = ask_claude("Summarize these patterns into actionable advice: ...")
"""
# ruff: noqa: S603,S607

from __future__ import annotations

import json
import subprocess
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from lib.diagnostics import log_debug

# Rate limiting: track calls to avoid hammering
_CALL_LOG_FILE = Path.home() / ".spark" / "llm_calls.json"
_MAX_CALLS_PER_HOUR = 30


def _get_claude_path() -> str:
    """Find claude CLI."""
    # Check common locations
    for p in [
        os.path.expanduser("~/.npm-global/claude.cmd"),
        os.path.expanduser("~/.npm-global/claude"),
        "claude",
    ]:
        if Path(p).exists() or p == "claude":
            return p
    return "claude"


def _check_rate_limit() -> bool:
    """Return True if we're under the rate limit."""
    import time
    now = time.time()
    hour_ago = now - 3600

    calls = []
    if _CALL_LOG_FILE.exists():
        try:
            calls = json.loads(_CALL_LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            calls = []

    # Filter to last hour
    calls = [t for t in calls if t > hour_ago]

    if len(calls) >= _MAX_CALLS_PER_HOUR:
        return False

    calls.append(now)
    try:
        _CALL_LOG_FILE.write_text(json.dumps(calls), encoding="utf-8")
    except Exception:
        pass
    return True


def ask_claude(
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    max_tokens: int = 2000,
    timeout_s: int = 60,
) -> Optional[str]:
    """Call Claude via CLI and return the response text.

    On Windows, uses file-based I/O with subprocess because Claude CLI
    requires a console/PTY for OAuth auth that Python subprocess can't provide.
    Falls back to direct subprocess on Linux/Mac.

    Returns None on any failure (auth, timeout, rate limit, etc.).
    """
    if not prompt or not prompt.strip():
        return None

    if not _check_rate_limit():
        log_debug("llm", f"Rate limited ({_MAX_CALLS_PER_HOUR}/hr)", None)
        return None

    claude_path = _get_claude_path()

    if os.name == "nt":
        return _call_claude_windows(claude_path, prompt, system_prompt, timeout_s)
    else:
        return _call_claude_unix(claude_path, prompt, system_prompt, timeout_s)


def _call_claude_windows(
    claude_path: str, prompt: str, system_prompt: Optional[str], timeout_s: int
) -> Optional[str]:
    """Windows: use PowerShell bridge script with 'start /wait /min'.

    Claude CLI on Windows requires a real console/TTY for OAuth auth.
    Python's subprocess doesn't provide one. The workaround:
    1. Write prompt (and optional system prompt) to temp files
    2. Launch 'start /wait /min powershell -File claude_call.ps1' which
       creates a minimized console window — giving Claude its TTY
    3. Read the response from the output file
    """
    spark_dir = Path.home() / ".spark"
    spark_dir.mkdir(parents=True, exist_ok=True)

    prompt_file = spark_dir / "llm_prompt.txt"
    response_file = spark_dir / "llm_response.txt"
    bridge_script = Path(__file__).parent.parent / "scripts" / "claude_call.ps1"

    # Write prompt
    prompt_file.write_text(prompt, encoding="utf-8")

    # Clear response file
    if response_file.exists():
        response_file.unlink()

    # Build the start command
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    cmd.extend(["-File", str(bridge_script)])
    cmd.extend(["-PromptFile", str(prompt_file), "-ResponseFile", str(response_file)])
    if system_prompt:
        sys_file = spark_dir / "llm_system.txt"
        sys_file.write_text(system_prompt, encoding="utf-8")
        cmd.extend(["-SystemFile", str(sys_file)])

    try:
        result = subprocess.run(
            cmd,
            shell=False,
            timeout=timeout_s,
            capture_output=True,
            text=True,
        )

        if response_file.exists():
            # utf-8-sig handles BOM that PowerShell's Set-Content adds
            response = response_file.read_text(encoding="utf-8-sig").strip()
            # Cleanup temp files
            for f in [prompt_file, response_file]:
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
            return response if response else None

        log_debug("llm", f"No response file created (exit={result.returncode})", None)
        return None

    except subprocess.TimeoutExpired:
        log_debug("llm", f"Timed out after {timeout_s}s", None)
        return None
    except Exception as e:
        log_debug("llm", "Windows call failed", e)
        return None


def _call_claude_unix(
    claude_path: str, prompt: str, system_prompt: Optional[str], timeout_s: int
) -> Optional[str]:
    """Unix/Mac: direct subprocess call."""
    cmd = [claude_path, "-p", "--output-format", "text"]
    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])
    cmd.append(prompt)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return None
        return (result.stdout or "").strip() or None
    except Exception:
        return None


def _detect_project_context() -> str:
    """Detect current project from recent events or git."""
    try:
        import subprocess
        # Check most common working directories from recent events
        from lib.queue import read_recent_events
        events = read_recent_events(20)
        dirs = set()
        for ev in events:
            cwd = (ev.data or {}).get("cwd") or (ev.tool_input or {}).get("workdir", "")
            if cwd:
                dirs.add(str(cwd))
            # Also check file paths for project root hints
            ti = ev.tool_input or {}
            fp = ti.get("file_path") or ti.get("path") or ""
            if fp and ("Desktop" in fp or "repos" in fp or "projects" in fp):
                # Extract project directory
                parts = Path(fp).parts
                for i, p in enumerate(parts):
                    if p in ("Desktop", "repos", "projects") and i + 1 < len(parts):
                        dirs.add(str(Path(*parts[:i+2])))
                        break

        if dirs:
            # Get git info for most common dir
            from collections import Counter
            most_common = Counter(dirs).most_common(1)[0][0]
            try:
                r = subprocess.run(
                    ["git", "log", "--oneline", "-3"],
                    capture_output=True, text=True, timeout=5, cwd=most_common
                )
                repo_name = Path(most_common).name
                recent_commits = r.stdout.strip() if r.returncode == 0 else ""
                # Get recently changed files
                r2 = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD~3", "HEAD"],
                    capture_output=True, text=True, timeout=5, cwd=most_common
                )
                changed = r2.stdout.strip() if r2.returncode == 0 else ""
                ctx = f"Project: {repo_name} ({most_common})"
                if recent_commits:
                    ctx += f"\nRecent commits:\n{recent_commits}"
                if changed:
                    files = changed.split("\n")[:10]
                    ctx += f"\nRecently changed files: {', '.join(files)}"
                return ctx
            except Exception:
                return f"Working directory: {most_common}"
    except Exception:
        pass
    return ""


def synthesize_advisory(
    patterns: list,
    insights: list,
    context: str = "",
) -> Optional[str]:
    """Turn raw patterns + insights into actionable advice.

    This is the key function that makes Spark's learnings actually useful.
    """
    if not patterns and not insights:
        return None

    pattern_text = "\n".join(f"- {p}" for p in patterns[:15])
    insight_text = "\n".join(f"- {i}" for i in insights[:15])

    # Auto-detect project context
    project_ctx = _detect_project_context()
    project_name = "the current project"
    if project_ctx:
        # Extract project name from first line
        if "Project: " in project_ctx:
            project_name = project_ctx.split("Project: ")[1].split(" (")[0]

    project_context = f"PROJECT CONTEXT:\n{project_ctx}" if project_ctx else ""
    additional_context = f"ADDITIONAL CONTEXT: {context}" if context else ""
    prompt = f"""You are Spark Intelligence, observing a live coding session on {project_name}.

SYSTEM INVENTORY (what actually exists — do NOT reference anything outside this list):
- Services: sparkd (port 8787, HTTP event ingestion), bridge_worker (background processing), openclaw_tailer (captures OpenClaw sessions), Spark Pulse dashboard (port 8765, uvicorn)
- Key files: lib/bridge_cycle.py (main processing loop), lib/llm.py (Claude CLI integration), lib/cognitive_learner.py (insight storage), lib/feedback_loop.py (agent feedback), lib/agent_feedback.py (report helpers)
- Tools available: Python scripts, PowerShell, git, Claude CLI (OAuth), OpenClaw cron/workspace files
- NO MCP tools, NO Streamlit, NO external APIs, NO databases. This is a file-based Python system.

WHAT'S HAPPENING NOW (patterns from this session):
{pattern_text}

LEARNED INSIGHTS (from past sessions):
{insight_text}

{project_context}
{additional_context}

CRITICAL RULES:
- ONLY recommend things supported by the data above. If the patterns show file edits, talk about those files. If they show errors, address those errors.
- NEVER reference tools, services, or capabilities not in the SYSTEM INVENTORY above.
- Never produce generic coding tips like "batch operations" or "use linting" — those are useless.
- Reference specific files, functions, or behaviors you can see in the data.
- If the data is too vague to make specific recommendations, say "Insufficient data for specific advice" instead of making something up.
- Each recommendation: 1-2 sentences, actionable NOW.
- Format as a numbered list.

NEVER suggest any of these (they are generic waste):
- "Check if services are running" or "verify pipeline flow"
- "Review recent changes" or "check logs"
- "Run tests" or "validate integration"
- "Consider adding error handling"
- Anything about "monitoring" or "observing" patterns
- Restating what already happened as a recommendation

GOOD advisory examples:
- "The repeated edits to api.py suggest the sybil scoring weights need rebalancing — social is at 20% but the data shows 74% single-mention authors, so temporal+fuzzy should be weighted higher."
- "You've edited bridge_cycle.py 4 times this session fixing the same chip merge logic — extract the merge threshold into a config constant."
- "Error pattern: 3 failed exec calls with encoding errors — add sys.stdout.reconfigure(encoding='utf-8') to the entry point."
"""

    return ask_claude(
        prompt,
        system_prompt="You are a concise technical advisor. Output only the numbered recommendations, nothing else.",
        max_tokens=1000,
        timeout_s=45,
    )


def _strip_json_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _resolve_eidos_provider() -> str:
    """Resolve EIDOS LLM provider from config-authority."""
    try:
        from lib.config_authority import resolve_section, env_str
        cfg = resolve_section("eidos", env_overrides={"llm_provider": env_str("SPARK_EIDOS_PROVIDER")}).data
        return str(cfg.get("llm_provider", "minimax")).strip().lower()
    except Exception:
        return (os.getenv("SPARK_EIDOS_PROVIDER") or "minimax").strip().lower()


def _ask_distillation_model(prompt: str, *, timeout_s: int = 45) -> Optional[str]:
    preferred = _resolve_eidos_provider()

    # Try provider chain first (MiniMax-preferred for structured distillation).
    try:
        from lib.advisory_synthesizer import _query_provider  # type: ignore

        chain: List[str] = []
        for p in [preferred, "gemini", "openai", "anthropic", "ollama"]:
            if p and p not in chain:
                chain.append(p)

        for provider in chain:
            resp = _query_provider(provider, prompt)
            if resp and resp.strip():
                return resp.strip()
    except Exception:
        pass

    # Fallback to Claude CLI path.
    return ask_claude(
        prompt,
        system_prompt="Return only valid JSON.",
        max_tokens=1200,
        timeout_s=timeout_s,
    )


def _infer_emotional_signal(evidence: str, action: str, usage_context: str) -> Dict[str, Any]:
    text = f"{evidence} {action} {usage_context}".lower()

    lexicon = {
        "frustration": ["frustrat", "stuck", "blocked", "drift", "not working", "failed", "issue", "error"],
        "stress": ["pressure", "overload", "overwhelmed", "urgent", "deadline", "chaos"],
        "relief": ["resolved", "stable", "fixed", "recovered", "unblocked"],
        "joy": ["great", "happy", "loved", "amazing", "beautiful", "perfect"],
        "breakthrough": ["breakthrough", "insight", "unlock", "clarity", "worked", "improved"],
    }

    scores: Dict[str, float] = {}
    for label, terms in lexicon.items():
        hit = sum(1 for t in terms if t in text)
        scores[label] = min(1.0, hit * 0.25)

    top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    primary, intensity = top[0] if top else ("neutral", 0.0)
    if intensity <= 0.0:
        primary = "neutral"

    # bounded multiplier (emotion boosts but does not dominate)
    multiplier = 1.0 + min(0.35, intensity * 0.35)
    return {
        "type": primary,
        "intensity": round(float(intensity), 3),
        "multiplier": round(float(multiplier), 3),
    }


def _compute_priority_score(confidence: float, decision: str, emotional_signal: Dict[str, Any], usage_context: str) -> float:
    base = confidence
    if decision == "drop":
        return round(max(0.0, base * 0.35), 3)

    usage_bonus = 0.08 if usage_context.strip() else 0.0
    mult = float(emotional_signal.get("multiplier") or 1.0)
    # cap final score in [0,1]
    return round(max(0.0, min(1.0, (base + usage_bonus) * mult)), 3)


def _normalize_distillation_payload(raw: str) -> Optional[Dict[str, Any]]:
    txt = _strip_json_fence(raw)
    try:
        data = json.loads(txt)
    except Exception:
        return None

    insights = data.get("insights") if isinstance(data, dict) else None
    if not isinstance(insights, list):
        return None

    out: List[Dict[str, Any]] = []
    for it in insights[:6]:
        if not isinstance(it, dict):
            continue
        decision = str(it.get("decision") or "drop").strip().lower()
        if decision not in {"keep", "drop"}:
            decision = "drop"

        confidence = it.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        evidence = str(it.get("evidence") or "").strip()[:500]
        action = str(it.get("action") or "").strip()[:500]
        usage_context = str(it.get("usage_context") or "").strip()[:240]

        emotional_signal = _infer_emotional_signal(evidence, action, usage_context)
        priority_score = _compute_priority_score(confidence, decision, emotional_signal, usage_context)

        item = {
            "insight_type": str(it.get("insight_type") or "pattern").strip()[:40],
            "confidence": round(confidence, 3),
            "evidence": evidence,
            "action": action,
            "usage_context": usage_context,
            "decision": decision,
            "emotional_signal": emotional_signal,
            "priority_score": priority_score,
        }
        if item["action"] and item["evidence"]:
            out.append(item)

    if not out:
        return None

    kept = [x for x in out if x["decision"] == "keep"]
    final = kept if kept else out[:3]
    # rank by usable priority so advisory gets best candidates first
    final = sorted(final, key=lambda x: float(x.get("priority_score") or 0.0), reverse=True)
    return {
        "schema": "spark.eidos.v1",
        "insights": final[:3],
        "meta": {
            "provider": _resolve_eidos_provider(),
            "count": len(final[:3]),
        },
    }


def distill_eidos(
    raw_observations: list,
    current_eidos: Optional[str] = None,
) -> Optional[str]:
    """Distill raw observations into structured EIDOS updates.

    Returns JSON string with schema spark.eidos.v1 and insight entries ready
    for downstream advisory use.
    """
    if not raw_observations:
        return None

    obs_text = "\n".join(f"- {o}" for o in raw_observations[:24])

    current_self_mode = f"CURRENT SELF-MODEL:\n{current_eidos[:700]}" if current_eidos else ""
    prompt = f"""You are distilling Spark behavior observations into a structured advisory-ready format.

OBSERVATIONS:
{obs_text}

{current_self_mode}

Return ONLY valid JSON with this exact shape:
{{
  "insights": [
    {{
      "insight_type": "pattern|failure|strength|workflow|communication",
      "confidence": 0.0,
      "evidence": "short concrete evidence from observations",
      "action": "specific action to improve behavior",
      "usage_context": "where this should be used (situation/context)",
      "decision": "keep|drop"
    }}
  ]
}}

Rules:
- 1 to 3 insights maximum
- keep only insights that are specific, actionable, and reusable
- if observation is noisy/error-like or vague, mark decision=drop
- do not include any text outside JSON
"""

    raw = _ask_distillation_model(prompt, timeout_s=45)
    if not raw:
        return None

    payload = _normalize_distillation_payload(raw)
    if not payload:
        return None

    return json.dumps(payload, ensure_ascii=False)


def interpret_patterns(events_summary: str) -> Optional[str]:
    """Use LLM to find deeper patterns in event data that rule-based detection misses."""
    if not events_summary:
        return None

    prompt = f"""Analyze these coding session events for non-obvious patterns:

{events_summary[:3000]}

Look for:
- Repeated mistakes or inefficiencies
- Workflow anti-patterns
- Opportunities for automation
- Things going well that should be reinforced

Output 2-5 observations, each 1-2 sentences."""

    return ask_claude(
        prompt,
        system_prompt="You are a coding workflow analyst. Be specific and actionable.",
        max_tokens=800,
        timeout_s=45,
    )
