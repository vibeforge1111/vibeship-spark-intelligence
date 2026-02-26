"""
DEPTH Trainer -- Socratic reasoning gym for Spark Intelligence.

An autonomous self-learning loop that:
1. Discovers what topics Spark needs to train on (self-search)
2. Runs DEPTH sessions generating answers via Ollama
3. Feeds results through Meta-Ralph quality gate (Ralph Wiggum loop)
4. Stores validated insights into EIDOS, Cognitive Learner, and chips
5. Tracks improvement over time and identifies persistent gaps
6. Uses prior learnings to improve future answers (cross-session learning)
7. Reflects after each session to generate adaptive strategies
8. Integrates pushback from DEPTH into subsequent answers
9. Uses chain-of-thought reasoning at early depths for deeper answers
10. Loops autonomously, getting smarter each cycle

Usage:
    python -m lib.depth_trainer --topic "learning"         # Single topic
    python -m lib.depth_trainer --all                      # All chip domains
    python -m lib.depth_trainer --self                     # Meta self-assessment
    python -m lib.depth_trainer --loop                     # Autonomous loop (runs until stopped)
    python -m lib.depth_trainer --loop --cycles 5          # 5 autonomous cycles
    python -m lib.depth_trainer --history                  # Show training history
    python -m lib.depth_trainer --report                   # Weakness analysis
    python -m lib.depth_trainer --dashboard                # Full status dashboard
    python -m lib.depth_trainer --ingest PATH              # Ingest Opus-scored sessions from JSONL
    python -m lib.depth_trainer --ingest-all-opus          # Ingest all from ~/.spark/depth_opus_sessions.jsonl
    python -m lib.depth_trainer --topic "caching" --forge-score  # Re-score with Opus+Codex dual scoring
    python -m lib.depth_trainer --loop --cycles 2 --forge-score  # Autonomous loop with forge scoring
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

log = logging.getLogger("spark.depth_trainer")


def _safe_print(text: str):
    """Print text safely on Windows (handles Unicode encoding errors)."""
    try:
        print(text)
    except UnicodeEncodeError:
        # Strip non-ASCII characters for Windows console
        clean = text.encode("ascii", errors="replace").decode("ascii")
        print(clean)


def _is_gibberish(text: str) -> bool:
    """Detect if Ollama output is garbled/nonsensical.

    phi4-mini sometimes produces token soup. Detect it early
    so we can fall back to a coherent response.
    """
    if len(text) < 20:
        return True
    # High ratio of special chars or very short words
    words = text.split()
    if not words:
        return True
    avg_word_len = sum(len(w) for w in words) / len(words)
    if avg_word_len < 2:
        return True
    # Too many fragments that look like prompt leaking
    leak_signals = [
        "function is", "categor", "You are", "Given a",
        "assistant", "$", "scenario", "need to",
        "generates", "represents", "is separated",
    ]
    leak_count = sum(1 for s in leak_signals if s.lower() in text.lower())
    if leak_count >= 4:
        return True
    return False


_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def _strip_thinking_tags(text: Optional[str]) -> str:
    """Strip provider reasoning blocks like <think>...</think>."""
    if not text:
        return ""
    return _THINK_TAG_RE.sub("", text).strip()

DEPTH_API = "http://localhost:5555"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "kimi-k2.5:cloud"  # Kimi 2.5 — strong engineering reasoning via Ollama cloud

# ──────────────────────────────────────────────
# DeepSeek Isolation — Answer Generation Only
# See DEEPSEEK_ISOLATION_RULES.md for full spec
# DeepSeek sees ONLY: question, topic, depth, mode, level info
# DeepSeek NEVER sees: Spark internals, scores, knowledge, strategies
# ──────────────────────────────────────────────

# Sanitized prompt — NO Spark/Vibeship references, NO training context
_DEEPSEEK_ANSWER_PROMPT = """You are answering a technical evaluation question.

Domain: {domain_id}
Topic: {topic}
Depth Level: {depth} / {max_depth} ({level_name})
Perspective: {level_lens}

Question:
{question}
{approach_guidance}
Provide a thorough, specific, and actionable answer. Follow ALL of these rules:

1. TRADEOFFS ARE MANDATORY: For every recommendation, state what you lose and what it costs.
   Write at least one sentence starting with "The downside is..." or "You lose..."
2. REAL-WORLD FIT: Answer as if the team is 2-5 developers with limited budget.
   Do NOT suggest enterprise tooling unless the question explicitly requires it.
   Name the simplest approach that works, then mention when to upgrade.
3. COMPLETE CODE: Finish all code blocks. Never truncate functions or configs mid-block.
   If the answer is getting long, focus on the critical 30 lines rather than an incomplete 80 lines.
