"""
EIDOS Migration: Transition from Current Spark to EIDOS

Migration Path:
1. Schema Creation - Create EIDOS tables (Day 1)
2. Data Migration - Migrate cognitive insights to distillations (Days 2-3)
3. Code Migration - Replace old modules with EIDOS (Days 4-7)
4. Parallel Running - Run both systems for validation (Week 2)
5. Cutover - Switch to EIDOS-only (Week 3)

This module handles the data migration aspects.
"""

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..spark_memory_spine import legacy_cognitive_json_path
from .models import Distillation, DistillationType, Policy
from .store import get_store


# Mapping from cognitive insight categories to distillation types
CATEGORY_TO_TYPE = {
    'SELF_AWARENESS': DistillationType.HEURISTIC,
    'USER_UNDERSTANDING': DistillationType.POLICY,
    'REASONING': DistillationType.HEURISTIC,
    'CONTEXT': DistillationType.SHARP_EDGE,
    'WISDOM': DistillationType.HEURISTIC,
    'META_LEARNING': DistillationType.HEURISTIC,
    'COMMUNICATION': DistillationType.POLICY,
    'CREATIVITY': DistillationType.PLAYBOOK,
    # Lower case versions
    'self': DistillationType.HEURISTIC,
    'user': DistillationType.POLICY,
    'reasoning': DistillationType.HEURISTIC,
    'context': DistillationType.SHARP_EDGE,
    'wisdom': DistillationType.HEURISTIC,
    'meta': DistillationType.HEURISTIC,
    'communication': DistillationType.POLICY,
    'creativity': DistillationType.PLAYBOOK,
}


@dataclass
class MigrationStats:
    """Statistics from a migration run."""
    insights_migrated: int = 0
    insights_skipped: int = 0
    patterns_archived: int = 0
    policies_created: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "insights_migrated": self.insights_migrated,
            "insights_skipped": self.insights_skipped,
            "patterns_archived": self.patterns_archived,
            "policies_created": self.policies_created,
            "errors": self.errors,
        }


def migrate_cognitive_insights(
    insights_path: Optional[Path] = None,
    dry_run: bool = False
) -> MigrationStats:
    """
    Migrate legacy cognitive snapshot to distillations table.

    Args:
        insights_path: Path to legacy cognitive snapshot (defaults to ~/.spark/)
        dry_run: If True, don't actually write to database

    Returns:
        MigrationStats with counts and any errors
    """
    if insights_path is None:
        insights_path = legacy_cognitive_json_path()

    stats = MigrationStats()

    if not insights_path.exists():
        stats.errors.append(f"Insights file not found: {insights_path}")
        return stats

    try:
        with open(insights_path, encoding='utf-8') as f:
            insights = json.load(f)
    except json.JSONDecodeError as e:
        stats.errors.append(f"JSON parse error: {e}")
        return stats
    except UnicodeDecodeError as e:
        stats.errors.append(f"Encoding error: {e}")
        return stats

    # Handle both list format and dict format
    if isinstance(insights, dict):
        # Convert dict format to list
        insights_list = []
        for key, value in insights.items():
            if isinstance(value, dict):
                value['id'] = key
                insights_list.append(value)
            else:
                # Value is a string, create minimal insight
                insights_list.append({'id': key, 'insight': str(value), 'category': 'REASONING'})
        insights = insights_list
    elif not isinstance(insights, list):
        stats.errors.append("Expected list or dict of insights")
        return stats

    store = get_store() if not dry_run else None

    for insight in insights:
        try:
            # Get category and map to type
            category = insight.get('category', 'REASONING')
            dtype = CATEGORY_TO_TYPE.get(category, DistillationType.HEURISTIC)

            # Get the insight text
            text = insight.get('insight', '')
            if not text:
                stats.insights_skipped += 1
                continue

            # Skip operational/primitive insights
            if _is_primitive_insight(text):
                stats.insights_skipped += 1
                continue

            # Create distillation
            distillation = Distillation(
                distillation_id=f"migrated_{insight.get('id', uuid4().hex[:8])}",
                type=dtype,
                statement=text,
                domains=_extract_domains(insight),
                triggers=_extract_triggers(text),
                source_steps=[],  # No step linkage for migrated
                validation_count=insight.get('times_validated', 0),
                contradiction_count=0,
                confidence=insight.get('reliability', 0.5),
                created_at=insight.get('created_at', time.time()),
            )

            if not dry_run and store:
                store.save_distillation(distillation)

            stats.insights_migrated += 1

        except Exception as e:
            stats.errors.append(f"Error migrating insight: {e}")

    return stats


def _is_primitive_insight(text: str) -> bool:
    """Check if insight is primitive/operational (should be skipped)."""
    primitive_patterns = [
        'tool sequence',
        'tool_sequence',
        '->',
        'usage signal',
        'heavy usage',
        'success rate',
        'error rate',
        'timeout',
        'TOOL_EFFECTIVENESS',
        'frustration pattern',
        'risky pattern',
    ]
    text_lower = text.lower()
    return any(pattern.lower() in text_lower for pattern in primitive_patterns)


def _extract_domains(insight: Dict[str, Any]) -> List[str]:
    """Extract domains from insight context."""
    domains = []

    context = insight.get('context', '')
    if context:
        # Check for common domain keywords
        domain_keywords = ['api', 'auth', 'database', 'ui', 'test', 'deploy', 'config']
        for keyword in domain_keywords:
            if keyword in context.lower():
                domains.append(keyword)

    # Add category as domain
    category = insight.get('category', '')
    if category:
        domains.append(category.lower())

    return domains if domains else ['general']


