"""Lightweight agent orchestration and routing.

KISS: file-based persistence, minimal features, no external deps.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .skills_router import recommend_skills
from .context_sync import build_compact_context
from .exposure_tracker import record_exposures
from .outcome_log import append_outcomes, make_outcome_id


_TRUTHY = {"1", "true", "yes", "on"}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def _load_orchestration_config() -> Dict[str, Any]:
    """Load orchestration settings through config-authority."""
    try:
        from .config_authority import resolve_section, env_bool, env_int
        # SPARK_AGENT_CONTEXT_LIMIT is a legacy alias for context_max_chars
        env_max_chars = env_int("SPARK_AGENT_CONTEXT_MAX_CHARS")
        if env_max_chars is None:
            env_max_chars = env_int("SPARK_AGENT_CONTEXT_LIMIT")
        return resolve_section(
            "orchestration",
            env_overrides={
                "inject_enabled": env_bool("SPARK_AGENT_INJECT"),
                "context_max_chars": env_max_chars,
                "context_item_limit": env_int("SPARK_AGENT_CONTEXT_ITEM_LIMIT"),
            },
        ).data
    except Exception:
        return {}


def inject_agent_context(
    prompt: str,
    *,
    project_dir: Optional[Path] = None,
    limit: int = 3,
) -> str:
    """Optionally prepend Spark context to an agent prompt.

    Enable via SPARK_AGENT_INJECT=1 to avoid unexpected prompt bloat.
    """
    if not prompt:
        return prompt

    cfg = _load_orchestration_config()
    if not cfg.get("inject_enabled", False) and not _env_truthy("SPARK_AGENT_INJECT"):
        return prompt

    max_chars = int(cfg.get("context_max_chars", 1200))
    limit = int(cfg.get("context_item_limit", limit))

    context, _ = build_compact_context(project_dir=project_dir, limit=limit)
    if not context:
        return prompt

    if max_chars > 0 and len(context) > max_chars:
        context = context[:max_chars].rstrip()

    return f"{context}\n\n{prompt}"


@dataclass
class Agent:
    agent_id: str
    name: str
    capabilities: List[str]
    specialization: str = "general"
    registered_at: float = field(default_factory=lambda: time.time())
    success_rate: float = 0.5
    total_tasks: int = 0
    success_count: int = 0
    fail_count: int = 0


class SparkOrchestrator:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or (Path.home() / ".spark" / "orchestration")
        self.agents_file = self.root_dir / "agents.json"
        self.handoffs_file = self.root_dir / "handoffs.jsonl"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.agents: Dict[str, Agent] = self._load_agents()

    # -------- Persistence --------
    def _load_agents(self) -> Dict[str, Agent]:
        if not self.agents_file.exists():
            return {}
        try:
            data = json.loads(self.agents_file.read_text(encoding="utf-8"))
            return {k: Agent(**v) for k, v in data.items()}
        except Exception:
            return {}

    def _save_agents(self) -> None:
        data = {k: asdict(v) for k, v in self.agents.items()}
        self.agents_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # -------- Agents --------
    def register_agent(self, agent_id: str, name: str, capabilities: List[str], specialization: str = "general") -> bool:
        if not agent_id:
            return False
        self.agents[agent_id] = Agent(
            agent_id=agent_id,
            name=name or agent_id,
            capabilities=capabilities or [],
            specialization=specialization or "general",
        )
        self._save_agents()
        return True

    def list_agents(self) -> List[Dict]:
        return [asdict(a) for a in self.agents.values()]

    def update_agent_result(self, agent_id: str, success: bool) -> None:
        if agent_id not in self.agents:
            return
        agent = self.agents[agent_id]
        agent.total_tasks += 1
        if success:
            agent.success_count += 1
        else:
            agent.fail_count += 1
        agent.success_rate = agent.success_count / max(agent.total_tasks, 1)
        self._save_agents()

    # -------- Routing --------
    def recommend_agent(self, query: str, task_type: str = "") -> Tuple[Optional[str], str]:
        q = (query or "").strip()
        if not q:
            return None, "No query provided"

        skills = recommend_skills(q, limit=3)
        if skills:
            skill_ids = [s.get("skill_id") or s.get("name") for s in skills if (s.get("skill_id") or s.get("name"))]
            candidates = [
                a for a in self.agents.values()
                if any(cap in skill_ids for cap in a.capabilities)
            ]
            if candidates:
                best = max(candidates, key=lambda a: a.success_rate)
                return best.agent_id, f"Matched skills {', '.join(skill_ids[:2])}"

        # Fallback: match on capability tokens
        tokens = {t for t in (task_type or q).lower().split() if t}
        scored = []
        for a in self.agents.values():
            caps = " ".join(a.capabilities).lower()
            score = sum(1 for t in tokens if t in caps)
            if score:
                scored.append((score, a))
        if scored:
            scored.sort(key=lambda x: (x[0], x[1].success_rate), reverse=True)
            return scored[0][1].agent_id, "Matched capability tokens"

        return None, "No suitable agent found"

    # -------- Handoffs --------
    def record_handoff(self, from_agent: str, to_agent: str, context: Dict, success: Optional[bool] = None) -> str:
        handoff_id = f"handoff_{int(time.time() * 1000)}"
        ctx = dict(context or {})
        prompt = ctx.get("prompt")
        if isinstance(prompt, str):
            injected = inject_agent_context(prompt, project_dir=None)
            if injected != prompt:
                ctx["prompt"] = injected
                ctx["spark_context_injected"] = True
        handoff_text = _handoff_text(ctx, to_agent)
        entry = {
            "handoff_id": handoff_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "context": ctx,
            "success": success,
            "timestamp": time.time(),
        }
        with self.handoffs_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        try:
            try:
                from lib.exposure_tracker import infer_latest_trace_id, infer_latest_session_id
                session_id = infer_latest_session_id()
                trace_id = infer_latest_trace_id(session_id)
            except Exception:
                session_id = None
                trace_id = None
            record_exposures(
                "orchestration",
                [{
                    "insight_key": handoff_id,
                    "category": "orchestration",
                    "text": handoff_text,
                }],
                session_id=session_id,
                trace_id=trace_id,
            )
        except Exception:
            pass
        if success is not None:
            append_outcomes([{
                "outcome_id": make_outcome_id(handoff_id, str(success)),
                "event_type": "handoff_result",
                "tool": None,
                "text": f"{handoff_text} -> {'success' if success else 'failure'}",
                "polarity": "pos" if success else "neg",
                "created_at": time.time(),
                "domain": "orchestration",
                "agent_id": to_agent,
                "handoff_id": handoff_id,
                "trace_id": trace_id,
            }])
            self.update_agent_result(to_agent, success)
        return handoff_id


def _handoff_text(ctx: Dict, to_agent: str) -> str:
    prompt = ctx.get("prompt") or ctx.get("task") or ctx.get("summary") or ""
    if isinstance(prompt, dict):
        prompt = prompt.get("text") or prompt.get("prompt") or ""
    text = str(prompt).replace("\n", " ").strip()
    if text:
        return f"Handoff to {to_agent}: {text[:200]}"
    return f"Handoff to {to_agent}"


# Singleton helpers
_orch: Optional[SparkOrchestrator] = None


def get_orchestrator() -> SparkOrchestrator:
    global _orch
    if _orch is None:
        _orch = SparkOrchestrator()
    return _orch


def register_agent(agent_id: str, name: str, capabilities: List[str], specialization: str = "general") -> bool:
    return get_orchestrator().register_agent(agent_id, name, capabilities, specialization)


def recommend_agent(query: str, task_type: str = "") -> Tuple[Optional[str], str]:
    return get_orchestrator().recommend_agent(query, task_type)


def record_handoff(from_agent: str, to_agent: str, context: Dict, success: Optional[bool] = None) -> str:
    return get_orchestrator().record_handoff(from_agent, to_agent, context, success)