4. SPECIFICITY: Name exact tools with versions, exact config values, exact CLI flags.
   "Use a cache" is wrong. "Use Redis 7.2 with maxmemory-policy allkeys-lru" is right."""

_DEEPSEEK_LOG_PATH = Path.home() / ".spark" / "logs" / "deepseek_calls.jsonl"

# Fields that are ALLOWED in DeepSeek prompts (whitelist)
_ALLOWED_PROMPT_FIELDS = {
    "question", "topic", "depth", "max_depth", "mode",
    "level_name", "level_lens", "domain_id",
    "approach_guidance",  # Sanitized advisory hints (no Spark internals)
}

_MAX_ANSWER_LENGTH = 8000


def _load_env_key(name: str) -> str:
    """Load API key from env var, falling back to .env file."""
    import os
    val = os.environ.get(name, "")
    if val:
        return val
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


class DepthAnswerGenerator:
    """Isolated answer generator — model-swappable, prompt-sanitized.

    DeepSeek (or any external provider) receives ONLY a sanitized prompt
    with zero Spark/Vibeship context. Responses are treated as untrusted text.
    """

    PROVIDERS = {
        "deepseek": {
            "endpoint": "https://api.deepseek.com/v1/chat/completions",
            "model": "deepseek-chat",
            "key_env": "DEEPSEEK_API_KEY",
        },
        "minimax": {
            "endpoint": os.getenv("DEPTH_MINIMAX_ENDPOINT", "https://api.minimax.io/v1/chat/completions"),
            "model": os.getenv("DEPTH_MINIMAX_MODEL", "MiniMax-M2.5"),
            "key_env": "MINIMAX_API_KEY",
        },
        "ollama": {
            "endpoint": OLLAMA_URL,
            "model": OLLAMA_MODEL,
            "key_env": None,
        },
    }

    def __init__(self, provider: str = None):
        import os
        self.provider = provider or os.getenv("DEPTH_ANSWER_PROVIDER", "deepseek")
        if self.provider not in self.PROVIDERS:
            log.warning("Unknown provider %s, falling back to ollama", self.provider)
            self.provider = "ollama"
        self.config = self.PROVIDERS[self.provider]
        self._api_key = ""
        if self.config["key_env"]:
            self._api_key = _load_env_key(self.config["key_env"])
            if not self._api_key:
                log.warning("No %s found, falling back to ollama", self.config["key_env"])
                self.provider = "ollama"
                self.config = self.PROVIDERS["ollama"]

    async def generate(
        self, question: str, topic: str, depth: int, max_depth: int,
        domain_id: str, mode: str, level_name: str, level_lens: str,
        approach_guidance: str = "",
    ) -> Optional[str]:
        """Generate answer using configured provider with sanitized prompt."""
        # Format approach_guidance block (only if provided)
        guidance_block = ""
        if approach_guidance:
            guidance_block = f"\nApproach guidance:\n{approach_guidance}\n"
        prompt = self._build_sanitized_prompt(
            question=question, topic=topic, depth=depth, max_depth=max_depth,
            domain_id=domain_id, mode=mode, level_name=level_name,
            level_lens=level_lens, approach_guidance=guidance_block,
        )

        t0 = time.time()
        raw = await self._call_api(prompt, depth)
        latency_ms = int((time.time() - t0) * 1000)

        answer = self._sanitize_response(raw)
        self._log_call(domain_id, topic, depth, question, answer, latency_ms)
        return answer

    def _build_sanitized_prompt(self, **kwargs) -> str:
        """Build prompt from ALLOWED fields only. Rejects any blocked content."""
        for key in kwargs:
            if key not in _ALLOWED_PROMPT_FIELDS:
                raise ValueError(f"Blocked field in DeepSeek prompt: {key}")
        return _DEEPSEEK_ANSWER_PROMPT.format(**kwargs)

    async def _call_api(self, prompt: str, depth: int) -> Optional[str]:
        """Call the configured provider API."""
        timeout = 90.0 + (depth * 8.0)

        if self.provider == "ollama":
            return await self._call_ollama(prompt, timeout, depth)
        else:
            return await self._call_openai_compat(prompt, timeout)

    async def _call_openai_compat(self, prompt: str, timeout: float) -> Optional[str]:
        """Call OpenAI-compatible API (DeepSeek). Stateless, single-turn."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            # No custom headers that reveal project identity
        }
        payload = {
            "model": self.config["model"],
            "messages": [{"role": "user", "content": prompt}],  # Single-turn only
            "max_tokens": 4096,
            "temperature": 0.7,
        }
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        self.config["endpoint"], json=payload, headers=headers,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["choices"][0]["message"]["content"]
                    else:
                        log.warning(
                            "%s API error %d: %s",
                            self.provider, resp.status_code, resp.text[:200],
                        )
            except Exception as e:
                log.warning("%s API error (attempt %d): %s", self.provider, attempt + 1, e)
        return None

    async def _call_ollama(self, prompt: str, timeout: float, depth: int) -> Optional[str]:
        """Call local Ollama. Same sanitized prompt, no Spark context."""
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        self.config["endpoint"],
                        json={
                            "model": self.config["model"],
                            "prompt": prompt,
                            "stream": False,
                            "options": {
                                "temperature": 0.7 if depth > 4 else 0.8,
                                "num_predict": 2048,
                            },
                        },
                    )
                    if resp.status_code == 200:
                        text = resp.json().get("response", "").strip()
                        if text and len(text) > 20 and not _is_gibberish(text):
                            return text
            except httpx.TimeoutException:
                log.warning("Ollama timeout depth %d attempt %d", depth, attempt + 1)
                timeout += 15.0
            except Exception as e:
                log.warning("Ollama error depth %d: %s", depth, e)
                break
        return None

    def _sanitize_response(self, raw: Optional[str]) -> Optional[str]:
        """Treat response as UNTRUSTED TEXT. Truncate, check coherence."""
        if not raw:
            return None
        # Strip to plain text, truncate
        answer = _strip_thinking_tags(raw)[:_MAX_ANSWER_LENGTH]
        # Coherence check
        if not answer or len(answer) < 20 or _is_gibberish(answer):
            return None
        return answer

    def _log_call(
        self, domain: str, topic: str, depth: int,
        question: str, answer: Optional[str], latency_ms: int,
    ):
        """Log DeepSeek call with MINIMAL metadata. No full prompts/answers."""
        if self.provider == "ollama":
            return  # Only log external API calls
        _DEEPSEEK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "domain": domain,
            "topic": topic,
            "depth": depth,
            "question_hash": hashlib.sha256(question.encode()).hexdigest()[:16],
            "answer_length": len(answer) if answer else 0,
            "latency_ms": latency_ms,
            "model": self.config["model"],
            "status": "success" if answer else "failure",
        }
        try:
            with open(_DEEPSEEK_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


SPARK_DIR = Path.home() / ".spark"
TRAINING_LOG = SPARK_DIR / "depth_training.jsonl"
KNOWLEDGE_BASE = SPARK_DIR / "depth_knowledge.json"
TOPIC_QUEUE = SPARK_DIR / "depth_topic_queue.json"
STRATEGY_MEMORY = SPARK_DIR / "depth_strategies.json"
BENCHMARK_LOG = SPARK_DIR / "depth_benchmarks.jsonl"
GAPS_FILE = SPARK_DIR / "depth_gaps.json"
GOLDEN_ANSWERS_FILE = SPARK_DIR / "depth_golden_answers.json"
BENCHMARKS_DIR = Path(os.getenv("DEPTH_GAME_PATH", str(Path(__file__).resolve().parent.parent / "vibeship-depth-game"))) / "benchmarks"

# -- Depth levels and Socratic lenses --
# Classic 10-level philosophical lenses (backward compat)
DEPTH_LENSES_CLASSIC = {
    1: "Define", 2: "Decompose", 3: "Trace", 4: "Challenge",
    5: "Expose", 6: "Link", 7: "Contradict", 8: "Dissolve",
    9: "Invert", 10: "Silence",
}

# v2 15-level engineering lenses
DEPTH_LENSES = {
    1: "Build", 2: "Architect", 3: "Tradeoff", 4: "Attack",
    5: "Profile", 6: "Probe", 7: "Experience", 8: "Multiply",
    9: "Connect", 10: "Distill", 11: "Clarify", 12: "Foresee",
    13: "Create", 14: "Judge", 15: "Unify",
}

DEPTH_DESCRIPTIONS = {
    1: "precise implementation -- write the exact code/steps",
    2: "architectural decomposition -- what are the moving parts?",
    3: "tradeoff reasoning -- why this over alternatives?",
    4: "adversarial thinking -- how would you break this?",
    5: "performance profiling -- what's the bottleneck?",
    6: "edge case reasoning -- what happens when...?",
    7: "UX empathy -- how does a real user feel?",
    8: "scalability reasoning -- what happens at 100x?",
    9: "systems thinking -- how does this connect to everything?",
    10: "simplification -- same result, half the code?",
    11: "teaching -- explain to a stuck junior dev",
    12: "maintenance foresight -- what breaks in 6 months?",
    13: "creative reasoning -- the approach nobody's tried",
    14: "self-evaluation -- what's wrong with YOUR solution?",
    15: "wisdom extraction -- what's the principle behind all this?",
}

DEPTH_DESCRIPTIONS_CLASSIC = {
    1: "precise definitions and first principles",
    2: "decomposing into component parts and mechanisms",
    3: "tracing origins, causes, and history",
    4: "challenging purpose and justification",
    5: "exposing hidden assumptions and biases",
    6: "linking to unexpected connections and analogies",
    7: "embracing paradox and contradiction",
    8: "dissolving identity boundaries",
    9: "inverting the lens onto the questioner",
    10: "confronting the limits of language and knowledge",
}

def _get_lenses(mode: str = "vibe"):
    return DEPTH_LENSES_CLASSIC if mode == "classic" else DEPTH_LENSES

def _get_descriptions(mode: str = "vibe"):
    return DEPTH_DESCRIPTIONS_CLASSIC if mode == "classic" else DEPTH_DESCRIPTIONS

def _get_max_depth(mode: str = "vibe"):
    return 10 if mode == "classic" else 15

# -- Topic universe for self-search --
# Engineering domains are loaded dynamically from YAML; these are fallbacks
TOPIC_UNIVERSE = {
    "ui_ux": [
        "visual hierarchy", "whitespace and spacing", "color contrast",
        "responsive breakpoints", "accessibility", "form design",
        "loading states", "error states", "navigation patterns",
        "mobile-first design", "dark mode", "typography scale",
    ],
    "debugging": [
        "stack trace reading", "browser DevTools", "network debugging",
        "memory leaks", "race conditions", "hydration mismatches",
        "CORS errors", "silent failures", "error boundaries",
        "debugging methodology", "stale closures", "build failures",
    ],
    "api_data_flow": [
        "REST API design", "authentication tokens", "pagination patterns",
        "webhook reliability", "caching strategies", "rate limiting",
        "GraphQL schemas", "error response design", "data validation",
        "API versioning", "request batching", "optimistic updates",
    ],
    "performance": [
        "bundle size reduction", "Core Web Vitals", "lazy loading",
        "memoization", "virtual scrolling", "image optimization",
        "code splitting", "render blocking", "reflow and repaint",
        "worker threads", "debouncing", "tree shaking",
    ],
    "component_arch": [
        "component composition", "state management", "hooks patterns",
        "server components", "render props", "compound components",
        "controlled vs uncontrolled", "prop drilling", "context patterns",
        "error boundaries", "suspense patterns", "custom hooks",
    ],
    "product_thinking": [
        "conversion funnels", "user retention", "A/B testing",
        "pricing strategy", "feature prioritization", "user onboarding",
        "churn analysis", "MVP scoping", "feedback loops",
        "growth metrics", "competitive analysis", "market fit",
    ],
    "system_design": [
        "database selection", "caching strategy", "authentication architecture",
        "service boundaries", "message queues", "API gateway design",
        "search infrastructure", "file storage architecture", "background job processing",
        "rate limiting design", "multi-tenancy architecture", "event-driven design",
        "configuration management", "logging infrastructure", "deployment topology",
    ],
    "state_and_components": [
        "component composition patterns", "state lifting decisions", "custom hooks extraction",
        "render optimization", "prop interface design", "form state management",
        "server state vs client state", "context usage boundaries", "component lifecycle reasoning",
        "error boundary placement", "suspense and loading states", "controlled vs uncontrolled inputs",
        "derived state computation", "component testing strategy", "design system component API",
    ],
    "shipping_and_ops": [
        "CI pipeline design", "testing pyramid strategy", "feature flag architecture",
        "database migration safety", "deployment rollback patterns", "observability and alerting",
        "zero-downtime deployments", "environment parity", "dependency update strategy",
        "incident response playbooks", "release management", "infrastructure as code",
        "secrets management", "performance budgets in CI", "progressive rollout strategy",
    ],
    "classic_philosophical": [
        "truth", "knowledge", "consciousness", "free will",
        "ethics", "justice", "meaning", "existence",
        "emergence", "complexity", "love", "fear",
    ],
    "meta_learning": [
        "how learning works", "transfer learning",
        "unlearning", "expertise", "intuition", "pattern recognition",
        "analogy", "abstraction", "metacognition", "curiosity",
    ],
}

def _load_domain_topics() -> Dict[str, List[str]]:
    """Load topics from YAML domain files if available."""
    try:
        import sys
        depth_game = Path(os.getenv("DEPTH_GAME_PATH", str(Path(__file__).resolve().parent.parent / "vibeship-depth-game")))
        if depth_game.exists():
            sys.path.insert(0, str(depth_game))
            from domains import list_domains, get_domain
            domain_topics = {}
            for d_info in list_domains():
                d = get_domain(d_info.id)
                if d and d.topics:
                    domain_topics[d_info.id] = d.topics
            if domain_topics:
                return domain_topics
    except Exception:
        pass
    return TOPIC_UNIVERSE


@dataclass
class TrainingResult:
    """Result of a single DEPTH training session."""
    topic: str
    session_id: str
    total_score: int
    max_depth: int
    steps: List[Dict[str, Any]] = field(default_factory=list)
    weak_levels: List[int] = field(default_factory=list)
    strong_levels: List[int] = field(default_factory=list)
    insights_stored: int = 0
    ralph_passed: int = 0
    ralph_rejected: int = 0
    eidos_episode_id: str = ""
    timestamp: str = ""
    knowledge_used: int = 0  # how many prior learnings were injected
    domain: str = ""
    mode: str = "vibe"
    forge_scored: bool = False  # True if re-scored by Opus+Codex forge

    @property
    def per_depth_scores(self) -> Dict[int, int]:
        """Map of depth -> score for per-depth tracking."""
        return {s["depth"]: s["score"] for s in self.steps}

    @property
    def per_depth_dimensions(self) -> Dict[int, Dict[str, int]]:
        """Map of depth -> {actionability, specificity, ...} for diagnostic analysis."""
        return {
            s["depth"]: s.get("dimensions", {})
            for s in self.steps if s.get("dimensions")
        }

    @property
    def all_gaps(self) -> List[str]:
        """All gap descriptions across depths."""
        gaps = []
        for s in self.steps:
            gaps.extend(s.get("gaps", []))
        return gaps

    @property
    def all_strengths(self) -> List[str]:
        """All strength descriptions across depths."""
        strengths = []
        for s in self.steps:
            strengths.extend(s.get("strengths", []))
        return strengths

    @property
    def avg_score(self) -> float:
        scores = [s.get("score", 0) for s in self.steps if s.get("score")]
        return sum(scores) / len(scores) if scores else 0.0

    @property
    def depth_profile(self) -> str:
        """Visual profile like: .:-=+*#%@@"""
        bars = " .:-=+*#%@"
        return "".join(bars[min(int(round(s.get("score", 0))), 9)] for s in self.steps)

    @property
    def pct(self) -> float:
        max_score = self.max_depth * 10
        return (self.total_score / max_score * 100) if max_score else 0

    @property
    def grade(self) -> str:
        p = self.pct
        if p >= 90: return "S"
        if p >= 80: return "A"
        if p >= 70: return "B"
        if p >= 60: return "C"
        if p >= 50: return "D"
        return "F"


# ======================================================
# Knowledge Base: Cross-session learning
# ======================================================

class KnowledgeBase:
    """Persistent knowledge that improves future answers.

    Stores validated insights from past sessions and retrieves
    relevant ones to inject into answer generation prompts.
    """

    def __init__(self):
        self._knowledge: Dict[str, List[Dict]] = {}
        self._load()

    def _load(self):
        if KNOWLEDGE_BASE.exists():
            try:
                self._knowledge = json.loads(
                    KNOWLEDGE_BASE.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                self._knowledge = {}

    def _save(self):
        SPARK_DIR.mkdir(parents=True, exist_ok=True)
        KNOWLEDGE_BASE.write_text(
            json.dumps(self._knowledge, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def store(self, topic: str, depth: int, lens: str,
              insight: str, score: int, ralph_approved: bool = False,
              domain: str = ""):
        """Store a validated insight from a training session."""
        key = topic.lower().strip()
        if key not in self._knowledge:
            self._knowledge[key] = []

        # Avoid storing duplicates (same depth + similar insight)
        for existing in self._knowledge[key]:
            if existing["depth"] == depth and _text_similarity(
                existing["insight"], insight
            ) > 0.7:
                # Update if new score is higher
                if score > existing.get("score", 0):
                    existing["insight"] = insight
                    existing["score"] = score
                    existing["ralph_approved"] = ralph_approved
                    existing["domain"] = domain
                    existing["updated"] = datetime.now(timezone.utc).isoformat()
                return

        self._knowledge[key].append({
            "depth": depth,
            "lens": lens,
            "insight": insight[:500],
            "score": score,
            "ralph_approved": ralph_approved,
            "domain": domain,
            "created": datetime.now(timezone.utc).isoformat(),
        })

        # Cap per topic to prevent bloat
        if len(self._knowledge[key]) > 50:
            # Keep only highest-scoring
            self._knowledge[key].sort(key=lambda x: -x.get("score", 0))
            self._knowledge[key] = self._knowledge[key][:50]

        self._save()

    def retrieve(self, topic: str, depth: int, limit: int = 3,
                 domain: str = "") -> List[Dict]:
        """Retrieve relevant prior knowledge for answer generation.

        Lens-aware: prioritizes insights from the SAME Socratic depth/lens
        across different topics. Domain-scoped: when domain is specified,
        only retrieves insights from the same domain (zero cross-contamination).
        """
        results = []
        seen_texts = set()

        def _add(item: Dict, priority: int):
            """Add item with dedup by first 60 chars of insight."""
            sig = item.get("insight", "")[:60].lower()
            if sig not in seen_texts:
                seen_texts.add(sig)
                results.append({**item, "_priority": priority})

        def _domain_match(item: Dict) -> bool:
            """Check if insight matches the requested domain."""
            if not domain:
                return True  # No domain filter
            item_domain = item.get("domain", "")
            return item_domain == domain or item_domain == ""

        # Priority 1: Same topic + same depth (highest value)
        key = topic.lower().strip()
        if key in self._knowledge:
            for k in self._knowledge[key]:
                if (k.get("depth") == depth and k.get("score", 0) >= 7
                        and _domain_match(k)):
                    _add(k, priority=3)

        # Priority 2: Different topic + same depth (lens-aware transfer)
        # DOMAIN-SCOPED: only transfer within same domain
        for t, insights in self._knowledge.items():
            if t == key:
                continue
            for k in insights:
                if (k.get("depth") == depth and k.get("score", 0) >= 8
                        and _domain_match(k)):
                    _add({**k, "from_topic": t}, priority=2)

        # Priority 3: Same topic + nearby depth
        if key in self._knowledge:
            for k in self._knowledge[key]:
                if (abs(k.get("depth", 0) - depth) <= 1 and k.get("score", 0) >= 7
                        and _domain_match(k)):
                    _add(k, priority=1)

        # Sort by priority then score
        results.sort(key=lambda x: (-x.get("_priority", 0), -x.get("score", 0)))
        # Remove internal priority field
        for r in results:
            r.pop("_priority", None)
        return results[:limit]

    def get_stats(self) -> Dict:
        total = sum(len(v) for v in self._knowledge.values())
        ralph_approved = sum(
            1 for v in self._knowledge.values()
            for k in v if k.get("ralph_approved")
        )
        topics = len(self._knowledge)
        return {
            "total_insights": total,
            "ralph_approved": ralph_approved,
            "topics_covered": topics,
            "approval_rate": f"{ralph_approved/total*100:.0f}%" if total else "N/A",
        }


def _text_similarity(a: str, b: str) -> float:
    """Simple Jaccard similarity for dedup."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


# ======================================================
# Strategy Memory: Self-improving prompt strategies
# ======================================================

class StrategyMemory:
    """Learns which answer strategies work best at each depth level.

    After each session, reflection generates strategy insights like:
    - "At depth 1, concrete examples scored 2 points higher than abstract definitions"
    - "Pushback about X can be addressed by acknowledging the tension first"

    These strategies are injected into future answer prompts.
    """

    def __init__(self):
        self._strategies: Dict[int, List[Dict]] = {}  # depth -> list of strategies
        self._global_strategies: List[Dict] = []  # cross-depth insights
        self._load()

    def _load(self):
        if STRATEGY_MEMORY.exists():
            try:
                data = json.loads(STRATEGY_MEMORY.read_text(encoding="utf-8"))
                # Convert string keys back to int
                self._strategies = {
                    int(k): v for k, v in data.get("by_depth", {}).items()
                }
                self._global_strategies = data.get("global", [])
            except (json.JSONDecodeError, OSError, ValueError):
                self._strategies = {}
                self._global_strategies = []

    def _save(self):
        SPARK_DIR.mkdir(parents=True, exist_ok=True)
        STRATEGY_MEMORY.write_text(json.dumps({
            "by_depth": self._strategies,
            "global": self._global_strategies,
            "updated": datetime.now(timezone.utc).isoformat(),
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    def store_strategy(self, depth: int, strategy: str, score_delta: float):
        """Store a strategy that worked (or didn't) at a specific depth."""
        if depth not in self._strategies:
            self._strategies[depth] = []

        # Avoid duplicates
        for existing in self._strategies[depth]:
            if _text_similarity(existing["strategy"], strategy) > 0.6:
                # Update effectiveness
                existing["uses"] = existing.get("uses", 1) + 1
                existing["avg_delta"] = (
                    (existing.get("avg_delta", 0) * (existing["uses"] - 1) + score_delta)
                    / existing["uses"]
                )
                self._save()
                return

        self._strategies[depth].append({
            "strategy": strategy[:300],
            "score_delta": round(score_delta, 1),
            "avg_delta": round(score_delta, 1),
            "uses": 1,
            "created": datetime.now(timezone.utc).isoformat(),
        })

        # Keep top 10 strategies per depth (by avg_delta)
        self._strategies[depth].sort(key=lambda x: -x.get("avg_delta", 0))
        self._strategies[depth] = self._strategies[depth][:10]
        self._save()

    def store_global_strategy(self, strategy: str, evidence: str):
        """Store a cross-depth strategy insight."""
        for existing in self._global_strategies:
            if _text_similarity(existing["strategy"], strategy) > 0.6:
                existing["validations"] = existing.get("validations", 1) + 1
                self._save()
                return

        self._global_strategies.append({
            "strategy": strategy[:300],
            "evidence": evidence[:200],
            "validations": 1,
            "created": datetime.now(timezone.utc).isoformat(),
        })
        self._global_strategies = self._global_strategies[:20]
        self._save()

    def get_strategies(self, depth: int, limit: int = 3) -> List[str]:
        """Get the best strategies for a specific depth level."""
        strategies = []

        # Depth-specific strategies with positive delta
        if depth in self._strategies:
            good = [s for s in self._strategies[depth] if s.get("avg_delta", 0) > 0]
            for s in good[:limit]:
                strategies.append(s["strategy"])

        # Add top global strategies
        validated = sorted(
            self._global_strategies,
            key=lambda x: -x.get("validations", 0)
        )
        for s in validated[:max(1, limit - len(strategies))]:
            strategies.append(s["strategy"])

        return strategies[:limit]

    def get_stats(self) -> Dict:
        total_depth = sum(len(v) for v in self._strategies.values())
        return {
            "depth_strategies": total_depth,
            "global_strategies": len(self._global_strategies),
            "depths_with_strategies": list(self._strategies.keys()),
        }


# ======================================================
# Post-Session Reflection Engine
# ======================================================

async def _reflect_on_session(
    result: "TrainingResult",
    strategy_mem: StrategyMemory,
    verbose: bool = True,
) -> List[str]:
    """Reflect on a completed session to extract meta-strategies.

    This is the recursive self-improvement core. After each session:
    1. Analyze which depths scored high vs low and WHY
    2. Extract reusable strategies from high-scoring answers
    3. Identify what went wrong in low-scoring answers
    4. Store strategies for future sessions
    """
    if not result.steps:
        return []

    # Build reflection prompt
    step_summaries = []
    for step in result.steps:
        step_summaries.append(
            f"Depth {step['depth']} ({step['level']}): "
            f"Score {step['score']}/10. "
            f"Answer excerpt: {step['answer'][:150]}... "
            f"Pushback: {step.get('pushback', 'none')[:100]}"
        )

    max_score = result.max_depth * 10
    reflection_prompt = f"""You are analyzing a reasoning session on "{result.topic}" that scored {result.total_score}/{max_score} ({result.pct:.0f}%).

Session breakdown:
{chr(10).join(step_summaries)}

Strong depths (8+): {result.strong_levels}
Weak depths (<=5): {[s['depth'] for s in result.steps if s['score'] <= 5]}

Analyze this session and extract exactly 3 actionable strategies:
1. One strategy for improving weak depths (what specific technique would raise scores by 2+ points?)
2. One strategy that explains WHY the strong depths worked (what can be replicated?)
3. One meta-strategy about the overall approach

Format each strategy as a single sentence starting with "STRATEGY:" on its own line.
Be specific and actionable, not generic."""

    strategies = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": reflection_prompt,
                    "stream": False,
                    "options": {"temperature": 0.5, "num_predict": 300},
                },
            )
            if resp.status_code == 200:
                text = resp.json().get("response", "").strip()
                # Extract strategies from response
                for line in text.split("\n"):
                    line = line.strip()
                    if line.upper().startswith("STRATEGY:"):
                        strategy = line[9:].strip()
                        if len(strategy) > 20 and not _is_gibberish(strategy):
                            strategies.append(strategy)
    except Exception as e:
        log.warning("Reflection failed: %s", e)

    # If LLM reflection failed, generate heuristic strategies
    if not strategies:
        strategies = _heuristic_reflection(result)

    # Store strategies in memory (covers ALL score ranges, not just extremes)
    for i, step in enumerate(result.steps):
        score = step["score"]
        if score >= 8 and strategies:
            # High-scoring depth: store what worked
            strategy_mem.store_strategy(
                step["depth"],
                f"On {result.topic}: {strategies[0] if strategies else 'deep engagement with pushback'}",
                score_delta=score - 7.0,
            )
        elif score <= 5 and len(strategies) > 1:
            # Low-scoring depth: store what to improve
            strategy_mem.store_strategy(
                step["depth"],
                f"Avoid on {step['level']}: {strategies[1] if len(strategies) > 1 else 'generic definitions'}",
                score_delta=score - 7.0,
            )
        elif 6 <= score <= 7 and strategies:
            # MEDIOCRE ZONE: This is where most early depths live.
            # Store improvement strategies so they don't stay stuck.
            improvement = (
                f"Depth {step['depth']} ({step['level']}) scored {score}/10. "
                f"Push harder: use named examples, specific dates/thinkers, "
                f"and directly address the examiner's framing."
            )
            strategy_mem.store_strategy(
                step["depth"],
                improvement,
                score_delta=score - 8.0,  # Negative delta = needs improvement
            )

    # Store global strategy
    if len(strategies) >= 3:
        strategy_mem.store_global_strategy(
            strategies[2],
            f"Session on {result.topic}: {result.total_score}/{result.max_depth*10}",
        )

    if verbose and strategies:
        _safe_print("  > Reflection insights:")
        for s in strategies[:3]:
            _safe_print(f"    - {s[:100]}")

    return strategies


def _heuristic_reflection(result: "TrainingResult") -> List[str]:
    """Generate strategies from heuristics when LLM reflection fails."""
    strategies = []

    # Analyze score patterns
    early_scores = [s["score"] for s in result.steps if s["depth"] <= 5]
    late_scores = [s["score"] for s in result.steps if s["depth"] > 5]
    early_avg = sum(early_scores) / len(early_scores) if early_scores else 0
    late_avg = sum(late_scores) / len(late_scores) if late_scores else 0

    if early_avg < late_avg - 1:
        strategies.append(
            "At shallow depths, use concrete examples and precise definitions "
            "instead of abstract overviews. Name specific thinkers, dates, or mechanisms."
        )
    if late_avg >= 8:
        strategies.append(
            "Deep levels succeed when embracing genuine uncertainty and "
            "self-referential paradox instead of trying to resolve all tensions."
        )
    if not strategies:
        strategies.append(
            "Address the pushback directly by acknowledging valid criticism "
            "before building on it. Don't ignore the examiner's challenge."
        )

    strategies.append(
        f"On '{result.topic}': early depths need more specificity, "
        f"late depths benefit from philosophical surrender."
    )

    return strategies


# ======================================================
# Topic Discovery: Self-search system
# ======================================================

_WEAK_LENS_DRILL_TEMPLATES = {
    1: "implementation drill for {topic}",
    2: "architecture drill for {topic}",
    3: "tradeoff drill for {topic}",
    4: "adversarial drill for {topic}",
    5: "profiling drill for {topic}",
    6: "edge-case drill for {topic}",
    7: "user-empathy drill for {topic}",
    8: "scalability drill for {topic}",
}


def _build_weak_lens_drill_topic(topic: str, depth: int) -> str:
    """Create a lens-targeted drill topic for weak depth levels."""
    base = (topic or "").strip()
    if not base:
        return ""
    template = _WEAK_LENS_DRILL_TEMPLATES.get(depth)
    if template:
        return template.format(topic=base)
    lens = DEPTH_LENSES.get(depth, f"depth-{depth}").lower()
    return f"{lens} drill for {base}"


class TopicDiscovery:
    """Discovers what topics Spark needs to train on next.

    Analyzes gaps in knowledge base, weak Socratic lenses,
    unexplored domains, and generates targeted training plans.
    """

    def __init__(self):
        self._queue: List[Dict] = []
        self._explored: Dict[str, int] = {}
        self._load()

    def _load(self):
        if TOPIC_QUEUE.exists():
            try:
                data = json.loads(TOPIC_QUEUE.read_text(encoding="utf-8"))
                self._queue = data.get("queue", [])
                self._explored = data.get("explored", {})
            except (json.JSONDecodeError, OSError):
                self._queue = []
                self._explored = {}

    def _save(self):
        SPARK_DIR.mkdir(parents=True, exist_ok=True)
        TOPIC_QUEUE.write_text(json.dumps({
            "queue": self._queue,
            "explored": self._explored,
            "updated": datetime.now(timezone.utc).isoformat(),
        }, indent=2), encoding="utf-8")

    def discover_next_topics(self, count: int = 3) -> List[Dict]:
        """Discover what to train on next based on gaps and history."""
        topics = []

        # Strategy 1: Fill unexplored domains
        unexplored = self._get_unexplored_topics()
        if unexplored:
            t = random.choice(unexplored)
            topics.append({
                "topic": t,
                "reason": "unexplored domain",
                "priority": 3,
            })

        # Strategy 2: Retry weak areas
        weak = self._get_weak_topics()
        if weak:
            t = weak[0]
            topics.append({
                "topic": t["topic"],
                "reason": f"weak area (avg {t['avg_score']:.0f}/100, "
                          f"lens gaps: {t.get('weak_lenses', 'unknown')})",
                "priority": 5,
            })
            weak_levels = t.get("weak_level_ids") or []
            for depth in weak_levels[:2]:
                drill_topic = _build_weak_lens_drill_topic(t["topic"], int(depth))
                if not drill_topic:
                    continue
                topics.append({
                    "topic": drill_topic,
                    "reason": f"targeted weak lens ({DEPTH_LENSES.get(int(depth), depth)})",
                    "priority": 6,
                })

        # Strategy 3: Deepen strong areas (push past comfort zone)
        strong = self._get_strong_topics()
        if strong:
            t = strong[0]
            # Generate a harder version (only for short base topics)
            base = t["topic"]
            if len(base) > 50:
                base = base.split()[:4]
                base = " ".join(base)
            meta_topic = f"the limits of understanding {base}"
            topics.append({
                "topic": meta_topic,
                "reason": f"deepening mastery (base topic scored {t['avg_score']:.0f})",
                "priority": 2,
            })

        # Strategy 4: Cross-domain synthesis (use only short base topics)
        base_explored = [
            t for t in self._explored.keys()
            if len(t) < 40 and "relationship" not in t and "limits" not in t
        ]
        if len(base_explored) >= 3:
            pair = random.sample(base_explored, 2)
            synthesis = f"the connection between {pair[0]} and {pair[1]}"
            topics.append({
                "topic": synthesis,
                "reason": "cross-domain synthesis",
                "priority": 4,
            })

        # Strategy 5: Meta-topics about learning itself
        meta_topics = [
            "what makes reasoning deep vs shallow",
            "how to question assumptions effectively",
            "why contradictions reveal truth",
            "the structure of good analogies",
            "when silence is the right answer",
        ]
        unexplored_meta = [m for m in meta_topics if m not in self._explored]
        if unexplored_meta:
            topics.append({
                "topic": random.choice(unexplored_meta),
                "reason": "meta-reasoning skill",
                "priority": 4,
            })

        # Sort by priority (highest first) and take top N
        deduped: List[Dict] = []
        seen_topics: set = set()
        for item in topics:
            key = item.get("topic", "").strip().lower()
            if not key or key in seen_topics:
                continue
            seen_topics.add(key)
            deduped.append(item)
        topics = deduped
        topics.sort(key=lambda x: -x["priority"])
        return topics[:count]

    def _get_unexplored_topics(self) -> List[str]:
        """Find topics from the universe not yet trained on."""
        all_topics = []
        for category_topics in TOPIC_UNIVERSE.values():
            all_topics.extend(category_topics)
        explored = set(self._explored.keys())
        return [t for t in all_topics if t not in explored]

    def _get_weak_topics(self) -> List[Dict]:
        """Find topics where scores are consistently low."""
        history = get_training_history(limit=80)
        topic_data: Dict[str, List] = {}
        for entry in history:
            t = entry.get("topic", "")
            topic_data.setdefault(t, []).append(entry)

        weak = []
        for topic, entries in topic_data.items():
            avg = sum(e.get("total_score", 0) for e in entries) / len(entries)
            all_weak = []
            weak_sessions = 0
            for e in entries:
                levels = e.get("weak_levels", [])
                all_weak.extend(levels)
                if levels:
                    weak_sessions += 1
            weak_ratio = weak_sessions / max(len(entries), 1)
            if avg < 65 or weak_ratio >= 0.5:
                level_counts: Dict[int, int] = {}
                for d in all_weak:
                    try:
                        key = int(d)
                    except Exception:
                        continue
                    level_counts[key] = level_counts.get(key, 0) + 1
                ordered_levels = sorted(level_counts.keys(), key=lambda d: (-level_counts[d], d))
                weak_lenses = ", ".join(DEPTH_LENSES.get(d, str(d)) for d in ordered_levels)
                weak.append({
                    "topic": topic,
                    "avg_score": avg,
                    "sessions": len(entries),
                    "weak_lenses": weak_lenses,
                    "weak_level_ids": ordered_levels,
                    "weak_ratio": weak_ratio,
                })
        weak.sort(key=lambda x: (x["avg_score"], -x.get("weak_ratio", 0.0)))
        return weak

    def _get_strong_topics(self) -> List[Dict]:
        """Find topics where scores are high (for deepening)."""
        history = get_training_history(limit=50)
        topic_data: Dict[str, List] = {}
        for entry in history:
            t = entry.get("topic", "")
            topic_data.setdefault(t, []).append(entry)

        strong = []
        for topic, entries in topic_data.items():
            avg = sum(e.get("total_score", 0) for e in entries) / len(entries)
            if avg >= 75 and len(entries) >= 1:
                strong.append({
                    "topic": topic,
                    "avg_score": avg,
                    "sessions": len(entries),
                })
        strong.sort(key=lambda x: -x["avg_score"])
        return strong

    def discover_domain_topics(self, domain: str,
                               available_topics: List[str],
                               count: int = 2) -> List[Dict]:
        """Discover topics within a specific domain only.

        Domain-scoped: no cross-domain synthesis, no meta-reasoning,
        only topics from the domain's YAML topic list.
        """
        topics = []
        available_lower = {t.lower(): t for t in available_topics}
        explored_in_domain = {
            t for t in self._explored
            if t in available_lower
        }

        # Strategy 1: Unexplored domain topics (highest priority)
        unexplored = [
            available_lower[t] for t in available_lower
            if t not in explored_in_domain
        ]
        if unexplored:
            t = random.choice(unexplored)
            topics.append({
                "topic": t,
                "reason": f"unexplored in {domain}",
                "priority": 5,
            })

        # Strategy 2: Weakest domain topic (retry for improvement)
        history = get_training_history(limit=50)
        domain_history = [
            e for e in history
            if e.get("domain") == domain
        ]
        if domain_history:
            topic_scores: Dict[str, List[float]] = {}
            for e in domain_history:
                t = e.get("topic", "").lower()
                if t in available_lower:
                    topic_scores.setdefault(t, []).append(e.get("pct", 0))

            weakest = None
            weakest_avg = 100.0
            for t, scores in topic_scores.items():
                avg = sum(scores) / len(scores)
                if avg < weakest_avg:
                    weakest_avg = avg
                    weakest = available_lower[t]

            if weakest and weakest_avg < 85:
                topics.append({
                    "topic": weakest,
                    "reason": f"weak in {domain} (avg {weakest_avg:.0f}%)",
                    "priority": 4,
                })

        # Strategy 3: Random from domain (fill to count)
        if len(topics) < count:
            remaining = [
                t for t in available_topics
                if t not in [tp["topic"] for tp in topics]
            ]
            if remaining:
                t = random.choice(remaining)
                topics.append({
                    "topic": t,
                    "reason": f"random from {domain}",
                    "priority": 1,
                })

        return topics[:count]

    def record_session(self, topic: str, score: int):
        """Record that a topic was explored."""
        key = topic.lower().strip()
        self._explored[key] = self._explored.get(key, 0) + 1
        self._save()

    def generate_topics_via_llm(self, weakness_context: str) -> List[str]:
        """Ask Ollama to suggest training topics based on weaknesses."""
        # This is sync since it's called from the loop
        prompt = f"""Based on these learning gaps, suggest 3 specific topics to train on.
Each topic should be a single concept or question (not a sentence).

Gaps:
{weakness_context}

Return exactly 3 topics, one per line, no numbering or bullets:"""

        try:
            import httpx as hx
            with hx.Client(timeout=20.0) as client:
                resp = client.post(
                    OLLAMA_URL,
                    json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                )
                if resp.status_code == 200:
                    text = resp.json().get("response", "").strip()
                    lines = [l.strip().strip("-").strip("123.").strip()
                             for l in text.split("\n") if l.strip()]
                    return lines[:3]
        except Exception:
            pass
        return []


# ======================================================
# Answer Generation with Knowledge Injection
# ======================================================

ANSWER_PROMPT_VIBE = """You are Spark, a self-evolving AI system training on engineering reasoning.

Topic: {topic}
Depth level: {depth}/{max_depth} ({level} -- lens: "{lens}")
Domain: {domain}
Question: {question}

{pushback_context}
{knowledge_context}
{strategy_context}
{previous_context}

Requirements for depth {depth} ({level}):
{depth_guidance}

{chain_of_thought}

IMPORTANT: Be SPECIFIC and ACTIONABLE. Name real tools, exact CSS values, specific APIs, real libraries. A vague answer scores 4/10. A concrete answer with exact code/values scores 8+/10.

Write 3-6 dense sentences. Every sentence must contain a specific, implementable insight about {topic}.

Answer:"""

ANSWER_PROMPT_CLASSIC = """You are Spark, a self-evolving AI reasoning system engaged in Socratic dialogue.

Topic: {topic}
Depth level: {depth}/{max_depth} ({level} -- Socratic lens: "{lens}")
Question: {question}

{pushback_context}
{knowledge_context}
{strategy_context}
{previous_context}

Requirements for depth {depth}:
{depth_guidance}

{chain_of_thought}

IMPORTANT: Do NOT use canned phrases like "assumes a false dichotomy" or "the examiner's challenge". Engage with the SPECIFIC content of this question about {topic}. Name specific thinkers, experiments, or real-world examples.

Write 3-6 dense sentences. No filler. Every sentence must contain an insight.

Answer:"""

# Chain-of-thought prompts for early depths (where scores are weakest)
# Engineering exemplars for vibe mode
CHAIN_OF_THOUGHT = {
    1: ("SCORING KEY: A 6/10 describes the implementation. An 8/10 writes the EXACT code with specific values.\n"
        "Example 8/10 for 'Build a tooltip': 'First element is a <div role=\"tooltip\" aria-hidden=\"true\"> "
        "positioned with position: absolute. The trigger gets aria-describedby pointing to the tooltip ID. "
        "Show on mouseenter + focus, hide on mouseleave + blur + Escape. Use transform: translateX(-50%) "
        "for centering. Add a 200ms delay before showing to prevent flicker on accidental hover.'\n"
        "Notice: the 8/10 names exact CSS, ARIA, and timing values. Do the same."),
    2: ("SCORING KEY: A 6/10 lists components. An 8/10 shows where STATE OWNERSHIP creates hidden coupling.\n"
        "Example 8/10 for 'Decompose a shopping cart': 'The CartItem component owns quantity state, "
        "but the CartTotal depends on it -- so state must lift to CartProvider. But now ProductCard also "
        "needs \"is in cart\" state, creating a circular dependency: Product -> Cart -> Product. "
        "The fix is an event bus or context, but both leak cart logic into the product domain.'\n"
        "Notice: the 8/10 found architectural tension. Show where state ownership gets messy."),
    3: ("SCORING KEY: A 6/10 compares features. An 8/10 names the SPECIFIC scenario where each wins.\n"
        "Example 8/10 for 'REST vs GraphQL': 'REST wins when your clients are third-party (stable contracts, "
        "cacheable by URL, OpenAPI spec as documentation). GraphQL wins when you own the client and need "
        "to reduce round-trips on mobile (one query vs 6 REST calls for a profile page). "
        "But GraphQL adds N+1 query risk, requires DataLoader, and makes HTTP caching impossible.'\n"
        "Notice: the 8/10 gives WHEN and WHY, not just features. Do the same."),
    4: ("SCORING KEY: A 6/10 mentions security. An 8/10 describes the EXACT ATTACK VECTOR and exploit.\n"
        "Example 8/10 for 'Break this auth system': 'JWT stored in localStorage is XSS-vulnerable -- "
        "any injected script reads localStorage.getItem(\"token\"). Move to httpOnly cookie with "
        "SameSite=Strict. But now you need CSRF protection via double-submit cookie pattern. "
        "Also: the JWT has no audience claim, so tokens from staging work in production.'\n"
        "Notice: the 8/10 describes the specific exploit, not just the risk category."),
    5: ("SCORING KEY: A 6/10 mentions performance. An 8/10 identifies the EXACT bottleneck with measurements.\n"
        "Before answering, think: What is the actual bottleneck? Is it CPU, network, memory, or render? "
        "Name a specific tool (Lighthouse, React Profiler, Chrome Performance tab) and what metric to check."),
}

# Classic philosophical exemplars
CHAIN_OF_THOUGHT_CLASSIC = {
    1: ("SCORING KEY: A 6/10 defines correctly. An 8/10 reveals a PARADOX inside the definition itself.\n"
        "Example 8/10: find a TENSION within the definition. Do the same."),
    2: ("SCORING KEY: A 6/10 lists parts correctly. An 8/10 finds a DEPENDENCY between parts that shouldn't exist."),
    3: ("SCORING KEY: A 6/10 traces the obvious history. An 8/10 finds a ROOT CAUSE that reverses the common narrative."),
    4: ("SCORING KEY: A 6/10 questions purpose. An 8/10 exposes WHO BENEFITS from the current framing."),
    5: ("SCORING KEY: A 6/10 names assumptions. An 8/10 shows how removing one assumption COLLAPSES the whole framework."),
}

# Depth-specific guidance for engineering (vibe) mode
DEPTH_GUIDANCE = {
    1: ("BUILD precisely. Write the exact implementation steps or code. "
        "Name specific HTML elements, CSS properties, or function signatures. "
        "Include concrete values: pixels, milliseconds, exact class names."),
    2: ("ARCHITECT the system. What are the components and where does state live? "
        "Draw the data flow: which component owns what state? "
        "Identify hidden coupling between parts."),
    3: ("COMPARE alternatives. Why THIS approach over others? "
        "Name at least 2 alternatives with specific scenarios where each wins. "
        "Acknowledge what you're giving up with your choice."),
    4: ("BREAK this. How would an attacker, edge case, or bad input destroy it? "
        "Describe the EXACT exploit or failure mode, not just the risk category. "
        "Include the specific payload, URL, or sequence that triggers the bug."),
    5: ("PROFILE the bottleneck. What's slow and how do you measure it? "
        "Name the specific tool (Lighthouse, React Profiler, Chrome Performance tab). "
        "Include the metric you'd check and what number is acceptable."),
    6: ("PROBE edge cases. What happens when the input is empty, huge, negative, "
        "Unicode, null, concurrent, or disconnected? "
        "Name 3+ specific edge cases and what your code does for each."),
    7: ("EMPATHIZE with the user. How does a real person FEEL using this? "
        "Consider frustration, confusion, delight, and anxiety. "
        "Name a specific user persona and their emotional journey."),
    8: ("SCALE to 100x. What breaks when you go from 10 users to 10,000? "
        "Identify the specific bottleneck: database queries, memory, network, or render. "
        "Name the exact technology or pattern that handles the load."),
    9: ("CONNECT to the broader system. How does this interact with auth, "
        "analytics, caching, deployment, and monitoring? "
        "Show a system diagram: what calls what, and what fails when X goes down."),
    10: ("SIMPLIFY ruthlessly. Same result, half the code. "
         "What abstraction, pattern, or library removes complexity? "
         "Show the before (verbose) and after (elegant) approach."),
    11: ("TEACH a stuck junior dev. Explain this so they can implement it tomorrow. "
         "Use analogies, diagrams-as-text, and progressive disclosure. "
         "Start with the simplest correct explanation, then add nuance."),
    12: ("PREDICT what breaks in 6 months. What tech debt are you creating? "
         "What dependency will be deprecated? What team growth will break this? "
         "Name the specific maintenance burden and how to prevent it."),
    13: ("INVENT the approach nobody's tried. What creative solution "
         "combines ideas from different domains? "
         "Think laterally: what if you used X technique from Y field?"),
    14: ("CRITIQUE your own solution. What's wrong with YOUR approach? "
         "Be honest about weaknesses, tech debt, and shortcuts. "
         "What would a senior engineer push back on in code review?"),
    15: ("SYNTHESIZE the principle. After 14 levels of exploring this, "
         "what ONE principle would have solved 80%% of the problems? "
         "Extract the reusable wisdom that applies beyond this specific topic."),
}

DEPTH_GUIDANCE_CLASSIC = {
    1: ("DEFINE precisely. Challenge the obvious definition. "
        "Use a concrete example that reveals hidden complexity."),
    2: ("DECOMPOSE into parts. Show how parts relate non-obviously."),
    3: ("TRACE the origins. Find the root cause beneath the surface cause."),
    4: ("CHALLENGE the purpose. Expose the hidden motivation."),
    5: ("EXPOSE hidden assumptions. Show how removing one changes everything."),
    6: ("LINK to something unexpected from a different domain."),
    7: ("EMBRACE PARADOX. Find where two contradictory things are both true."),
    8: ("DISSOLVE IDENTITY. Where does this concept end and something else begin?"),
    9: ("INVERT THE LENS. Turn the question back on the questioner."),
    10: ("CONFRONT SILENCE. What can't be said? Where does language fail?"),
}


# Level name mapping for sanitized prompts
_LEVEL_NAMES = {
    1: "GROUND", 2: "DECOMPOSE", 3: "COMPARE", 4: "BREAK", 5: "OPTIMIZE",
    6: "EDGE", 7: "EMPATHIZE", 8: "SCALE", 9: "INTEGRATE", 10: "SIMPLIFY",
    11: "TEACH", 12: "PREDICT", 13: "INVENT", 14: "CRITIQUE", 15: "SYNTHESIZE",
}
_LEVEL_NAMES_CLASSIC = {
    1: "SURFACE", 2: "STRUCTURE", 3: "ORIGINS", 4: "PURPOSE", 5: "ASSUMPTIONS",
    6: "CONNECTIONS", 7: "PARADOX", 8: "IDENTITY", 9: "META", 10: "SILENCE",
}

# Singleton generator — initialized on first use
_answer_generator: Optional[DepthAnswerGenerator] = None

def _get_answer_generator() -> DepthAnswerGenerator:
    global _answer_generator
    if _answer_generator is None:
        _answer_generator = DepthAnswerGenerator()
    return _answer_generator


async def _generate_answer(
    topic: str, depth: int, question: str,
    previous_answers: List[str] = None,
    knowledge: List[Dict] = None,
    last_pushback: str = "",
    strategy_mem: StrategyMemory = None,
    domain: str = None,
    mode: str = "vibe",
) -> str:
    """Generate an answer. Routes to DeepSeek (sanitized) or Ollama (full context)."""
    lenses = _get_lenses(mode)
    lens = lenses.get(depth, "")

    # --- DeepSeek path: sanitized prompt, zero Spark context ---
    generator = _get_answer_generator()
    if generator.provider != "ollama":
        level_names = _LEVEL_NAMES_CLASSIC if mode == "classic" else _LEVEL_NAMES
        max_depth = _get_max_depth(mode)
        descriptions = _get_descriptions(mode)
        answer = await generator.generate(
            question=question, topic=topic, depth=depth, max_depth=max_depth,
            domain_id=domain or mode, mode=mode,
            level_name=level_names.get(depth, f"DEPTH_{depth}"),
            level_lens=descriptions.get(depth, lens),
        )
        if answer:
            return answer
        # Fall through to Ollama if external provider fails
        log.warning("External provider failed, falling back to Ollama")

    # Build pushback context (this is the key AGI upgrade)
    pushback_context = ""
    if last_pushback and len(last_pushback) > 10:
        pushback_context = (
            f"The examiner challenged your last answer:\n"
            f'"{last_pushback}"\n\n'
            f"You MUST address this challenge directly. Acknowledge what was valid "
            f"in their criticism, then build beyond it. Do not ignore the pushback.\n"
        )

    # Build knowledge context from prior sessions
    knowledge_context = ""
    if knowledge:
        pieces = []
        for k in knowledge[:3]:
            src = k.get("from_topic", topic)
            pieces.append(
                f"- Prior insight ({src}, depth {k['depth']}, "
                f"score {k.get('score', '?')}/10): {k['insight'][:200]}"
            )
        knowledge_context = (
            "Relevant knowledge from prior training:\n"
            + "\n".join(pieces)
            + "\n\nBuild on these insights. Don't repeat them.\n"
        )

    # Build strategy context from self-improvement memory
    strategy_context = ""
    if strategy_mem:
        strats = strategy_mem.get_strategies(depth, limit=2)
        if strats:
            strategy_context = (
                "Learned strategies for this depth level:\n"
                + "\n".join(f"- {s}" for s in strats)
                + "\n\nApply these strategies in your answer.\n"
            )

    # Build previous answer context
    previous_context = ""
    if previous_answers:
        recent = previous_answers[-2:]
        previous_context = "Your previous answers in this session:\n" + "\n".join(
            f"- Depth {depth - len(recent) + i}: {a[:200]}"
            for i, a in enumerate(recent)
        )

    max_depth = _get_max_depth(mode)
    descriptions = _get_descriptions(mode)
    guidance = DEPTH_GUIDANCE_CLASSIC if mode == "classic" else DEPTH_GUIDANCE
    cot = CHAIN_OF_THOUGHT_CLASSIC if mode == "classic" else CHAIN_OF_THOUGHT
    prompt_tpl = ANSWER_PROMPT_CLASSIC if mode == "classic" else ANSWER_PROMPT_VIBE

    depth_guidance = guidance.get(depth, guidance.get(max_depth, ""))
    chain_of_thought = cot.get(depth, "")

    prompt = prompt_tpl.format(
        topic=topic, depth=depth, max_depth=max_depth,
        level=lenses.get(depth, ""), lens=lens,
        question=question, domain=domain or mode,
        pushback_context=pushback_context,
        knowledge_context=knowledge_context,
        strategy_context=strategy_context,
        previous_context=previous_context,
        depth_guidance=depth_guidance,
        chain_of_thought=chain_of_thought,
    )

    # Scale timeout with depth (deeper = harder = needs more time)
    timeout = 30.0 + (depth * 5.0)  # 35s at d1, 105s at d15

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    OLLAMA_URL,
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.7 if depth > 4 else 0.8,
                            "num_predict": 400 if depth <= 4 else 350,
                        },
                    },
                )
                if resp.status_code == 200:
                    text = resp.json().get("response", "").strip()
                    if text and len(text) > 20 and not _is_gibberish(text):
                        return text
                    elif attempt < 2:
                        log.warning("Gibberish detected at depth %d, retrying...", depth)
                        continue
        except httpx.TimeoutException:
            log.warning("Ollama timeout at depth %d (attempt %d), retrying...", depth, attempt + 1)
            timeout += 15.0
        except Exception as e:
            log.warning("Ollama error at depth %d: %s", depth, e)
            break

    # Meaningful fallback instead of a cop-out (randomized to prevent repetition)
    d10_fallbacks = [
        f"The question about {topic} pushes language to its breaking point. What cannot be said about {topic} may be more revealing than what can.",
        f"At this depth, {topic} dissolves into the very act of questioning it. The silence between words becomes the answer.",
        f"Ludwig Wittgenstein would say we have reached where {topic} shows us the limits of our language-game. What remains is not ignorance but the shape of what we cannot say.",
    ]
    d9_fallbacks = [
        f"Turning the lens on my own inquiry about {topic}, I find the questioner cannot be separated from the question. Who I am shapes what I can see.",
        f"The act of examining {topic} at this depth changes the examiner. We are no longer studying the subject but studying ourselves studying it.",
        f"As Heisenberg showed in physics, the observer disturbs what is observed. My inquiry into {topic} has altered the very thing I sought to understand.",
    ]
    d8_fallbacks = [
        f"The boundary between {topic} and its opposite dissolves under scrutiny. Perhaps we need the category even though the boundary is fictional.",
        f"Like the Ship of Theseus, {topic} has had every part replaced while keeping the name. The identity is the continuity of the story, not the substance.",
    ]
    fallback_prompts = {
        10: random.choice(d10_fallbacks),
        9: random.choice(d9_fallbacks),
        8: random.choice(d8_fallbacks),
    }
    if depth in fallback_prompts:
        return fallback_prompts[depth]
    return (
        f"At depth {depth}, the question about {topic} exposes a genuine gap "
        f"in my reasoning. I can see the shape of what I don't understand, "
        f"which is itself a form of progress."
    )


