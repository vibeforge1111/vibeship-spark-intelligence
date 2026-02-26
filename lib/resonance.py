#!/usr/bin/env python3
"""
Spark Resonance - Connection depth evolution

The spark that grows brighter as resonance deepens.

States:
  ✦ Spark    (0-25%)   - Just met. Learning signals.
  ⚡ Pulse   (25-50%)  - Catching frequency. Patterns forming.
  ✺ Blaze   (50-75%)  - Burning together. I know you now.
  ☀ Radiant (75-100%) - Full sync. Deep partnership.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from enum import Enum


class ResonanceState(Enum):
    SPARK = "spark"
    PULSE = "pulse"
    BLAZE = "blaze"
    RADIANT = "radiant"


RESONANCE_CONFIG = {
    ResonanceState.SPARK: {
        "icon": "✦",
        "name": "Spark",
        "range": (0, 25),
        "description": "Just met. Learning your signals.",
        "color": "#6b7489",  # dim
    },
    ResonanceState.PULSE: {
        "icon": "⚡",
        "name": "Pulse", 
        "range": (25, 50),
        "description": "Catching your frequency. Patterns forming.",
        "color": "#D97757",  # orange
    },
    ResonanceState.BLAZE: {
        "icon": "✺",
        "name": "Blaze",
        "range": (50, 75),
        "description": "Burning together. I know you now.",
        "color": "#00C49A",  # green
    },
    ResonanceState.RADIANT: {
        "icon": "☀",
        "name": "Radiant",
        "range": (75, 100),
        "description": "Full sync. Deep partnership.",
        "color": "#D9985A",  # warm amber - closer to the orange palette
    },
}


@dataclass
class ResonanceScore:
    """Breakdown of resonance calculation."""
    insights_score: float      # From cognitive insights
    surprises_score: float     # From aha moments
    opinions_score: float      # From personality opinions
    growth_score: float        # From growth moments
    interactions_score: float  # From interaction count
    validation_score: float    # From validated insights
    total: float               # Combined resonance (0-100)
    state: ResonanceState      # Current evolution state
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "insights_score": round(self.insights_score, 1),
            "surprises_score": round(self.surprises_score, 1),
            "opinions_score": round(self.opinions_score, 1),
            "growth_score": round(self.growth_score, 1),
            "interactions_score": round(self.interactions_score, 1),
            "validation_score": round(self.validation_score, 1),
            "total": round(self.total, 1),
            "state": self.state.value,
            "state_config": RESONANCE_CONFIG[self.state],
        }


class ResonanceCalculator:
    """
    Calculates resonance level based on Spark's learning state.
    
    Resonance = how deeply connected we are, not just time spent.
    """
    
    # Weights for each component (total = 100)
    WEIGHTS = {
        "insights": 30,        # Core learning about the user
        "surprises": 15,       # Aha moments and lessons
        "opinions": 20,        # Personality development
        "growth": 15,          # Growth moments
        "interactions": 10,    # Time together
        "validation": 10,      # Trust/verified learnings
    }
    
    # Thresholds for max score
    THRESHOLDS = {
        "insights": 50,        # 50 insights = max score
        "surprises": 20,       # 20 surprises = max score
        "opinions": 15,        # 15 opinions = max score
        "growth": 10,          # 10 growth moments = max score
        "interactions": 100,   # 100 interactions = max score
        "validation": 30,      # 30 validated insights = max score
    }
    
    def __init__(self) -> None:
        pass
    
    def _score_component(self, value: int, threshold: int, weight: int) -> float:
        """Score a component, capped at weight."""
        ratio = min(value / threshold, 1.0)
        return ratio * weight
    
    def calculate(
        self,
        insights_count: int = 0,
        user_insights_count: int = 0,  # Insights specifically about user
        surprises_count: int = 0,
        lessons_count: int = 0,
        opinions_count: int = 0,
        strong_opinions_count: int = 0,
        growth_count: int = 0,
        interactions_count: int = 0,
        validated_count: int = 0,
    ) -> ResonanceScore:
        """
        Calculate resonance score from Spark metrics.
        
        User-specific insights count double.
        Strong opinions count double.
        Lessons count as bonus.
        """
        # Insights (user insights count double)
        effective_insights = insights_count + user_insights_count
        insights_score = self._score_component(
            effective_insights, 
            self.THRESHOLDS["insights"], 
            self.WEIGHTS["insights"]
        )
        
        # Surprises (lessons add bonus)
        effective_surprises = surprises_count + (lessons_count * 0.5)
        surprises_score = self._score_component(
            effective_surprises,
            self.THRESHOLDS["surprises"],
            self.WEIGHTS["surprises"]
        )
        
        # Opinions (strong opinions count double)
        effective_opinions = opinions_count + strong_opinions_count
        opinions_score = self._score_component(
            effective_opinions,
            self.THRESHOLDS["opinions"],
            self.WEIGHTS["opinions"]
        )
        
        # Growth
        growth_score = self._score_component(
            growth_count,
            self.THRESHOLDS["growth"],
            self.WEIGHTS["growth"]
        )
        
        # Interactions
        interactions_score = self._score_component(
            interactions_count,
            self.THRESHOLDS["interactions"],
            self.WEIGHTS["interactions"]
        )
        
        # Validation
        validation_score = self._score_component(
            validated_count,
            self.THRESHOLDS["validation"],
            self.WEIGHTS["validation"]
        )
        
        # Total
        total = (
            insights_score + 
            surprises_score + 
            opinions_score + 
            growth_score + 
            interactions_score + 
            validation_score
        )
        
        # Determine state
        state = self._get_state(total)
        
        return ResonanceScore(
            insights_score=insights_score,
            surprises_score=surprises_score,
            opinions_score=opinions_score,
            growth_score=growth_score,
            interactions_score=interactions_score,
            validation_score=validation_score,
            total=total,
            state=state,
        )
    
    def _get_state(self, total: float) -> ResonanceState:
        """Get resonance state from total score."""
        if total < 25:
            return ResonanceState.SPARK
        elif total < 50:
            return ResonanceState.PULSE
        elif total < 75:
            return ResonanceState.BLAZE
        else:
            return ResonanceState.RADIANT


def calculate_current_resonance() -> ResonanceScore:
    """Calculate resonance from current Spark state."""
    from lib.cognitive_learner import CognitiveLearner, CognitiveCategory
    from lib.aha_tracker import AhaTracker
    from lib.spark_voice import SparkVoice
    
    cognitive = CognitiveLearner()
    aha = AhaTracker()
    voice = SparkVoice()
    
    # Gather metrics
    insights = list(cognitive.insights.values())
    user_insights = [i for i in insights if i.category == CognitiveCategory.USER_UNDERSTANDING]
    validated = [i for i in insights if i.times_validated >= 1]
    
    aha_stats = aha.get_stats()
    voice_stats = voice.get_stats()
    
    opinions = voice.get_opinions()
    strong_opinions = voice.get_strong_opinions()
    
    # Calculate
    calc = ResonanceCalculator()
    return calc.calculate(
        insights_count=len(insights),
        user_insights_count=len(user_insights),
        surprises_count=aha_stats["total_captured"],
        lessons_count=aha_stats["lessons_extracted"],
        opinions_count=len(opinions),
        strong_opinions_count=len(strong_opinions),
        growth_count=voice_stats["growth_moments"],
        interactions_count=voice_stats["interactions"],
        validated_count=len(validated),
    )


def get_resonance_display() -> Dict[str, Any]:
    """Get resonance data for display."""
    score = calculate_current_resonance()
    config = RESONANCE_CONFIG[score.state]
    
    return {
        "score": score.total,
        "state": score.state.value,
        "icon": config["icon"],
        "name": config["name"],
        "description": config["description"],
        "color": config["color"],
        "breakdown": score.to_dict(),
        "next_state": _get_next_state(score.state),
        "to_next": _points_to_next(score.total, score.state),
    }


def _get_next_state(current: ResonanceState) -> Optional[Dict[str, Any]]:
    """Get info about next resonance state."""
    order = [ResonanceState.SPARK, ResonanceState.PULSE, ResonanceState.BLAZE, ResonanceState.RADIANT]
    idx = order.index(current)
    if idx < len(order) - 1:
        next_state = order[idx + 1]
        return {
            "state": next_state.value,
            "icon": RESONANCE_CONFIG[next_state]["icon"],
            "name": RESONANCE_CONFIG[next_state]["name"],
        }
    return None


def _points_to_next(total: float, current: ResonanceState) -> Optional[float]:
    """Calculate points needed for next state."""
    thresholds = {
        ResonanceState.SPARK: 25,
        ResonanceState.PULSE: 50,
        ResonanceState.BLAZE: 75,
        ResonanceState.RADIANT: 100,
    }
    target = thresholds[current]
    if current == ResonanceState.RADIANT:
        return None
    
    order = [ResonanceState.SPARK, ResonanceState.PULSE, ResonanceState.BLAZE, ResonanceState.RADIANT]
    idx = order.index(current)
    next_threshold = thresholds[order[idx + 1]]
    
    return round(next_threshold - total, 1)


def calculate_user_resonance(
    user_handle: str,
    interaction_count: int = 0,
    they_initiated_count: int = 0,
    successful_tones: int = 0,
    topics_shared: int = 0,
) -> float:
    """Calculate resonance with a specific X user.

    Lightweight version of the full resonance calculator, scoped to
    a single user relationship rather than the whole system.

    Args:
        user_handle: The X handle (for logging/identification).
        interaction_count: Total interactions with this user.
        they_initiated_count: Times they reached out first.
        successful_tones: Number of successful tone matches.
        topics_shared: Number of topics we've engaged on together.

    Returns:
        Resonance score 0-100.
    """
    # Interaction depth (40%)
    interaction_score = min(interaction_count / 20.0, 1.0) * 40

    # Reciprocity (25%) - they initiate too, not just us
    reciprocity = 0.0
    if interaction_count > 0:
        reciprocity = they_initiated_count / interaction_count
    reciprocity_score = reciprocity * 25

    # Tone alignment (20%) - we know what works with them
    tone_score = min(successful_tones / 5.0, 1.0) * 20

    # Topic breadth (15%) - varied conversations
    topic_score = min(topics_shared / 5.0, 1.0) * 15

    return round(
        interaction_score + reciprocity_score + tone_score + topic_score, 1
    )


if __name__ == "__main__":
    display = get_resonance_display()
    print(f"\n{display['icon']} {display['name']} - {display['score']:.0f}% Resonance")
    print(f"   {display['description']}")
    print()
    print("Breakdown:")
    breakdown = display['breakdown']
    print(f"   Insights: {breakdown['insights_score']:.1f}/30")
    print(f"   Surprises: {breakdown['surprises_score']:.1f}/15")
    print(f"   Opinions: {breakdown['opinions_score']:.1f}/20")
    print(f"   Growth: {breakdown['growth_score']:.1f}/15")
    print(f"   Interactions: {breakdown['interactions_score']:.1f}/10")
    print(f"   Validation: {breakdown['validation_score']:.1f}/10")
    
    if display['next_state']:
        print()
        print(f"Next: {display['next_state']['icon']} {display['next_state']['name']} ({display['to_next']:.1f} points to go)")
