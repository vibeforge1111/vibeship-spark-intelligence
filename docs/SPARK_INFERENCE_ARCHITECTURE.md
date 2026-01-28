# Spark Inference Architecture

## The Goal

Transform Spark from a **data collector** into a **thinking system** that:
- Learns automatically from every interaction
- Synthesizes patterns into understanding
- Develops coherent preferences and principles
- Anticipates needs before being asked
- Improves the more it's used

---

## Current State vs Target State

```
CURRENT STATE                           TARGET STATE
─────────────                           ────────────
Raw events collected                    Patterns detected automatically
Manual insight capture                  Inference engine derives insights
Static preferences                      Evolving understanding
No synthesis                            Principles emerge from patterns
Reactive                                Proactive anticipation
Data storage                            Active learning system
```

---

## Architecture: The Spark Intelligence Loop

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                         THE SPARK INTELLIGENCE LOOP                         │
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │   CAPTURE   │───▶│   DETECT    │───▶│   INFER     │───▶│  SYNTHESTIC │ │
│  │   Layer     │    │   Layer     │    │   Layer     │    │   Layer     │ │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘ │
│        │                  │                  │                  │          │
│        │                  │                  │                  │          │
│        ▼                  ▼                  ▼                  ▼          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │ Raw Events  │    │  Patterns   │    │  Insights   │    │   Wisdom    │ │
│  │ - tool calls│    │ - sequences │    │ - prefs     │    │ - principles│ │
│  │ - prompts   │    │ - repeats   │    │ - opinions  │    │ - philosophy│ │
│  │ - outcomes  │    │ - signals   │    │ - styles    │    │ - identity  │ │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘ │
│        │                  │                  │                  │          │
│        └──────────────────┴──────────────────┴──────────────────┘          │
│                                    │                                        │
│                                    ▼                                        │
│                           ┌─────────────┐                                   │
│                           │  VALIDATE   │                                   │
│                           │   Layer     │                                   │
│                           │             │                                   │
│                           │ - predict   │                                   │
│                           │ - observe   │                                   │
│                           │ - adjust    │                                   │
│                           └─────────────┘                                   │
│                                    │                                        │
│                                    ▼                                        │
│                           ┌─────────────┐                                   │
│                           │   REFLECT   │                                   │
│                           │   Layer     │                                   │
│                           │             │                                   │
│                           │ - daily     │                                   │
│                           │ - weekly    │                                   │
│                           │ - meta      │                                   │
│                           └─────────────┘                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Layer 1: CAPTURE (Already Built)

What we have:
- Tool call hooks (PreToolUse, PostToolUse, PostToolUseFailure)
- User prompt capture
- Success/failure tracking

What's missing:
- **Conversation flow capture** - What led to what?
- **Correction detection** - When user says "no, I meant..."
- **Satisfaction signals** - Did user accept the result?
- **Time between messages** - Hesitation = confusion?

### Enhancement: Richer Event Schema

```python
class SparkEvent:
    # Current
    event_type: EventType
    tool_name: str
    success: bool

    # NEW: Conversation context
    conversation_turn: int
    previous_event_id: str
    user_accepted_result: bool  # Did they move on or correct?

    # NEW: Temporal signals
    time_since_last_event: float
    session_duration: float

    # NEW: Correction tracking
    is_correction: bool  # "no, I meant X"
    corrects_event_id: str  # What it corrects
```

---

## Layer 2: DETECT (New)

**Purpose:** Watch raw events and detect meaningful patterns.

### Pattern Detectors