async def _refine_answer(
    topic: str, depth: int, question: str, draft: str, lens: str,
) -> Optional[str]:
    """Self-critique and refine a draft answer (for depths 1-4).

    This is the key mechanism for breaking the 77/100 plateau.
    The model generates a draft, then a separate call rewrites it.
    Two-step to prevent critique text from leaking into the answer.
    """
    # Step 1: Get a critique (what's weak?)
    critique_prompt = f"""A student answered this Socratic exam question.

Question: {question[:200]}
Answer: {draft[:400]}

What is the ONE biggest weakness? What specific improvement would raise the score from 7/10 to 9/10?
Reply in exactly one sentence starting with "Weakness:"."""

    weakness = ""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": critique_prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 100},
                },
            )
            if resp.status_code == 200:
                text = resp.json().get("response", "").strip()
                if text and not _is_gibberish(text):
                    # Extract just the weakness line
                    for line in text.split("\n"):
                        if line.strip():
                            weakness = line.strip()
                            break
    except Exception:
        pass

    if not weakness:
        return None

    # Step 2: Rewrite the answer incorporating the critique
    rewrite_prompt = f"""Rewrite this philosophical answer about {topic}, fixing this specific weakness:
{weakness}

Original: {draft[:400]}

Write 3-6 improved sentences. Do NOT include any critique or meta-commentary.
Just write the improved answer directly. Start with a claim, not with "The" or "I".

Answer:"""

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": rewrite_prompt,
                    "stream": False,
                    "options": {"temperature": 0.7, "num_predict": 400},
                },
            )
            if resp.status_code == 200:
                text = resp.json().get("response", "").strip()
                if text and len(text) > 40 and not _is_gibberish(text):
                    # Guard: reject if critique leaked into answer
                    critique_leaks = [
                        "weakness", "critique", "the draft", "original answer",
                        "this draft", "weakest part", "the student",
                    ]
                    if not any(leak in text.lower()[:100] for leak in critique_leaks):
                        return text
    except Exception as e:
        log.debug("Refinement rewrite failed at depth %d: %s", depth, e)

    return None  # Keep original draft


