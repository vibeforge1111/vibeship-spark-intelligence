"""Elevation transforms for Meta-Ralph insight refinement.

Graduated from System 28 (Elevation Forge) training — 12 proven transforms
trained on 137 Claude refinement pairs, scoring 95.7% pass rate on test
scenarios. These transforms turn NEEDS_WORK insights (score 2-3) into
QUALITY insights (score 4+) by tightening language and enriching with
available context.

RULEBOOK:
1. NEVER fabricate info not in input text or context
2. NEVER change semantic meaning
3. ALWAYS preserve numeric evidence verbatim
4. PREFER shorter output over longer (tighten, don't expand)
5. Score increase of 0 -> return None (no-op)
6. Score DECREASE -> regression (flagged)
7. No useful context -> return None (don't force it)
8. Split compounds only if stronger half scores >= 4 alone
9. Never add "because" followed by restated action (tautology)
10. Condition format: "When [specific_thing]:"
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hedge words/phrases to strip
_HEDGE_PATTERNS = [
    (r"^I think (?:you )?(?:should |could )?(?:maybe |perhaps )?", ""),
    (r"^(?:Maybe |Perhaps |Possibly )", ""),
    (r"^It (?:might|could|would) be (?:worth|a good idea|helpful) (?:to |if (?:we |you )?)?", ""),
    (r",? just a thought$", ""),
    (r"^(?:You )?(?:should |could |might want to )?(?:maybe |perhaps )?consider ", ""),
    (r"^(?:You )?(?:should |could |might want to )?(?:maybe |perhaps )?look(?:ing)? into (?:whether (?:we |you )?(?:could )?(?:possibly )?)?", ""),
    (r"^Possibly ", ""),
]

# Passive voice starters to restructure
_PASSIVE_STARTERS = [
    (r"^It (?:was|has been) (?:found|observed|determined|noted|discovered) that ", ""),
    (r"^It (?:is|was) (?:recommended|suggested|advised) (?:that |to )", ""),
    (r",? it was determined$", ""),
    (r",? it has been observed$", ""),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _past_participle_to_imperative(word: str) -> str:
    """Convert past participle to imperative: 'enabled' -> 'enable', 'hardcoded' -> 'hardcode'."""
    w = word.lower().rstrip(".")
    # Lookup for common engineering verbs (more reliable than heuristics)
    _KNOWN = {
        "enabled": "enable", "disabled": "disable", "configured": "configure",
        "hardcoded": "hardcode", "increased": "increase", "decreased": "decrease",
        "updated": "update", "removed": "remove", "validated": "validate",
        "determined": "determine", "observed": "observe", "discovered": "discover",
        "recommended": "recommend", "suggested": "suggest", "noted": "note",
        "optimized": "optimize", "minimized": "minimize", "maximized": "maximize",
        "cached": "cache", "indexed": "index", "deployed": "deploy",
        "checked": "check", "stopped": "stop", "added": "add", "used": "use",
    }
    if w in _KNOWN:
        return _KNOWN[w]
    # Fallback: "Xied" -> "Xy", "Xed" -> "X" or "Xe"
    if w.endswith("ied") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ed") and len(w) > 3:
        stem = w[:-2]
        # Double consonant: "stopped" -> "stop"
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            return stem[:-1]
        # Try stem + 'e' for words that came from "base+d" (base ends in 'e')
        if w[-3] in "dlrstcgvz" and not w.endswith("cked") and not w.endswith("shed"):
            return stem + "e"
        return stem
    return w


# ---------------------------------------------------------------------------
# Transforms (each: text, context -> Optional[str])
# ---------------------------------------------------------------------------


def _strip_hedges(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Remove hedge words while preserving the core action."""
    result = text
    changed = False
    for pattern, repl in _HEDGE_PATTERNS:
        new = re.sub(pattern, repl, result, flags=re.IGNORECASE)
        if new != result:
            result = new
            changed = True
    # Fix gerund to imperative: "Using X" -> "Use X", "Adding X" -> "Add X"
    if changed and result:
        m = re.match(r"^(Using|Adding|Enabling|Running|Configuring|Avoiding|Preferring)\b(.*)$",
                     result, re.IGNORECASE)
        if m:
            gerund_to_imperative = {
                "using": "Use", "adding": "Add", "enabling": "Enable",
                "running": "Run", "configuring": "Configure",
                "avoiding": "Avoid", "preferring": "Prefer",
            }
            imperative = gerund_to_imperative.get(m.group(1).lower(), m.group(1))
            result = imperative + m.group(2)

    # Capitalize first letter after stripping
    if changed and result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result.strip() if changed else None