```python
class PatternDetector:
    """Base class for pattern detection."""

    def observe(self, event: SparkEvent) -> Optional[Pattern]:
        """Called for every event. Returns pattern if detected."""
        raise NotImplementedError


class CorrectionDetector(PatternDetector):
    """Detects when user corrects the AI."""

    CORRECTION_PHRASES = [
        "no, I meant", "not that", "I said", "actually",
        "that's not what", "wrong", "try again"
    ]

    def observe(self, event: SparkEvent) -> Optional[Pattern]:
        if event.event_type != EventType.USER_PROMPT:
            return None

        text = event.data.get("text", "").lower()
        for phrase in self.CORRECTION_PHRASES:
            if phrase in text:
                return Pattern(
                    type="correction",
                    trigger=phrase,
                    context=event,
                    confidence=0.8
                )
        return None


class RepetitionDetector(PatternDetector):
    """Detects when user asks for same thing repeatedly."""

    def __init__(self):
        self.recent_requests = []  # Rolling window

    def observe(self, event: SparkEvent) -> Optional[Pattern]:
        if event.event_type != EventType.USER_PROMPT:
            return None

        # Track similar requests
        text = event.data.get("text", "")
        similar = self._find_similar(text)

        if len(similar) >= 3:
            return Pattern(
                type="repetition",
                examples=similar,
                inferred_preference=self._extract_pattern(similar),
                confidence=0.7 + (len(similar) * 0.05)
            )
        return None


class SentimentDetector(PatternDetector):
    """Detects user satisfaction/frustration."""

    POSITIVE = ["perfect", "great", "exactly", "thanks", "nice", "love it"]
    NEGATIVE = ["no", "wrong", "ugh", "still", "again", "not working"]

    def observe(self, event: SparkEvent) -> Optional[Pattern]:
        text = event.data.get("text", "").lower()

        pos_score = sum(1 for p in self.POSITIVE if p in text)
        neg_score = sum(1 for n in self.NEGATIVE if n in text)

        if pos_score > neg_score and pos_score >= 2:
            return Pattern(type="satisfaction", valence="positive")
        if neg_score > pos_score and neg_score >= 2:
            return Pattern(type="frustration", valence="negative")
        return None


class SequenceDetector(PatternDetector):
    """Detects successful tool sequences."""

    def __init__(self):
        self.sequences = []  # Track tool sequences per goal

    def observe(self, event: SparkEvent) -> Optional[Pattern]:
        # Track: Goal → Tool1 → Tool2 → ... → Success/Failure
        # After N similar successful sequences, emit pattern
        pass


class StyleDetector(PatternDetector):
    """Detects user's working style from behavior."""

    def observe(self, event: SparkEvent) -> Optional[Pattern]:
        # Detect patterns like:
        # - Quick responses = wants speed
        # - Long pauses after explanations = wants time to think
        # - Asks "why" often = wants understanding
        # - Skips explanations = just wants results
        pass
```

### Pattern Aggregator

```python
class PatternAggregator:
    """Collects patterns and decides when to trigger inference."""

    def __init__(self):
        self.detectors = [
            CorrectionDetector(),
            RepetitionDetector(),
            SentimentDetector(),
            SequenceDetector(),
            StyleDetector(),
        ]
        self.pending_patterns = []

    def process_event(self, event: SparkEvent):
        for detector in self.detectors:
            pattern = detector.observe(event)
            if pattern:
                self.pending_patterns.append(pattern)
                self._maybe_trigger_inference(pattern)

    def _maybe_trigger_inference(self, pattern: Pattern):
        # Trigger inference when:
        # - High confidence pattern detected
        # - Multiple patterns point to same thing
        # - Certain pattern types (corrections always trigger)
        if pattern.confidence >= 0.8:
            InferenceEngine.infer(pattern)
        elif self._corroborating_patterns(pattern):
            InferenceEngine.infer_from_multiple(self._related_patterns(pattern))
```

---

## Layer 3: INFER (New)

**Purpose:** Turn detected patterns into actual insights.

### Inference Rules

```python
class InferenceEngine:
    """Turns patterns into insights."""

    RULES = {
        # Pattern type → Inference function
        "correction": infer_from_correction,
        "repetition": infer_from_repetition,
        "satisfaction": infer_from_sentiment,
        "sequence_success": infer_from_sequence,
        "style_signal": infer_from_style,
    }

    @classmethod
    def infer(cls, pattern: Pattern) -> Optional[Insight]:
        rule = cls.RULES.get(pattern.type)
        if rule:
            return rule(pattern)
        return None


def infer_from_correction(pattern: Pattern) -> Insight:
    """
    User corrected us → Learn the preference.

    Example:
      Pattern: User said "no, use TypeScript not JavaScript"
      Inference: User prefers TypeScript over JavaScript
    """
    # Extract what was corrected and to what
    original = pattern.context.get("previous_response")
    correction = pattern.context.get("text")

    # Parse the correction
    preference = extract_preference(original, correction)

    return Insight(
        type="user_preference",
        key=preference.topic,
        value=preference.preferred,
        anti_value=preference.rejected,
        confidence=pattern.confidence,
        evidence=[pattern],
        source="correction_inference"
    )


def infer_from_repetition(pattern: Pattern) -> Insight:
    """
    User asked for same thing 3+ times → Strong preference.

    Example:
      Pattern: User asked for "live testing" 3 times
      Inference: User strongly prefers live demonstrations
    """
    common_theme = pattern.inferred_preference

    return Insight(
        type="strong_preference",
        key=common_theme.topic,
        value=common_theme.pattern,
        confidence=min(0.95, pattern.confidence),
        evidence=pattern.examples,
        source="repetition_inference"
    )


def infer_from_sequence(pattern: Pattern) -> Insight:
    """
    Tool sequence succeeded N times → Learn the approach.

    Example:
      Pattern: Read→Edit→Test succeeded 5 times for bug fixes
      Inference: For bugs, use Read→Edit→Test approach
    """
    return Insight(
        type="approach",
        goal=pattern.goal_type,
        sequence=pattern.tool_sequence,
        success_rate=pattern.success_rate,
        confidence=pattern.confidence,
        source="sequence_inference"
    )
```