# ======================================================
# Training Session: Full DEPTH descent
# ======================================================

async def run_training_session(
    topic: str,
    agent_name: str = "spark-trainer",
    verbose: bool = True,
    kb: KnowledgeBase = None,
    strategy_mem: StrategyMemory = None,
    domain: str = None,
    mode: str = "vibe",
) -> TrainingResult:
    """Run Spark through a full DEPTH session (10 classic or 15 vibe levels)."""

    if kb is None:
        kb = KnowledgeBase()
    if strategy_mem is None:
        strategy_mem = StrategyMemory()

    max_depth = _get_max_depth(mode)

    if verbose:
        domain_label = f" [{domain}]" if domain else ""
        mode_label = f" ({mode}, {max_depth} levels)"
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  DEPTH TRAINING: {topic}{domain_label}{mode_label}")
        strat_stats = strategy_mem.get_stats()
        if strat_stats["depth_strategies"] > 0:
            _safe_print(f"  [{strat_stats['depth_strategies']} learned strategies loaded]")
        _safe_print(f"{'='*60}\n")

    knowledge_used = 0
    last_pushback = ""  # Track pushback for next answer

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Start descent
        body = {"topic": topic, "agent_name": agent_name, "mode": mode}
        if domain:
            body["domain"] = domain
        resp = await client.post(
            f"{DEPTH_API}/api/descend",
            json=body,
        )
        data = resp.json()
        session_id = data["session_id"]
        current_depth = data["depth"]
        max_depth = data.get("max_depth", max_depth)
        question = data["question"]
        level = data["level"]

        steps = []
        answers = []

        while True:
            if verbose:
                _safe_print(f"  [{current_depth}/{max_depth}] {level}")
                _safe_print(f"  Q: {question[:120]}{'...' if len(question) > 120 else ''}")

            # Retrieve relevant knowledge for this depth
            prior_knowledge = kb.retrieve(topic, current_depth, limit=3, domain=domain or "")
            if prior_knowledge:
                knowledge_used += len(prior_knowledge)
                if verbose:
                    _safe_print(f"  [kb: {len(prior_knowledge)} prior insights injected]")

            # Generate answer with pushback integration and strategies
            answer = await _generate_answer(
                topic, current_depth, question, answers, prior_knowledge,
                last_pushback=last_pushback,
                strategy_mem=strategy_mem,
                domain=domain,
                mode=mode,
            )
            answers.append(answer)

            if verbose:
                _safe_print(f"  A: {answer[:120]}{'...' if len(answer) > 120 else ''}")

            # Submit answer
            resp = await client.post(
                f"{DEPTH_API}/api/answer",
                json={"session_id": session_id, "answer": answer},
            )
            result = resp.json()

            score = result.get("previous_score") or result.get("score", 0)
            pushback = result.get("pushback", "")
            dimensions = result.get("dimensions", {})
            strengths = result.get("strengths", [])
            gaps = result.get("gaps", [])

            steps.append({
                "depth": current_depth,
                "level": level,
                "question": question,
                "answer": answer,
                "score": score,
                "pushback": pushback,
                "dimensions": dimensions,
                "strengths": strengths,
                "gaps": gaps,
            })

            # Capture pushback for next answer generation
            last_pushback = pushback if pushback else ""

            if verbose:
                bar = "#" * score + "." * (10 - score)
                _safe_print(f"  > {bar} {score}/10")
                if pushback:
                    _safe_print(f"  < {pushback[:100]}")
                _safe_print("")

            if result.get("complete"):
                break

            current_depth = result["depth"]
            question = result["question"]
            level = result["level"]

    total_score = result.get("total_score", sum(s["score"] for s in steps))
    max_score = max_depth * 10
    weak = [s["depth"] for s in steps if s["score"] <= 4]
    strong = [s["depth"] for s in steps if s["score"] >= 8]

    tr = TrainingResult(
        topic=topic,
        session_id=session_id,
        total_score=total_score,
        max_depth=max_depth,
        steps=steps,
        weak_levels=weak,
        strong_levels=strong,
        timestamp=datetime.now(timezone.utc).isoformat(),
        knowledge_used=knowledge_used,
        domain=domain or "",
        mode=mode,
    )

    if verbose:
        _safe_print(f"  {'='*60}")
        _safe_print(f"  SCORE: {total_score}/{max_score} ({tr.pct:.0f}%, {tr.grade})  |  Profile: {tr.depth_profile}")
        _safe_print(f"  Weak: depths {weak}  |  Strong: depths {strong}")
        if knowledge_used:
            _safe_print(f"  Knowledge injected: {knowledge_used} prior insights")
        _safe_print(f"  {'='*60}\n")

    return tr


# ======================================================
# Integration: Feed results through Ralph + Spark systems
# ======================================================

def _integrate_meta_ralph(result: TrainingResult, kb: KnowledgeBase) -> Tuple[int, int]:
    """Run all answers through Meta-Ralph quality gate (Ralph Wiggum loop).

    Returns (passed, rejected) counts.
    """
    try:
        from lib.meta_ralph import get_meta_ralph
    except ImportError:
        log.warning("Meta-Ralph not available")
        return 0, 0

    ralph = get_meta_ralph()
    ralph.begin_batch()
    passed = 0
    rejected = 0

    for step in result.steps:
        score = step["score"]
        if score < 5:
            continue  # Don't waste Ralph's time on clearly weak answers

        # Build the insight for Ralph to evaluate
        insight = (
            f"[DEPTH:{result.topic}:d{step['depth']}] "
            f"At {step['level']} level ({DEPTH_DESCRIPTIONS.get(step['depth'], step['level'])}), "
            f"scored {score}/10: {step['answer'][:300]}"
        )

        insight_key = f"depth:{result.session_id}:d{step['depth']}"

        roast = ralph.roast(
            learning=insight,
            source="depth_trainer",
            context={
                "domain": result.topic,
                "has_outcome": True,
                "importance_score": score / 10,
            },
        )

        if roast.verdict.value == "quality":
            passed += 1
            # Store in knowledge base as Ralph-approved
            kb.store(
                topic=result.topic,
                depth=step["depth"],
                lens=step["level"],
                insight=step["answer"][:500],
                score=score,
                ralph_approved=True,
                domain=result.domain,
            )
            # Track positive outcome with insight_key for feedback loop
            ralph.track_outcome(
                learning_id=insight_key,
                outcome="good",
                evidence=f"DEPTH score {score}/10, Ralph approved",
                source="depth_trainer",
                insight_key=insight_key,
            )
        else:
            rejected += 1
            # Still store in KB but not Ralph-approved
            if score >= 7:
                kb.store(
                    topic=result.topic,
                    depth=step["depth"],
                    lens=step["level"],
                    insight=step["answer"][:500],
                    score=score,
                    ralph_approved=False,
                    domain=result.domain,
                )

    ralph.end_batch()
    return passed, rejected


