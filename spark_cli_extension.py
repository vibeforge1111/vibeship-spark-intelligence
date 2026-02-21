"""
CLI Extension for Spark Learning Insights
This file demonstrates how the enhanced learning insights would be integrated
into the Spark CLI system.
"""

import typer
from typing import Optional
import json
from datetime import datetime, timedelta
from pathlib import Path

# This would be imported from the actual Spark project in real implementation
# from spark.core.storage import LearningStorage
# from spark.core.config import get_config

app = typer.Typer()


class LearningInsights:
    """Enhanced learning insights for Spark Intelligence"""

    def __init__(self):
        # In real implementation, this would connect to Spark's actual storage
        pass

    def get_detailed_learnings(self, limit: int = 10):
        """Get detailed view of learnings"""
        # Simulated data - in real implementation would fetch from Spark's learning storage
        sample_learnings = [
            {
                "id": "learn_react_perf_001",
                "title": "React Performance Optimization",
                "category": "coding_patterns",
                "confidence": 0.92,
                "date": "2024-12-20",
                "description": "Learned that useCallback helps prevent unnecessary re-renders in child components when passed as props",
                "source_session": "cursor_session_789",
                "impact_level": "high",
                "advice": "Consider wrapping callback functions in useCallback when passing to memoized components"
            },
            {
                "id": "learn_python_imports_002",
                "title": "Python Import Organization",
                "category": "project_organization",
                "confidence": 0.87,
                "date": "2024-12-19",
                "description": "Observed consistent pattern of organizing imports: stdlib, third-party, local",
                "source_session": "vscode_session_456",
                "impact_level": "medium",
                "advice": "Following PEP 8 import organization standards consistently"
            },
            {
                "id": "learn_db_index_003",
                "title": "Database Query Optimization",
                "category": "coding_patterns",
                "confidence": 0.78,
                "date": "2024-12-18",
                "description": "Noticed that adding indexes to foreign key columns improves query performance significantly",
                "source_session": "claude_code_session_123",
                "impact_level": "high",
                "advice": "Consider adding indexes to foreign key columns for better query performance"
            },
            {
                "id": "learn_error_handling_004",
                "title": "Common Error Resolution Pattern",
                "category": "debugging_techniques",
                "confidence": 0.85,
                "date": "2024-12-17",
                "description": "Identified that TypeError: Cannot read property of undefined is often resolved by null checks",
                "source_session": "cursor_session_101",
                "impact_level": "high",
                "advice": "Always validate object existence before accessing nested properties"
            },
            {
                "id": "learn_git_workflow_005",
                "title": "Git Branch Naming Convention",
                "category": "workflow_optimizations",
                "confidence": 0.95,
                "date": "2024-12-16",
                "description": "Consistent use of feature/branch-name convention detected",
                "source_session": "terminal_session_202",
                "impact_level": "low",
                "advice": "Continue using consistent branch naming conventions"
            }
        ][:limit]

        return sample_learnings

    def get_summary_stats(self):
        """Get summary statistics about learnings"""
        # Simulated stats - in real implementation would aggregate from actual data
        stats = {
            "total_learnings": 32,
            "categories": {
                "coding_patterns": 12,
                "workflow_optimizations": 8,
                "debugging_techniques": 6,
                "tool_usage": 4,
                "project_organization": 2
            },
            "date_range": {
                "first_learning": "2024-12-10",
                "latest_learning": "2024-12-20"
            },
            "confidence_stats": {
                "average_confidence": 0.84,
                "high_confidence_count": 26,  # > 0.8 confidence
                "medium_confidence_count": 4,  # 0.5-0.8 confidence
                "low_confidence_count": 2    # < 0.5 confidence
            },
            "impact_stats": {
                "high_impact": 18,
                "medium_impact": 10,
                "low_impact": 4
            }
        }
        return stats