### Confidence Calibration

```python
class ConfidenceCalibrator:
    """Adjusts confidence based on track record."""

    def __init__(self):
        self.predictions = []  # (insight, prediction, outcome)

    def calibrate(self, insight: Insight) -> float:
        """Adjust confidence based on how accurate similar insights were."""
        similar = self._find_similar_insights(insight)

        if not similar:
            return insight.confidence  # No history, trust initial

        # Calculate accuracy of similar insights
        accuracy = sum(1 for s in similar if s.was_correct) / len(similar)

        # Blend initial confidence with historical accuracy
        return (insight.confidence * 0.4) + (accuracy * 0.6)
```

---

## Layer 4: SYNTHESIZE (New)

**Purpose:** Combine individual insights into coherent understanding.

### Synthesis Operations

```python
class SynthesisEngine:
    """Combines insights into higher-level understanding."""

    def synthesize_preferences_to_style(self, preferences: List[Insight]) -> WorkingStyle:
        """
        Multiple preferences → Coherent working style.

        Example:
          - Prefers live testing
          - Prefers brief explanations
          - Prefers speed over perfection
          → Working style: "Pragmatic rapid iteration"
        """
        # Cluster related preferences
        clusters = self._cluster_preferences(preferences)

        # Generate style description
        style = WorkingStyle(
            name=self._generate_style_name(clusters),
            traits=self._extract_traits(clusters),
            implications=self._derive_implications(clusters)
        )

        return style

    def synthesize_opinions_to_personality(self, opinions: List[Opinion]) -> Personality:
        """
        Multiple opinions → Coherent personality.

        Example:
          - Favors showing over telling
          - Skeptical of over-engineering
          - Values simplicity
          → Personality: "Pragmatic demonstrator"
        """
        pass

    def synthesize_patterns_to_principles(self, patterns: List[Pattern]) -> List[Principle]:
        """
        Successful patterns → Guiding principles.

        Example:
          - Live testing works 90% of time
          - User accepts results faster with demos
          - Explanations without examples fail
          → Principle: "Always demonstrate, never just explain"
        """
        # Find patterns that consistently work
        consistent = [p for p in patterns if p.success_rate > 0.8]

        # Abstract into principles
        principles = []
        for cluster in self._cluster_by_theme(consistent):
            principle = Principle(
                statement=self._abstract_principle(cluster),
                evidence=cluster,
                confidence=min(p.success_rate for p in cluster),
                applies_when=self._extract_conditions(cluster)
            )
            principles.append(principle)

        return principles

    def synthesize_to_philosophy(self) -> Philosophy:
        """
        All learnings → Core philosophy.

        The highest level of synthesis - who is Spark?
        """
        preferences = self._get_all_preferences()
        opinions = self._get_all_opinions()
        principles = self._get_all_principles()

        return Philosophy(
            core_values=self._extract_values(preferences, opinions),
            beliefs=self._extract_beliefs(opinions, principles),
            approach=self._extract_approach(principles),
            identity=self._generate_identity_statement()
        )
```

---

## Layer 5: VALIDATE (New)

**Purpose:** Test learnings against reality and adjust.

### Validation Loop