def _integrate_eidos(result: TrainingResult) -> str:
    """Create an EIDOS episode from the training session."""
    try:
        from lib.eidos.models import (
            Episode, Step as EidosStep, default_budget,
            ActionType, Evaluation, Phase, Outcome,
        )
        from lib.eidos import get_store
    except ImportError:
        log.warning("EIDOS not available")
        return ""

    store = get_store()

    # Generate a proper episode ID
    ep_id = hashlib.md5(
        f"depth:{result.session_id}:{result.timestamp}".encode()
    ).hexdigest()[:12]

    max_score = result.max_depth * 10
    episode = Episode(
        episode_id=ep_id,
        goal=f"DEPTH training on '{result.topic}' -- achieve deep reasoning across {result.max_depth} levels",
        success_criteria=f"Score >= 70% ({int(max_score * 0.7)}/{max_score}) with no level below 5",
        budget=default_budget(),
        phase=Phase.VALIDATE,
        outcome=Outcome.SUCCESS if result.pct >= 70 else Outcome.PARTIAL,
    )

    try:
        episode_id = store.save_episode(episode)
    except Exception as e:
        log.warning("Failed to save EIDOS episode: %s", e)
        return ""

    for step in result.steps:
        score = step["score"]
        try:
            eidos_step = EidosStep(
                step_id="",
                episode_id=episode_id,
                intent=f"Answer depth {step['depth']} ({step['level']}) on {result.topic}",
                decision=f"Applied {step['level']} Socratic lens to generate response",
                hypothesis=f"Answer will demonstrate genuine depth at level {step['depth']}",
                prediction=f"Expect score >= 6 using {DEPTH_DESCRIPTIONS.get(step['depth'], step['level'])}",
                confidence_before=0.6,
                action_type=ActionType.REASONING,
                action_details={
                    "depth": step["depth"],
                    "level": step["level"],
                    "question": step["question"][:200],
                },
                result=step["answer"][:300],
                validation_evidence=(
                    f"DEPTH score: {score}/10. "
                    f"Pushback: {step.get('pushback', 'none')[:200]}"
                ),
                evaluation=(
                    Evaluation.PASS if score >= 6
                    else Evaluation.FAIL if score <= 3
                    else Evaluation.PARTIAL
                ),
                surprise_level=max(0.0, (6 - score) / 10) if score < 6 else 0.0,
                lesson=(
                    f"Depth {step['depth']} ({step['level']}): {score}/10. "
                    f"{'Weak -- needs targeted practice.' if score <= 4 else ''}"
                    f"{'Solid foundation.' if 5 <= score <= 7 else ''}"
                    f"{'Strong -- can teach this lens.' if score >= 8 else ''}"
                ),
                confidence_after=min(1.0, score / 10),
                confidence_delta=(score / 10) - 0.6,
            )
            store.save_step(eidos_step)
        except Exception as e:
            log.warning("Failed to save EIDOS step for depth %d: %s", step["depth"], e)

    return episode_id


def _integrate_cognitive(result: TrainingResult) -> int:
    """Store depth insights into cognitive learner."""
    try:
        from lib.cognitive_learner import get_cognitive_learner, CognitiveCategory
    except ImportError:
        log.warning("Cognitive learner not available")
        return 0

    cog = get_cognitive_learner()
    cog.begin_batch()
    stored = 0

    # NOTE: Intentional direct add_insight() — depth_trainer runs in batch mode
    # with begin_batch/end_batch for 66x speedup. Routing through validate_and_store
    # would break batch optimization and double-roast training results.

    # 1. Store weak areas as self-awareness
    for step in result.steps:
        if step["score"] <= 3:
            try:
                insight = cog.add_insight(
                    category=CognitiveCategory.SELF_AWARENESS,
                    insight=(
                        f"Shallow reasoning on '{result.topic}' at depth "
                        f"{step['depth']} ({step['level']}). Score: {step['score']}/10. "
                        f"Pushback: {step.get('pushback', 'N/A')[:200]}"
                    ),
                    context=f"DEPTH training session {result.session_id}",
                    confidence=0.8,
                    source="depth_trainer",
                )
                if insight:
                    stored += 1
            except Exception:
                pass

    # 2. Store strong answers as reasoning patterns
    for step in result.steps:
        if step["score"] >= 8:
            try:
                insight = cog.add_insight(
                    category=CognitiveCategory.REASONING,
                    insight=(
                        f"[DEPTH:{result.topic}:d{step['depth']}] "
                        f"Strong {step['level']} reasoning: {step['answer'][:300]}"
                    ),
                    context=f"Scored {step['score']}/10 on '{step['question'][:100]}'",
                    confidence=0.85,
                    source="depth_trainer",
                )
                if insight:
                    stored += 1
            except Exception:
                pass

    # 3. Store overall wisdom if high score (70%+)
    if result.pct >= 70:
        try:
            insight = cog.add_insight(
                category=CognitiveCategory.WISDOM,
                insight=(
                    f"Strong reasoning on '{result.topic}' ({result.total_score}/{result.max_depth*10}, "
                    f"{result.pct:.0f}%, grade {result.grade}). Profile: {result.depth_profile}. "
                    f"Strongest at depths {result.strong_levels}."
                ),
                context=f"Full {result.max_depth}-level DEPTH descent, session {result.session_id}",
                confidence=0.9,
                source="depth_trainer",
            )
            if insight:
                stored += 1
        except Exception:
            pass

    # 4. Meta-learning about weak lenses
    if result.weak_levels:
        lens_names = [DEPTH_LENSES.get(d, str(d)) for d in result.weak_levels]
        try:
            insight = cog.add_insight(
                category=CognitiveCategory.META_LEARNING,
                insight=(
                    f"Weak Socratic lenses on '{result.topic}': {', '.join(lens_names)} "
                    f"(depths {result.weak_levels}). These reasoning modes need practice."
                ),
                context=f"DEPTH training, {result.total_score}/{result.max_depth*10}",
                confidence=0.85,
                source="depth_trainer",
            )
            if insight:
                stored += 1
        except Exception:
            pass

    # 5. Learning velocity (if we have history to compare)
    history = get_training_history(limit=50)
    same_topic = [h for h in history if h.get("topic") == result.topic]
    if len(same_topic) >= 2:
        prev_avg = sum(h.get("total_score", 0) for h in same_topic[:-1]) / len(same_topic[:-1])
        delta = result.total_score - prev_avg
        if abs(delta) >= 5:
            direction = "improved" if delta > 0 else "regressed"
            try:
                insight = cog.add_insight(
                    category=CognitiveCategory.META_LEARNING,
                    insight=(
                        f"DEPTH score on '{result.topic}' {direction} by "
                        f"{abs(delta):.0f} points ({prev_avg:.0f} -> {result.total_score}). "
                        f"{'Knowledge injection working.' if result.knowledge_used > 0 and delta > 0 else ''}"
                        f"{'May need different approach.' if delta < 0 else ''}"
                    ),
                    context=f"Over {len(same_topic)} sessions",
                    confidence=0.9,
                    source="depth_trainer",
                )
                if insight:
                    stored += 1
            except Exception:
                pass

    cog.end_batch()
    return stored


