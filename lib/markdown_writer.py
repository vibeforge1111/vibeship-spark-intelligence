"""
Spark Markdown Writer: Human-readable learning output

Writes cognitive insights to .learnings/ directory in markdown format
compatible with the ClawdHub self-improving-agent specification.

Output files:
- .learnings/LEARNINGS.md - Cognitive insights and patterns
- .learnings/ERRORS.md - Failure patterns and recovery strategies
- .learnings/FEATURE_REQUESTS.md - Capability gaps identified

This provides:
1. Human-readable audit trail
2. Git-trackable learning history
3. Compatibility with other tools expecting .learnings/
"""

from __future__ import annotations

import os
import random
import string
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from .cognitive_learner import CognitiveInsight, CognitiveCategory, get_cognitive_learner


# ============= Configuration =============
DEFAULT_LEARNINGS_DIR = ".learnings"


def _generate_id(prefix: str) -> str:
    """Generate a unique ID: PREFIX-YYYYMMDD-XXX"""
    date_str = datetime.now().strftime("%Y%m%d")
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
    return f"{prefix}-{date_str}-{suffix}"


def _category_to_area(category: CognitiveCategory) -> str:
    """Map cognitive category to learning area tag."""
    mapping = {
        CognitiveCategory.SELF_AWARENESS: "config",
        CognitiveCategory.USER_UNDERSTANDING: "docs",
        CognitiveCategory.WISDOM: "docs",
        CognitiveCategory.REASONING: "backend",
        CognitiveCategory.CONTEXT: "config",
        CognitiveCategory.META_LEARNING: "docs",
        CognitiveCategory.COMMUNICATION: "docs",
        CognitiveCategory.CREATIVITY: "frontend",
    }
    return mapping.get(category, "docs")


def _category_to_learning_category(category: CognitiveCategory) -> str:
    """Map cognitive category to learning category tag."""
    mapping = {
        CognitiveCategory.SELF_AWARENESS: "self_awareness",
        CognitiveCategory.USER_UNDERSTANDING: "user_preference",
        CognitiveCategory.WISDOM: "best_practice",
        CognitiveCategory.REASONING: "reasoning_pattern",
        CognitiveCategory.CONTEXT: "context_rule",
        CognitiveCategory.META_LEARNING: "knowledge_gap",
        CognitiveCategory.COMMUNICATION: "correction",
        CognitiveCategory.CREATIVITY: "best_practice",
    }
    return mapping.get(category, "observation")


def _reliability_to_priority(reliability: float) -> str:
    """Map reliability score to priority level."""
    if reliability >= 0.9:
        return "critical"
    elif reliability >= 0.7:
        return "high"
    elif reliability >= 0.5:
        return "medium"
    return "low"


class MarkdownWriter:
    """
    Writes cognitive insights to markdown files in .learnings/ directory.

    Compatible with ClawdHub self-improving-agent format.
    """

    def __init__(self, project_dir: Optional[Path] = None, learnings_dir: str = DEFAULT_LEARNINGS_DIR) -> None:
        self.project_dir = project_dir or Path.cwd()
        self.learnings_dir = self.project_dir / learnings_dir
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Ensure .learnings directory exists with template files."""
        self.learnings_dir.mkdir(parents=True, exist_ok=True)

        # Create template files if they don't exist
        learnings_file = self.learnings_dir / "LEARNINGS.md"
        if not learnings_file.exists():
            learnings_file.write_text(self._learnings_header(), encoding="utf-8")

        errors_file = self.learnings_dir / "ERRORS.md"
        if not errors_file.exists():
            errors_file.write_text(self._errors_header(), encoding="utf-8")

    def _learnings_header(self) -> str:
        """Generate header for LEARNINGS.md"""
        return """# Learnings

Cognitive insights and patterns captured by Spark.

Format: `[LRN-YYYYMMDD-XXX] category`

---

"""

    def _errors_header(self) -> str:
        """Generate header for ERRORS.md"""
        return """# Errors

Failure patterns and recovery strategies captured by Spark.

Format: `[ERR-YYYYMMDD-XXX] error_type`

---

"""

    def insight_to_markdown(self, insight: CognitiveInsight) -> str:
        """Convert a CognitiveInsight to markdown entry."""
        entry_id = _generate_id("LRN")
        timestamp = datetime.now().isoformat()
        category = _category_to_learning_category(insight.category)
        priority = _reliability_to_priority(insight.reliability)
        area = _category_to_area(insight.category)

        # Build evidence list
        evidence_lines = ""
        if insight.evidence:
            evidence_lines = "\n".join(f"- {e}" for e in insight.evidence[:5])

        # Build counter-examples
        counter_lines = ""
        if insight.counter_examples:
            counter_lines = "\n**Exceptions:**\n" + "\n".join(f"- {c}" for c in insight.counter_examples[:3])

        entry = f"""## [{entry_id}] {category}

**Logged**: {timestamp}
**Priority**: {priority}
**Status**: pending
**Area**: {area}
**Cognitive Category**: {insight.category.value}
**Reliability**: {insight.reliability:.0%}

### Summary
{insight.insight}