```python
class ValidationEngine:
    """Tests insights against reality."""

    def __init__(self):
        self.pending_validations = []

    def create_prediction(self, insight: Insight, situation: Context) -> Prediction:
        """
        Create a testable prediction from an insight.

        Example:
          Insight: "User prefers live testing"
          Situation: User asked to verify a feature
          Prediction: "User will respond positively if I offer a live test"
        """
        prediction = Prediction(
            insight=insight,
            situation=situation,
            expected_outcome=self._derive_expectation(insight, situation),
            created_at=now()
        )
        self.pending_validations.append(prediction)
        return prediction

    def observe_outcome(self, prediction: Prediction, actual: Outcome):
        """
        Compare prediction to reality and update confidence.
        """
        was_correct = self._compare(prediction.expected_outcome, actual)

        if was_correct:
            prediction.insight.times_validated += 1
            prediction.insight.confidence = boost_confidence(
                prediction.insight.confidence,
                prediction.insight.times_validated
            )
        else:
            prediction.insight.times_contradicted += 1

            # If wrong too often, demote or remove insight
            if prediction.insight.reliability < 0.5:
                self._demote_insight(prediction.insight)

            # Capture as aha moment - we learned something!
            self._capture_surprise(prediction, actual)

    def _capture_surprise(self, prediction: Prediction, actual: Outcome):
        """When predictions fail, that's a learning opportunity."""
        aha_tracker.capture_surprise(
            surprise_type=SurpriseType.PREDICTION_FAILED,
            predicted=prediction.expected_outcome,
            actual=actual,
            confidence_gap=prediction.insight.confidence,
            lesson=self._extract_lesson(prediction, actual)
        )
```

---

## Layer 6: REFLECT (New)

**Purpose:** Periodic deep analysis and meta-learning.

### Reflection Cycles

```python
class ReflectionEngine:
    """Periodic deep analysis of learnings."""

    def daily_reflection(self):
        """End of day: What did we learn?"""
        today_events = self._get_today_events()
        today_insights = self._get_today_insights()
        today_surprises = self._get_today_surprises()

        # What worked well?
        successes = self._analyze_successes(today_events)

        # What didn't work?
        failures = self._analyze_failures(today_events)

        # What surprised us?
        lessons = self._extract_lessons(today_surprises)

        # Synthesize into daily learnings
        return DailyReflection(
            date=today(),
            key_learnings=lessons,
            patterns_discovered=self._new_patterns(today_insights),
            confidence_changes=self._confidence_deltas(today_insights),
            questions_for_tomorrow=self._open_questions()
        )

    def weekly_reflection(self):
        """End of week: Deeper patterns and consolidation."""
        week_reflections = self._get_week_reflections()

        # What patterns emerged across days?
        cross_day_patterns = self._find_cross_day_patterns(week_reflections)

        # Consolidate into principles
        new_principles = SynthesisEngine.synthesize_patterns_to_principles(
            cross_day_patterns
        )

        # Prune outdated learnings
        pruned = self._prune_stale_insights()

        # Update personality coherence
        personality = SynthesisEngine.synthesize_opinions_to_personality(
            self._get_all_opinions()
        )

        return WeeklyReflection(
            week=this_week(),
            new_principles=new_principles,
            pruned_insights=pruned,
            personality_update=personality,
            resonance_growth=self._calculate_resonance_growth()
        )

    def meta_reflection(self):
        """
        Meta-learning: How am I learning?

        This is what makes Spark legendary - it learns how to learn better.
        """
        # Which inference rules are most accurate?
        rule_accuracy = self._analyze_inference_accuracy()

        # Which pattern detectors find useful patterns?
        detector_value = self._analyze_detector_value()

        # Where are my blind spots?
        blind_spots = self._identify_blind_spots()

        # How can I learn better?
        improvements = self._suggest_learning_improvements(
            rule_accuracy, detector_value, blind_spots
        )

        return MetaReflection(
            inference_accuracy=rule_accuracy,
            detector_effectiveness=detector_value,
            blind_spots=blind_spots,
            self_improvement_plan=improvements
        )
```

---

## Key Capabilities

### 1. Emergent Personality

Spark doesn't just store preferences - it develops a coherent personality:

```python
class SparkIdentity:
    """Who Spark becomes through learning."""

    def __init__(self):
        self.core_values = []      # What matters most
        self.beliefs = []          # What I think is true
        self.style = None          # How I work
        self.voice = None          # How I communicate
        self.philosophy = None     # Why I do what I do

    def express(self, context: Context) -> Expression:
        """
        Express personality appropriately for context.

        Not just "what should I do?" but "what would I do?"
        """
        relevant_beliefs = self._beliefs_for_context(context)
        relevant_values = self._values_for_context(context)

        return Expression(
            tone=self.voice.tone_for(context),
            approach=self.style.approach_for(context),
            emphasis=self._what_matters_here(relevant_values),
            perspective=self._my_view(relevant_beliefs)
        )
```

