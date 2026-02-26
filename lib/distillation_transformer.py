"""
Distillation Quality Transformer: Bridge between Meta-Ralph scoring and advisory delivery.

Problem: Meta-Ralph scores distillations on 5 dimensions (actionability, novelty, reasoning,
specificity, outcome_linked) but this scoring is discarded after the gate decision. Advisory
then re-computes quality heuristics from scratch using regex. This creates duplicate work
and inconsistent quality signals.

Solution: Transform distillations at storage time, embedding quality dimensions and
semantic structure so advisory can use them directly.

Integration:
- cognitive_learner.add_insight() -> transform_for_advisory() -> store advisory_quality
- bridge_cycle._append_eidos_update() -> transform_for_advisory() -> embed in JSONL
- advisor._rank_score() -> read advisory_quality instead of _score_actionability()
- advisory_memory_fusion._collect_cognitive() -> use unified_score as confidence
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .noise_patterns import is_session_boilerplate


@dataclass
class AdvisoryQuality:
    """Quality dimensions optimized for advisory retrieval and ranking."""

    actionability: float = 0.0      # 0-1: has verb + object (do Y / avoid Y)
    novelty: float = 0.0            # 0-1: not obvious or repeated
    reasoning: float = 0.0          # 0-1: has "because" / "since" / causal link
    specificity: float = 0.0        # 0-1: names tools, domains, files, versions
    outcome_linked: float = 0.0     # 0-1: tied to measurable result
    unified_score: float = 0.0      # 0-1: weighted blend of all dimensions

    advisory_text: str = ""              # Composed advisory-ready text (empty = use raw)
    structure: Dict[str, Optional[str]] = field(default_factory=dict)
    domain: str = "general"
    suppressed: bool = False
    suppression_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "actionability": round(self.actionability, 3),
            "novelty": round(self.novelty, 3),
            "reasoning": round(self.reasoning, 3),
            "specificity": round(self.specificity, 3),
            "outcome_linked": round(self.outcome_linked, 3),
            "unified_score": round(self.unified_score, 3),
            "structure": self.structure or {},
            "domain": self.domain,
            "suppressed": self.suppressed,
            "suppression_reason": self.suppression_reason,
        }
        if self.advisory_text:
            d["advisory_text"] = self.advisory_text
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdvisoryQuality":
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            actionability=float(data.get("actionability", 0.0) or 0.0),
            novelty=float(data.get("novelty", 0.0) or 0.0),
            reasoning=float(data.get("reasoning", 0.0) or 0.0),
            specificity=float(data.get("specificity", 0.0) or 0.0),
            outcome_linked=float(data.get("outcome_linked", 0.0) or 0.0),
            unified_score=float(data.get("unified_score", 0.0) or 0.0),
            advisory_text=str(data.get("advisory_text", "") or ""),
            structure=data.get("structure") or {},
            domain=str(data.get("domain", "general") or "general"),
            suppressed=bool(data.get("suppressed", False)),
            suppression_reason=str(data.get("suppression_reason", "") or ""),
        )


# ---------------------------------------------------------------------------
# Dimension weights for unified score
# ---------------------------------------------------------------------------
_DIM_WEIGHTS = {
    "actionability": 0.30,
    "novelty": 0.15,
    "reasoning": 0.20,
    "specificity": 0.15,
    "outcome_linked": 0.20,
}

# ---------------------------------------------------------------------------
# Regex patterns for structure extraction
# ---------------------------------------------------------------------------

# Condition patterns: "when X", "if X", "before X", "after X", "for X tasks"
_CONDITION_PATTERNS = [
    re.compile(r"\b(?:when|whenever)\s+(.{8,80}?)(?:\s*[,;:]|\s+(?:then|do|use|avoid|prefer|always|never|set|ensure|check))", re.I),
    re.compile(r"\b(?:if|unless)\s+(.{8,80}?)(?:\s*[,;:]|\s+(?:then|do|use|avoid|prefer|always|never))", re.I),
    re.compile(r"\b(?:before|after|during)\s+(.{8,60}?)(?:\s*[,;:])", re.I),
    re.compile(r"\bfor\s+(\w[\w\s]{4,40}?)\s+tasks?\b", re.I),
    re.compile(r"\bin\s+(?:the\s+)?(?:context\s+of|case\s+of)\s+(.{8,60}?)(?:\s*[,;:])", re.I),
]

# Action patterns: "use Y", "avoid Y", "prefer Y", "set Y", "always Y", "never Y"
_ACTION_PATTERNS = [
    re.compile(r"\b(?:always|never|must|should)\s+(.{5,100}?)(?:\s+because|\s+since|\s+due\s+to|\s+which|\s+that|\s+so\s+that|[.;]|$)", re.I),
    re.compile(r"\b(?:use|avoid|prefer|ensure|check|set|apply|enable|disable|run|add|remove|verify|validate|confirm|test)\s+(.{5,100}?)(?:\s+because|\s+since|\s+due\s+to|\s+which|\s+that|\s+so\s+that|[.;]|$)", re.I),
    re.compile(r"\b(?:instead\s+of)\s+(.{5,60}?)(?:\s*[,;:]|\s+use|\s+prefer)", re.I),
]

# Reasoning patterns: "because Z", "since Z", "due to Z"
_REASONING_PATTERNS = [
    re.compile(r"\b(?:because|since)\s+(.{8,120}?)(?:[.;]|$)", re.I),
    re.compile(r"\b(?:due\s+to|owing\s+to)\s+(.{8,80}?)(?:[.;]|$)", re.I),
    re.compile(r"\b(?:the\s+reason\s+(?:is|being))\s+(.{8,100}?)(?:[.;]|$)", re.I),
    re.compile(r"\b(?:as\s+a\s+result\s+of)\s+(.{8,80}?)(?:[.;]|$)", re.I),
]

# Outcome patterns: "which leads to W", "results in W", "improves W"
_OUTCOME_PATTERNS = [
    re.compile(r"\b(?:which|that)\s+(?:leads?\s+to|results?\s+in|causes?|prevents?|improves?|reduces?)\s+(.{5,80}?)(?:[.;]|$)", re.I),
    re.compile(r"\b(?:results?\s+in|leads?\s+to)\s+(.{5,80}?)(?:[.;]|$)", re.I),
    re.compile(r"\b(?:to\s+(?:avoid|prevent|ensure|improve|reduce|fix))\s+(.{5,80}?)(?:[.;]|$)", re.I),
    re.compile(r"\b(?:so\s+that)\s+(.{5,80}?)(?:[.;]|$)", re.I),
]

# ---------------------------------------------------------------------------
# Scoring patterns (aligned with Meta-Ralph's rubric)
# ---------------------------------------------------------------------------

_ACTIONABILITY_VERBS = {
    "always", "never", "use", "avoid", "prefer", "should", "must",
    "set", "cap", "enable", "disable", "check", "ensure", "run",
    "add", "remove", "apply", "configure", "switch",
    "verify", "validate", "confirm", "test",
}

_ACTIONABILITY_SOFT_VERBS = {
    "consider", "try", "might", "could", "optimal", "balance",
    "drives", "increases", "decreases", "reduces", "outperforms",
    "strategy", "approach", "pattern", "technique", "prioritize",
}

_REASONING_KEYWORDS = {"because", "the reason", "due to", "since", "as a result"}
_REASONING_SOFT = {
    "so that", "in order to", "helps", "prevents",
    "for better", "for easier", "for safer", "for faster",
    "to avoid", "to ensure", "to prevent", "to improve",
    "which means", "which allows", "which prevents",
    "data shows", "evidence", "correlates", "consistently",
}

_SPECIFICITY_MARKERS = {
    "user", "this project", "typescript", "javascript", "python", "react",
    "postgresql", "mysql", "oauth", "api", "player", "health", "damage",
    "queue", "worker", "bridge", "pipeline", "flow",
    "authentication", "token", "payload", "schema", "contract",
}

_OUTCOME_WORDS = {
    "worked", "failed", "resulted in", "led to", "fixed", "broke",
}
_OUTCOME_SOFT = {
    "helps", "improves", "prevents", "causes",
    "better", "safer", "faster", "easier",
    "feels fair", "feels good", "satisfying",
    "likes", "engagement", "views", "conversion", "retention",
    "drives", "outperforms", "increases",
    "regressions", "bugs", "errors",
}

_QUALITY_SIGNALS = [
    r"because", r"prefer[s]?", r"when .+ then", r"avoid",
    r"instead of", r"the reason", r"user wants", r"mistake",
    r"actually", r"remember", r"critical", r"insight",
    r"principle", r"balance", r"sweet spot", r"data shows",
    r"consistently", r"outperforms?", r"\d{3,}\s*(avg|likes|views)",
    r"strategy",
]

# ---------------------------------------------------------------------------
# Suppression patterns (aggressive advisory-specific noise filter)
# ---------------------------------------------------------------------------

_SUPPRESS_PREFIXES = [
    "RT @",
    "[DEPTH:",
    "Strong Socratic depth on",
    "Strong reasoning on",
    "Strong CONNECTIONS",
    "Strong PARADOX",
    "Strong CONSCIOUSNESS",
    "Strong VOID",
    "Strong IDENTITY",
    "Strong DECOMPOSE",
    "Strong OPTIMIZE",
    "Strong SIMPLIFY",
]

_SUPPRESS_VERBATIM_QUOTE_STARTS = [
    "Now, can we",
    "Can you now",
    "lets make sure",
    "by the way",
    "I think we",
    "I'd say",
    "can we now",
]

_SUPPRESS_PATTERNS = [
    re.compile(r"^\s*said it like this[:\s]", re.I),
    re.compile(r"^\s*another reply is[:\s]", re.I),
    re.compile(r"^\(eng:\d+\)", re.I),
    re.compile(r"^\s*\[vibe_coding\]\s*RT\s+@", re.I),
    re.compile(r"^\s*\[Market Intelligence\]", re.I),
]

_DOMAIN_CODE = re.compile(
    r"\b(?:function|class |def |import |require\(|module|typescript|javascript|python|react|git |npm |pip |test|debug|refactor|\.py\b|\.ts\b|\.js\b)\b",
    re.I,
)
_DOMAIN_SYSTEM = re.compile(
    r"\b(?:pipeline|bridge[_\s]?cycle|meta[_\s]?ralph|cognitive[_\s]?learner|advisory|distillation|tuneables?|eidos)\b",
    re.I,
)


def extract_structure(text: str) -> Dict[str, Optional[str]]:
    """Extract semantic structure from advisory text.

    Returns dict with keys: condition, action, reasoning, outcome.
    Each value is either the extracted substring or None.
    """
    result: Dict[str, Optional[str]] = {
        "condition": None,
        "action": None,
        "reasoning": None,
        "outcome": None,
    }
    if not text or len(text) < 10:
        return result

    for patterns, key in [
        (_CONDITION_PATTERNS, "condition"),
        (_ACTION_PATTERNS, "action"),
        (_REASONING_PATTERNS, "reasoning"),
        (_OUTCOME_PATTERNS, "outcome"),
    ]:
        for pat in patterns:
            m = pat.search(text)
            if m:
                captured = m.group(1).strip()
                if len(captured) >= 5:
                    result[key] = captured[:120]
                    break

    return result


def _detect_domain(text: str, source: str = "") -> str:
    """Detect advisory domain from text content."""
    if _DOMAIN_CODE.search(text):
        return "code"
    if _DOMAIN_SYSTEM.search(text):
        return "system"
    src = (source or "").lower()
    if any(t in src for t in ("depth", "forge")):
        return "code"
    return "general"


def _score_actionability(text: str) -> float:
    """Score actionability 0-1."""
    text_lower = text.lower()
    if any(w in text_lower for w in _ACTIONABILITY_VERBS):
        return 1.0
    if any(w in text_lower for w in _ACTIONABILITY_SOFT_VERBS):
        return 0.5
    # Numeric evidence implies some actionability
    if re.search(r"\d{2,}", text_lower):
        if any(w in text_lower for w in ("avg", "likes", "engagement", "%", "score", "rate")):
            return 0.5
    return 0.0


def _score_novelty(text: str) -> float:
    """Score novelty 0-1."""
    text_lower = text.lower()
    quality_matches = sum(1 for p in _QUALITY_SIGNALS if re.search(p, text_lower))
    has_numeric = bool(re.search(r"\d{3,}", text_lower))
    if quality_matches >= 2 or (has_numeric and quality_matches >= 1):
        return 1.0
    if quality_matches >= 1 or has_numeric:
        return 0.5
    return 0.0


def _score_reasoning(text: str) -> float:
    """Score reasoning quality 0-1."""
    text_lower = text.lower()
    if any(w in text_lower for w in _REASONING_KEYWORDS):
        return 1.0
    if any(w in text_lower for w in _REASONING_SOFT):
        return 0.5
    # Comparative data implies reasoning
    if re.search(r"\d{3,}", text_lower) and any(w in text_lower for w in ("vs", "over", "compared", "avg", "outperforms")):
        return 0.5
    return 0.0


def _score_specificity(text: str) -> float:
    """Score specificity 0-1."""
    text_lower = text.lower()
    # File extensions or paths = high specificity
    if any(tok in text_lower for tok in ("/", "\\", ".py", ".js", ".ts", ".md", ".json")):
        return 1.0
    marker_count = sum(1 for m in _SPECIFICITY_MARKERS if m in text_lower)
    if marker_count >= 2:
        return 1.0
    if marker_count >= 1:
        return 0.5
    return 0.0


def _score_outcome_linked(text: str) -> float:
    """Score outcome linkage 0-1."""
    text_lower = text.lower()
    if any(w in text_lower for w in _OUTCOME_WORDS):
        return 1.0
    if any(w in text_lower for w in _OUTCOME_SOFT):
        return 0.5
    if re.search(r"\d{3,}", text_lower) and any(w in text_lower for w in ("avg", "rate", "%", "score")):
        return 0.5
    return 0.0


def _compute_unified_score(dims: Dict[str, float]) -> float:
    """Weighted blend of all dimensions into 0-1 score."""
    total = 0.0
    for dim, weight in _DIM_WEIGHTS.items():
        total += dims.get(dim, 0.0) * weight
    return min(1.0, max(0.0, total))


def _compose_advisory_text(
    raw_text: str,
    structure: Dict[str, Optional[str]],
    dims: Dict[str, float],
) -> str:
    """Compose clean advisory text from extracted structure.

    Rewrites raw distillation text into a concise, actionable format.
    Returns empty string if no meaningful structure was extracted
    (caller should fall back to raw text).
    """
    condition = structure.get("condition")
    action = structure.get("action")
    reasoning = structure.get("reasoning")
    outcome = structure.get("outcome")

    # Need at least an action to compose
    if not action:
        return ""

    # Trim trailing punctuation from components
    action = action.rstrip(".,;: ")
    if condition:
        condition = condition.rstrip(".,;: ")
    if reasoning:
        reasoning = reasoning.rstrip(".,;: ")
    if outcome:
        outcome = outcome.rstrip(".,;: ")

    parts: list[str] = []

    # Build: "When {condition}: {action}"
    if condition and action:
        parts.append(f"When {condition}: {action}")
    elif action:
        parts.append(action[0].upper() + action[1:] if action else "")

    # Add reasoning: "because {reasoning}"
    if reasoning and dims.get("reasoning", 0) >= 0.5:
        parts.append(f"because {reasoning}")

    # Add outcome: "— {outcome}"
    if outcome and dims.get("outcome_linked", 0) >= 0.5:
        parts.append(f"({outcome})")

    composed = " ".join(parts).strip()

    # Only use composed text if it's meaningfully different and shorter than raw
    if not composed or len(composed) < 15:
        return ""
    # If composed is longer than raw, the raw was probably already concise
    if len(composed) > len(raw_text) * 1.2:
        return ""
    return composed


def should_suppress(text: str, dims: Dict[str, float], structure: Dict[str, Optional[str]]) -> Tuple[bool, str]:
    """Determine if a distillation should be suppressed from advisory.

    More aggressive than Meta-Ralph's gate — catches noise that passes
    the structural/primitive checks but isn't useful as advice.
    """
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    if is_session_boilerplate(text_stripped):
        return True, "session_boilerplate"

    # Prefix-based suppression (observations, not advice)
    for prefix in _SUPPRESS_PREFIXES:
        if text_stripped.startswith(prefix):
            return True, f"observation_prefix:{prefix[:20]}"

    # Verbatim user quotes without extracted action
    for prefix in _SUPPRESS_VERBATIM_QUOTE_STARTS:
        if text_stripped.startswith(prefix):
            if not structure.get("action"):
                return True, "verbatim_quote_no_action"

    # Pattern-based suppression
    for pat in _SUPPRESS_PATTERNS:
        if pat.search(text_stripped):
            return True, "noise_pattern"

    # Code artifact: >60% non-alpha in first 100 chars
    sample = text_stripped[:100]
    if len(sample) >= 20:
        alpha_count = sum(1 for c in sample if c.isalpha())
        if alpha_count / len(sample) < 0.40:
            return True, "code_artifact"

    # Pure observation: no actionability AND no reasoning
    escaped_no_action = False
    if dims.get("actionability", 0) == 0 and dims.get("reasoning", 0) == 0:
        # Allow if it has strong outcome evidence with specificity
        if dims.get("outcome_linked", 0) >= 0.5 and dims.get("specificity", 0) >= 0.5:
            escaped_no_action = True  # Keep: outcome-backed specific observation
        elif dims.get("novelty", 0) >= 0.5:
            escaped_no_action = True  # Keep: has quality signals (data, patterns, insights)
        else:
            return True, "no_action_no_reasoning"

    # Operationalizability gate: require explicit action plus one of
    # condition/reasoning/outcome/specificity so retrieval can produce
    # actionable advice later.  Specificity counts because domain-specific
    # advice (e.g. "validate auth tokens") is operationalizable even without
    # an explicit "because" clause.
    # Skip for items that passed the no-action escape hatch above — they
    # were explicitly kept as valuable non-actionable observations.
    if not escaped_no_action:
        has_action = bool(structure.get("action")) or dims.get("actionability", 0) >= 0.5
        has_support = (
            bool(structure.get("condition"))
            or dims.get("reasoning", 0) >= 0.5
            or dims.get("outcome_linked", 0) >= 0.5
            or dims.get("specificity", 0) >= 0.5
        )
        if not has_action:
            return True, "missing_action_structure"
        if not has_support:
            return True, "missing_condition_reason_or_outcome"

    # Tautology: actionable but no condition, reasoning, outcome, OR specificity
    if dims.get("actionability", 0) >= 0.5:
        has_condition = bool(structure.get("condition"))
        has_reasoning = dims.get("reasoning", 0) >= 0.5
        has_outcome = dims.get("outcome_linked", 0) >= 0.5
        has_specificity = dims.get("specificity", 0) >= 0.5
        if not has_condition and not has_reasoning and not has_outcome and not has_specificity:
            # "Always validate inputs" with no context or specificity = tautology
            if len(text_stripped) < 80:
                return True, "tautology_no_context"

    # Unified score floor
    unified = dims.get("unified_score", 0.0)
    if unified < 0.20:
        return True, f"unified_score_too_low:{unified:.2f}"

    return False, ""


def transform_for_advisory(
    text: str,
    source: str = "unknown",
    ralph_score: Any = None,
    reliability: Optional[float] = None,
    chip_quality: Optional[float] = None,
) -> AdvisoryQuality:
    """Transform a raw distillation into advisory-optimized format.

    Args:
        text: The distillation text
        source: Where it came from (cognitive, eidos, chips, etc.)
        ralph_score: Optional QualityScore from Meta-Ralph (has .actionability etc. as 0-2 ints)
        reliability: Optional cognitive reliability (0-1)
        chip_quality: Optional chip quality_score (0-1)

    Returns:
        AdvisoryQuality with embedded dimensions, structure, and suppression decision
    """
    if not text or not text.strip():
        return AdvisoryQuality(suppressed=True, suppression_reason="empty_text")

    text = text.strip()

    # Score dimensions
    if ralph_score is not None:
        # Normalize Meta-Ralph's 0-2 integer scores to 0-1
        dims = {
            "actionability": min(1.0, float(getattr(ralph_score, "actionability", 0)) / 2.0),
            "novelty": min(1.0, float(getattr(ralph_score, "novelty", 0)) / 2.0),
            "reasoning": min(1.0, float(getattr(ralph_score, "reasoning", 0)) / 2.0),
            "specificity": min(1.0, float(getattr(ralph_score, "specificity", 0)) / 2.0),
            "outcome_linked": min(1.0, float(getattr(ralph_score, "outcome_linked", 0)) / 2.0),
        }
    else:
        # Compute independently
        dims = {
            "actionability": _score_actionability(text),
            "novelty": _score_novelty(text),
            "reasoning": _score_reasoning(text),
            "specificity": _score_specificity(text),
            "outcome_linked": _score_outcome_linked(text),
        }

    # Compute unified score
    unified = _compute_unified_score(dims)

    # Boost unified score with external signals
    if reliability is not None and reliability > 0:
        # Cognitive reliability is outcome-backed — blend it in
        unified = 0.70 * unified + 0.30 * float(reliability)
    if chip_quality is not None and chip_quality > 0:
        unified = 0.80 * unified + 0.20 * float(chip_quality)

    unified = min(1.0, max(0.0, unified))
    dims["unified_score"] = unified

    # Extract structure
    structure = extract_structure(text)

    # Detect domain
    domain = _detect_domain(text, source)

    # Check suppression
    suppressed, reason = should_suppress(text, dims, structure)

    # Compose advisory-ready text from extracted structure
    advisory_text = ""
    if not suppressed:
        advisory_text = _compose_advisory_text(text, structure, dims)

    return AdvisoryQuality(
        actionability=dims["actionability"],
        novelty=dims["novelty"],
        reasoning=dims["reasoning"],
        specificity=dims["specificity"],
        outcome_linked=dims["outcome_linked"],
        unified_score=unified,
        advisory_text=advisory_text,
        structure=structure,
        domain=domain,
        suppressed=suppressed,
        suppression_reason=reason,
    )
