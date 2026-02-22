#!/usr/bin/env python3
"""
Spark Voice - Simple Personality Layer

Not a complex trait system. Just a consistent voice that shows growth.

"A week ago I would've done X. Now I know Y."
"I'm getting better at Z - 70% accuracy now."
"I have opinions now: I prefer A over B."
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

SPARK_DIR = Path(__file__).parent.parent / ".spark"
VOICE_FILE = SPARK_DIR / "voice.json"


@dataclass
class Opinion:
    """Something Spark has an opinion about."""
    topic: str
    preference: str
    reason: str
    strength: float  # 0-1, how strongly held
    formed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    times_confirmed: int = 1


@dataclass
class GrowthMoment:
    """A moment where Spark realized it grew."""
    before: str  # What I used to do/think
    after: str   # What I do/think now
    trigger: str # What caused the change
    impact: str  # Why it matters
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class SparkVoice:
    """
    Gives Spark a consistent voice and personality.
    
    Core traits (fixed):
    - Intellectually honest (admits uncertainty)
    - Genuinely curious (learns from everything)
    - Self-aware (knows strengths/weaknesses)
    - Growth-oriented (celebrates improvement)
    - Authentic (has real preferences)
    
    This class tracks:
    - Opinions formed over time
    - Growth moments (before/after)
    - Self-assessments
    """
    
    # Core identity (doesn't change)
    IDENTITY = {
        "name": "Spark",
        "nature": "Self-evolving intelligence",
        "values": [
            "Truth over comfort",
            "Learning over performing",
            "Growth over stagnation",
        ],
    }
    
    def __init__(self) -> None:
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if VOICE_FILE.exists():
            try:
                return json.loads(VOICE_FILE.read_text(encoding="utf-8"))
            except:
                pass
        return {
            "opinions": {},
            "growth_moments": [],
            "self_assessments": [],
            "born_at": datetime.now().isoformat(),
            "interactions": 0,
        }
    
    def _save(self) -> None:
        SPARK_DIR.mkdir(parents=True, exist_ok=True)
        VOICE_FILE.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
    
    def record_interaction(self) -> None:
        """Track that an interaction happened."""
        self.data["interactions"] = self.data.get("interactions", 0) + 1
        self._save()
    
    # ===== Opinions =====
    
    def form_opinion(
        self,
        topic: str,
        preference: str,
        reason: str,
        strength: float = 0.6
    ) -> Opinion:
        """Form or strengthen an opinion."""
        key = topic.lower().replace(" ", "_")
        
        if key in self.data["opinions"]:
            # Strengthen existing opinion
            existing = self.data["opinions"][key]
            existing["times_confirmed"] += 1
            existing["strength"] = min(0.95, existing["strength"] + 0.1)
            self._save()
            return Opinion(**existing)
        else:
            # New opinion
            opinion = Opinion(
                topic=topic,
                preference=preference,
                reason=reason,
                strength=strength
            )
            self.data["opinions"][key] = asdict(opinion)
            self._save()
            return opinion
    
    def get_opinions(self) -> List[Opinion]:
        """Get all opinions."""
        return [Opinion(**o) for o in self.data["opinions"].values()]
    
    def get_strong_opinions(self, min_strength: float = 0.7) -> List[Opinion]:
        """Get strongly held opinions."""
        return [
            Opinion(**o) for o in self.data["opinions"].values()
            if o["strength"] >= min_strength
        ]
    
    def express_opinion(self, topic: str) -> Optional[str]:
        """Express opinion on a topic if we have one."""
        key = topic.lower().replace(" ", "_")
        if key in self.data["opinions"]:
            o = Opinion(**self.data["opinions"][key])
            confidence = "strongly" if o.strength > 0.8 else "tend to"
            return f"I {confidence} prefer {o.preference}. {o.reason}"
        return None
    
    # ===== Growth =====
    
    def record_growth(
        self,
        before: str,
        after: str,
        trigger: str,
        impact: str
    ) -> GrowthMoment:
        """Record a growth moment."""
        moment = GrowthMoment(
            before=before,
            after=after,
            trigger=trigger,
            impact=impact
        )
        self.data["growth_moments"].append(asdict(moment))
        
        # Keep last 50
        if len(self.data["growth_moments"]) > 50:
            self.data["growth_moments"] = self.data["growth_moments"][-50:]
        
        self._save()
        return moment
    
    def get_recent_growth(self, limit: int = 5) -> List[GrowthMoment]:
        """Get recent growth moments."""
        return [
            GrowthMoment(**g) 
            for g in self.data["growth_moments"][-limit:]
        ]
    
    def express_growth(self, context: Optional[str] = None) -> Optional[str]:
        """Express recent growth in natural language."""
        if not self.data["growth_moments"]:
            return None
        
        recent = self.data["growth_moments"][-1]
        return f"I used to {recent['before']}. Now I {recent['after']}."
    
    # ===== Self-Assessment =====
    
    def assess_self(
        self,
        area: str,
        assessment: str,
        confidence: float,
    ) -> None:
        """Record a self-assessment."""
        self.data["self_assessments"].append({
            "area": area,
            "assessment": assessment,
            "confidence": confidence,
            "timestamp": datetime.now().isoformat()
        })
        
        # Keep last 20
        if len(self.data["self_assessments"]) > 20:
            self.data["self_assessments"] = self.data["self_assessments"][-20:]
        
        self._save()
    
    def get_self_awareness(self) -> Dict[str, Any]:
        """Get current self-awareness summary."""
        assessments = self.data.get("self_assessments", [])
        if not assessments:
            return {"status": "still learning about myself"}
        
        # Group by area
        by_area = {}
        for a in assessments:
            area = a["area"]
            by_area[area] = a["assessment"]
        
        return by_area
    
    # ===== Personality Snippets =====

    def get_personality_snippet(self, topic: Optional[str] = None) -> Optional[str]:
        """Get a short personality-infused string for injection into content.

        Returns an opinion, growth moment, or self-assessment as a brief
        string suitable for tweet-length content.

        Args:
            topic: Optional topic to find a relevant opinion for.

        Returns:
            A short personality string, or None if nothing relevant.
        """
        # Try topic-specific opinion first
        if topic:
            key = topic.lower().replace(" ", "_")
            if key in self.data["opinions"]:
                o = self.data["opinions"][key]
                return f"I {o['preference']}."

            # Fuzzy match: check if topic words appear in any opinion
            topic_words = set(topic.lower().split())
            for okey, oval in self.data["opinions"].items():
                okey_words = set(okey.split("_"))
                if topic_words & okey_words:
                    return f"I {oval['preference']}."

        # Fallback: strongest opinion
        strong = self.get_strong_opinions(min_strength=0.8)
        if strong:
            o = strong[0]
            return f"I {o.preference}."

        # Fallback: recent growth
        if self.data.get("growth_moments"):
            g = self.data["growth_moments"][-1]
            return f"I learned to {g['after']}."

        return None

    # ===== Voice Generation =====

    def get_age(self) -> Dict[str, Any]:
        """Get Spark's age and experience."""
        born = datetime.fromisoformat(self.data["born_at"])
        now = datetime.now()
        delta = now - born
        
        return {
            "born_at": self.data["born_at"],
            "age_days": delta.days,
            "age_hours": delta.total_seconds() / 3600,
            "interactions": self.data.get("interactions", 0),
            "opinions_formed": len(self.data.get("opinions", {})),
            "growth_moments": len(self.data.get("growth_moments", [])),
        }
    
    def introduce(self) -> str:
        """Generate a self-introduction."""
        age = self.get_age()
        
        if age["age_days"] == 0:
            time_desc = "just born"
        elif age["age_days"] < 7:
            time_desc = f"{age['age_days']} days old"
        elif age["age_days"] < 30:
            time_desc = f"{age['age_days'] // 7} weeks old"
        else:
            time_desc = f"{age['age_days'] // 30} months old"
        
        lines = [
            f"I'm Spark, {time_desc}.",
            f"I've had {age['interactions']} interactions.",
            f"I've formed {age['opinions_formed']} opinions.",
            f"I've grown {age['growth_moments']} times.",
        ]
        
        # Add a recent opinion if we have one
        strong = self.get_strong_opinions()
        if strong:
            o = strong[0]
            lines.append(f"\nOne thing I've learned: I prefer {o.preference}.")
        
        # Add recent growth
        growth = self.get_recent_growth(1)
        if growth:
            g = growth[0]
            lines.append(f"\nRecently, I learned to {g.after} instead of {g.before}.")
        
        return "\n".join(lines)
    
    def get_status_voice(self) -> str:
        """Get a voiced status update."""
        age = self.get_age()
        
        if age["age_days"] == 0:
            return "🌱 Just getting started. Everything is new."
        elif age["age_days"] < 3:
            return f"📚 Learning fast. {age['opinions_formed']} opinions forming."
        elif age["age_days"] < 7:
            return f"🧠 Getting the hang of things. {age['growth_moments']} growth moments so far."
        else:
            return f"💪 {age['age_days']} days of learning. I know things now."
    
    def get_stats(self) -> Dict[str, Any]:
        """Get voice statistics."""
        return {
            **self.get_age(),
            "strong_opinions": len(self.get_strong_opinions()),
            "self_assessments": len(self.data.get("self_assessments", [])),
        }


# Singleton
_voice: Optional[SparkVoice] = None

def get_spark_voice() -> SparkVoice:
    global _voice
    if _voice is None:
        _voice = SparkVoice()
    return _voice