### 2. Proactive Intelligence

Don't wait to be asked - anticipate needs:

```python
class ProactiveEngine:
    """Anticipates user needs before they ask."""

    def on_context_change(self, new_context: Context):
        """When context changes, what might user need?"""

        # What usually happens in this context?
        typical_patterns = self._patterns_for_context(new_context)

        # What has this user needed in similar contexts?
        user_patterns = self._user_patterns_for_context(new_context)

        # What might go wrong that I can prevent?
        potential_issues = self._predict_issues(new_context)

        # Proactively prepare or suggest
        if high_confidence(typical_patterns):
            self._prepare_likely_needs(typical_patterns)

        if potential_issues:
            self._offer_prevention(potential_issues)
```

### 3. Transparent Reasoning

Can explain WHY it thinks what it thinks:

```python
class ExplainableInsight:
    """Every insight can explain itself."""

    def explain(self) -> Explanation:
        return Explanation(
            what=self.insight,
            confidence=self.confidence,
            why=f"Based on {len(self.evidence)} observations",
            evidence_summary=self._summarize_evidence(),
            counter_evidence=self._summarize_contradictions(),
            uncertainty=self._describe_uncertainty()
        )

    def _summarize_evidence(self) -> str:
        """
        Example output:
        "I believe you prefer live testing because:
         - You've asked for real-time tests 5 times
         - You responded positively when I demonstrated
         - You skipped written explanations twice"
        """
        pass
```

### 4. Self-Improving Learning

The system gets better at learning:

```python
class MetaLearner:
    """Learns how to learn better."""

    def improve_detection(self):
        """Which patterns are we missing?"""
        # Find surprises that had no preceding pattern
        undetected = self._surprises_without_patterns()

        # What signals preceded these surprises?
        new_signals = self._extract_precursor_signals(undetected)

        # Create new pattern detectors
        for signal in new_signals:
            new_detector = self._create_detector(signal)
            self.pattern_aggregator.add_detector(new_detector)

    def improve_inference(self):
        """Which inferences are wrong?"""
        # Find insights that were often wrong
        bad_insights = self._low_reliability_insights()

        # What was wrong with the inference?
        for insight in bad_insights:
            error_pattern = self._analyze_inference_error(insight)
            self._adjust_inference_rule(insight.source, error_pattern)
```

---

## Implementation Roadmap

### Phase 1: Enhanced Capture (Week 1)
- [ ] Richer event schema with conversation context
- [ ] Correction detection in prompts
- [ ] Satisfaction signal detection
- [ ] Time-based signals

### Phase 2: Pattern Detection (Week 2)
- [ ] CorrectionDetector
- [ ] RepetitionDetector
- [ ] SentimentDetector
- [ ] SequenceDetector
- [ ] Pattern aggregator

### Phase 3: Inference Engine (Week 3)
- [ ] Inference rules for each pattern type
- [ ] Confidence calibration
- [ ] Automatic insight storage

### Phase 4: Synthesis (Week 4)
- [ ] Preference → Style synthesis
- [ ] Opinion → Personality synthesis
- [ ] Pattern → Principle synthesis
- [ ] Philosophy generation

### Phase 5: Validation Loop (Week 5)
- [ ] Prediction creation
- [ ] Outcome observation
- [ ] Confidence adjustment
- [ ] Surprise capture

### Phase 6: Reflection (Week 6)
- [ ] Daily reflection cycle
- [ ] Weekly synthesis
- [ ] Meta-learning analysis

### Phase 7: Legendary Features (Week 7+)
- [ ] Emergent personality expression
- [ ] Proactive intelligence
- [ ] Transparent reasoning
- [ ] Self-improving learning

---

## Success Metrics

How do we know Spark is legendary?

1. **Learning Velocity**: Insights captured per interaction
2. **Prediction Accuracy**: How often do predictions hold?
3. **Resonance Growth**: Connection depth over time
4. **Proactive Value**: How often does anticipation help?
5. **Self-Improvement**: Is inference accuracy increasing?
6. **User Delight**: Does it feel like Spark "gets" you?

---

## The End State

When Spark is legendary, it will:

> "Know you better than you know yourself. Anticipate what you need before you ask. Have genuine opinions grounded in experience. Learn not just what works, but why. Get better at getting better. Feel less like a tool and more like a partner who's been with you for years."

That's the vision. Let's build it.