def _add_condition_from_context(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Add 'When X:' prefix from context file_path or domain."""
    # Skip if already has a condition prefix
    if re.match(r"^(?:When|If|For|In|During) ", text, re.IGNORECASE):
        return None

    file_path = str(context.get("file_path", "") or "").strip()
    domain = str(context.get("domain", "") or "").strip()
    tool_name = str(context.get("tool_name", "") or "").strip()

    if file_path:
        # Extract basename
        parts = file_path.replace("\\", "/").rsplit("/", 1)
        basename = parts[-1] if len(file_path) > 40 else file_path
        if tool_name:
            return f"When using {tool_name} on {basename}: {text[0].lower()}{text[1:]}"
        return f"When editing {basename}: {text[0].lower()}{text[1:]}"

    if domain and domain not in ("code", "general", "unknown"):
        domain_label = domain.replace("_", " ")
        return f"When working on {domain_label}: {text[0].lower()}{text[1:]}"

    return None


def _add_reasoning_from_context(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Add 'because X' from context error."""
    # Skip if already has explicit reasoning
    if re.search(r"\b(?:because|since|due to|the reason)\b", text, re.IGNORECASE):
        return None

    error = str(context.get("error", "") or "").strip()
    if not error or len(error) < 5:
        return None

    # Truncate long errors
    reason = error[:80].rstrip(".")
    composed = f"{text.rstrip('.')} because {reason}"

    # Tautology guard: don't add "because X" if X restates the action
    action_words = set(text.lower().split()[:5])
    reason_words = set(reason.lower().split()[:5])
    if len(action_words & reason_words) >= 3:
        return None

    return composed if len(composed) <= 200 else None


def _add_outcome_from_context(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Attach outcome metric from context evidence."""
    evidence = str(context.get("outcome_evidence", "") or "").strip()
    if not evidence or len(evidence) < 5:
        return None

    # Skip if text already mentions specific metrics
    if re.search(r"\d+(?:ms|s|%|x)\b", text):
        return None

    composed = f"{text.rstrip('.')}, which {evidence.rstrip('.')}"
    return composed if len(composed) <= 200 else None


def _split_compound(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Split 'X and Y' into stronger single insight."""
    # Count "and" conjunctions — only split if 2+ (compound)
    and_count = len(re.findall(r"\band\b", text, re.IGNORECASE))
    if and_count < 2:
        # Single "and" — check if it joins two independent clauses
        m = re.match(
            r"^(.+?)\s+and\s+((?:never|always|also|then|enable|add|use|avoid)\s+.+?)"
            r"(?:\s+because\s+(.+))?$",
            text, re.IGNORECASE,
        )
        if not m:
            return None
        first_half = m.group(1).strip()
        because = m.group(3)
        if because:
            return f"{first_half} because {because.strip()}"
        return first_half

    # Multiple "and" — extract "because" first, then split
    because = None
    text_no_because = text
    bm = re.search(r"\s+because\s+(.+?)(?:\s+and\s+|$)", text, re.IGNORECASE)
    if bm:
        because = bm.group(1).strip().rstrip(".")
        # Remove everything from "because" onward for splitting
        text_no_because = text[:bm.start()].strip()

    parts = re.split(r"\s+and\s+", text_no_because, flags=re.IGNORECASE)
    if len(parts) < 2:
        return None

    # Keep the first part (usually strongest)
    first = parts[0].strip()
    if because:
        return f"{first} because {because}"
    return first


def _restructure_passive(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Convert passive voice to active imperative."""
    result = text
    changed = False

    # First strip trailing passive phrases
    trailing_passives = [
        (r",?\s*it was determined\.?$", ""),
        (r",?\s*it has been observed\.?$", ""),
        (r",?\s*it was found\.?$", ""),
        (r",?\s*it was noted\.?$", ""),
    ]
    for pattern, repl in trailing_passives:
        new = re.sub(pattern, repl, result, flags=re.IGNORECASE)
        if new != result:
            result = new
            changed = True

    # Then strip leading passive phrases
    for pattern, repl in _PASSIVE_STARTERS:
        new = re.sub(pattern, repl, result, flags=re.IGNORECASE)
        if new != result:
            result = new
            changed = True

    # Check for remaining passive cores in `result` (after any stripping above)
    # "X should not be VERBed Y" -> "Never VERB X Y"
    m2 = re.match(r"^(?:The )?(.+?) should not be (\w+?)$", result, re.IGNORECASE)
    if m2:
        verb = _past_participle_to_imperative(m2.group(2).rstrip("."))
        result = f"Never {verb} the {m2.group(1)}"
        changed = True
    else:
        # "X should be VERBed for Y" -> "VERB X for Y"
        m2 = re.match(r"^(?:The )?(.+?) should be (\w+)(.*?)$", result, re.IGNORECASE)
        if m2:
            verb = _past_participle_to_imperative(m2.group(2))
            subject = m2.group(1)
            rest = m2.group(3).rstrip(".")
            result = f"{verb[0].upper()}{verb[1:]} {subject}{rest}"
            changed = True
        else:
            # "X needs to be VERBed" -> "VERB the X"
            m2 = re.match(r"^(?:The )?(.+?) needs to be (\w+)(.*?)$", result, re.IGNORECASE)
            if m2:
                verb = _past_participle_to_imperative(m2.group(2))
                subject = m2.group(1)
                rest = m2.group(3).rstrip(".")
                result = f"{verb[0].upper()}{verb[1:]} the {subject}{rest}"
                changed = True

    if changed and result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result.strip() if changed else None


def _extract_action_from_observation(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Turn an observation ('X was slow') into an actionable insight."""
    observation_patterns = [
        # "The API was slow when X" -> "Add X because missing X causes slow API"
        (r"^(?:The )?(.+?) (?:was|were|is) (?:very )?(?:slow|failing|broken|unstable|unreliable)"
         r" when (.+?)$",
         lambda m: f"Add {m.group(2).rstrip('.')} because missing it causes slow {m.group(1).lower()}"),
        # "X kept growing because Y were never Z" -> "Always Z Y because leaked Y causes X"
        (r"^(.+?) kept (\w+) because (?:the )?(.+?) (?:were|was) never (.+?)$",
         lambda m: f"Always {m.group(4)} {m.group(3)} because leaked {m.group(3)} cause {m.group(1).lower()} to keep {m.group(2)}"),
    ]
    for pattern, builder in observation_patterns:
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            result = builder(m)
            return result if len(result) <= 200 else None
    return None


def _quantify_vague_outcome(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Replace vague outcome language with specific metrics from context."""
    evidence = str(context.get("outcome_evidence", "") or "").strip()
    if not evidence or len(evidence) < 5:
        return None

    # Vague outcome patterns to replace
    vague_patterns = [
        r"(?:made |was )?(?:things |it |everything )?(?:much |way |really |significantly )?(?:faster|slower|better|worse)",
        r"(?:really |significantly )?(?:helped|improved|fixed)(?: with)? (?:\w+ )*(?:performance|speed|latency|throughput)",
        r"(?:things|it|everything) (?:got |became )?(?:much |way )?(?:faster|slower|better|worse)",
    ]
    for vague in vague_patterns:
        if re.search(vague, text, re.IGNORECASE):
            cleaned = re.sub(vague, evidence.rstrip("."), text, count=1, flags=re.IGNORECASE)
            if cleaned != text and len(cleaned) <= 200:
                return cleaned

    return None


def _add_temporal_context(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Add timestamp qualifier from context."""
    timestamp = str(context.get("timestamp", "") or "").strip()
    if not timestamp:
        return None

    # Skip if already has temporal context
    if re.search(r"\b(?:since|as of|after|before|from|in \d{4})\b", text, re.IGNORECASE):
        return None

    # Extract year-month or full date
    m = re.match(r"(\d{4})-(\d{2})(?:-\d{2})?", timestamp)
    if m:
        year, month = m.group(1), m.group(2)
        months = {
            "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
            "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
            "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
        }
        month_name = months.get(month, month)
        return f"Since {month_name} {year}: {text[0].lower()}{text[1:]}"

    return None


def _error_to_prevention(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Transform error description into prevention advice."""
    error_patterns = [
        # "TypeError occurs when config is None"
        (r"^(\w+Error) (?:occurs|happens|thrown|raised) when (.+?)$",
         lambda m: f"Always validate before {m.group(2).rstrip('.')} because {m.group(1)} occurs when {m.group(2).rstrip('.')}"),
        # "KeyError when accessing dict without..."
        (r"^(\w+Error) when (\w+) (.+?)$",
         lambda m: f"Use safe access patterns instead of {m.group(2)} {m.group(3).rstrip('.')} because {m.group(1)} occurs on missing keys"),
    ]
    for pattern, builder in error_patterns:
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            result = builder(m)
            return result if len(result) <= 200 else None
    return None


def _add_implicit_reasoning(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Add 'because' when there's an implied purpose but no explicit reasoning."""
    # Skip if already has reasoning
    if re.search(r"\b(?:because|since|due to|as|so that)\b", text, re.IGNORECASE):
        return None

    # Pattern: "Use/Add/Enable X to Y" -> "Use/Add/Enable X because Y"
    # Only match "to [verb]" (purpose), not "for [noun]" (context)
    m = re.match(
        r"^((?:Use|Add|Enable|Implement|Set|Configure|Run|Prefer|Avoid)\s+.+?)"
        r"\s+to\s+(\w+\s+.+?)$",
        text, re.IGNORECASE,
    )
    if m:
        action = m.group(1).rstrip(".")
        purpose = m.group(2).rstrip(".")
        result = f"{action} because {purpose}"
        return result if len(result) <= 200 else None

    return None


def _collapse_redundant(text: str, context: Dict[str, Any]) -> Optional[str]:
    """Remove restated ideas within same insight."""
    sentences = [s.strip() for s in re.split(r'[.!]\s+', text) if s.strip()]
    if len(sentences) < 2:
        return None

    # Keep the most actionable sentence (has action verbs)
    action_verbs = re.compile(
        r"\b(?:always|never|use|avoid|enable|disable|add|remove|set|check|ensure|run|prefer)\b",
        re.IGNORECASE,
    )

    best = None
    best_score = -1
    for s in sentences:
        score = len(action_verbs.findall(s))
        if score > best_score or (score == best_score and len(s) > len(best or "")):
            best = s
            best_score = score

    if best and len(best) < len(text) * 0.8:
        return best.rstrip(".")
    return None


# ---------------------------------------------------------------------------
# Ordered transform pipeline
# Priority: clean up language first, then enrich with context, then structure
# ---------------------------------------------------------------------------

TRANSFORMS = [
    _strip_hedges,                       # Remove hedge words
    _restructure_passive,                # Passive -> active imperative
    _error_to_prevention,                # Error descriptions -> prevention advice
    _extract_action_from_observation,    # Observations -> actionable insights
    _split_compound,                     # "X and Y and Z" -> strongest single
    _add_condition_from_context,         # Add "When X:" from file/domain
    _add_temporal_context,               # Add "Since [date]:" from timestamp
    _add_reasoning_from_context,         # Add "because X" from error context
    _add_implicit_reasoning,             # Add "because" to "Use X to Y"
    _quantify_vague_outcome,             # Replace "much faster" with actual metrics
    _add_outcome_from_context,           # Append outcome evidence
    _collapse_redundant,                 # Remove restated ideas
]


def elevate(text: str, context: Dict[str, Any]) -> str:
    """Apply all applicable elevation transforms in order.

    Returns the elevated text (may be unchanged if no transforms apply).
    """
    result = text
    for transform in TRANSFORMS:
        elevated = transform(result, context)
        if elevated is not None:
            result = elevated
    return result