### Context
{insight.context}

### Evidence
{evidence_lines if evidence_lines else "- (Initial observation)"}
{counter_lines}

### Suggested Action
Review and validate this insight. If confirmed, consider promoting to CLAUDE.md or AGENTS.md.

### Metadata
- Source: spark_cognitive_learner
- Times Validated: {insight.times_validated}
- Times Contradicted: {insight.times_contradicted}
- Created: {insight.created_at}

---

"""
        return entry

    def error_to_markdown(self, tool_name: str, error: str, context: Dict[str, Any]) -> str:
        """Convert an error to markdown entry."""
        entry_id = _generate_id("ERR")
        timestamp = datetime.now().isoformat()

        # Extract context details
        tool_input = context.get("tool_input", {})
        recovery = context.get("recovery_suggestion", {})

        entry = f"""## [{entry_id}] {tool_name}

**Logged**: {timestamp}
**Priority**: high
**Status**: pending
**Area**: backend

### Summary
{tool_name} failed: {error[:200]}

### Error
```
{error[:500]}
```

### Context
- Command/operation: {tool_name}
- Input: {str(tool_input)[:200]}

### Suggested Fix
{recovery.get("approach", "Investigate the error and determine root cause.")}

### Alternative Tools
{", ".join(recovery.get("alternative_tools", [])) or "None suggested"}

### Metadata
- Reproducible: unknown
- Source: spark_error_capture

---

"""
        return entry

    def write_insight(self, insight: CognitiveInsight) -> str:
        """Write a single insight to LEARNINGS.md."""
        self._ensure_dir()

        entry = self.insight_to_markdown(insight)
        learnings_file = self.learnings_dir / "LEARNINGS.md"

        with open(learnings_file, "a") as f:
            f.write(entry)

        entry_id = entry.split("]")[0].split("[")[1]
        print(f"[SPARK] Written to .learnings/LEARNINGS.md: {entry_id}")
        return entry_id

    def write_error(self, tool_name: str, error: str, context: Dict[str, Any] = None) -> str:
        """Write an error to ERRORS.md."""
        self._ensure_dir()

        entry = self.error_to_markdown(tool_name, error, context or {})
        errors_file = self.learnings_dir / "ERRORS.md"

        with open(errors_file, "a") as f:
            f.write(entry)

        entry_id = entry.split("]")[0].split("[")[1]
        print(f"[SPARK] Written to .learnings/ERRORS.md: {entry_id}")
        return entry_id

    def write_all_insights(self) -> Dict[str, int]:
        """Write all unwritten insights to markdown."""
        cognitive = get_cognitive_learner()
        stats = {"written": 0, "skipped": 0}

        # Track what we've already written
        written_file = self.learnings_dir / ".written_insights.txt"
        written_hashes = set()
        if written_file.exists():
            written_hashes = set(written_file.read_text(encoding="utf-8").strip().split("\n"))

        new_hashes = []
        for key, insight in cognitive.insights.items():
            if key in written_hashes:
                stats["skipped"] += 1
                continue

            self.write_insight(insight)
            new_hashes.append(key)
            stats["written"] += 1

        # Update written tracker
        if new_hashes:
            with open(written_file, "a") as f:
                f.write("\n".join(new_hashes) + "\n")

        print(f"[SPARK] Markdown write complete: {stats}")
        return stats

    def get_stats(self) -> Dict:
        """Get writer statistics."""
        learnings_count = 0
        errors_count = 0

        learnings_file = self.learnings_dir / "LEARNINGS.md"
        if learnings_file.exists():
            content = learnings_file.read_text(encoding="utf-8")
            learnings_count = content.count("## [LRN-")

        errors_file = self.learnings_dir / "ERRORS.md"
        if errors_file.exists():
            content = errors_file.read_text(encoding="utf-8")
            errors_count = content.count("## [ERR-")

        return {
            "learnings_dir": str(self.learnings_dir),
            "learnings_count": learnings_count,
            "errors_count": errors_count,
            "dir_exists": self.learnings_dir.exists()
        }


# ============= Singleton =============
_markdown_writer: Optional[MarkdownWriter] = None

def get_markdown_writer(project_dir: Optional[Path] = None) -> MarkdownWriter:
    """Get the markdown writer instance."""
    global _markdown_writer
    if _markdown_writer is None or (project_dir and _markdown_writer.project_dir != project_dir):
        _markdown_writer = MarkdownWriter(project_dir)
    return _markdown_writer


# ============= Convenience Functions =============
def write_learning(insight: CognitiveInsight, project_dir: Optional[Path] = None) -> str:
    """Write a single learning to markdown."""
    return get_markdown_writer(project_dir).write_insight(insight)


def write_error(tool_name: str, error: str, context: Dict[str, Any] = None,
                project_dir: Optional[Path] = None) -> str:
    """Write an error to markdown."""
    return get_markdown_writer(project_dir).write_error(tool_name, error, context)


def write_all_learnings(project_dir: Optional[Path] = None) -> Dict[str, int]:
    """Write all cognitive insights to markdown."""
    return get_markdown_writer(project_dir).write_all_insights()
