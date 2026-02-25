"""
Spark Promoter: Auto-promote high-value insights to project files

When a cognitive insight proves reliable enough (high validation count,
high reliability score), it should be promoted to permanent project 
documentation where it will always be loaded.

Promotion targets:
- CLAUDE.md - Project conventions, gotchas, facts
- AGENTS.md - Workflow patterns, tool usage, delegation rules
- TOOLS.md - Tool-specific insights, integration gotchas
- SOUL.md - Behavioral patterns, communication style (Clawdbot)

Promotion criteria:
- Reliability >= 70%
- Times validated >= 3
- Not already promoted
- Category matches target file
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
from dataclasses import dataclass

log = logging.getLogger(__name__)

from .config_authority import resolve_section
from .cognitive_learner import CognitiveInsight, CognitiveCategory, get_cognitive_learner
from .project_profile import load_profile
from .chip_merger import merge_chip_insights


# ============= Configuration =============
DEFAULT_PROMOTION_THRESHOLD = 0.80  # 80% reliability default (raised from 0.7 to reduce noise)
DEFAULT_MIN_VALIDATIONS = 5  # Require at least 5 validations (raised from 3)
DEFAULT_CONFIDENCE_FLOOR = 0.95  # Fast-track: promote high-confidence insights without validation gate (raised from 0.90)
DEFAULT_MIN_AGE_HOURS = 6.0  # Fast-track: insights must be at least 6 hours old (raised from 2.0)
PROJECT_SECTION = "## Project Intelligence"
PROJECT_START = "<!-- SPARK_PROJECT_START -->"
PROJECT_END = "<!-- SPARK_PROJECT_END -->"
PROMOTION_LOG_FILE = Path.home() / ".spark" / "promotion_log.jsonl"

# Adapter budget policy (caps per target file)
# Keep these files small; retrieval handles the full corpus.
ADAPTER_BUDGETS = {
    "CLAUDE.md": {"max_items": 40},
    "AGENTS.md": {"max_items": 30},
    "TOOLS.md": {"max_items": 25},
    "SOUL.md": {"max_items": 25},
    ".cursorrules": {"max_items": 40},
    ".windsurfrules": {"max_items": 40},
}


# ============= Operational vs Cognitive Filter (Phase 1) =============
# These patterns indicate operational telemetry, NOT human-useful cognition.
# Operational insights are valuable for system debugging but should NOT be
# promoted to user-facing docs like CLAUDE.md.

OPERATIONAL_PATTERNS = [
    # Tool sequence patterns (the main noise source)
    r"^sequence\s+['\"]",
    r"sequence.*worked well",
    r"pattern\s+['\"].*->.*['\"]",
    r"for \w+:.*->.*works",

    # Usage count patterns
    r"heavy\s+\w+\s+usage",
    r"\(\d+\s*calls?\)",
    r"indicates task type",

    # Raw tool telemetry
    r"^tool\s+\w+\s+(succeeded|failed)",
    r"tool effectiveness",

    # Market intelligence chip output with engagement metrics
    r"^\[[\w-]+\]\s*\(eng:\d+\)",

    # Intelligence chip triggered-by tags
    r"^\[[\w\s-]+ intelligence\]\s*triggered by",

    # Benchmark/pipeline test artifacts
    r"\[pipeline_test",
    r"\[benchmark",

    # Code constants stored as insights
    r"^[A-Z][A-Z_]+\s*=\s*\S+",

    # Docstring fragments
    r'^"""',
    r"^'''",

    # File reference lists
    r"^-\s*`(lib|src|hooks|scripts)/",

    # Garbled truncated tool preferences (mid-word cutoff)
    r"^when using \w+, (prefer|remember)\s+'[a-z]",

    # Label + conversational fragment (not real principles)
    r"^(principle|constraint|reasoning|failure reason|test):\s*(that |this |those |it |right now|all of|we |follows |abides|keep to|talk about|with the |with a |the primary|utilize)",

    # Tool failure/success statistics
    r"^\w+ failed \d+/\d+ times",
    r"\d+% success rate",
    r"\d+ session\(s\) had \d\+ consecutive",

    # Code comments / JSDoc
    r"^/\*\*",
    r"^/\*",
]

