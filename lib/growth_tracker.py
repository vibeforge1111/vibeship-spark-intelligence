#!/usr/bin/env python3
"""
Growth Tracker - Visualize Learning Over Time

Shows PROGRESS, not just stats. Makes improvement tangible.

Day 1: "Learning your codebase..."
Day 7: "40% more accurate on your preferences"
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
from enum import Enum


class Milestone(Enum):
    """Achievement milestones."""
    FIRST_INSIGHT = "first_insight"
    TEN_INSIGHTS = "ten_insights"
    FIFTY_INSIGHTS = "fifty_insights"
    FIRST_PROMOTION = "first_promotion"
    FIRST_AHA = "first_aha"
    PATTERN_MASTER = "pattern_master"      # 10 patterns recognized
    PREFERENCE_LEARNED = "preference_learned"
    WEEK_ACTIVE = "week_active"
    MONTH_ACTIVE = "month_active"
    ACCURACY_70 = "accuracy_70"
    ACCURACY_90 = "accuracy_90"


MILESTONE_MESSAGES = {
    Milestone.FIRST_INSIGHT: "🌱 First insight captured! The learning begins.",
    Milestone.TEN_INSIGHTS: "📚 10 insights learned. Building knowledge.",
    Milestone.FIFTY_INSIGHTS: "🧠 50 insights! Deep understanding forming.",
    Milestone.FIRST_PROMOTION: "⭐ First insight promoted to docs!",
    Milestone.FIRST_AHA: "💡 First aha moment! Self-awareness emerging.",
    Milestone.PATTERN_MASTER: "🔄 10 patterns mastered. I see how you work.",
    Milestone.PREFERENCE_LEARNED: "💜 Your preferences are becoming clear.",
    Milestone.WEEK_ACTIVE: "📅 One week of learning together.",
    Milestone.MONTH_ACTIVE: "🎂 One month! I know you well now.",
    Milestone.ACCURACY_70: "🎯 70% prediction accuracy reached.",
    Milestone.ACCURACY_90: "🏆 90% accuracy! I really get you.",
}


@dataclass
class GrowthSnapshot:
    """A point-in-time snapshot of growth."""
    timestamp: str
    insights_count: int
    promoted_count: int
    aha_count: int
    avg_reliability: float
    categories_active: int
    events_processed: int
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GrowthSnapshot":
        return cls(**data)


@dataclass  
class MilestoneRecord:
    """Record of achieved milestone."""
    milestone: Milestone
    achieved_at: str
    context: str  # What triggered it
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['milestone'] = self.milestone.value
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MilestoneRecord":
        data['milestone'] = Milestone(data['milestone'])
        return cls(**data)


class GrowthTracker:
    """
    Tracks learning progress over time.
    
    Creates a narrative of growth, not just numbers.
    """
    
    GROWTH_FILE = Path(__file__).parent.parent / ".spark" / "growth.json"
    
    def __init__(self) -> None:
        self.snapshots: List[GrowthSnapshot] = []
        self.milestones: Dict[str, MilestoneRecord] = {}
        self.started_at: Optional[str] = None
        self._load()

    def _load(self) -> None:
        """Load growth data from disk."""
        if self.GROWTH_FILE.exists():
            try:
                data = json.loads(self.GROWTH_FILE.read_text(encoding="utf-8"))
                self.snapshots = [GrowthSnapshot.from_dict(s) for s in data.get("snapshots", [])]
                self.milestones = {
                    k: MilestoneRecord.from_dict(v) 
                    for k, v in data.get("milestones", {}).items()
                }
                self.started_at = data.get("started_at")
            except Exception:
                pass
        
        if not self.started_at:
            self.started_at = datetime.now().isoformat()
            self._save()
    
    def _save(self) -> None:
        """Save growth data to disk."""
        self.GROWTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "started_at": self.started_at,
            "snapshots": [s.to_dict() for s in self.snapshots],
            "milestones": {k: v.to_dict() for k, v in self.milestones.items()},
        }
        self.GROWTH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    
    def record_snapshot(
        self,
        insights_count: int,
        promoted_count: int,
        aha_count: int,
        avg_reliability: float,
        categories_active: int,
        events_processed: int,
    ) -> GrowthSnapshot:
        """Record a growth snapshot."""
        snapshot = GrowthSnapshot(
            timestamp=datetime.now().isoformat(),
            insights_count=insights_count,
            promoted_count=promoted_count,
            aha_count=aha_count,
            avg_reliability=avg_reliability,
            categories_active=categories_active,
            events_processed=events_processed,
        )
        
        self.snapshots.append(snapshot)
        
        # Keep last 1000 snapshots
        if len(self.snapshots) > 1000:
            self.snapshots = self.snapshots[-1000:]
        
        self._save()
        
        # Check for new milestones
        self._check_milestones(snapshot)
        
        return snapshot
    
    def _check_milestones(self, snapshot: GrowthSnapshot) -> List[Milestone]:
        """Check and record any new milestones."""
        new_milestones = []
        
        checks = [
            (Milestone.FIRST_INSIGHT, snapshot.insights_count >= 1),
            (Milestone.TEN_INSIGHTS, snapshot.insights_count >= 10),
            (Milestone.FIFTY_INSIGHTS, snapshot.insights_count >= 50),
            (Milestone.FIRST_PROMOTION, snapshot.promoted_count >= 1),
            (Milestone.FIRST_AHA, snapshot.aha_count >= 1),
            (Milestone.ACCURACY_70, snapshot.avg_reliability >= 0.7),
            (Milestone.ACCURACY_90, snapshot.avg_reliability >= 0.9),
        ]
        
        for milestone, achieved in checks:
            if achieved and milestone.value not in self.milestones:
                self.milestones[milestone.value] = MilestoneRecord(
                    milestone=milestone,
                    achieved_at=datetime.now().isoformat(),
                    context=f"Snapshot: {snapshot.insights_count} insights, {snapshot.avg_reliability:.0%} reliability"
                )
                new_milestones.append(milestone)
        
        # Time-based milestones
        if self.started_at:
            started = datetime.fromisoformat(self.started_at)
            days_active = (datetime.now() - started).days
            
            if days_active >= 7 and Milestone.WEEK_ACTIVE.value not in self.milestones:
                self.milestones[Milestone.WEEK_ACTIVE.value] = MilestoneRecord(
                    milestone=Milestone.WEEK_ACTIVE,
                    achieved_at=datetime.now().isoformat(),
                    context=f"7 days of learning"
                )
                new_milestones.append(Milestone.WEEK_ACTIVE)
            
            if days_active >= 30 and Milestone.MONTH_ACTIVE.value not in self.milestones:
                self.milestones[Milestone.MONTH_ACTIVE.value] = MilestoneRecord(
                    milestone=Milestone.MONTH_ACTIVE,
                    achieved_at=datetime.now().isoformat(),
                    context=f"30 days of learning"
                )
                new_milestones.append(Milestone.MONTH_ACTIVE)
        
        if new_milestones:
            self._save()
        
        return new_milestones
    
    def get_growth_narrative(self) -> str:
        """Generate a human-readable growth narrative."""
        if not self.started_at:
            return "Just getting started. Learning begins now."
        
        started = datetime.fromisoformat(self.started_at)
        days_active = (datetime.now() - started).days
        
        latest = self.snapshots[-1] if self.snapshots else None
        
        if not latest:
            return f"Day {days_active + 1}: Beginning to learn..."
        
        # Build narrative
        lines = []
        
        # Time context
        if days_active == 0:
            lines.append("🌱 **Day 1** — Just getting started")
        elif days_active < 7:
            lines.append(f"📅 **Day {days_active + 1}** — Building foundations")
        elif days_active < 30:
            lines.append(f"📈 **Week {days_active // 7 + 1}** — Growing steadily")
        else:
            lines.append(f"🧠 **Month {days_active // 30 + 1}** — Deep understanding")
        
        # Stats narrative
        lines.append(f"")
        lines.append(f"**{latest.insights_count}** insights learned")
        lines.append(f"**{latest.avg_reliability:.0%}** average reliability")
        lines.append(f"**{latest.promoted_count}** promoted to docs")
        
        if latest.aha_count > 0:
            lines.append(f"**{latest.aha_count}** aha moments")
        
        # Recent milestone
        recent_milestones = sorted(
            self.milestones.values(),
            key=lambda m: m.achieved_at,
            reverse=True
        )[:1]
        
        if recent_milestones:
            ms = recent_milestones[0]
            lines.append(f"")
            lines.append(f"🏆 Latest: {MILESTONE_MESSAGES.get(ms.milestone, ms.milestone.value)}")
        
        return "\n".join(lines)
    
    def get_growth_delta(self, hours: int = 24) -> Dict[str, Any]:
        """Get growth change over time period."""
        if len(self.snapshots) < 2:
            return {"change": "insufficient_data"}
        
        cutoff = datetime.now() - timedelta(hours=hours)
        
        # Find snapshot closest to cutoff
        old_snapshot = None
        for s in self.snapshots:
            if datetime.fromisoformat(s.timestamp) <= cutoff:
                old_snapshot = s
            else:
                break
        
        if not old_snapshot:
            old_snapshot = self.snapshots[0]
        
        latest = self.snapshots[-1]
        
        return {
            "period_hours": hours,
            "insights_delta": latest.insights_count - old_snapshot.insights_count,
            "reliability_delta": latest.avg_reliability - old_snapshot.avg_reliability,
            "promoted_delta": latest.promoted_count - old_snapshot.promoted_count,
            "aha_delta": latest.aha_count - old_snapshot.aha_count,
        }
    
    def get_timeline(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get timeline of milestones and significant events."""
        timeline = []
        
        for ms in self.milestones.values():
            timeline.append({
                "type": "milestone",
                "timestamp": ms.achieved_at,
                "title": MILESTONE_MESSAGES.get(ms.milestone, ms.milestone.value),
                "context": ms.context,
            })
        
        # Sort by time
        timeline.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return timeline[:limit]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get growth statistics."""
        started = datetime.fromisoformat(self.started_at) if self.started_at else datetime.now()
        days_active = (datetime.now() - started).days + 1
        
        latest = self.snapshots[-1] if self.snapshots else None
        
        return {
            "started_at": self.started_at,
            "days_active": days_active,
            "total_snapshots": len(self.snapshots),
            "milestones_achieved": len(self.milestones),
            "milestone_list": [m.value for m in self.milestones.keys()] if self.milestones else [],
            "latest_snapshot": latest.to_dict() if latest else None,
        }


# ============= Singleton =============
_tracker: Optional[GrowthTracker] = None

def get_growth_tracker() -> GrowthTracker:
    """Get the global growth tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = GrowthTracker()
    return _tracker