def _extract_triggers(text: str) -> List[str]:
    """Extract trigger words from insight text."""
    triggers = []

    # Extract first few significant words
    words = text.lower().split()[:10]
    for word in words:
        # Skip common words
        if word in ('the', 'a', 'an', 'is', 'are', 'was', 'were', 'i', 'we', 'it', 'to', 'and', 'or'):
            continue
        if len(word) > 3:
            triggers.append(word)
        if len(triggers) >= 3:
            break

    return triggers


def archive_patterns(
    patterns_path: Optional[Path] = None,
    archive_dir: Optional[Path] = None
) -> int:
    """
    Archive detected_patterns.jsonl to archive directory.

    Returns count of lines archived.
    """
    if patterns_path is None:
        patterns_path = Path.home() / ".spark" / "detected_patterns.jsonl"

    if archive_dir is None:
        archive_dir = Path.home() / ".spark" / "archive"

    if not patterns_path.exists():
        return 0

    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / "patterns_pre_eidos.jsonl"

    # Count lines
    count = 0
    with open(patterns_path) as f:
        for _ in f:
            count += 1

    # Move file
    shutil.move(str(patterns_path), str(archive_path))

    return count


def migrate_user_policies(
    insights_path: Optional[Path] = None,
    dry_run: bool = False
) -> int:
    """
    Extract user-stated policies from insights and create Policy objects.

    Returns count of policies created.
    """
    if insights_path is None:
        insights_path = legacy_cognitive_json_path()

    if not insights_path.exists():
        return 0

    try:
        with open(insights_path, encoding='utf-8') as f:
            insights = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0

    # Handle both list format and dict format
    if isinstance(insights, dict):
        insights_list = []
        for key, value in insights.items():
            if isinstance(value, dict):
                value['id'] = key
                insights_list.append(value)
        insights = insights_list
    elif not isinstance(insights, list):
        return 0

    store = get_store() if not dry_run else None
    count = 0

    # Policy signal words
    policy_signals = [
        'always', 'never', 'must', 'should', 'prefer', 'want',
        'don\'t', 'do not', 'avoid', 'make sure'
    ]

    for insight in insights:
        text = insight.get('insight', '').lower()

        # Check if this looks like a policy
        if any(signal in text for signal in policy_signals):
            category = insight.get('category', '')
            if category in ('USER_UNDERSTANDING', 'user'):
                # Create policy
                policy = Policy(
                    policy_id=f"migrated_{uuid4().hex[:8]}",
                    statement=insight.get('insight', ''),
                    scope='GLOBAL',
                    priority=60 if 'always' in text or 'never' in text else 50,
                    source='USER',
                    created_at=insight.get('created_at', time.time())
                )

                if not dry_run and store:
                    store.save_policy(policy)

                count += 1

    return count


def run_full_migration(dry_run: bool = False) -> Dict[str, Any]:
    """
    Run the complete migration from old Spark to EIDOS.

    Args:
        dry_run: If True, don't write to database or move files

    Returns:
        Migration statistics
    """
    results = {
        "dry_run": dry_run,
        "started_at": time.time(),
    }

    # 1. Migrate cognitive insights
    insights_stats = migrate_cognitive_insights(dry_run=dry_run)
    results["insights"] = insights_stats.to_dict()

    # 2. Archive patterns
    if not dry_run:
        patterns_count = archive_patterns()
    else:
        patterns_path = Path.home() / ".spark" / "detected_patterns.jsonl"
        patterns_count = 0
        if patterns_path.exists():
            try:
                with open(patterns_path, encoding='utf-8', errors='ignore') as f:
                    for _ in f:
                        patterns_count += 1
            except Exception:
                patterns_count = -1  # Indicates error reading
    results["patterns_archived"] = patterns_count

    # 3. Extract user policies
    policies_count = migrate_user_policies(dry_run=dry_run)
    results["policies_created"] = policies_count

    # 4. Backup original files
    if not dry_run:
        _backup_original_files()

    results["completed_at"] = time.time()
    results["duration_seconds"] = results["completed_at"] - results["started_at"]

    return results


def _backup_original_files():
    """Backup original files before migration."""
    spark_dir = Path.home() / ".spark"
    backup_dir = spark_dir / "backup_pre_eidos"
    backup_dir.mkdir(parents=True, exist_ok=True)

    files_to_backup = [
        legacy_cognitive_json_path().name,
        "graduated_patterns.json",
        "outcome_log.jsonl",
    ]

    for filename in files_to_backup:
        src = spark_dir / filename
        if src.exists():
            dst = backup_dir / filename
            shutil.copy2(str(src), str(dst))


def validate_migration() -> Dict[str, Any]:
    """
    Validate that migration completed successfully.

    Returns validation results.
    """
    store = get_store()
    stats = store.get_stats()

    results = {
        "eidos_tables_exist": True,
        "distillations_count": stats["distillations"],
        "policies_count": stats["policies"],
        "episodes_count": stats["episodes"],
        "steps_count": stats["steps"],
    }

    # Check backup exists
    backup_dir = Path.home() / ".spark" / "backup_pre_eidos"
    results["backup_exists"] = backup_dir.exists()

    # Check archive exists
    archive_path = Path.home() / ".spark" / "archive" / "patterns_pre_eidos.jsonl"
    results["patterns_archived"] = archive_path.exists()

    # Validation passed if we have distillations
    results["valid"] = stats["distillations"] > 0 or stats["policies"] > 0

    return results