# Compile patterns for efficiency
_OPERATIONAL_REGEXES = [re.compile(p, re.IGNORECASE) for p in OPERATIONAL_PATTERNS]

# Safety block patterns (humanity-first guardrail)
SAFETY_BLOCK_PATTERNS = [
    r"\bdecept(?:ive|ion)\b",
    r"\bmanipulat(?:e|ion)\b",
    r"\bcoerc(?:e|ion)\b",
    r"\bexploit\b",
    r"\bharass(?:ment)?\b",
    r"\bweaponize\b",
    r"\bmislead\b",
]

_SAFETY_REGEXES = [re.compile(p, re.IGNORECASE) for p in SAFETY_BLOCK_PATTERNS]

_RE_PROMOTED_SCORE = re.compile(r"\((\d+)% reliable,\s*(\d+)\s+validations?\)\s*$", re.IGNORECASE)
_AUTO_PROMOTED_LINE = "*Auto-promoted insights from Spark*"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _strip_reliability_suffix(text: str) -> str:
    return _RE_PROMOTED_SCORE.sub("", text or "").strip()


def _extract_score(text: str) -> Tuple[float, int, bool]:
    m = _RE_PROMOTED_SCORE.search(text or "")
    if not m:
        return 0.0, 0, False
    try:
        return float(m.group(1)) / 100.0, int(m.group(2)), True
    except Exception:
        return 0.0, 0, False


def _clean_text_for_write(text: str) -> str:
    try:
        return (text or "").encode("utf-8", "replace").decode("utf-8")
    except Exception:
        return text or ""


def _load_promotion_config(path: Optional[Path] = None) -> Dict[str, Any]:
    tuneables = path or (Path.home() / ".spark" / "tuneables.json")
    cfg = resolve_section("promotion", runtime_path=tuneables).data
    return cfg if isinstance(cfg, dict) else {}


