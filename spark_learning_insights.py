"""
Learning Insights Module for Spark Intelligence
File: spark_learning_insights.py

This module adds enhanced learning visualization capabilities to Spark.
It provides multiple views of what Spark has learned to help users 
understand the AI's growth and insights.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import os


class LearningInsights:
    """Provides enhanced insights into what Spark has learned"""

    def __init__(self, storage_path: str = "./.spark/storage"):
        self.storage_path = storage_path

    def get_learning_stats(self) -> Dict[str, Any]:
        """Get statistics about learned patterns"""
        # In a real implementation, this would connect to Spark's actual learning storage
        # For this PR, we'll simulate the data that would be available
        stats = {
            "total_learnings": 24,
            "categories": {
                "coding_patterns": 8,
                "workflow_optimizations": 6,
                "debugging_techniques": 5,
                "tool_usage": 3,
                "project_organization": 2
            },
            "date_range": {
                "first_learning": "2024-12-15",
                "latest_learning": "2024-12-20"
            },
            "confidence_stats": {
                "average_confidence": 0.82,
                "high_confidence_count": 18  # > 0.8 confidence
            }
        }
        return stats

    def detailed_view(self, limit: int = 10) -> None:
        """Display detailed view of recent learnings"""
        print("\n🔍 SPARK LEARNING INSIGHTS - DETAILED VIEW")
        print("=" * 60)

        # Simulated recent learnings - in real implementation would come from storage
        recent_learnings = [
            {
                "id": "rec_001",
                "title": "React Performance Optimization",
                "category": "coding_patterns",
                "confidence": 0.92,
                "date": "2024-12-20",
                "description": "Learned that useCallback helps prevent unnecessary re-renders in child components when passed as props",
                "source_session": "cursor_session_789",
                "impact_level": "high"
            },
            {
                "id": "rec_002",
                "title": "Python Import Organization",
                "category": "project_organization",
                "confidence": 0.87,
                "date": "2024-12-19",
                "description": "Observed consistent pattern of organizing imports: stdlib, third-party, local",
                "source_session": "vscode_session_456",
                "impact_level": "medium"
            },
            {
                "id": "rec_003",
                "title": "Database Query Optimization",
                "category": "coding_patterns",
                "confidence": 0.78,
                "date": "2024-12-18",
                "description": "Noticed that adding indexes to foreign key columns improves query performance significantly",
                "source_session": "claude_code_session_123",
                "impact_level": "high"
            }
        ][:limit]

        for i, learning in enumerate(recent_learnings, 1):
            print(f"\n{i}. {learning['title']}")
            print(
                f"   🏷️  Category: {learning['category'].replace('_', ' ').title()}")
            print(f"   📅 Date: {learning['date']}")
            print(f"   🎯 Confidence: {int(learning['confidence'] * 100)}%")
            print(f"   💡 Impact: {learning['impact_level'].title()}")
            print(f"   🔍 Description: {learning['description']}")
            print(f"   📚 Source: {learning['source_session']}")

    def summary_view(self) -> None:
        """Display summary of learning patterns"""
        stats = self.get_learning_stats()

        print("\n📊 SPARK LEARNING SUMMARY")
        print("=" * 40)
        print(f"Total Learnings Captured: {stats['total_learnings']}")
        print(
            f"Date Range: {stats['date_range']['first_learning']} to {stats['date_range']['latest_learning']}")
        print(
            f"Average Confidence: {int(stats['confidence_stats']['average_confidence'] * 100)}%")
        print(
            f"High Confidence Items: {stats['confidence_stats']['high_confidence_count']}")

        print("\nBreakdown by Category:")
        for category, count in stats['categories'].items():
            category_name = category.replace('_', ' ').title()
            print(f"  • {category_name}: {count}")

    def timeline_view(self, days: int = 7) -> None:
        """Display chronological view of learnings"""
        print(f"\n⏰ LEARNING TIMELINE (Last {days} Days)")
        print("=" * 50)

        # Generate simulated timeline data
        base_date = datetime.now() - timedelta(days=days-1)
        timeline_learnings = []

        for i in range(days):
            current_date = base_date + timedelta(days=i)
            # Simulate different numbers of learnings per day
            day_learnings = [
                {
                    "date": current_date.strftime("%m/%d"),
                    "title": f"Learning #{(i*2)+1}",
                    "category": ["coding", "workflow", "debugging"][i % 3],
                    "confidence": round(0.7 + (i*0.05), 2)
                },
                {
                    "date": current_date.strftime("%m/%d"),
                    "title": f"Pattern #{(i*2)+2}",
                    "category": ["tool_usage", "organization", "coding"][i % 3],
                    "confidence": round(0.8 - (i*0.02), 2)
                }
            ]
            timeline_learnings.extend(day_learnings)

        # Show most recent first
        for learning in reversed(timeline_learnings[-10:]):  # Last 10 items
            print(f"{learning['date']} | {learning['title']} ({learning['category']}) - "
                  f"Conf: {int(learning['confidence']*100)}%")

    def export_data(self, filepath: str, format_type: str = "json") -> bool:
        """Export learning data to file"""
        try:
            data = {
                "export_timestamp": datetime.now().isoformat(),
                "learning_stats": self.get_learning_stats(),
                "recent_learnings": [
                    {
                        "title": "React Performance Optimization",
                        "category": "coding_patterns",
                        "confidence": 0.92,
                        "date": "2024-12-20",
                        "description": "Learned that useCallback helps prevent unnecessary re-renders"
                    },
                    {
                        "title": "Python Import Organization",
                        "category": "project_organization",
                        "confidence": 0.87,
                        "date": "2024-12-19",
                        "description": "Consistent pattern of organizing imports by type"
                    }
                ]
            }

            if format_type.lower() == "json":
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            else:
                raise ValueError(f"Unsupported format: {format_type}")

            print(f"✅ Successfully exported learning data to {filepath}")
            return True

        except Exception as e:
            print(f"❌ Failed to export data: {str(e)}")
            return False


def main():
    """Main entry point for the learning insights feature"""
    parser = argparse.ArgumentParser(
        description="Enhanced learning insights for Spark Intelligence"
    )
    parser.add_argument(
        "--view",
        choices=["detailed", "summary", "timeline", "export"],
        default="detailed",
        help="Type of learning insights to display"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of items to display (for detailed view)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to show in timeline (for timeline view)"
    )
    parser.add_argument(
        "--output-file",
        type=str,
        help="Output file path for export view"
    )

    args = parser.parse_args()

    insights = LearningInsights()

    if args.view == "detailed":
        insights.detailed_view(args.limit)
    elif args.view == "summary":
        insights.summary_view()
    elif args.view == "timeline":
        insights.timeline_view(args.days)
    elif args.view == "export":
        if not args.output_file:
            print("Error: --output-file is required for export view")
            sys.exit(1)
        success = insights.export_data(args.output_file)
        if not success:
            sys.exit(1)

    print(f"\n💡 Tip: Run 'spark learnings --help' for more options")
    print(f"📖 Learn more at: https://spark.vibeship.co")


if __name__ == "__main__":
    main()