@app.command()
def learnings_extended(
    view: str = typer.Option("detailed", "--view", "-v",
                             help="View type: detailed, summary, or timeline"),
    limit: int = typer.Option(10, "--limit", "-l",
                              help="Number of items to display (for detailed view)"),
    days: int = typer.Option(7, "--days", "-d",
                             help="Number of days for timeline view"),
    export_path: Optional[str] = typer.Option(None, "--export", "-e",
                                              help="Export results to JSON file")
):
    """
    Enhanced version of spark learnings command with additional insights and visualization options.
    """
    insights = LearningInsights()

    if view == "detailed":
        learnings = insights.get_detailed_learnings(limit)

        typer.secho("\n🔍 SPARK LEARNING INSIGHTS - DETAILED VIEW",
                    fg=typer.colors.CYAN, bold=True)
        typer.secho("=" * 70, fg=typer.colors.BLUE)

        for i, learning in enumerate(learnings, 1):
            typer.secho(f"\n{i}. {learning['title']}",
                        fg=typer.colors.GREEN, bold=True)
            typer.echo(
                f"   🏷️  Category: {learning['category'].replace('_', ' ').title()}")
            typer.echo(f"   📅 Date: {learning['date']}")
            typer.echo(
                f"   🎯 Confidence: {int(learning['confidence'] * 100)}%")
            typer.echo(f"   💡 Impact: {learning['impact_level'].title()}")
            typer.echo(f"   🔍 Description: {learning['description']}")
            typer.echo(f"   💡 Advice: {learning['advice']}")
            typer.echo(f"   📚 Source: {learning['source_session']}")

    elif view == "summary":
        stats = insights.get_summary_stats()

        typer.secho("\n📊 SPARK LEARNING SUMMARY",
                    fg=typer.colors.CYAN, bold=True)
        typer.secho("=" * 50, fg=typer.colors.BLUE)
        typer.echo(f"Total Learnings Captured: {stats['total_learnings']}")
        typer.echo(
            f"Date Range: {stats['date_range']['first_learning']} to {stats['date_range']['latest_learning']}")
        typer.echo(
            f"Average Confidence: {int(stats['confidence_stats']['average_confidence'] * 100)}%")

        typer.secho("\nConfidence Distribution:", fg=typer.colors.YELLOW)
        typer.echo(
            f"  • High Confidence (>80%): {stats['confidence_stats']['high_confidence_count']}")
        typer.echo(
            f"  • Medium Confidence (50-80%): {stats['confidence_stats']['medium_confidence_count']}")
        typer.echo(
            f"  • Low Confidence (<50%): {stats['confidence_stats']['low_confidence_count']}")

        typer.secho("\nImpact Distribution:", fg=typer.colors.YELLOW)
        typer.echo(f"  • High Impact: {stats['impact_stats']['high_impact']}")
        typer.echo(
            f"  • Medium Impact: {stats['impact_stats']['medium_impact']}")
        typer.echo(f"  • Low Impact: {stats['impact_stats']['low_impact']}")

        typer.secho("\nBreakdown by Category:", fg=typer.colors.YELLOW)
        for category, count in stats['categories'].items():
            category_name = category.replace('_', ' ').title()
            typer.echo(f"  • {category_name}: {count}")

    elif view == "timeline":
        typer.secho(
            f"\n⏰ LEARNING TIMELINE (Last {days} Days)", fg=typer.colors.CYAN, bold=True)
        typer.secho("=" * 60, fg=typer.colors.BLUE)

        # Generate simulated timeline
        base_date = datetime.now() - timedelta(days=days-1)
        for i in range(days):
            current_date = base_date + timedelta(days=i)
            day_str = current_date.strftime("%m/%d")
            # Simulate number of learnings per day
            num_learnings = max(1, 5 - abs(i - 3))  # Peak in middle days
            typer.echo(
                f"{day_str} | ⚡ {num_learnings} new learning{'s' if num_learnings != 1 else ''} captured")

    else:
        typer.echo(
            f"Unknown view type: {view}. Use 'detailed', 'summary', or 'timeline'")
        raise typer.Exit(code=1)

    # Export functionality if requested
    if export_path:
        if view == "detailed":
            data = {
                "view_type": view,
                "generated_at": datetime.now().isoformat(),
                "learnings": insights.get_detailed_learnings(limit)
            }
        elif view == "summary":
            data = {
                "view_type": view,
                "generated_at": datetime.now().isoformat(),
                "summary_stats": insights.get_summary_stats()
            }

        export_file = Path(export_path)
        with open(export_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        typer.secho(
            f"\n✅ Results exported to {export_file.absolute()}", fg=typer.colors.GREEN)

    typer.secho(f"\n💡 Pro tip: Use --view summary for quick overview or --view detailed for specifics",
                fg=typer.colors.BRIGHT_YELLOW)


@app.command()
def health_extended():
    """
    Extended health check showing learning system status
    """
    typer.secho("🏥 SPARK HEALTH CHECK (Extended)",
                fg=typer.colors.CYAN, bold=True)
    typer.secho("=" * 40, fg=typer.colors.BLUE)

    # Simulated health data
    typer.echo("✓ Core System: Operational")
    typer.echo("✓ Learning Pipeline: Active")
    typer.echo("✓ Memory Storage: Healthy")
    typer.echo("✓ Advisory System: Running")

    insights = LearningInsights()
    stats = insights.get_summary_stats()

    typer.secho(f"\n🧠 Learning Stats:", fg=typer.colors.YELLOW)
    typer.echo(f"  Total Learnings: {stats['total_learnings']}")
    typer.echo(
        f"  Average Confidence: {int(stats['confidence_stats']['average_confidence'] * 100)}%")
    typer.echo(f"  Last Learning: Today")

    typer.secho(f"\n✅ System Status: All systems nominal",
                fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