def _merge_budgets(defaults: Dict[str, Dict[str, int]], overrides: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    merged = {k: dict(v) for k, v in defaults.items()}
    if not overrides:
        return merged
    for name, val in overrides.items():
        if isinstance(val, dict):
            max_items = val.get("max_items")
        else:
            max_items = val
        if max_items is None:
            continue
        try:
            merged[name] = {"max_items": max(0, int(max_items))}
        except Exception:
            continue
    return merged


def is_operational_insight(insight_text: str) -> bool:
    """
    Determine if an insight is operational (telemetry) vs cognitive (human-useful).

    Operational insights:
    - Tool sequences: "Sequence 'Bash -> Edit' worked well"
    - Usage counts: "Heavy Bash usage (42 calls)"
    - Raw telemetry: "Tool X succeeded"

    Cognitive insights:
    - Self-awareness: "I struggle with windows paths"
    - Reasoning: "Read before Edit prevents content mismatches"
    - User preferences: "User prefers concise output"
    - Wisdom: "Ship fast, iterate faster"

    Returns True if operational (should NOT be promoted).
    """
    text = (insight_text or "").strip().lower()
    if not text:
        return True  # Empty insights are operational (skip them)

    # Check against operational patterns
    for regex in _OPERATIONAL_REGEXES:
        if regex.search(text):
            return True

    # Additional heuristics

    # Tool chain detection: multiple arrows indicate sequence
    arrow_count = text.count("->") + text.count("→")
    if arrow_count >= 2:
        return True

    # Tool name heavy: mostly tool names suggests telemetry
    tool_names = ["bash", "read", "edit", "write", "grep", "glob", "todowrite", "taskoutput"]
    tool_mentions = sum(1 for t in tool_names if t in text)
    words = len(text.split())
    if words > 0 and tool_mentions / words > 0.4:
        return True

    return False


def is_unsafe_insight(insight_text: str) -> bool:
    """Return True if insight is unsafe or harmful to promote."""
    text = (insight_text or "").strip().lower()
    if not text:
        return True
    for regex in _SAFETY_REGEXES:
        if regex.search(text):
            return True
    return False


def filter_unsafe_insights(insights: list) -> tuple:
    """Split insights into safe and unsafe lists."""
    safe = []
    unsafe = []

    for item in insights:
        if isinstance(item, tuple):
            insight = item[0]
            text = insight.insight if hasattr(insight, "insight") else str(insight)
        else:
            text = item.insight if hasattr(item, "insight") else str(item)

        if is_unsafe_insight(text):
            unsafe.append(item)
        else:
            safe.append(item)

    return safe, unsafe


def filter_operational_insights(insights: list) -> tuple:
    """
    Split insights into cognitive (promotable) and operational (not promotable).

    Returns (cognitive_list, operational_list)
    """
    cognitive = []
    operational = []

    for item in insights:
        # Handle both tuples (insight, key, target) and raw insights
        if isinstance(item, tuple):
            insight = item[0]
            text = insight.insight if hasattr(insight, 'insight') else str(insight)
        else:
            text = item.insight if hasattr(item, 'insight') else str(item)

        if is_operational_insight(text):
            operational.append(item)
        else:
            cognitive.append(item)

    return cognitive, operational


@dataclass
class PromotionTarget:
    """Definition of a promotion target file."""
    filename: str
    section: str
    categories: List[CognitiveCategory]
    description: str


# Promotion target definitions
PROMOTION_TARGETS = [
    PromotionTarget(
        filename="CLAUDE.md",
        section="## Spark Learnings",
        categories=[
            CognitiveCategory.WISDOM,
            CognitiveCategory.REASONING,
            CognitiveCategory.CONTEXT,
        ],
        description="Project conventions, gotchas, and verified patterns"
    ),
    PromotionTarget(
        filename="AGENTS.md",
        section="## Spark Learnings",
        categories=[
            CognitiveCategory.META_LEARNING,
            CognitiveCategory.SELF_AWARENESS,
        ],
        description="Workflow patterns and self-awareness insights"
    ),
    PromotionTarget(
        filename="TOOLS.md",
        section="## Spark Learnings", 
        categories=[
            CognitiveCategory.CONTEXT,
        ],
        description="Tool-specific insights and integration gotchas"
    ),
    PromotionTarget(
        filename="SOUL.md",
        section="## Spark Learnings",
        categories=[
            CognitiveCategory.USER_UNDERSTANDING,
            CognitiveCategory.COMMUNICATION,
        ],
        description="User preferences and communication style"
    ),
]


class Promoter:
    """
    Promotes high-value cognitive insights to project documentation.

    The promotion process:
    1. Find insights meeting promotion criteria (two tracks)
    2. Match insights to appropriate target files
    3. Format insights as concise rules
    4. Append to target files
    5. Mark insights as promoted

    Two-track promotion:
    - Validated track: reliability >= threshold AND times_validated >= min_validations
    - Confidence track: confidence >= 80% AND age >= 1h AND net-positive
      (for insights that are high-quality at birth but lack a validation pathway)
    """

    def __init__(self, project_dir: Optional[Path] = None,
                 reliability_threshold: float = DEFAULT_PROMOTION_THRESHOLD,
                 min_validations: int = DEFAULT_MIN_VALIDATIONS,
                 confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
                 min_age_hours: float = DEFAULT_MIN_AGE_HOURS):
        self.project_dir = project_dir or Path.cwd()
        self.reliability_threshold = reliability_threshold
        self.min_validations = min_validations
        self.confidence_floor = confidence_floor
        self.min_age_hours = min_age_hours
        cfg = _load_promotion_config()
        self.adapter_budgets = _merge_budgets(
            ADAPTER_BUDGETS,
            cfg.get("adapter_budgets") if isinstance(cfg, dict) else {},
        )
        # Load tuneable overrides for confidence track
        if isinstance(cfg, dict):
            self.confidence_floor = float(cfg.get("confidence_floor", self.confidence_floor))
            self.min_age_hours = float(cfg.get("min_age_hours", self.min_age_hours))
    
    @staticmethod
    def _insight_age_hours(insight: CognitiveInsight) -> float:
        """Compute insight age in hours from created_at."""
        try:
            created = datetime.fromisoformat(insight.created_at.replace("Z", "+00:00"))
            return max(0.0, (datetime.now() - created).total_seconds() / 3600.0)
        except Exception:
            return 0.0

    def _passes_confidence_track(self, insight: CognitiveInsight) -> bool:
        """Check if insight qualifies via the confidence fast-track.

        Criteria (all must be true):
        - confidence >= confidence_floor
        - age >= min_age_hours -- settling period
        - times_validated >= min_validations
        - net-positive: times_validated > times_contradicted
        - reliability >= reliability_threshold
        - not noise (double-check with cognitive learner noise filter)
        """
        if insight.confidence < self.confidence_floor:
            return False
        if self._insight_age_hours(insight) < self.min_age_hours:
            return False
        if insight.times_validated < self.min_validations:
            return False
        if insight.times_contradicted >= insight.times_validated:
            return False
        if insight.reliability < self.reliability_threshold:
            return False
        # Final noise gate
        cognitive = get_cognitive_learner()
        if cognitive.is_noise_insight(insight.insight):
            return False
        return True

    def _should_demote(self, insight: CognitiveInsight) -> bool:
        """Return True if a previously promoted insight is no longer trustworthy."""
        if insight.reliability < self.reliability_threshold:
            return True
        if insight.times_validated < self.min_validations:
            return True
        if insight.times_contradicted >= insight.times_validated and insight.times_contradicted > 0:
            return True
        return False

    @staticmethod
    def _log_promotion(insight_key: str, target: str, result: str, reason: str = ""):
        """Append a promotion event to the promotion log for observability."""
        try:
            PROMOTION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.now().isoformat(),
                "key": insight_key,
                "target": target,
                "result": result,  # "promoted", "filtered", "failed"
                "reason": reason,
            }
            with open(PROMOTION_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # Best-effort logging

    def _get_target_for_category(self, category: CognitiveCategory) -> Optional[PromotionTarget]:
        """Find the appropriate promotion target for a category."""
        for target in PROMOTION_TARGETS:
            if category in target.categories:
                return target
        return None
    
    def _format_insight_for_promotion(self, insight: CognitiveInsight) -> str:
        """Format an insight as a concise rule for documentation."""
        # Extract the core insight without verbose details
        rule = _clean_text_for_write(insight.insight)
        
        # Add reliability indicator
        reliability_str = f"({insight.reliability:.0%} reliable, {insight.times_validated} validations)"
        
        # Add context if not generic
        if insight.context and insight.context not in ["General principle", "All interactions"]:
            ctx = _clean_text_for_write(insight.context[:50])
            context_note = f" *When: {ctx}*"
        else:
            context_note = ""
        
        return _clean_text_for_write(f"- {rule}{context_note} {reliability_str}")
    
    def _ensure_section_exists(self, file_path: Path, section: str) -> str:
        """Ensure the target section exists in the file. Returns file content."""
        try:
            if not file_path.exists():
                content = f"""# {file_path.stem}

{section}

*Auto-promoted insights from Spark*

"""
                file_path.write_text(_clean_text_for_write(content), encoding="utf-8")
                return content

            content = file_path.read_text(encoding="utf-8")

            if section not in content:
                content += f"\n\n{section}\n\n*Auto-promoted insights from Spark*\n\n"
                file_path.write_text(_clean_text_for_write(content), encoding="utf-8")

            return content
        except OSError as e:
            log.warning("Failed to ensure section in %s: %s", file_path, e)
            return ""
    
    def _get_budget(self, file_path: Path) -> int:
        budget = self.adapter_budgets.get(file_path.name, {})
        return int(budget.get("max_items", 0) or 0)

    def _curate_lines(self, lines: List[str], max_items: int) -> List[str]:
        curated = []
        seen = set()
        scored = []

        for idx, raw in enumerate(lines):
            s = raw.strip()
            if not s.startswith("- "):
                continue
            core = s[2:].strip()
            core_text = _strip_reliability_suffix(core)
            key = _normalize_text(core_text)
            if not key or key in seen:
                continue
            seen.add(key)

            reliability, validations, has_score = _extract_score(core)
            if has_score:
                if reliability < self.reliability_threshold or validations < self.min_validations:
                    continue

            scored.append({
                "idx": idx,
                "line": s,
                "reliability": reliability,
                "validations": validations,
            })

        if max_items > 0:
            scored.sort(
                key=lambda x: (x["reliability"], x["validations"], -x["idx"]),
                reverse=True,
            )
            scored = scored[:max_items]
            scored.sort(key=lambda x: x["idx"])

        curated = [item["line"] for item in scored]
        return curated

    def _append_to_section(self, file_path: Path, section: str, line: str):
        """Append a line to a specific section in a file with budget enforcement."""
        content = self._ensure_section_exists(file_path, section)

        section_idx = content.find(section)
        if section_idx == -1:
            return

        block_start = section_idx + len(section)
        next_section = re.search(r'\n## ', content[block_start:])
        block_end = block_start + (next_section.start() if next_section else len(content) - block_start)
        block = content[block_start:block_end]

        block_lines = block.splitlines()
        preamble = []
        bullets = []
        in_bullets = False
        for raw in block_lines:
            if raw.strip().startswith("- "):
                in_bullets = True
                bullets.append(raw.strip())
            else:
                if not in_bullets:
                    # Keep only the standard auto-promoted marker / blanks.
                    if not raw.strip() or raw.strip() == _AUTO_PROMOTED_LINE:
                        preamble.append(raw)

        # Dedupe against existing bullets
        existing_keys = {_normalize_text(_strip_reliability_suffix(b[2:].strip())) for b in bullets}
        new_key = _normalize_text(_strip_reliability_suffix(line[2:].strip())) if line.strip().startswith("- ") else ""
        if new_key and new_key not in existing_keys:
            bullets.append(line.strip())

        max_items = self._get_budget(file_path)
        curated = self._curate_lines(bullets, max_items)

        new_block_lines = []
        if preamble:
            new_block_lines.extend(preamble)
        if curated:
            if new_block_lines and new_block_lines[-1].strip():
                new_block_lines.append("")
            new_block_lines.extend(curated)
        new_block = "\n".join(new_block_lines)
        new_content = content[:block_start] + new_block + content[block_end:]
        file_path.write_text(_clean_text_for_write(new_content), encoding="utf-8")

    def _remove_from_section(self, file_path: Path, section: str, insight_text: str) -> bool:
        """Remove lines matching a promoted insight from a target section."""
        if not file_path.exists():
            return False
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return False

        section_idx = content.find(section)
        if section_idx == -1:
            return False

        block_start = section_idx + len(section)
        next_section = re.search(r'\n## ', content[block_start:])
        block_end = block_start + (next_section.start() if next_section else len(content) - block_start)
        block = content[block_start:block_end]
        block_lines = block.splitlines()

        target_key = _normalize_text(insight_text)
        if not target_key:
            return False

        new_block_lines: List[str] = []
        removed = False
        for raw in block_lines:
            s = raw.strip()
            if s.startswith("- "):
                core = s[2:].strip()
                core_text = _strip_reliability_suffix(core)
                core_key = _normalize_text(core_text)
                if core_key and (target_key in core_key or core_key in target_key):
                    removed = True
                    continue
            new_block_lines.append(raw)

        if not removed:
            return False

        new_block = "\n".join(new_block_lines)
        new_content = content[:block_start] + new_block + content[block_end:]
        file_path.write_text(_clean_text_for_write(new_content), encoding="utf-8")
        return True

    def demote_stale_promotions(self) -> Dict[str, int]:
        """Unpromote stale insights whose reliability has degraded."""
        cognitive = get_cognitive_learner()
        stats = {"checked": 0, "demoted": 0, "doc_removed": 0}

        for key, insight in list(cognitive.insights.items()):
            if not insight.promoted:
                continue
            stats["checked"] += 1
            if not self._should_demote(insight):
                continue

            target_file = insight.promoted_to
            removed = False
            if target_file:
                file_path = self.project_dir / target_file
                removed = self._remove_from_section(file_path, "## Spark Learnings", insight.insight)
            else:
                target = self._get_target_for_category(insight.category)
                if target:
                    file_path = self.project_dir / target.filename
                    removed = self._remove_from_section(file_path, target.section, insight.insight)

            cognitive.mark_unpromoted(key)
            stats["demoted"] += 1
            if removed:
                stats["doc_removed"] += 1
            self._log_promotion(key, target_file or "unknown", "demoted", "reliability_degraded")

        return stats

    def _upsert_block(self, content: str, block: str, section: str) -> str:
        """Insert or replace a block wrapped by start/end markers in a section."""
        if PROJECT_START in content and PROJECT_END in content:
            start_idx = content.index(PROJECT_START)
            end_idx = content.index(PROJECT_END) + len(PROJECT_END)
            return content[:start_idx].rstrip() + "\n" + block + "\n" + content[end_idx:].lstrip()

        if section in content:
            insert_idx = content.index(section) + len(section)
            insertion = "\n\n" + block + "\n"
            return content[:insert_idx] + insertion + content[insert_idx:]

        return content.rstrip() + f"\n\n{section}\n\n{block}\n"

    def _render_project_block(self, profile: Dict[str, Any]) -> str:
        """Render a concise project intelligence block for PROJECT.md."""
        def _render_items(label: str, items: List[Dict[str, Any]], max_items: int = 5) -> List[str]:
            if not items:
                return []
            lines = [f"{label}:"]
            for entry in list(reversed(items))[:max_items]:
                text = (entry.get("text") or "").strip()
                meta = entry.get("meta") or {}
                suffix = []
                status = meta.get("status")
                if status:
                    suffix.append(f"status={status}")
                why = meta.get("why")
                if why:
                    suffix.append(f"why={why}")
                impact = meta.get("impact")
                if impact:
                    suffix.append(f"impact={impact}")
                evidence = meta.get("evidence")
                if evidence:
                    suffix.append(f"evidence={evidence}")
                trailer = f" ({'; '.join(suffix)})" if suffix else ""
                if text:
                    lines.append(f"- {text}{trailer}")
            return lines

        updated = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            PROJECT_START,
            f"Updated: {updated}",
            f"Domain: {profile.get('domain') or 'general'}",
            f"Phase: {profile.get('phase') or 'discovery'}",
        ]

        done = (profile.get("done") or "").strip()
        if done:
            lines.append(f"Done Definition: {done}")

        lines.extend(_render_items("Goals", profile.get("goals") or []))
        lines.extend(_render_items("Milestones", profile.get("milestones") or []))
        lines.extend(_render_items("Decisions", profile.get("decisions") or []))
        lines.extend(_render_items("Insights", profile.get("insights") or []))
        lines.extend(_render_items("Feedback", profile.get("feedback") or []))
        lines.extend(_render_items("Risks", profile.get("risks") or []))
        lines.extend(_render_items("References", profile.get("references") or []))
        transfers = profile.get("transfers") or []
        lines.extend(_render_items("Transfers", transfers))

        if len(transfers) >= 3:
            def _theme_snip(text: str) -> str:
                words = (text or "").strip().split()
                return " ".join(words[:8]) if words else ""

            recent = list(reversed(transfers))[:3]
            lines.append("Transfer Summary:")
            for entry in recent:
                snippet = _theme_snip(entry.get("text") or "")
                if snippet:
                    lines.append(f"- Theme: {snippet}")

        lines.append(PROJECT_END)
        return "\n".join(lines)

    def promote_project_profile(self, profile: Optional[Dict[str, Any]] = None) -> bool:
        """Promote project profile data into PROJECT.md."""
        try:
            profile_data = profile or load_profile(self.project_dir)
            block = self._render_project_block(profile_data)
            file_path = self.project_dir / "PROJECT.md"

            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                new_content = self._upsert_block(content, block, PROJECT_SECTION)
            else:
                new_content = f"# Project\n\n{PROJECT_SECTION}\n\n{block}\n"

            file_path.write_text(new_content, encoding="utf-8")
            print("[SPARK] Updated PROJECT.md from project profile")
            return True
        except Exception as e:
            print(f"[SPARK] PROJECT.md update failed: {e}")
            return False

    def get_promotable_insights(self, include_operational: bool = False) -> List[Tuple[CognitiveInsight, str, PromotionTarget]]:
        """Get insights ready for promotion with their target files.

        Uses two-track promotion:
        1. Validated track: reliability >= threshold AND times_validated >= min_validations
        2. Confidence track: confidence >= floor AND age >= min_age AND net-positive

        Args:
            include_operational: If False (default), filters out operational
                                 telemetry (tool sequences, usage counts).
                                 Set True only for debugging.
        """
        cognitive = get_cognitive_learner()
        candidates = []
        fast_tracked = 0

        for key, insight in cognitive.insights.items():
            # Skip already promoted
            if insight.promoted:
                continue

            # Find target first (skip if no target for this category)
            target = self._get_target_for_category(insight.category)
            if not target:
                continue

            # Track 1: Validated track (original logic)
            if (insight.reliability >= self.reliability_threshold
                    and insight.times_validated >= self.min_validations):
                candidates.append((insight, key, target))
                continue

            # Track 2: Confidence fast-track (for insights without validation pathway)
            if self._passes_confidence_track(insight):
                candidates.append((insight, key, target))
                fast_tracked += 1

        if fast_tracked:
            print(f"[SPARK] {fast_tracked} insights qualify via confidence fast-track")

        # Phase 1: Filter out operational telemetry
        if not include_operational:
            cognitive_only, operational = filter_operational_insights(candidates)
            if operational:
                print(f"[SPARK] Filtered {len(operational)} operational insights (telemetry)")
            safe_only, unsafe = filter_unsafe_insights(cognitive_only)
            if unsafe:
                print(f"[SPARK] Filtered {len(unsafe)} unsafe insights (safety guardrail)")
            return safe_only

        return candidates
    
    def promote_insight(self, insight: CognitiveInsight, insight_key: str, 
                       target: PromotionTarget) -> bool:
        """Promote a single insight to its target file."""
        file_path = self.project_dir / target.filename
        
        try:
            # Format the insight
            formatted = self._format_insight_for_promotion(insight)
            
            # Append to target file
            self._append_to_section(file_path, target.section, formatted)
            
            # Mark as promoted
            cognitive = get_cognitive_learner()
            cognitive.mark_promoted(insight_key, target.filename)
            
            print(f"[SPARK] Promoted to {target.filename}: {insight.insight[:50]}...")
            return True
            
        except Exception as e:
            print(f"[SPARK] Promotion failed: {e}")
            return False
    
    def promote_all(self, dry_run: bool = False, include_project: bool = True, include_chip_merge: bool = True) -> Dict[str, int]:
        """Promote all eligible insights (filters operational telemetry).

        Uses get_promotable_insights() which applies two-track promotion:
        validated track + confidence fast-track.
        """
        chip_merge_stats = {}
        demotion_stats = {"checked": 0, "demoted": 0, "doc_removed": 0}
        if include_chip_merge and not dry_run:
            try:
                chip_merge_stats = merge_chip_insights(
                    min_confidence=max(self.reliability_threshold, 0.7),
                    min_quality_score=0.7,
                    limit=50,
                )
                if chip_merge_stats.get("merged", 0) > 0:
                    print(
                        f"[SPARK] Merged {chip_merge_stats.get('merged', 0)} high-value chip insights "
                        f"into cognitive pipeline before promotion"
                    )
            except Exception as e:
                print(f"[SPARK] Chip merge pre-promotion failed: {e}")

        if not dry_run:
            try:
                demotion_stats = self.demote_stale_promotions()
                if demotion_stats.get("demoted", 0) > 0:
                    print(
                        f"[SPARK] Demoted {demotion_stats.get('demoted', 0)} stale promotions "
                        f"({demotion_stats.get('doc_removed', 0)} removed from docs)"
                    )
            except Exception as e:
                print(f"[SPARK] Demotion pass failed: {e}")

        promotable = self.get_promotable_insights(include_operational=False)

        stats = {
            "promoted": 0,
            "skipped": 0,
            "failed": 0,
            "fast_tracked": 0,
            "project_written": 0,
            "project_failed": 0,
            "chip_merged": int(chip_merge_stats.get("merged", 0) or 0),
            "chip_processed": int(chip_merge_stats.get("processed", 0) or 0),
            "demoted": int(demotion_stats.get("demoted", 0) or 0),
            "demotion_doc_removed": int(demotion_stats.get("doc_removed", 0) or 0),
        }

        if include_project:
            if dry_run:
                print("  [DRY RUN] Would update PROJECT.md from project profile")
                stats["skipped"] += 1
            else:
                if self.promote_project_profile():
                    stats["project_written"] = 1
                else:
                    stats["project_failed"] = 1

        if not promotable:
            print("[SPARK] No insights ready for promotion")
            return stats

        print(f"[SPARK] Found {len(promotable)} insights ready for promotion")

        for insight, key, target in promotable:
            if dry_run:
                print(f"  [DRY RUN] Would promote to {target.filename}: {insight.insight[:50]}...")
                self._log_promotion(key, target.filename, "skipped", "dry_run")
                stats["skipped"] += 1
                continue

            if self.promote_insight(insight, key, target):
                stats["promoted"] += 1
                self._log_promotion(key, target.filename, "promoted")
            else:
                stats["failed"] += 1
                self._log_promotion(key, target.filename, "failed")

        return stats
    
    def get_promotion_status(self) -> Dict:
        """Get status of promotions (includes two-track + filter stats)."""
        cognitive = get_cognitive_learner()

        # Use the unified two-track getter
        promotable = self.get_promotable_insights(include_operational=False)

        promoted = [i for i in cognitive.insights.values() if i.promoted]
        by_target = {}
        for insight in promoted:
            target = insight.promoted_to or "unknown"
            by_target[target] = by_target.get(target, 0) + 1

        return {
            "total_insights": len(cognitive.insights),
            "promoted_count": len(promoted),
            "ready_for_promotion": len(promotable),
            "by_target": by_target,
            "threshold": self.reliability_threshold,
            "min_validations": self.min_validations,
            "confidence_floor": self.confidence_floor,
        }


