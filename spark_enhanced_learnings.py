"""
Enhanced Learnings Feature for Spark Intelligence

This module adds enhanced capabilities to the spark learnings command
to provide more detailed insights into what Spark has learned.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional


def enhanced_learnings_command(output_format: str = "detailed", limit: int = 10):
    """
    Enhanced version of the spark learnings command that provides more detailed insights
    
    Args:
        output_format: Format of output ('detailed', 'summary', 'timeline')
        limit: Number of learnings to display
    """
    print(f"\n🔍 SPARK LEARNINGS ANALYSIS")
    print("="*50)
    
    # Mock data representing typical learnings from Spark
    sample_learnings = [
        {
            "id": "learn_001",
            "timestamp": "2024-12-19T10:30:00Z",
            "category": "coding_pattern",
            "title": "React Component Optimization Pattern",
            "description": "Learned that memoizing child components in React improves performance when parent re-renders",
            "confidence": 0.85,
            "source": "cursor_session_abc123",
            "impact_score": 4.2
        },
        {
            "id": "learn_002", 
            "timestamp": "2024-12-19T14:22:00Z",
            "category": "workflow",
            "title": "Git Branch Naming Convention",
            "description": "Detected consistent pattern of using feature/branch-name convention",
            "confidence": 0.92,
            "source": "vscode_hooks_xyz789", 
            "impact_score": 3.8
        },
        {
            "id": "learn_003",
            "timestamp": "2024-12-20T09:15:00Z", 
            "category": "debugging",
            "title": "Common Error Resolution",
            "description": "Identified that TypeError: Cannot read property 'length' of undefined is often resolved by checking if variable is null",
            "confidence": 0.78,
            "source": "claude_code_session_def456",
            "impact_score": 4.5
        }
    ]
    
    if output_format == "detailed":
        _display_detailed_learnings(sample_learnings[:limit])
    elif output_format == "summary":
        _display_summary_learnings(sample_learnings[:limit])
    elif output_format == "timeline":
        _display_timeline_learnings(sample_learnings[:limit])
    else:
        _display_detailed_learnings(sample_learnings[:limit])


def _display_detailed_learnings(learnings: List[Dict]):
    """Display detailed view of learnings"""
    for i, learning in enumerate(learnings, 1):
        print(f"\n{i}. {learning['title']}")
        print(f"   🏷️  Category: {learning['category'].title()}")
        print(f"   📅 Date: {learning['timestamp']}")
        print(f"   🎯 Confidence: {int(learning['confidence'] * 100)}%")
        print(f"   💡 Impact: {learning['impact_score']}/5.0")
        print(f"   🔬 Description: {learning['description']}")
        print(f"   📚 Source: {learning['source']}")
        print()


def _display_summary_learnings(learnings: List[Dict]):
    """Display summary view of learnings"""
    categories = {}
    for learning in learnings:
        cat = learning['category']
        categories[cat] = categories.get(cat, 0) + 1
    
    print(f"📊 LEARNING SUMMARY")
    print(f"Total Learnings: {len(learnings)}")
    print("By Category:")
    for cat, count in categories.items():
        print(f"  • {cat.title()}: {count}")
    
    avg_confidence = sum(l['confidence'] for l in learnings) / len(learnings) if learnings else 0
    print(f"Average Confidence: {int(avg_confidence * 100)}%")


def _display_timeline_learnings(learnings: List[Dict]):
    """Display timeline view of learnings"""
    print("⏰ LEARNING TIMELINE")
    sorted_learnings = sorted(learnings, key=lambda x: x['timestamp'], reverse=True)
    
    for learning in sorted_learnings:
        dt = datetime.fromisoformat(learning['timestamp'].replace('Z', '+00:00'))
        formatted_time = dt.strftime("%m/%d %H:%M")
        print(f"{formatted_time} | {learning['title']} [{learning['category']}]")
    

def export_learnings(file_path: str, format_type: str = "json"):
    """Export learnings to a file"""
    # This would connect to actual Spark data in real implementation
    sample_data = {
        "export_date": datetime.now().isoformat(),
        "total_learnings": 42,
        "categories": ["coding_pattern", "workflow", "debugging", "tool_usage"],
        "recent_learnings": [
            {
                "title": "React Component Optimization Pattern",
                "description": "Learned that memoizing child components in React improves performance when parent re-renders",
                "date": "2024-12-19",
                "confidence": 0.85
            }
        ]
    }
    
    if format_type.lower() == "json":
        with open(file_path, 'w') as f:
            json.dump(sample_data, f, indent=2)
        print(f"✅ Learnings exported to {file_path}")
    else:
        print(f"❌ Format {format_type} not supported yet")


if __name__ == "__main__":
    # Demonstrate the enhanced learnings functionality
    print("Spark Intelligence - Enhanced Learnings View")
    print("This is a demonstration of an enhanced 'spark learnings' command")
    print()
    
    print("DETAILED VIEW:")
    enhanced_learnings_command(output_format="detailed", limit=3)
    
    print("\nSUMMARY VIEW:")
    enhanced_learnings_command(output_format="summary", limit=3)
    
    print("\nTIMELINE VIEW:")
    enhanced_learnings_command(output_format="timeline", limit=3)
    
    print("\nEXPORT FUNCTION:")
    export_learnings("./sample_learnings_export.json")