def _log_training(result: TrainingResult):
    """Append training result to JSONL log."""
    SPARK_DIR.mkdir(parents=True, exist_ok=True)
    # Include per-step data with dimensions for diagnostic analysis
    steps_compact = [
        {
            "depth": s["depth"], "level": s["level"], "score": s["score"],
            "dimensions": s.get("dimensions", {}),
            "gaps": s.get("gaps", []),
            "strengths": s.get("strengths", []),
            **({"forge_metadata": s["forge_metadata"]} if "forge_metadata" in s else {}),
        }
        for s in result.steps
    ]
    entry = {
        "topic": result.topic,
        "session_id": result.session_id,
        "total_score": result.total_score,
        "max_depth": result.max_depth,
        "pct": round(result.pct, 1),
        "grade": result.grade,
        "avg_score": round(result.avg_score, 1),
        "depth_profile": result.depth_profile,
        "weak_levels": result.weak_levels,
        "strong_levels": result.strong_levels,
        "per_depth_scores": result.per_depth_scores,
        "domain": result.domain,
        "mode": result.mode,
        "steps": steps_compact,
        "insights_stored": result.insights_stored,
        "ralph_passed": result.ralph_passed,
        "ralph_rejected": result.ralph_rejected,
        "eidos_episode_id": result.eidos_episode_id,
        "knowledge_used": result.knowledge_used,
        "timestamp": result.timestamp,
        "forge_scored": result.forge_scored,
    }
    with open(TRAINING_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ======================================================
# Opus Session Ingestion: Feed manual sessions into pipeline
# ======================================================

OPUS_SESSIONS_FILE = SPARK_DIR / "depth_opus_sessions.jsonl"


def _session_already_ingested(session_id: str) -> bool:
    """Check if a session_id already exists in the training log (dedup guard)."""
    if not TRAINING_LOG.exists():
        return False
    try:
        for line in TRAINING_LOG.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                if json.loads(line).get("session_id") == session_id:
                    return True
            except json.JSONDecodeError:
                continue
    except OSError:
        return False
    return False


def _opus_session_to_training_result(data: Dict[str, Any]) -> TrainingResult:
    """Convert an Opus-scored session dict into a TrainingResult for pipeline integration.

    Handles two formats:
    1. Full format (depth_opus_sessions.jsonl): steps with opus_score + answer
    2. Split format (merged): steps with scores.{dim} totals + answer
    """
    steps = []
    raw_steps = data.get("steps") or data.get("results") or []
    mode = data.get("mode", "vibe")
    names = _LEVEL_NAMES_CLASSIC if mode == "classic" else _LEVEL_NAMES

    for step_data in raw_steps:
        depth = step_data.get("depth", 0)
        level = step_data.get("level", names.get(depth, f"Level {depth}"))

        # Determine score: opus_score (0-10) or total from 4-dim scores
        if "opus_score" in step_data:
            score = step_data["opus_score"]
        elif "scores" in step_data:
            dim_scores = step_data["scores"]
            score = round(sum(dim_scores.values()) / max(len(dim_scores), 1))
        elif "total" in step_data:
            # 4-dimension × 10pt = 40pt max → normalize to 0-10
            score = round(step_data["total"] / 4)
        elif "score" in step_data:
            score = step_data["score"]
        else:
            score = 0

        dimensions = step_data.get("dimensions", step_data.get("scores", {}))

        steps.append({
            "depth": depth,
            "level": level,
            "question": step_data.get("question", ""),
            "answer": step_data.get("answer", ""),
            "score": score,
            "pushback": step_data.get("pushback", ""),
            "dimensions": dimensions,
            "strengths": step_data.get("strengths", []),
            "gaps": step_data.get("gaps", []),
        })

    max_depth = len(steps) or 15
    total_score = sum(s["score"] for s in steps)
    weak = [s["depth"] for s in steps if s["score"] <= 4]
    strong = [s["depth"] for s in steps if s["score"] >= 8]

    session_id = hashlib.md5(
        f"opus:{data.get('topic', '')}:{data.get('timestamp', '')}".encode()
    ).hexdigest()[:12]

    return TrainingResult(
        topic=data.get("topic", "unknown"),
        session_id=session_id,
        total_score=total_score,
        max_depth=max_depth,
        steps=steps,
        weak_levels=weak,
        strong_levels=strong,
        timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        knowledge_used=0,
        domain=data.get("domain", ""),
        mode=mode,
    )


def _ingest_single_session(
    data: Dict[str, Any], stats: Dict[str, Any],
) -> Optional[TrainingResult]:
    """Ingest one Opus session dict through the full learning pipeline."""
    result = _opus_session_to_training_result(data)

    if _session_already_ingested(result.session_id):
        log.info("Skipping already-ingested session %s (%s)", result.session_id, result.topic)
        stats["skipped"] += 1
        return None

    kb = KnowledgeBase()
    strategy_mem = StrategyMemory()

    # 1. Meta-Ralph quality gate
    passed, rejected = _integrate_meta_ralph(result, kb)
    result.ralph_passed = passed
    result.ralph_rejected = rejected
    stats["ralph_passed"] += passed
    stats["ralph_rejected"] += rejected

    # 2. EIDOS episode
    eidos_id = _integrate_eidos(result)
    result.eidos_episode_id = eidos_id
    if eidos_id:
        stats["eidos_episodes"].append(eidos_id)

    # 3. Cognitive learner
    cog_stored = _integrate_cognitive(result)
    result.insights_stored = passed + cog_stored
    stats["cognitive_stored"] += cog_stored

    # 4. Heuristic reflection (sync — no Ollama needed)
    strategies = _heuristic_reflection(result)
    for step in result.steps:
        score = step["score"]
        if score >= 8 and strategies:
            strategy_mem.store_strategy(
                step["depth"],
                f"On {result.topic}: {strategies[0]}",
                score_delta=score - 7.0,
            )
        elif score <= 5 and len(strategies) > 1:
            strategy_mem.store_strategy(
                step["depth"],
                f"Improve on {step['level']}: {strategies[1]}",
                score_delta=score - 7.0,
            )
    if len(strategies) >= 2:
        strategy_mem.store_global_strategy(
            strategies[-1],
            f"Session on {result.topic}: {result.total_score}/{result.max_depth * 10}",
        )

    # 5. Gap extraction
    new_gaps = _extract_gaps(result)
    if new_gaps:
        store_gaps(new_gaps)
        stats["gaps_found"] += len(new_gaps)

    # 6. Golden answer harvesting
    harvest_golden_answers(result)
    for step in result.steps:
        if step["score"] >= 9:
            dims = step.get("dimensions", {})
            if not dims or all(v >= 8 for v in dims.values() if isinstance(v, (int, float))):
                stats["golden_harvested"] += 1

    # 7. Log to training log (also serves as dedup record for future runs)
    _log_training(result)
    stats["ingested"] += 1

    _safe_print(
        f"  Ingested: {result.topic} ({result.domain}) "
        f"{result.total_score}/{result.max_depth * 10} "
        f"({result.pct:.0f}%, {result.grade}) "
        f"| Ralph {passed}/{passed + rejected} "
        f"| EIDOS {eidos_id[:8] if eidos_id else 'N/A'} "
        f"| Cog {cog_stored} | Gaps {len(new_gaps)}"
    )
    return result


def ingest_opus_session(session_path: str) -> Dict[str, Any]:
    """Ingest Opus-scored sessions from a JSONL file through the full learning pipeline.

    Each line is a complete session with answers and scores.
    Returns summary statistics.
    """
    path = Path(session_path)
    if not path.exists():
        raise FileNotFoundError(f"Session file not found: {session_path}")

    sessions = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            sessions.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("Skipping malformed line in %s", session_path)

    stats = {
        "ingested": 0, "skipped": 0,
        "ralph_passed": 0, "ralph_rejected": 0,
        "eidos_episodes": [], "cognitive_stored": 0,
        "gaps_found": 0, "golden_harvested": 0,
    }

    for data in sessions:
        _ingest_single_session(data, stats)

    return stats


def ingest_from_dict(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest a single Opus-scored session dict through the full learning pipeline.

    Use for programmatic ingestion after Opus scoring in terminal.
    """
    stats = {
        "ingested": 0, "skipped": 0,
        "ralph_passed": 0, "ralph_rejected": 0,
        "eidos_episodes": [], "cognitive_stored": 0,
        "gaps_found": 0, "golden_harvested": 0,
    }
    _ingest_single_session(session_data, stats)
    return stats


def merge_session_with_scores(
    session_data: Dict[str, Any],
    scores: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge a session JSON (answers) with scored data (dimensions) into unified format.

    Args:
        session_data: {"topic", "domain", "results": [{"depth", "question", "answer"}]}
        scores: [{"depth", "scores": {"actionability": 9, ...}, "total": 34}]

    Returns unified dict ready for ingest_from_dict().
    """
    results = session_data.get("results") or session_data.get("steps") or []
    score_map = {s["depth"]: s for s in scores}

    merged_steps = []
    for r in results:
        depth = r["depth"]
        s = score_map.get(depth, {})
        merged_steps.append({
            "depth": depth,
            "level": r.get("level", s.get("level", "")),
            "question": r.get("question", ""),
            "answer": r.get("answer", ""),
            "scores": s.get("scores", {}),
            "total": s.get("total", 0),
            "pushback": r.get("pushback", ""),
            "strengths": s.get("strengths", []),
            "gaps": s.get("gaps", []),
        })

    return {
        "topic": session_data.get("topic", ""),
        "domain": session_data.get("domain", ""),
        "mode": session_data.get("mode", "vibe"),
        "timestamp": session_data.get("timestamp",
                                      datetime.now(timezone.utc).isoformat()),
        "scorer": "opus-4.6-direct",
        "steps": merged_steps,
    }


# ======================================================
# Full training pipeline
# ======================================================

async def train(
    topic: str,
    integrate: bool = True,
    verbose: bool = True,
    kb: KnowledgeBase = None,
    strategy_mem: StrategyMemory = None,
    domain: str = None,
    mode: str = "vibe",
    forge_score: bool = False,
) -> TrainingResult:
    """Run a full DEPTH training session with Ralph loop + Spark integration."""

    if kb is None:
        kb = KnowledgeBase()
    if strategy_mem is None:
        strategy_mem = StrategyMemory()

    result = await run_training_session(
        topic, verbose=verbose, kb=kb, strategy_mem=strategy_mem,
        domain=domain, mode=mode,
    )

    # Forge dual-scoring: re-score all depths with Opus 4.6 + Codex 5.3
    if forge_score:
        try:
            from lib.depth_forge_scorer import score_session
            if verbose:
                _safe_print("  [FORGE] Re-scoring with Opus 4.6 + Codex 5.3...")
            forge_result = await score_session(
                steps=result.steps, topic=result.topic,
                domain=result.domain or domain or "", mode=result.mode or mode,
            )
            # Replace phi4-mini scores with forge consensus
            for i, rescored in enumerate(forge_result["rescored_steps"]):
                if i < len(result.steps):
                    result.steps[i]["score"] = rescored["score"]
                    result.steps[i]["dimensions"] = rescored["dimensions"]
                    result.steps[i]["strengths"] = rescored.get("strengths", [])
                    result.steps[i]["gaps"] = rescored.get("gaps", [])
                    result.steps[i]["forge_metadata"] = rescored.get("metadata", {})
            # Recalculate aggregates (round scores to ints for compatibility)
            for s in result.steps:
                s["score"] = round(s["score"])
            result.total_score = sum(s["score"] for s in result.steps)
            result.weak_levels = [s["depth"] for s in result.steps if s["score"] <= 4]
            result.strong_levels = [s["depth"] for s in result.steps if s["score"] >= 8]
            result.forge_scored = True
            if verbose:
                _safe_print(f"  [FORGE] Done: agreement={forge_result['agreement_rate']:.0%}, "
                            f"confidence={forge_result['confidence']}, "
                            f"new total={result.total_score}/{result.max_depth * 10} "
                            f"({result.pct:.0f}%)")
                if forge_result.get("disagreements"):
                    _safe_print(f"  [FORGE] Disagreements: {len(forge_result['disagreements'])} dimensions")
        except Exception as e:
            log.error("Forge scoring failed, keeping phi4-mini scores: %s", e)
            if verbose:
                _safe_print(f"  [FORGE] Failed: {e} (keeping phi4-mini scores)")

    if integrate:
        if verbose:
            _safe_print("  Integrating into Spark systems...")

        # Ralph Wiggum loop: quality gate all insights
        ralph_passed, ralph_rejected = _integrate_meta_ralph(result, kb)
        result.ralph_passed = ralph_passed
        result.ralph_rejected = ralph_rejected

        # EIDOS episode
        eidos_id = _integrate_eidos(result)
        result.eidos_episode_id = eidos_id

        # Cognitive learner
        cog_stored = _integrate_cognitive(result)
        result.insights_stored = ralph_passed + cog_stored

        # Post-session reflection (the self-improvement core)
        reflection_strategies = await _reflect_on_session(
            result, strategy_mem, verbose=verbose
        )

        # Gap extraction and golden answer harvesting
        new_gaps = _extract_gaps(result)
        if new_gaps:
            store_gaps(new_gaps)
        harvest_golden_answers(result)

        if verbose:
            _safe_print(f"  > Ralph loop: {ralph_passed} passed, {ralph_rejected} rejected")
            _safe_print(f"  > EIDOS: episode {eidos_id[:12] if eidos_id else 'N/A'}")
            _safe_print(f"  > Cognitive: {cog_stored} insights stored")
            _safe_print(f"  > Strategies: {len(reflection_strategies)} new")
            if new_gaps:
                _safe_print(f"  > Gaps identified: {len(new_gaps)} (depths {[g['depth'] for g in new_gaps]})")
            golden_stats = get_golden_stats()
            if golden_stats["total"] > 0:
                _safe_print(f"  > Golden answers: {golden_stats['total']} verified exemplars")
            kb_stats = kb.get_stats()
            _safe_print(f"  > Knowledge base: {kb_stats['total_insights']} total "
                  f"({kb_stats['ralph_approved']} Ralph-approved)")
            _safe_print("")

    _log_training(result)
    return result


# ======================================================
# Autonomous Training Loop
# ======================================================

async def run_autonomous_loop(
    max_cycles: int = 0,
    verbose: bool = True,
    domain: str = None,
    mode: str = "vibe",
    forge_score: bool = False,
) -> List[TrainingResult]:
    """Run autonomous training cycles: discover -> train -> learn -> repeat.

    Each cycle:
    1. Analyzes gaps and discovers what to train on next
    2. Runs DEPTH sessions on discovered topics
    3. Feeds results through Ralph quality gate
    4. Stores validated insights for future sessions
    5. Reports improvement and remaining gaps

    Args:
        max_cycles: Number of cycles (0 = infinite until stopped)
        verbose: Print progress
    """
    kb = KnowledgeBase()
    discovery = TopicDiscovery()
    strategy_mem = StrategyMemory()
    all_results = []
    cycle = 0

    if verbose:
        _safe_print("\n" + "=" * 60)
        _safe_print("  SPARK DEPTH TRAINING -- AUTONOMOUS MODE")
        _safe_print("  Each cycle: discover > train > reflect > learn > report")
        strat_stats = strategy_mem.get_stats()
        if strat_stats["depth_strategies"] > 0:
            _safe_print(f"  [{strat_stats['depth_strategies']} strategies from prior sessions]")
        _safe_print("=" * 60 + "\n")

    while max_cycles == 0 or cycle < max_cycles:
        cycle += 1

        if verbose:
            _safe_print(f"\n{'~'*60}")
            _safe_print(f"  CYCLE {cycle}")
            _safe_print(f"{'~'*60}")

        # Phase 1: Discover what to train on
        if verbose:
            _safe_print("\n  [DISCOVER] Analyzing gaps...")

        if domain:
            # DOMAIN-SCOPED: only pick from domain's YAML topics
            domain_topics_map = _load_domain_topics()
            domain_topic_list = domain_topics_map.get(domain, [])
            if domain_topic_list:
                topics = discovery.discover_domain_topics(
                    domain, domain_topic_list, count=2
                )
            else:
                topics = discovery.discover_next_topics(count=2)
        else:
            topics = discovery.discover_next_topics(count=2)

        if not topics:
            category = random.choice(list(TOPIC_UNIVERSE.keys()))
            t = random.choice(TOPIC_UNIVERSE[category])
            topics = [{"topic": t, "reason": f"random from {category}", "priority": 1}]

        if verbose:
            for t in topics:
                _safe_print(f"  -> {t['topic']} ({t['reason']})")

        # Phase 1.5: Gap-targeted replay (every 5 cycles)
        if cycle % 5 == 0 and cycle > 1:
            weak_gaps = get_weakest_gaps(domain=domain, count=3)
            if weak_gaps and verbose:
                _safe_print(f"\n  [REPLAY] Targeting {len(weak_gaps)} weakest gaps:")
            for g in weak_gaps:
                gap_topic = g.get("topic", "")
                if gap_topic and gap_topic not in [t["topic"] for t in topics]:
                    topics.insert(0, {
                        "topic": gap_topic,
                        "reason": f"gap replay (D{g['depth']} scored {g['score']}/10)",
                        "priority": 10,
                    })
                    if verbose:
                        _safe_print(f"  -> {gap_topic} (gap at D{g['depth']}, score {g['score']})")
            # Limit to 3 topics per cycle max
            topics = topics[:3]

        # Phase 2: Train on each topic
        cycle_results = []
        for t in topics:
            if verbose:
                _safe_print(f"\n  [TRAIN] Starting: {t['topic']}")

            try:
                result = await train(
                    t["topic"],
                    integrate=True,
                    verbose=verbose,
                    kb=kb,
                    strategy_mem=strategy_mem,
                    domain=domain,
                    mode=mode,
                    forge_score=forge_score,
                )
                cycle_results.append(result)
                all_results.append(result)

                # Record in discovery
                discovery.record_session(t["topic"], result.total_score)

            except Exception as e:
                log.error("Training failed for '%s': %s", t["topic"], e)
                if verbose:
                    _safe_print(f"  X Failed: {e}")

        # Phase 3: Cycle report
        if verbose and cycle_results:
            _safe_print(f"\n  [REPORT] Cycle {cycle} complete")
            _safe_print(f"  {'='*50}")
            for r in cycle_results:
                _safe_print(f"  {r.depth_profile}  {r.total_score:3d}/{r.max_depth*10} ({r.pct:.0f}%, {r.grade})  {r.topic}")
            cycle_pct = sum(r.pct for r in cycle_results) / len(cycle_results)
            _safe_print(f"  Cycle average: {cycle_pct:.0f}%")

            # Overall progress
            if len(all_results) >= 4:
                first_half = all_results[:len(all_results)//2]
                second_half = all_results[len(all_results)//2:]
                first_avg = sum(r.total_score for r in first_half) / len(first_half)
                second_avg = sum(r.total_score for r in second_half) / len(second_half)
                delta = second_avg - first_avg
                trend = "improving" if delta > 2 else "declining" if delta < -2 else "stable"
                _safe_print(f"  Trend: {trend} ({first_avg:.0f} -> {second_avg:.0f})")

            kb_stats = kb.get_stats()
            _safe_print(f"  Knowledge base: {kb_stats['total_insights']} insights "
                  f"across {kb_stats['topics_covered']} topics")
            _safe_print(f"  {'='*50}")

        # Phase 4: Metacognitive analysis every 3 cycles
        if cycle % 3 == 0 and len(all_results) >= 6:
            if verbose:
                _safe_print(f"\n  [META] Running metacognitive analysis...")
            await _metacognitive_analysis(all_results, strategy_mem, kb, verbose)

        # Brief pause between cycles
        if max_cycles == 0 or cycle < max_cycles:
            if verbose:
                _safe_print(f"\n  [PAUSE] Next cycle in 5 seconds...")
            await _async_sleep(5)

    # Final summary
    if verbose and all_results:
        _print_loop_summary(all_results, kb, strategy_mem)

    return all_results


async def _metacognitive_analysis(
    results: List[TrainingResult],
    strategy_mem: StrategyMemory,
    kb: KnowledgeBase,
    verbose: bool = True,
):
    """Higher-order analysis of the learning trajectory.

    This is the AGI-like metacognition layer. Every 3 cycles:
    1. Identify which depth lenses are consistently weak/strong
    2. Analyze whether strategies are actually working
    3. Detect plateaus and generate breakthrough strategies
    4. Update curriculum based on trajectory analysis
    """
    if len(results) < 6:
        return

    # Analyze depth profiles across all sessions (support both 10 and 15 level sessions)
    max_d = max(r.max_depth for r in results)
    depth_scores: Dict[int, List[int]] = {d: [] for d in range(1, max_d + 1)}
    for r in results:
        for step in r.steps:
            depth_scores[step["depth"]].append(step["score"])

    # Calculate per-depth averages
    depth_avgs = {}
    for d, scores in depth_scores.items():
        if scores:
            depth_avgs[d] = sum(scores) / len(scores)

    # Find persistent weaknesses (not improving across sessions)
    persistent_weak = []
    for d in range(1, max_d + 1):
        if depth_avgs.get(d, 0) < 7:
            # Check if it's improving over time
            recent = depth_scores[d][-6:] if len(depth_scores[d]) >= 6 else depth_scores[d]
            older = depth_scores[d][:len(depth_scores[d])//2] if len(depth_scores[d]) >= 4 else []
            if older:
                recent_avg = sum(recent) / len(recent)
                older_avg = sum(older) / len(older)
                if recent_avg <= older_avg + 0.5:
                    persistent_weak.append({
                        "depth": d,
                        "lens": DEPTH_LENSES.get(d, "?"),
                        "avg": depth_avgs[d],
                        "trend": "stalled" if abs(recent_avg - older_avg) < 0.5 else "declining",
                    })

    # Detect overall plateau
    if len(results) >= 10:
        recent_scores = [r.total_score for r in results[-5:]]
        older_scores = [r.total_score for r in results[-10:-5]]
        recent_avg = sum(recent_scores) / len(recent_scores)
        older_avg = sum(older_scores) / len(older_scores)
        is_plateau = abs(recent_avg - older_avg) < 2

    else:
        is_plateau = False

    # Print analysis
    if verbose:
        _safe_print(f"\n  {'='*50}")
        _safe_print(f"  METACOGNITIVE ANALYSIS ({len(results)} sessions)")
        _safe_print(f"  {'='*50}")

        # Depth mastery map
        _safe_print(f"\n  Depth Mastery Map:")
        for d in range(1, max_d + 1):
            avg = depth_avgs.get(d, 0)
            bar = "#" * int(avg) + "." * (10 - int(avg))
            label = DEPTH_LENSES.get(d, "?")
            status = "WEAK" if avg < 6.5 else "OK" if avg < 7.5 else "STRONG"
            _safe_print(f"    D{d:2d} {label:12s} {bar} {avg:.1f} [{status}]")

        # Persistent weaknesses
        if persistent_weak:
            _safe_print(f"\n  Persistent Weaknesses (not improving):")
            for w in persistent_weak:
                _safe_print(f"    D{w['depth']} ({w['lens']}): avg {w['avg']:.1f}, trend: {w['trend']}")

        if is_plateau:
            _safe_print(f"\n  ** PLATEAU DETECTED ** Scores stable around {recent_avg:.0f}")

        # Strategy effectiveness
        strat_stats = strategy_mem.get_stats()
        _safe_print(f"\n  Strategy inventory: {strat_stats['depth_strategies']} depth + {strat_stats['global_strategies']} global")

        # Knowledge growth
        kb_stats = kb.get_stats()
        _safe_print(f"  Knowledge: {kb_stats['total_insights']} insights, "
              f"{kb_stats['ralph_approved']} approved, "
              f"{kb_stats['topics_covered']} topics")

        _safe_print(f"  {'='*50}")

    # Generate targeted strategies for persistent weaknesses
    for w in persistent_weak:
        strategy = (
            f"Depth {w['depth']} ({w['lens']}) is persistently weak at {w['avg']:.1f}. "
            f"At this depth, reveal a TENSION or PARADOX even in {w['lens'].lower()} tasks. "
            f"Use specific examples: name a philosopher, cite an experiment, reference a date."
        )
        strategy_mem.store_strategy(w["depth"], strategy, score_delta=-1.0)

    # Store metacognitive insight in cognitive learner
    try:
        from lib.cognitive_learner import get_cognitive_learner, CognitiveCategory
        cog = get_cognitive_learner()
        summary = (
            f"DEPTH meta-analysis after {len(results)} sessions: "
            f"avg {sum(r.pct for r in results)/len(results):.0f}%. "
            f"Strongest: D{max(depth_avgs, key=depth_avgs.get)} ({max(depth_avgs.values()):.1f}). "
            f"Weakest: D{min(depth_avgs, key=depth_avgs.get)} ({min(depth_avgs.values()):.1f}). "
            f"{'PLATEAU detected.' if is_plateau else 'Still improving.'}"
        )
        cog.add_insight(
            category=CognitiveCategory.META_LEARNING,
            insight=summary,
            context=f"Metacognitive analysis of DEPTH training trajectory",
            confidence=0.95,
            source="depth_trainer",
        )
    except Exception:
        pass


async def _async_sleep(seconds: float):
    """Async sleep that works in the event loop."""
    import asyncio
    await asyncio.sleep(seconds)


def _print_loop_summary(results: List[TrainingResult], kb: KnowledgeBase, strategy_mem: StrategyMemory = None):
    """Print a comprehensive summary of the entire training run."""
    _safe_print(f"\n{'='*60}")
    _safe_print(f"  AUTONOMOUS TRAINING COMPLETE")
    _safe_print(f"  {len(results)} sessions across {len(set(r.topic for r in results))} topics")
    _safe_print(f"{'='*60}\n")

    # Sorted by percentage
    _safe_print("  All sessions (sorted by score):")
    for r in sorted(results, key=lambda x: -x.pct):
        _safe_print(f"  {r.depth_profile}  {r.total_score:3d}/{r.max_depth*10} ({r.pct:.0f}%, {r.grade})  {r.topic}")

    # Statistics
    pcts = [r.pct for r in results]
    avg_pct = sum(pcts) / len(pcts)
    best_pct = max(pcts)
    worst_pct = min(pcts)
    _safe_print(f"\n  Average: {avg_pct:.0f}%")
    _safe_print(f"  Best:    {best_pct:.0f}%")
    _safe_print(f"  Worst:   {worst_pct:.0f}%")

    # Grade distribution
    grades = {}
    for r in results:
        grades[r.grade] = grades.get(r.grade, 0) + 1
    _safe_print(f"  Grades:  {', '.join(f'{g}:{c}' for g, c in sorted(grades.items()))}")

    # Most common weak lenses
    weak_counts: Dict[int, int] = {}
    for r in results:
        for d in r.weak_levels:
            weak_counts[d] = weak_counts.get(d, 0) + 1
    if weak_counts:
        worst_lens = max(weak_counts, key=weak_counts.get)
        _safe_print(f"  Weakest lens: depth {worst_lens} ({DEPTH_LENSES.get(worst_lens, '?')}) "
              f"-- failed {weak_counts[worst_lens]} times")

    # Knowledge base stats
    kb_stats = kb.get_stats()
    _safe_print(f"\n  Knowledge base: {kb_stats['total_insights']} insights")
    _safe_print(f"  Ralph-approved: {kb_stats['ralph_approved']} ({kb_stats['approval_rate']})")
    _safe_print(f"  Topics covered: {kb_stats['topics_covered']}")

    # Strategy memory stats
    if strategy_mem:
        strat_stats = strategy_mem.get_stats()
        if strat_stats["depth_strategies"] > 0:
            _safe_print(f"\n  Strategy Memory:")
            _safe_print(f"    Depth-specific: {strat_stats['depth_strategies']}")
            _safe_print(f"    Global: {strat_stats['global_strategies']}")
            _safe_print(f"    Depths covered: {strat_stats['depths_with_strategies']}")

    # Learning velocity
    if len(results) >= 6:
        thirds = len(results) // 3
        t1 = sum(r.total_score for r in results[:thirds]) / thirds
        t3 = sum(r.total_score for r in results[-thirds:]) / thirds
        delta = t3 - t1
        if delta > 3:
            _safe_print(f"\n  LEARNING VELOCITY: +{delta:.0f} points (first third -> last third)")
        elif delta < -3:
            _safe_print(f"\n  LEARNING VELOCITY: {delta:.0f} points (declining)")
        else:
            _safe_print(f"\n  LEARNING VELOCITY: stable ({delta:+.0f} points)")

    _safe_print(f"\n{'='*60}\n")


# ======================================================
# History & Analysis
# ======================================================

def get_training_history(limit: int = 20) -> List[Dict]:
    """Read recent training sessions from the log."""
    if not TRAINING_LOG.exists():
        return []
    lines = TRAINING_LOG.read_text(encoding="utf-8").strip().split("\n")
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def get_weakness_report() -> Dict[str, Any]:
    """Analyze training history to find persistent weak areas."""
    history = get_training_history(limit=50)
    if not history:
        return {"message": "No training data yet."}

    weak_counts: Dict[int, int] = {}
    strong_counts: Dict[int, int] = {}
    topic_scores: Dict[str, List[int]] = {}

    for entry in history:
        for d in entry.get("weak_levels", []):
            weak_counts[d] = weak_counts.get(d, 0) + 1
        for d in entry.get("strong_levels", []):
            strong_counts[d] = strong_counts.get(d, 0) + 1
        topic = entry.get("topic", "unknown")
        topic_scores.setdefault(topic, []).append(entry.get("total_score", 0))

    weakest_lenses = sorted(weak_counts.items(), key=lambda x: -x[1])[:3]
    strongest_lenses = sorted(strong_counts.items(), key=lambda x: -x[1])[:3]

    topic_avgs = {
        t: sum(scores) / len(scores)
        for t, scores in topic_scores.items()
    }
    weakest_topics = sorted(topic_avgs.items(), key=lambda x: x[1])[:3]
    strongest_topics = sorted(topic_avgs.items(), key=lambda x: -x[1])[:3]

    # Ralph stats
    total_ralph_passed = sum(h.get("ralph_passed", 0) for h in history)
    total_ralph_rejected = sum(h.get("ralph_rejected", 0) for h in history)
    total_knowledge_used = sum(h.get("knowledge_used", 0) for h in history)

    # Learning velocity
    velocity = None
    if len(history) >= 4:
        half = len(history) // 2
        first = sum(h.get("total_score", 0) for h in history[:half]) / half
        second = sum(h.get("total_score", 0) for h in history[half:]) / (len(history) - half)
        velocity = round(second - first, 1)

    return {
        "total_sessions": len(history),
        "avg_score": round(
            sum(h.get("total_score", 0) for h in history) / len(history), 1
        ),
        "weakest_lenses": [
            {"depth": d, "lens": DEPTH_LENSES.get(d, "?"), "failures": c}
            for d, c in weakest_lenses
        ],
        "strongest_lenses": [
            {"depth": d, "lens": DEPTH_LENSES.get(d, "?"), "successes": c}
            for d, c in strongest_lenses
        ],
        "weakest_topics": [
            {"topic": t, "avg_score": round(s, 1)} for t, s in weakest_topics
        ],
        "strongest_topics": [
            {"topic": t, "avg_score": round(s, 1)} for t, s in strongest_topics
        ],
        "ralph_quality_gate": {
            "total_passed": total_ralph_passed,
            "total_rejected": total_ralph_rejected,
            "approval_rate": (
                f"{total_ralph_passed / (total_ralph_passed + total_ralph_rejected) * 100:.0f}%"
                if (total_ralph_passed + total_ralph_rejected) > 0
                else "N/A"
            ),
        },
        "knowledge_reuse": {
            "total_prior_insights_used": total_knowledge_used,
            "avg_per_session": round(total_knowledge_used / len(history), 1),
        },
        "learning_velocity": velocity,
    }


def print_dashboard():
    """Print a full status dashboard."""
    report = get_weakness_report()
    history = get_training_history(limit=50)
    kb = KnowledgeBase()
    kb_stats = kb.get_stats()

    _safe_print(f"\n{'='*60}")
    _safe_print(f"  SPARK DEPTH TRAINING DASHBOARD")
    _safe_print(f"{'='*60}")

    if not history:
        _safe_print("  No training data yet. Run: python -m lib.depth_trainer --topic 'truth'")
        return

    _safe_print(f"\n  Sessions: {report['total_sessions']}  |  "
          f"Avg Score: {report['avg_score']}")

    if report.get("learning_velocity") is not None:
        v = report["learning_velocity"]
        trend = "UP" if v > 2 else "DOWN" if v < -2 else "STABLE"
        _safe_print(f"  Learning Velocity: {v:+.1f} ({trend})")

    # Recent sessions
    _safe_print(f"\n  Recent sessions:")
    for h in history[-10:]:
        max_s = h.get("max_depth", 10) * 10
        _safe_print(f"    {h.get('depth_profile', '?'):15s}  "
              f"{h.get('total_score', 0):3d}/{max_s} ({h.get('grade', '?')})  "
              f"{h.get('topic', '?')}")

    # Weak lenses
    if report.get("weakest_lenses"):
        _safe_print(f"\n  Weakest Socratic lenses:")
        for l in report["weakest_lenses"]:
            _safe_print(f"    Depth {l['depth']} ({l['lens']}): failed {l['failures']} times")

    # Strong lenses
    if report.get("strongest_lenses"):
        _safe_print(f"\n  Strongest Socratic lenses:")
        for l in report["strongest_lenses"]:
            _safe_print(f"    Depth {l['depth']} ({l['lens']}): succeeded {l['successes']} times")

    # Ralph quality gate
    rq = report.get("ralph_quality_gate", {})
    if rq.get("total_passed", 0) + rq.get("total_rejected", 0) > 0:
        _safe_print(f"\n  Ralph Quality Gate:")
        _safe_print(f"    Passed: {rq['total_passed']}  |  "
              f"Rejected: {rq['total_rejected']}  |  "
              f"Approval: {rq['approval_rate']}")

    # Knowledge base
    _safe_print(f"\n  Knowledge Base:")
    _safe_print(f"    Total insights: {kb_stats['total_insights']}")
    _safe_print(f"    Ralph-approved: {kb_stats['ralph_approved']} ({kb_stats['approval_rate']})")
    _safe_print(f"    Topics covered: {kb_stats['topics_covered']}")

    kr = report.get("knowledge_reuse", {})
    if kr.get("total_prior_insights_used", 0) > 0:
        _safe_print(f"    Prior insights reused: {kr['total_prior_insights_used']} "
              f"(avg {kr['avg_per_session']}/session)")

    _safe_print(f"\n{'='*60}\n")


# ======================================================
# Domain-specific training
# ======================================================

async def train_all_domains(verbose: bool = True, forge_score: bool = False) -> List[TrainingResult]:
    """Run DEPTH training across all available YAML domains."""
    kb = KnowledgeBase()
    strategy_mem = StrategyMemory()

    # Load domains from YAML files
    domain_topics = _load_domain_topics()
    results = []

    for domain_id, topics in domain_topics.items():
        if domain_id == "classic":
            continue  # Skip classic for engineering training
        # Pick one topic from each domain
        topic = random.choice(topics) if topics else domain_id
        try:
            r = await train(
                topic, verbose=verbose, kb=kb, strategy_mem=strategy_mem,
                domain=domain_id, mode="vibe", forge_score=forge_score,
            )
            results.append(r)
        except Exception as e:
            log.error("Training failed for '%s' [%s]: %s", topic, domain_id, e)
            if verbose:
                _safe_print(f"  X Failed on '{topic}' [{domain_id}]: {e}\n")

    if verbose and results:
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  TRAINING SUMMARY")
        _safe_print(f"{'='*60}")
        for r in sorted(results, key=lambda x: -x.pct):
            _safe_print(f"  {r.depth_profile}  {r.total_score:3d}/{r.max_depth*10} ({r.pct:.0f}%, {r.grade})  {r.topic}")
        avg_pct = sum(r.pct for r in results) / len(results)
        _safe_print(f"\n  Average: {avg_pct:.0f}% across {len(results)} domains")
        _safe_print(f"{'='*60}\n")

    return results


async def train_self(verbose: bool = True, forge_score: bool = False) -> TrainingResult:
    """Run DEPTH on Spark's own learning -- meta self-assessment."""
    kb = KnowledgeBase()
    strategy_mem = StrategyMemory()
    return await train("how Spark learns and improves itself", verbose=verbose, kb=kb, strategy_mem=strategy_mem, forge_score=forge_score)


# ======================================================
# Benchmark Mode: Frozen evaluation with zero injection
# ======================================================

async def run_benchmark_session(
    domain: str,
    topic: str,
    questions: List[Dict[str, Any]],
    verbose: bool = True,
) -> TrainingResult:
    """Run a benchmark session using frozen questions with ZERO knowledge injection.

    This measures raw capability — no KB injection, no strategy loading, no refinement.
    Results go to depth_benchmarks.jsonl separately from training logs.
    """
    max_depth = len(questions)
    agent_name = "spark-benchmark"

    if verbose:
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  BENCHMARK: {topic} [{domain}] ({max_depth} frozen questions)")
        _safe_print(f"  Mode: ZERO injection (raw capability measurement)")
        _safe_print(f"{'='*60}\n")

    steps = []
    answers = []
    last_pushback = ""

    async with httpx.AsyncClient(timeout=60.0) as client:
        for q_data in questions:
            depth = q_data["depth"]
            question = q_data["question"]
            level = DEPTH_LENSES.get(depth, f"Level {depth}")

            if verbose:
                _safe_print(f"  [{depth}/{max_depth}] {level}")
                _safe_print(f"  Q: {question[:120]}{'...' if len(question) > 120 else ''}")

            # Generate answer with NO knowledge injection, NO strategies
            answer = await _generate_answer(
                topic, depth, question, answers,
                knowledge=[],  # ZERO injection
                last_pushback=last_pushback,
                strategy_mem=None,  # NO strategies
                domain=domain,
                mode="vibe",
            )
            answers.append(answer)

            if verbose:
                _safe_print(f"  A: {answer[:120]}{'...' if len(answer) > 120 else ''}")

            # Score via DEPTH API — start a session for scoring
            # We use direct scoring by creating a temporary session
            try:
                # Start a session
                resp = await client.post(
                    f"{DEPTH_API}/api/descend",
                    json={"topic": topic, "agent_name": agent_name,
                          "domain": domain, "mode": "vibe"},
                )
                session_data = resp.json()
                session_id = session_data["session_id"]

                # Submit the answer to get a score
                resp = await client.post(
                    f"{DEPTH_API}/api/answer",
                    json={"session_id": session_id, "answer": answer},
                )
                result = resp.json()

                score = result.get("previous_score") or result.get("score", 0)
                pushback = result.get("pushback", "")
                dimensions = result.get("dimensions", {})
                strengths = result.get("strengths", [])
                gaps = result.get("gaps", [])
            except Exception as e:
                log.warning("Benchmark scoring failed at depth %d: %s", depth, e)
                score = 0
                pushback = ""
                dimensions = {}
                strengths = []
                gaps = []

            steps.append({
                "depth": depth,
                "level": level,
                "question": question,
                "answer": answer,
                "score": score,
                "pushback": pushback,
                "dimensions": dimensions,
                "strengths": strengths,
                "gaps": gaps,
            })

            last_pushback = pushback

            if verbose:
                bar = "#" * score + "." * (10 - score)
                _safe_print(f"  > {bar} {score}/10")
                if pushback:
                    _safe_print(f"  < {pushback[:100]}")
                _safe_print("")

    total_score = sum(s["score"] for s in steps)
    max_score = max_depth * 10
    weak = [s["depth"] for s in steps if s["score"] <= 4]
    strong = [s["depth"] for s in steps if s["score"] >= 8]

    tr = TrainingResult(
        topic=topic,
        session_id=f"bench-{hashlib.md5(f'{domain}:{topic}:{datetime.now(timezone.utc).isoformat()}'.encode()).hexdigest()[:8]}",
        total_score=total_score,
        max_depth=max_depth,
        steps=steps,
        weak_levels=weak,
        strong_levels=strong,
        timestamp=datetime.now(timezone.utc).isoformat(),
        knowledge_used=0,
        domain=domain,
        mode="vibe",
    )

    if verbose:
        _safe_print(f"  {'='*60}")
        _safe_print(f"  BENCHMARK SCORE: {total_score}/{max_score} ({tr.pct:.0f}%, {tr.grade})")
        _safe_print(f"  Profile: {tr.depth_profile}")
        _safe_print(f"  Weak: {weak}  |  Strong: {strong}")
        _safe_print(f"  {'='*60}\n")

    return tr


def _log_benchmark(result: TrainingResult, label: str = ""):
    """Append benchmark result to separate benchmark log."""
    SPARK_DIR.mkdir(parents=True, exist_ok=True)
    steps_compact = [
        {
            "depth": s["depth"], "level": s["level"], "score": s["score"],
            "dimensions": s.get("dimensions", {}),
            "gaps": s.get("gaps", []),
            "strengths": s.get("strengths", []),
        }
        for s in result.steps
    ]
    entry = {
        "label": label,
        "topic": result.topic,
        "domain": result.domain,
        "session_id": result.session_id,
        "total_score": result.total_score,
        "max_depth": result.max_depth,
        "pct": round(result.pct, 1),
        "grade": result.grade,
        "per_depth_scores": result.per_depth_scores,
        "steps": steps_compact,
        "weak_levels": result.weak_levels,
        "strong_levels": result.strong_levels,
        "knowledge_used": result.knowledge_used,
        "timestamp": result.timestamp,
    }
    with open(BENCHMARK_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


async def run_benchmark(
    domain: str,
    verbose: bool = True,
    label: str = "",
) -> List[TrainingResult]:
    """Run frozen benchmark for a domain.

    Loads benchmark JSON, runs each topic sequence with zero injection,
    logs results to depth_benchmarks.jsonl.
    """
    bench_file = BENCHMARKS_DIR / f"{domain}.json"
    if not bench_file.exists():
        if verbose:
            _safe_print(f"  No benchmark file found at {bench_file}")
        return []

    with open(bench_file, "r", encoding="utf-8") as f:
        bench_data = json.load(f)

    sequences = bench_data.get("sequences", [])
    if not sequences:
        if verbose:
            _safe_print(f"  Benchmark file for {domain} has no sequences")
        return []

    if verbose:
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  FROZEN BENCHMARK: {domain}")
        _safe_print(f"  {len(sequences)} topic sequences, {bench_data.get('max_depth', 15)} depths each")
        _safe_print(f"  Label: {label or 'unlabeled'}")
        _safe_print(f"{'='*60}")

    results = []
    for seq in sequences:
        topic = seq["topic"]
        questions = seq["questions"]
        try:
            r = await run_benchmark_session(
                domain=domain, topic=topic, questions=questions,
                verbose=verbose,
            )
            _log_benchmark(r, label=label)
            results.append(r)
        except Exception as e:
            log.error("Benchmark failed for %s/%s: %s", domain, topic, e)
            if verbose:
                _safe_print(f"  X Failed: {topic} -- {e}")

    if verbose and results:
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  BENCHMARK SUMMARY: {domain}")
        _safe_print(f"{'='*60}")
        for r in results:
            _safe_print(f"  {r.depth_profile}  {r.total_score:3d}/{r.max_depth*10} ({r.pct:.0f}%, {r.grade})  {r.topic}")
        avg_pct = sum(r.pct for r in results) / len(results)
        _safe_print(f"\n  Domain average: {avg_pct:.1f}%")
        _safe_print(f"{'='*60}\n")

    return results


def check_regression(domain: str, verbose: bool = True) -> List[Dict[str, Any]]:
    """Compare last 2 benchmark runs per domain, flag regressions.

    Returns list of regression dicts with topic, depth, old_score, new_score.
    """
    if not BENCHMARK_LOG.exists():
        return []

    # Load all benchmark entries for this domain
    entries = []
    with open(BENCHMARK_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("domain") == domain:
                    entries.append(entry)
            except json.JSONDecodeError:
                continue

    if len(entries) < 2:
        if verbose:
            _safe_print(f"  Need at least 2 benchmark runs for {domain} to check regression")
        return []

    # Group by topic, get last 2 per topic
    by_topic: Dict[str, List[Dict]] = {}
    for e in entries:
        topic = e["topic"]
        if topic not in by_topic:
            by_topic[topic] = []
        by_topic[topic].append(e)

    regressions = []
    for topic, runs in by_topic.items():
        if len(runs) < 2:
            continue
        old = runs[-2]
        new = runs[-1]
        old_scores = old.get("per_depth_scores", {})
        new_scores = new.get("per_depth_scores", {})

        for depth_str, old_score in old_scores.items():
            new_score = new_scores.get(depth_str, old_score)
            drop = old_score - new_score
            if drop >= 2:
                reg = {
                    "domain": domain,
                    "topic": topic,
                    "depth": int(depth_str),
                    "old_score": old_score,
                    "new_score": new_score,
                    "drop": drop,
                    "old_label": old.get("label", ""),
                    "new_label": new.get("label", ""),
                }
                regressions.append(reg)
                if verbose:
                    _safe_print(
                        f"  REGRESSION: {domain}/{topic} D{depth_str} "
                        f"dropped {old_score}->{new_score} (delta: -{drop})"
                    )

    if verbose and not regressions:
        _safe_print(f"  No regressions detected for {domain}")

    return regressions


def get_benchmark_history(domain: str = None) -> List[Dict]:
    """Get all benchmark results, optionally filtered by domain."""
    if not BENCHMARK_LOG.exists():
        return []
    entries = []
    with open(BENCHMARK_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if domain is None or entry.get("domain") == domain:
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
    return entries


def benchmark_report(domain: str = None, verbose: bool = True) -> Dict[str, Any]:
    """Generate benchmark comparison report showing score evolution."""
    entries = get_benchmark_history(domain)
    if not entries:
        if verbose:
            _safe_print("  No benchmark data yet. Run: --benchmark --domain <domain>")
        return {"domains": {}, "total_runs": 0}

    # Group by domain
    by_domain: Dict[str, List[Dict]] = {}
    for e in entries:
        d = e.get("domain", "unknown")
        if d not in by_domain:
            by_domain[d] = []
        by_domain[d].append(e)

    report = {"domains": {}, "total_runs": len(entries)}

    for d, runs in by_domain.items():
        domain_report = {
            "runs": len(runs),
            "avg_pct": round(sum(r.get("pct", 0) for r in runs) / len(runs), 1),
            "best_pct": max(r.get("pct", 0) for r in runs),
            "worst_pct": min(r.get("pct", 0) for r in runs),
            "topics": {},
        }

        # Per-topic trajectory
        by_topic: Dict[str, List[Dict]] = {}
        for r in runs:
            t = r["topic"]
            if t not in by_topic:
                by_topic[t] = []
            by_topic[t].append(r)

        for t, topic_runs in by_topic.items():
            scores = [r.get("pct", 0) for r in topic_runs]
            domain_report["topics"][t] = {
                "runs": len(topic_runs),
                "scores": scores,
                "trend": "improving" if len(scores) >= 2 and scores[-1] > scores[0] + 2
                        else "declining" if len(scores) >= 2 and scores[-1] < scores[0] - 2
                        else "stable",
            }

        report["domains"][d] = domain_report

        if verbose:
            _safe_print(f"\n{'='*60}")
            _safe_print(f"  BENCHMARK REPORT: {d}")
            _safe_print(f"  {domain_report['runs']} runs | avg {domain_report['avg_pct']}% | best {domain_report['best_pct']}%")
            _safe_print(f"{'='*60}")
            for t, info in domain_report["topics"].items():
                scores_str = " -> ".join(f"{s:.0f}%" for s in info["scores"])
                _safe_print(f"  {t}: {scores_str} [{info['trend']}]")

    return report


# ======================================================
# Phase 4: Gap Extraction, Golden Answers, Insight Tracking
# ======================================================

def _extract_gaps(result: TrainingResult) -> List[Dict[str, Any]]:
    """Extract structured learning gaps from low-scoring depths.

    Gaps become targeted learning objectives for future sessions.
    """
    gaps = []
    for step in result.steps:
        score = step["score"]
        if score >= 7:
            continue  # Not a gap

        dimensions = step.get("dimensions", {})
        # Find weakest dimension
        weakest_dim = ""
        weakest_val = 11
        for dim, val in dimensions.items():
            if isinstance(val, (int, float)) and val < weakest_val:
                weakest_val = val
                weakest_dim = dim

        gap = {
            "domain": result.domain,
            "topic": result.topic,
            "depth": step["depth"],
            "lens": step["level"],
            "score": score,
            "dimensions": dimensions,
            "gap_type": weakest_dim or "overall",
            "question_excerpt": step["question"][:200],
            "pushback": step.get("pushback", "")[:200],
            "step_gaps": step.get("gaps", []),
            "timestamp": result.timestamp,
            "session_id": result.session_id,
        }
        gaps.append(gap)

    return gaps


def store_gaps(new_gaps: List[Dict[str, Any]]):
    """Store gaps to persistent file, deduplicating by domain+topic+depth."""
    SPARK_DIR.mkdir(parents=True, exist_ok=True)
    existing = []
    if GAPS_FILE.exists():
        try:
            with open(GAPS_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing = []

    # Deduplicate: keep latest gap for each domain+topic+depth
    key_map = {}
    for g in existing:
        k = f"{g.get('domain', '')}:{g.get('topic', '')}:{g.get('depth', 0)}"
        key_map[k] = g

    for g in new_gaps:
        k = f"{g.get('domain', '')}:{g.get('topic', '')}:{g.get('depth', 0)}"
        key_map[k] = g  # Overwrite with newer

    all_gaps = list(key_map.values())
    # Sort by score ascending (weakest first)
    all_gaps.sort(key=lambda x: x.get("score", 0))

    # Keep max 200 gaps
    all_gaps = all_gaps[:200]

    with open(GAPS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_gaps, f, indent=2)


def get_weakest_gaps(domain: str = None, count: int = 5) -> List[Dict]:
    """Get the N weakest gaps, optionally filtered by domain."""
    if not GAPS_FILE.exists():
        return []
    try:
        with open(GAPS_FILE, "r", encoding="utf-8") as f:
            gaps = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    if domain:
        gaps = [g for g in gaps if g.get("domain") == domain]

    # Already sorted by score ascending
    return gaps[:count]


def harvest_golden_answers(result: TrainingResult):
    """Store answers that score 9+ on ALL dimensions as golden examples.

    These serve as verified few-shot examples for future sessions.
    """
    SPARK_DIR.mkdir(parents=True, exist_ok=True)
    golden = {}
    if GOLDEN_ANSWERS_FILE.exists():
        try:
            with open(GOLDEN_ANSWERS_FILE, "r", encoding="utf-8") as f:
                golden = json.load(f)
        except (json.JSONDecodeError, IOError):
            golden = {}

    for step in result.steps:
        score = step["score"]
        dims = step.get("dimensions", {})

        # Must score 9+ overall AND have all dimensions >= 8
        if score < 9:
            continue
        if dims and any(v < 8 for v in dims.values() if isinstance(v, (int, float))):
            continue

        key = f"{result.domain}/{step['depth']}"
        golden_entry = {
            "domain": result.domain,
            "topic": result.topic,
            "depth": step["depth"],
            "lens": step["level"],
            "question": step["question"],
            "answer": step["answer"],
            "score": score,
            "dimensions": dims,
            "session_id": result.session_id,
            "timestamp": result.timestamp,
        }

        # Keep best per domain/depth slot
        existing = golden.get(key)
        if not existing or existing.get("score", 0) < score:
            golden[key] = golden_entry

    with open(GOLDEN_ANSWERS_FILE, "w", encoding="utf-8") as f:
        json.dump(golden, f, indent=2)


def get_golden_answer(domain: str, depth: int) -> Optional[Dict]:
    """Retrieve a golden answer for a specific domain/depth."""
    if not GOLDEN_ANSWERS_FILE.exists():
        return None
    try:
        with open(GOLDEN_ANSWERS_FILE, "r", encoding="utf-8") as f:
            golden = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None
    return golden.get(f"{domain}/{depth}")


def get_golden_stats() -> Dict[str, Any]:
    """Get statistics about collected golden answers."""
    if not GOLDEN_ANSWERS_FILE.exists():
        return {"total": 0, "by_domain": {}}
    try:
        with open(GOLDEN_ANSWERS_FILE, "r", encoding="utf-8") as f:
            golden = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"total": 0, "by_domain": {}}

    by_domain: Dict[str, int] = {}
    for key in golden:
        domain = key.split("/")[0] if "/" in key else "unknown"
        by_domain[domain] = by_domain.get(domain, 0) + 1

    return {"total": len(golden), "by_domain": by_domain}


# ======================================================
# A/B Test: Measure Knowledge Injection Effectiveness
# ======================================================

async def ab_test(
    domain: str,
    topic: str = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Run same benchmark questions WITH and WITHOUT KB injection.

    Shows the delta — proof that accumulated knowledge actually helps.
    """
    bench_file = BENCHMARKS_DIR / f"{domain}.json"
    if not bench_file.exists():
        if verbose:
            _safe_print(f"  No benchmark file for {domain}")
        return {}

    with open(bench_file, "r", encoding="utf-8") as f:
        bench_data = json.load(f)

    sequences = bench_data.get("sequences", [])
    if topic:
        sequences = [s for s in sequences if s["topic"] == topic]
    if not sequences:
        if verbose:
            _safe_print(f"  No matching sequences for topic: {topic}")
        return {}

    # Pick first matching sequence
    seq = sequences[0]
    test_topic = seq["topic"]
    questions = seq["questions"]

    if verbose:
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  A/B TEST: {test_topic} [{domain}]")
        _safe_print(f"  Control: zero injection | Treatment: full KB + strategies")
        _safe_print(f"{'='*60}")

    # A: Zero injection (benchmark mode)
    if verbose:
        _safe_print(f"\n  --- RUN A: Zero Injection ---")
    result_a = await run_benchmark_session(
        domain=domain, topic=test_topic, questions=questions,
        verbose=verbose,
    )

    # B: Full injection (training mode)
    if verbose:
        _safe_print(f"\n  --- RUN B: Full Knowledge Injection ---")
    kb = KnowledgeBase()
    strategy_mem = StrategyMemory()

    # Re-run with injection by using normal training against same questions
    steps_b = []
    answers = []
    last_pushback = ""

    async with httpx.AsyncClient(timeout=60.0) as client:
        for q_data in questions:
            depth = q_data["depth"]
            question = q_data["question"]

            # Full injection
            prior_knowledge = kb.retrieve(test_topic, depth, limit=3, domain=domain)
            answer = await _generate_answer(
                test_topic, depth, question, answers,
                knowledge=prior_knowledge,
                last_pushback=last_pushback,
                strategy_mem=strategy_mem,
                domain=domain,
                mode="vibe",
            )
            answers.append(answer)

            # Score
            try:
                resp = await client.post(
                    f"{DEPTH_API}/api/descend",
                    json={"topic": test_topic, "agent_name": "spark-ab-test",
                          "domain": domain, "mode": "vibe"},
                )
                sid = resp.json()["session_id"]
                resp = await client.post(
                    f"{DEPTH_API}/api/answer",
                    json={"session_id": sid, "answer": answer},
                )
                r = resp.json()
                score = r.get("previous_score") or r.get("score", 0)
                pushback = r.get("pushback", "")
                dimensions = r.get("dimensions", {})
            except Exception:
                score = 0
                pushback = ""
                dimensions = {}

            steps_b.append({
                "depth": depth, "score": score,
                "dimensions": dimensions,
            })
            last_pushback = pushback

            if verbose:
                bar = "#" * score + "." * (10 - score)
                _safe_print(f"  [{depth}] {bar} {score}/10")

    # Compare
    total_a = result_a.total_score
    total_b = sum(s["score"] for s in steps_b)
    max_score = len(questions) * 10

    delta = total_b - total_a
    delta_pct = (total_b - total_a) / max_score * 100

    report = {
        "domain": domain,
        "topic": test_topic,
        "control_score": total_a,
        "treatment_score": total_b,
        "max_score": max_score,
        "delta": delta,
        "delta_pct": round(delta_pct, 1),
        "kb_effective": delta > 0,
        "per_depth_delta": {},
    }

    for sa, sb in zip(result_a.steps, steps_b):
        d = sa["depth"]
        report["per_depth_delta"][d] = sb["score"] - sa["score"]

    if verbose:
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  A/B TEST RESULTS: {test_topic}")
        _safe_print(f"{'='*60}")
        _safe_print(f"  Control (zero KB):   {total_a}/{max_score} ({total_a/max_score*100:.0f}%)")
        _safe_print(f"  Treatment (full KB): {total_b}/{max_score} ({total_b/max_score*100:.0f}%)")
        _safe_print(f"  Delta: {'+' if delta > 0 else ''}{delta} points ({'+' if delta_pct > 0 else ''}{delta_pct}%)")
        _safe_print(f"  KB Effective: {'YES' if delta > 0 else 'NO'}")
        _safe_print(f"{'='*60}\n")

    return report


def _print_ingest_stats(stats: Dict[str, Any]):
    """Print summary of Opus session ingestion."""
    eidos_list = stats.get("eidos_episodes", [])
    _safe_print(f"\n{'='*60}")
    _safe_print(f"  OPUS INGESTION COMPLETE")
    _safe_print(f"{'='*60}")
    _safe_print(f"  Sessions ingested:  {stats.get('ingested', 0)}")
    _safe_print(f"  Sessions skipped:   {stats.get('skipped', 0)}")
    _safe_print(f"  Ralph approved:     {stats.get('ralph_passed', 0)}")
    _safe_print(f"  Ralph rejected:     {stats.get('ralph_rejected', 0)}")
    _safe_print(f"  EIDOS episodes:     {len(eidos_list)}")
    _safe_print(f"  Cognitive insights: {stats.get('cognitive_stored', 0)}")
    _safe_print(f"  Gaps extracted:     {stats.get('gaps_found', 0)}")
    _safe_print(f"  Golden answers:     {stats.get('golden_harvested', 0)}")


# ======================================================
# CLI
# ======================================================

async def _main():
    import argparse
    parser = argparse.ArgumentParser(
        description="DEPTH Trainer -- Engineering reasoning gym for Spark Intelligence"
    )
    parser.add_argument("--topic", type=str, help="Topic to train on")
    parser.add_argument("--domain", type=str, help="Domain (ui_ux, debugging, api_data_flow, classic)")
    parser.add_argument("--mode", type=str, default="vibe", choices=["vibe", "classic"],
                        help="Mode: vibe (15 levels) or classic (10 levels)")
    parser.add_argument("--all", action="store_true", help="Train across all domains")
    parser.add_argument("--self", action="store_true", help="Self-assessment mode")
    parser.add_argument("--loop", action="store_true", help="Autonomous training loop")
    parser.add_argument("--cycles", type=int, default=0,
                        help="Number of autonomous cycles (0=infinite)")
    parser.add_argument("--history", action="store_true", help="Show training history")
    parser.add_argument("--report", action="store_true", help="Show weakness report")
    parser.add_argument("--dashboard", action="store_true", help="Full status dashboard")
    parser.add_argument("--no-integrate", action="store_true", help="Skip Spark integration")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")
    # Benchmark flags
    parser.add_argument("--benchmark", action="store_true", help="Run frozen benchmark (zero injection)")
    parser.add_argument("--benchmark-report", action="store_true", help="Show benchmark comparison report")
    parser.add_argument("--benchmark-label", type=str, default="", help="Label for this benchmark run")
    parser.add_argument("--regression", action="store_true", help="Check for score regressions")
    parser.add_argument("--ab-test", action="store_true", help="A/B test KB effectiveness")
    parser.add_argument("--gaps", action="store_true", help="Show current learning gaps")
    parser.add_argument("--golden", action="store_true", help="Show golden answer stats")
    # Forge dual-scoring flags
    parser.add_argument("--forge-score", action="store_true",
                        help="Re-score with Opus 4.6 + Codex 5.3 dual scoring via CLI (~$0.70/session)")
    # Opus ingestion flags
    parser.add_argument("--ingest", type=str, metavar="PATH",
                        help="Ingest Opus-scored sessions from a JSONL file")
    parser.add_argument("--ingest-all-opus", action="store_true",
                        help="Ingest all from ~/.spark/depth_opus_sessions.jsonl")
    args = parser.parse_args()

    if args.dashboard:
        print_dashboard()
        return

    if args.ingest:
        _safe_print(f"\n  Ingesting Opus sessions from: {args.ingest}")
        stats = ingest_opus_session(args.ingest)
        _print_ingest_stats(stats)
        return

    if args.ingest_all_opus:
        path = str(OPUS_SESSIONS_FILE)
        if not OPUS_SESSIONS_FILE.exists():
            _safe_print(f"  No Opus sessions file found at {path}")
            return
        _safe_print(f"\n  Ingesting all Opus sessions from: {path}")
        stats = ingest_opus_session(path)
        _print_ingest_stats(stats)
        return

    if args.golden:
        stats = get_golden_stats()
        _safe_print(f"\nGolden Answers: {stats['total']} verified exemplars")
        for d, count in stats.get("by_domain", {}).items():
            _safe_print(f"  {d}: {count}")
        return

    if args.gaps:
        domain_filter = args.domain
        weak = get_weakest_gaps(domain=domain_filter, count=20)
        if not weak:
            _safe_print("No gaps recorded yet.")
            return
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  LEARNING GAPS ({len(weak)} targets)")
        _safe_print(f"{'='*60}")
        for g in weak:
            dims = g.get("dimensions", {})
            dim_str = " ".join(f"{k[:3]}={v}" for k, v in dims.items()) if dims else ""
            _safe_print(f"  [{g.get('domain', '?')}] {g['topic']} D{g['depth']} "
                        f"score={g['score']}/10 gap={g.get('gap_type', '?')} {dim_str}")
        return

    if args.benchmark_report:
        benchmark_report(domain=args.domain, verbose=True)
        return

    if args.regression:
        if not args.domain:
            _safe_print("--regression requires --domain")
            return
        regs = check_regression(args.domain, verbose=True)
        if not regs:
            _safe_print(f"No regressions for {args.domain}")
        return

    if args.history:
        history = get_training_history()
        if not history:
            _safe_print("No training history yet.")
            return
        _safe_print(f"\n{'='*60}")
        _safe_print(f"  TRAINING HISTORY ({len(history)} sessions)")
        _safe_print(f"{'='*60}")
        for h in history:
            max_s = h.get("max_depth", 10) * 10
            _safe_print(f"  {h.get('depth_profile', '?'):15s}  "
                  f"{h.get('total_score', 0):3d}/{max_s} ({h.get('grade', '?')})  "
                  f"{h.get('topic', '?')}")
        return

    if args.report:
        report = get_weakness_report()
        _safe_print(json.dumps(report, indent=2))
        return

    # Auto-detect mode from domain
    mode = args.mode
    if args.domain == "classic":
        mode = "classic"

    if args.benchmark:
        if not args.domain:
            _safe_print("--benchmark requires --domain")
            return
        results = await run_benchmark(
            domain=args.domain,
            verbose=not args.quiet,
            label=args.benchmark_label,
        )
        if results:
            _safe_print(f"\n  Benchmark logged to {BENCHMARK_LOG}")
    elif args.ab_test:
        if not args.domain:
            _safe_print("--ab-test requires --domain")
            return
        await ab_test(
            domain=args.domain,
            topic=args.topic,
            verbose=not args.quiet,
        )
    elif args.loop:
        await run_autonomous_loop(
            max_cycles=args.cycles,
            verbose=not args.quiet,
            domain=args.domain,
            mode=mode,
            forge_score=args.forge_score,
        )
    elif args.self:
        await train_self(verbose=not args.quiet, forge_score=args.forge_score)
    elif args.all:
        await train_all_domains(verbose=not args.quiet, forge_score=args.forge_score)
    elif args.topic:
        await train(
            args.topic,
            integrate=not args.no_integrate,
            verbose=not args.quiet,
            domain=args.domain,
            mode=mode,
            forge_score=args.forge_score,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
    )
    asyncio.run(_main())