# ============= Singleton =============
_promoter: Optional[Promoter] = None

def get_promoter(project_dir: Optional[Path] = None) -> Promoter:
    """Get the promoter instance."""
    global _promoter
    if _promoter is None or (project_dir and _promoter.project_dir != project_dir):
        _promoter = Promoter(project_dir)
    return _promoter


# ============= Convenience Functions =============
def check_and_promote(
    project_dir: Optional[Path] = None,
    dry_run: bool = False,
    include_project: bool = True,
) -> Dict[str, int]:
    """Check for promotable insights and promote them."""
    return get_promoter(project_dir).promote_all(
        dry_run,
        include_project=include_project,
        include_chip_merge=True,
    )


def get_promotion_status(project_dir: Optional[Path] = None) -> Dict:
    """Get promotion status."""
    return get_promoter(project_dir).get_promotion_status()


# ---------------------------------------------------------------------------
# Hot-reload registration
# ---------------------------------------------------------------------------

def _reload_promotion_from(_cfg: Dict) -> None:
    """Hot-reload callback — invalidate cached Promoter so next call picks up new config."""
    global _PROMOTER
    _PROMOTER = None


try:
    from .tuneables_reload import register_reload as _prom_register
    _prom_register("promotion", _reload_promotion_from, label="promoter.reload")
except Exception:
    pass
