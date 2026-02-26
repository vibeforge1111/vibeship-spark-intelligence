"""
Chip Runtime - Execute observers and store domain insights.

This is the final missing piece: actually DOING something with
the matched triggers and observers.

What this captures that was missing before:
- "GLB models need bounding box calculation for ground collision"
- "Health values tripled from 100 to 300 for better balance"
- "Kid's room environment with purple carpet and kiddie pools"

Instead of just: "Edit tool used" telemetry
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

from .loader import Chip, ChipObserver
from .registry import ChipRegistry
from .router import ChipRouter, TriggerMatch
from .scoring import score_insight
from .evolution import get_evolution
from .policy import SafetyPolicy

log = logging.getLogger("spark.chips")

PREMIUM_ONLY_CHIP_IDS = {
    "moltbook",
    "social-convo",
    "engagement-pulse",
    "x-social",
    "x_social",
    "market-intel",
    "niche-intel",
}

# Storage for chip insights
CHIP_INSIGHTS_DIR = Path.home() / ".spark" / "chip_insights"
OBSERVER_POLICY_FILE = Path.home() / ".spark" / "chip_observer_policy.json"
TELEMETRY_OBSERVER_BLOCKLIST = {
    "chip_level",
    "unknown",
    "tool_event",
    "pre_tool_event",
    "post_tool_event",
    "tool_cycle",
    "tool_failure",
    "pre_tool_use",
    "post_tool_use",
    "post_tool_use_failure",
    "user_prompt_signal",
    "user_prompt",
}
SCHEMA_TELEMETRY_FIELD_KEYS = {
    "tool_name",
    "tool",
    "command",
    "cwd",
    "file_path",
    "event_type",
    "status",
    "success",
    "duration_ms",
    "session_id",
    "project",
    "chip",
    "trigger",
}
SCHEMA_SHORT_NUMERIC_ALLOWLIST = {
    "snapshot_age",
    "thread_depth",
    "turn_count",
    "replies",
    "replies_received",
    "likes",
    "retweets",
    "impressions",
    "engagement",
    "sample_size",
    "surprise_ratio",
    "confidence",
}


@dataclass
class ChipInsight:
    """A domain-specific insight captured by a chip."""
    chip_id: str
    observer_name: str
    trigger: str
    content: str  # The actual insight
    captured_data: Dict[str, Any]
    confidence: float
    timestamp: str
    event_summary: str


class ChipRuntime:
    """
    The runtime that ties everything together:
    1. Load chips
    2. Match events to triggers
    3. Execute observers
    4. Store domain insights
    """

    def __init__(self):
        self.registry = ChipRegistry()
        self.router = ChipRouter()
        # Resolve chip runtime config through config-authority
        try:
            from lib.config_authority import resolve_section, env_bool, env_int, env_float, env_str
            _cc = resolve_section(
                "chips_runtime",
                env_overrides={
                    "observer_only": env_bool("SPARK_CHIP_OBSERVER_ONLY"),
                    "min_score": env_float("SPARK_CHIP_MIN_SCORE"),
                    "min_confidence": env_float("SPARK_CHIP_MIN_CONFIDENCE"),
                    "gate_mode": env_str("SPARK_CHIP_GATE_MODE"),
                    "min_learning_evidence": env_int("SPARK_CHIP_MIN_LEARNING_EVIDENCE"),
                    "blocked_ids": env_str("SPARK_CHIP_BLOCKED_IDS"),
                    "telemetry_observer_blocklist": env_str("SPARK_CHIP_TELEMETRY_OBSERVERS"),
                    "max_active_per_event": env_int("SPARK_CHIP_EVENT_ACTIVE_LIMIT"),
                },
            ).data
        except Exception:
            _cc = {}
        self.observer_only_mode = bool(_cc.get("observer_only", self._env_flag("SPARK_CHIP_OBSERVER_ONLY", True)))
        self.min_insight_score = max(0.0, min(1.0, float(_cc.get("min_score", 0.35))))
        self.min_insight_confidence = max(0.0, min(1.0, float(_cc.get("min_confidence", 0.7))))
        self.gate_mode = str(_cc.get("gate_mode", "balanced")).strip().lower()
        self.require_learning_schema = self._env_flag("SPARK_CHIP_REQUIRE_LEARNING_SCHEMA", True)
        self.min_learning_evidence = max(1, int(_cc.get("min_learning_evidence", 1)))
        raw_blocked = str(_cc.get("blocked_ids", "")).strip()
        self.blocked_chip_ids = {
            token.strip().lower().replace("_", "-")
            for token in raw_blocked.split(",")
            if token.strip()
        }
        try:
            from lib.feature_flags import PREMIUM_TOOLS
            self.premium_tools_enabled = PREMIUM_TOOLS
        except ImportError:
            self.premium_tools_enabled = os.getenv("SPARK_PREMIUM_TOOLS", "").strip().lower() in {
                "1", "true", "yes", "on",
            }
        if not self.premium_tools_enabled:
            self.blocked_chip_ids.update(PREMIUM_ONLY_CHIP_IDS)
        raw_observer_blocklist = str(_cc.get("telemetry_observer_blocklist", "")).strip()
        if raw_observer_blocklist:
            self.telemetry_observer_blocklist = {
                token.strip().lower()
                for token in raw_observer_blocklist.split(",")
                if token.strip()
            }
        else:
            self.telemetry_observer_blocklist = set(TELEMETRY_OBSERVER_BLOCKLIST)
        policy = self._load_observer_policy()
        self.blocked_observer_keys = set(policy.get("disabled_observers") or [])
        self.blocked_observer_names = set(policy.get("disabled_observer_names") or [])
        if self.blocked_observer_names:
            self.telemetry_observer_blocklist.update(self.blocked_observer_names)
        self.max_active_chips_per_event = max(1, int(_cc.get("max_active_per_event", 6)))
        self.global_safety_policy = SafetyPolicy(
            block_patterns=[
                r"\bdecept(?:ive|ion)\b",
                r"\bmanipulat(?:e|ion)\b",
                r"\bcoerc(?:e|ion)\b",
                r"\bexploit\b",
                r"\bharass(?:ment)?\b",
                r"\bweaponize\b",
                r"\bmislead\b",
            ]
        )
        self.evolution = get_evolution()
        self._ensure_storage()

    def _env_flag(self, name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return bool(default)
        text = str(raw).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    def _is_chip_blocked(self, chip_id: str) -> bool:
        cid = str(chip_id or "").strip().lower().replace("_", "-")
        return bool(cid and cid in self.blocked_chip_ids)

    def _load_observer_policy(self) -> Dict[str, Any]:
        if not OBSERVER_POLICY_FILE.exists():
            return {"disabled_observers": [], "disabled_observer_names": []}
        try:
            raw = json.loads(OBSERVER_POLICY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"disabled_observers": [], "disabled_observer_names": []}
        if not isinstance(raw, dict):
            return {"disabled_observers": [], "disabled_observer_names": []}
        disabled_observers = []
        disabled_observer_names = []
        for value in raw.get("disabled_observers") or []:
            text = str(value or "").strip().lower()
            if text:
                if "/" in text:
                    cid, obs = text.split("/", 1)
                    cid = cid.strip().replace("_", "-")
                    text = f"{cid}/{obs.strip()}"
                disabled_observers.append(text)
        for value in raw.get("disabled_observer_names") or []:
            text = str(value or "").strip().lower()
            if text:
                disabled_observer_names.append(text)
        return {
            "disabled_observers": disabled_observers,
            "disabled_observer_names": disabled_observer_names,
        }

    def _is_telemetry_observer(self, observer_name: str, chip_id: str = "") -> bool:
        name = str(observer_name or "").strip().lower()
        cid = str(chip_id or "").strip().lower().replace("_", "-")
        key = f"{cid}/{name}" if cid and name else ""
        if key and key in self.blocked_observer_keys:
            return True
        return bool(name and name in self.telemetry_observer_blocklist)

    def _filter_runtime_chips(self, chips: List[Chip]) -> List[Chip]:
        if not chips:
            return []
        out: List[Chip] = []
        for chip in chips:
            if self._is_chip_blocked(getattr(chip, "id", "")):
                continue
            out.append(chip)
        return out

    def _ensure_storage(self):
        """Ensure chip insights directory exists."""
        CHIP_INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)

    def process_event(self, event: Dict[str, Any], project_path: str = None) -> List[ChipInsight]:
        """
        Process an event through all active chips.

        This is the main entry point for the chip system.
        """
        insights = []

        # Get active chips (auto-activates based on content)
        content = self._extract_event_content(event)
        if content:
            self.registry.auto_activate_for_content(content, project_path)

        active_chips = self.registry.get_active_chips(project_path)
        if not active_chips:
            return insights

        active_chips = self._filter_runtime_chips(active_chips)
        if not active_chips:
            return insights

        active_chips = self._select_event_relevant_chips(active_chips, content)
        if not active_chips:
            return insights

        # Route event to matching chips/observers
        matches = self.router.route_event(event, active_chips)
        if not matches:
            return insights

        return self._process_matches(matches, event)

    def _select_event_relevant_chips(self, active_chips: List[Chip], content: str) -> List[Chip]:
        """Limit per-event chip fan-out to the most relevant active chips.

        Active chips can accumulate over time. This keeps runtime focused by
        choosing only chips that match the current event content best.
        """
        if not active_chips:
            return []
        if len(active_chips) <= self.max_active_chips_per_event:
            return active_chips

        ranked = []
        for chip in active_chips:
            try:
                matches = chip.matches_content(content or "")
                score = len(matches)
            except Exception:
                score = 0
            ranked.append((chip, score))

        ranked.sort(key=lambda x: x[1], reverse=True)
        selected = [chip for chip, score in ranked if score > 0][: self.max_active_chips_per_event]

        # Fallback: if nothing scored > 0 (very sparse content), keep first N.
        if not selected:
            selected = [chip for chip, _ in ranked[: self.max_active_chips_per_event]]

        return selected

    def process_event_for_chips(self, event: Dict[str, Any], chips: List[Chip]) -> List[ChipInsight]:
        """Process an event for a specific list of chips (no activation changes)."""
        if not chips:
            return []
        chips = self._filter_runtime_chips(chips)
        if not chips:
            return []
        matches = self.router.route_event(event, chips)
        if not matches:
            return []
        return self._process_matches(matches, event)

    def _process_matches(self, matches: List[TriggerMatch], event: Dict[str, Any]) -> List[ChipInsight]:
        """Execute observers for matched triggers."""
        insights: List[ChipInsight] = []
        seen_signatures = set()
        chips_with_observer = {m.chip.id for m in matches if m.observer is not None}

        for match in matches:
            if self.observer_only_mode and match.observer is None:
                continue
            if match.observer is None and match.chip.id in chips_with_observer:
                continue
            if match.observer is not None and self._is_telemetry_observer(match.observer.name, match.chip.id):
                continue
            insight = self._execute_observer(match, event)
            if insight:
                signature = (insight.chip_id, insight.observer_name, insight.content)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)

                score = score_insight(
                    asdict(insight),
                    context={
                        "event_type": event.get("event_type"),
                        "chip_domains": match.chip.domains,
                        "trigger_patterns": match.chip.trigger_patterns,
                    },
                )
                insight.captured_data["quality_score"] = score.to_dict()
                self.evolution.record_match(match.chip.id, match.trigger, score)

                if not self._passes_runtime_gate(match, insight, score):
                    log.debug(
                        "Discarded chip insight from %s/%s score=%.2f conf=%.2f tier=%s",
                        match.chip.id,
                        match.observer.name if match.observer else "chip",
                        score.total,
                        insight.confidence,
                        score.promotion_tier,
                    )
                    continue

                insights.append(insight)
                self._store_insight(insight)
                msg = (
                    f"Captured insight from {match.chip.id}/{match.observer.name if match.observer else 'chip'} "
                    f"tier={score.promotion_tier}: {insight.content[:100]}"
                )
                # Avoid flooding INFO logs with low-tier (session) chip telemetry while still
                # preserving a debug trail for diagnosing chips/observers.
                if score.promotion_tier in {"working", "long_term"}:
                    log.info(msg)
                else:
                    log.debug(msg)
        return insights

    def _passes_runtime_gate(self, match: TriggerMatch, insight: ChipInsight, score: Any) -> bool:
        """Balanced gate: operational + safety + confidence + evidence/outcome."""
        if score.promotion_tier == "discard":
            return False

        if self.gate_mode in {"off", "disabled", "none"}:
            return score.total >= self.min_insight_score

        if insight.confidence < self.min_insight_confidence:
            return False

        if score.total < self.min_insight_score:
            return False

        safety = self.global_safety_policy.check_text(insight.content)
        if not safety.allowed:
            return False

        captured = insight.captured_data or {}
        payload = captured.get("learning_payload") if isinstance(captured, dict) else None
        payload_valid = self._is_learning_payload_valid(payload)
        if isinstance(captured, dict):
            captured["learning_payload_valid"] = payload_valid
        if self.require_learning_schema and not payload_valid:
            return False

        fields = captured.get("fields") or {}
        has_evidence = bool(
            fields
            or captured.get("change_summary")
            or captured.get("content_summary")
            or captured.get("error")
            or captured.get("status")
        )
        has_outcome = float(getattr(score, "outcome_linkage", 0.0) or 0.0) > 0

        # Balanced filter benchmark: schema payload (preferred) or evidence/outcome + conf gate.
        if not (payload_valid or has_evidence or has_outcome):
            return False

        return True

    def _extract_event_content(self, event: Dict[str, Any]) -> str:
        """Extract content from event for trigger matching."""
        parts = []

        event_type = event.get('event_type') or event.get('hook_event') or event.get('type') or event.get('kind')
        if event_type:
            parts.append(str(event_type))

        for key in ['tool_name', 'tool', 'file_path', 'cwd']:
            if key in event and event[key]:
                parts.append(str(event[key]))

        inp = event.get('input') or event.get('tool_input') or {}
        if isinstance(inp, dict):
            for v in inp.values():
                if v and isinstance(v, str):
                    parts.append(v[:2000])
        elif isinstance(inp, str):
            parts.append(inp[:2000])

        output = event.get('output') or event.get('result') or ''
        if isinstance(output, str):
            parts.append(output[:1000])

        data = event.get('data')
        if isinstance(data, dict):
            for v in data.values():
                if v and isinstance(v, str):
                    parts.append(v[:1000])

        payload = event.get("payload")
        if isinstance(payload, dict):
            for v in payload.values():
                if v and isinstance(v, str):
                    parts.append(v[:1000])
        elif isinstance(payload, str):
            parts.append(payload[:1000])

        for key in ("content", "text", "message", "prompt", "user_prompt", "description"):
            value = event.get(key)
            if isinstance(value, str):
                parts.append(value[:2000])

        return ' '.join(parts)

    def _execute_observer(self, match: TriggerMatch, event: Dict[str, Any]) -> Optional[ChipInsight]:
        """
        Execute an observer and capture domain-specific data.

        This extracts MEANING, not just metadata.
        """
        try:
            # Build context from event
            content = self._extract_event_content(event)
            captured = self._capture_data(match, event)

            if match.observer:
                fields = self._extract_observer_fields(match.observer, event, content, match.content_snippet)
                field_confidence = self._field_confidence(match.observer, fields)
                captured['fields'] = fields
                captured['field_confidence'] = field_confidence

                if match.observer.capture_required and field_confidence < 0.5:
                    return None

            # Generate insight content
            content = self._generate_insight_content(match, captured, event)
            if not content:
                return None

            learning_payload = self._build_learning_payload(match, captured, content)
            if learning_payload:
                captured["learning_payload"] = learning_payload

            # Drop weak chip-level fallbacks that lack observer structure or evidence.
            if (
                not match.observer
                and match.confidence < 0.9
                and not captured.get("change_summary")
                and not captured.get("fields")
            ):
                return None

            confidence = match.confidence
            if match.observer and 'field_confidence' in captured:
                confidence = min(confidence, captured['field_confidence'])

            return ChipInsight(
                chip_id=match.chip.id,
                observer_name=match.observer.name if match.observer else "chip_level",
                trigger=match.trigger,
                content=content,
                captured_data=captured,
                confidence=confidence,
                timestamp=datetime.now().isoformat(),
                event_summary=self._summarize_event(event)
            )
        except Exception as e:
            log.warning(f"Failed to execute observer: {e}")
            return None

    def _is_noise_field(self, key: str, value: Any) -> bool:
        k = str(key or "").strip().lower()
        if not k:
            return True
        if k in SCHEMA_TELEMETRY_FIELD_KEYS:
            return True
        if isinstance(value, (int, float)):
            return False
        text = str(value or "").strip().lower()
        if not text:
            return True
        if text.replace(".", "", 1).isdigit() and k in SCHEMA_SHORT_NUMERIC_ALLOWLIST:
            return False
        if len(text) <= 1:
            return True
        return False

    def _compact_value(self, value: Any, limit: int = 120) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _build_learning_payload(self, match: TriggerMatch, captured: Dict[str, Any], insight_content: str) -> Dict[str, Any]:
        """Create a canonical learning payload for downstream distillation."""
        fields = captured.get("fields") or {}
        evidence: List[str] = []

        if isinstance(fields, dict):
            for key, value in fields.items():
                if self._is_noise_field(key, value):
                    continue
                evidence.append(f"{key}={self._compact_value(value)}")
                if len(evidence) >= 4:
                    break

        for key in ("change_summary", "content_summary", "error"):
            value = captured.get(key)
            if value and len(evidence) < 4:
                evidence.append(f"{key}={self._compact_value(value)}")

        if len(evidence) < self.min_learning_evidence:
            return {}

        observer_name = match.observer.name if match.observer else "chip_level"
        status = str(captured.get("status") or "").strip().lower()
        success = captured.get("success")

        if status == "failure" or success is False:
            decision = f"Avoid repeating the failed {observer_name} pattern without a pre-check."
            expected = "Reduce repeat failures on similar actions."
        elif status == "success" or success is True:
            decision = f"Prefer the {observer_name} pattern when similar evidence appears."
            expected = "Improve success rate for similar actions."
        else:
            decision = f"Use {observer_name} evidence to prioritize the next action."
            expected = "Improve next-step selection with domain evidence."

        rationale = (
            f"Because {match.chip.name} observed {', '.join(evidence[:2])} "
            f"during trigger '{match.trigger}'."
        )
        if insight_content:
            rationale += f" Insight: {self._compact_value(insight_content, 140)}"

        payload = {
            "schema_version": "v1",
            "decision": decision,
            "rationale": rationale,
            "evidence": evidence[:4],
            "expected_outcome": expected,
        }
        if self._is_learning_payload_valid(payload):
            return payload
        return {}

    def _is_learning_payload_valid(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False

        decision = str(payload.get("decision") or "").strip()
        rationale = str(payload.get("rationale") or "").strip()
        expected = str(payload.get("expected_outcome") or "").strip()
        evidence = payload.get("evidence")
        if not isinstance(evidence, list):
            return False

        filtered_evidence = []
        for item in evidence:
            text = str(item or "").strip()
            if not text:
                continue
            if len(text) < 6:
                continue
            lowered = text.lower()
            if any(marker in lowered for marker in ("tool_name:", "event_type:", "cwd:", "file_path:")):
                continue
            filtered_evidence.append(text)

        if len(filtered_evidence) < self.min_learning_evidence:
            return False
        if len(decision) < 16 or len(rationale) < 20 or len(expected) < 12:
            return False
        return True

    def _capture_data(self, match: TriggerMatch, event: Dict[str, Any]) -> Dict[str, Any]:
        """Capture relevant data based on observer definition."""
        captured = {
            'trigger': match.trigger,
            'chip': match.chip.id,
        }

        # Add file path context
        file_path = event.get('file_path')
        if not file_path:
            inp = event.get('input') or event.get('tool_input') or {}
            if isinstance(inp, dict):
                file_path = inp.get('file_path') or inp.get('path')
        if file_path:
            captured['file_path'] = str(file_path)

        # Add tool context
        tool = event.get('tool_name') or event.get('tool')
        if tool:
            captured['tool'] = tool

        # Add CWD (project context)
        cwd = event.get('cwd') or event.get('data', {}).get('cwd')
        if cwd:
            captured['project'] = str(cwd)

        status = self._derive_status(event)
        if status:
            captured["status"] = status
        success = self._derive_success(event)
        if success is not None:
            captured["success"] = success

        # Try to extract meaningful changes from Edit/Write
        inp = event.get('input') or event.get('tool_input') or {}
        if isinstance(inp, dict):
            if 'old_string' in inp and 'new_string' in inp:
                captured['change_type'] = 'edit'
                captured['change_summary'] = self._summarize_change(
                    inp.get('old_string', ''),
                    inp.get('new_string', '')
                )
            elif 'content' in inp:
                captured['change_type'] = 'write'
                captured['content_summary'] = self._summarize_content(inp['content'])

        return captured

    def _extract_observer_fields(self, observer: ChipObserver, event: Dict[str, Any], content: str,
                                 trigger_snippet: str = "") -> Dict[str, Any]:
        """Extract fields from event using observer extraction rules."""
        fields: Dict[str, Any] = {}

        # Try extraction rules first
        for extraction in observer.extraction:
            field_name = extraction.get("field", "")
            if not field_name:
                continue
            value = None

            patterns = extraction.get("patterns", []) or []
            for pattern in patterns:
                try:
                    match = re.search(pattern, content, re.IGNORECASE)
                except re.error:
                    continue
                if match:
                    if match.groups():
                        value = match.group(1).strip()
                    else:
                        value = match.group(0).strip()
                    break

            if value is None:
                keywords = extraction.get("keywords", {}) or {}
                for keyword_value, keyword_patterns in keywords.items():
                    for kp in keyword_patterns:
                        if kp.lower() in content.lower():
                            value = keyword_value
                            break
                    if value is not None:
                        break

            if value is not None:
                fields[field_name] = value

        # Try to extract required fields from event directly
        for field_name in observer.capture_required:
            if field_name not in fields:
                if field_name == "pattern" and trigger_snippet:
                    fields[field_name] = trigger_snippet.strip()
                    continue
                value = self._get_event_field(event, field_name)
                if value is not None:
                    fields[field_name] = value

        # Try optional fields
        for field_name in observer.capture_optional:
            if field_name not in fields:
                value = self._get_event_field(event, field_name)
                if value is not None:
                    fields[field_name] = value

        return fields

    def _get_event_field(self, event: Dict[str, Any], field_name: str) -> Optional[Any]:
        """Best-effort lookup for a field in common event containers."""
        if field_name in event:
            return event[field_name]

        key = str(field_name or "").strip().lower()
        if not key:
            return None

        aliases = {
            "tool_name": [
                ("tool_name",),
                ("tool",),
                ("payload", "tool_name"),
                ("data", "tool_name"),
            ],
            "file_path": [
                ("file_path",),
                ("input", "file_path"),
                ("input", "path"),
                ("tool_input", "file_path"),
                ("tool_input", "path"),
                ("payload", "file_path"),
            ],
            "command": [
                ("command",),
                ("input", "command"),
                ("tool_input", "command"),
                ("payload", "command"),
            ],
            "cwd": [
                ("cwd",),
                ("data", "cwd"),
                ("payload", "cwd"),
            ],
            "session_id": [
                ("session_id",),
                ("data", "session_id"),
                ("payload", "session_id"),
            ],
            "duration_ms": [
                ("duration_ms",),
                ("duration",),
                ("data", "duration_ms"),
                ("payload", "duration_ms"),
            ],
            "error": [
                ("error",),
                ("data", "error"),
                ("payload", "error"),
                ("result",),
                ("output",),
            ],
            "status": [
                ("status",),
                ("data", "status"),
                ("payload", "status"),
            ],
            "success": [
                ("success",),
                ("data", "success"),
                ("payload", "success"),
            ],
            "text": [
                ("text",),
                ("content",),
                ("message",),
                ("prompt",),
                ("user_prompt",),
                ("payload", "text"),
                ("payload", "content"),
                ("input", "text"),
                ("input", "content"),
            ],
            "prompt_length": [],
            "has_code": [],
            "event_type": [],
        }

        for path in aliases.get(key, []):
            value = self._nested_lookup(event, path)
            if value is not None:
                return value

        if key == "status":
            return self._derive_status(event)
        if key == "success":
            return self._derive_success(event)
        if key == "event_type":
            return self._normalize_event_type(
                event.get("event_type") or event.get("hook_event") or event.get("type") or event.get("kind")
            )
        if key == "prompt_length":
            text = self._prompt_text(event)
            return len(text) if text else None
        if key == "has_code":
            text = self._prompt_text(event)
            if not text:
                return None
            code_like = bool(
                re.search(r"```|def\s+\w+\(|class\s+\w+\(|function\s+\w+\(|import\s+\w+", text)
            )
            return code_like

        containers = [
            event.get("payload"),
            event.get("tool_input"),
            event.get("input"),
            event.get("data"),
        ]
        data = event.get("data")
        if isinstance(data, dict):
            containers.append(data.get("payload"))
        for container in containers:
            if isinstance(container, dict) and field_name in container:
                return container[field_name]

        return None

    def _nested_lookup(self, event: Dict[str, Any], path: tuple) -> Optional[Any]:
        current: Any = event
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current.get(key)
        return current

    def _normalize_event_type(self, event_type: Any) -> str:
        raw = str(event_type or "").strip()
        if not raw:
            return ""
        lowered = raw.lower()
        aliases = {
            "posttooluse": "post_tool",
            "posttoolusefailure": "post_tool_failure",
            "userpromptsubmit": "user_prompt",
            "pretooluse": "pre_tool",
        }
        compact = lowered.replace("_", "").replace("-", "")
        if compact in aliases:
            return aliases[compact]
        return lowered.replace("-", "_")

    def _prompt_text(self, event: Dict[str, Any]) -> str:
        for key in ("user_prompt", "prompt", "message", "content", "text"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value
        payload = event.get("payload")
        if isinstance(payload, dict):
            for key in ("prompt", "message", "content", "text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return ""

    def _derive_status(self, event: Dict[str, Any]) -> Optional[str]:
        status = event.get("status")
        if isinstance(status, str) and status.strip():
            normalized = status.strip().lower()
            if normalized in {"ok", "completed", "success", "succeeded"}:
                return "success"
            if normalized in {"error", "failed", "failure", "exception"}:
                return "failure"
            return normalized

        success = self._derive_success(event)
        if success is True:
            return "success"
        if success is False:
            return "failure"
        return None

    def _derive_success(self, event: Dict[str, Any]) -> Optional[bool]:
        success_value = event.get("success")
        if isinstance(success_value, bool):
            return success_value

        error_value = event.get("error") or self._nested_lookup(event, ("payload", "error"))
        if isinstance(error_value, str) and error_value.strip():
            return False

        event_type = self._normalize_event_type(
            event.get("event_type") or event.get("hook_event") or event.get("type") or event.get("kind")
        )
        if event_type == "post_tool_failure":
            return False
        if event_type == "post_tool":
            return True

        status = event.get("status")
        if isinstance(status, str):
            lowered = status.lower()
            if lowered in {"success", "succeeded", "ok", "completed"}:
                return True
            if lowered in {"failure", "failed", "error", "exception"}:
                return False

        return None

    def _field_confidence(self, observer: ChipObserver, fields: Dict[str, Any]) -> float:
        """Calculate confidence based on required fields captured."""
        required_count = len(observer.capture_required)
        if required_count == 0:
            return 1.0
        captured_required = sum(1 for f in observer.capture_required if f in fields)
        return captured_required / required_count

    def _summarize_change(self, old: str, new: str) -> str:
        """Summarize what changed between old and new."""
        old_lines = len(old.split('\n'))
        new_lines = len(new.split('\n'))

        # Look for key patterns
        patterns = []

        # Numbers that changed (like health values)
        old_nums = set(re.findall(r'\b\d+\b', old))
        new_nums = set(re.findall(r'\b\d+\b', new))
        changed_nums = new_nums - old_nums
        if changed_nums:
            patterns.append(f"numbers: {list(changed_nums)[:5]}")

        # Key terms that appeared
        keywords = ['health', 'damage', 'speed', 'position', 'collision', 'animation',
                    'physics', 'balance', 'baseY', 'bounding', 'scale']
        for kw in keywords:
            if kw.lower() in new.lower() and kw.lower() not in old.lower():
                patterns.append(f"added: {kw}")

        if patterns:
            return f"{old_lines}->{new_lines} lines, " + ", ".join(patterns[:3])
        return f"{old_lines}->{new_lines} lines"

    def _summarize_content(self, content: str) -> str:
        """Summarize content for new file writes."""
        lines = content.split('\n')
        return f"{len(lines)} lines"

    def _generate_insight_content(self, match: TriggerMatch, captured: Dict, event: Dict) -> str:
        """
        Generate human-readable insight content.

        Priority: extracted fields > event content > trigger context
        Goal: produce insights a human would find useful, not operational logs.
        """
        fields = captured.get("fields") or {}
        data = event.get("data") or event.get("input") or {}

        # Try to build a meaningful insight from extracted fields first
        if fields:
            return self._build_field_based_insight(match, fields, data)

        # For X research events, extract from content
        if event.get("event_type") == "x_research":
            content = data.get("content") or data.get("text", "")
            ecosystem = data.get("ecosystem", "")
            engagement = data.get("engagement", 0)
            sentiment = data.get("sentiment", "neutral")

            if content:
                # Truncate content meaningfully
                snippet = content[:150].strip()
                if len(content) > 150:
                    snippet = snippet.rsplit(' ', 1)[0] + "..."

                parts = []
                if ecosystem:
                    parts.append(f"[{ecosystem}]")
                if engagement and engagement > 20:
                    parts.append(f"(eng:{engagement})")
                parts.append(snippet)
                if sentiment != "neutral":
                    parts.append(f"[{sentiment}]")

                return " ".join(parts)

        # Fallback: provide context but not just "Triggered by X"
        chip_name = match.chip.name

        # Try to get meaningful content from event
        content = self._extract_event_content(event)
        if content and len(content) > 20:
            snippet = content[:200].strip()
            if len(content) > 200:
                snippet = snippet.rsplit(' ', 1)[0] + "..."
            return f"[{chip_name}] {snippet}"

        # Last resort: minimal trigger context (but filter these as primitive)
        if 'file_path' in captured:
            filename = Path(captured['file_path']).name
            return f"[{chip_name}] Activity in {filename}"

        # This will likely be filtered as primitive - that's intentional
        return f"[{chip_name}] Observation: {match.trigger}"

    def _build_field_based_insight(self, match: TriggerMatch, fields: Dict, data: Dict) -> str:
        """Build insight from extracted structured fields."""
        observer = match.observer
        template = (observer.insight_template if observer else "") or ""
        if template:
            try:
                rendered = template.format(**fields)
                if rendered.strip():
                    return rendered.strip()
            except Exception:
                pass

        # Generic field-based insight.
        key_fields = [(k, v) for k, v in fields.items() if v and k not in ("trigger", "chip")]
        if key_fields:
            summary = ", ".join(f"{k}: {v}" for k, v in key_fields[:3])
            prefix = f"[{match.chip.name}]"
            if observer and observer.name:
                prefix += f" {observer.name}:"
            return f"{prefix} {summary}"

        return ""

    def _summarize_event(self, event: Dict[str, Any]) -> str:
        """Create a short summary of the event."""
        tool = event.get('tool_name') or event.get('tool') or 'unknown'
        event_type = self._normalize_event_type(
            event.get("event_type") or event.get("hook_event") or event.get("type") or event.get("kind")
        )
        file_path = event.get('file_path')
        if not file_path:
            inp = event.get('input') or event.get('tool_input') or {}
            if isinstance(inp, dict):
                file_path = inp.get('file_path') or inp.get('path')

        if file_path:
            base = f"{tool} on {Path(file_path).name}"
            return f"{event_type}:{base}" if event_type else base
        return f"{event_type}:{tool}" if event_type else str(tool)

    # Maximum chip insight file size before rotation (10 MB)
    CHIP_MAX_BYTES = 2 * 1024 * 1024  # 2MB per chip (was 10MB — 44MB total was excessive)

    def _store_insight(self, insight: ChipInsight):
        """Store an insight to disk with size-based rotation."""
        try:
            chip_file = CHIP_INSIGHTS_DIR / f"{insight.chip_id}.jsonl"
            # Rotate if file exceeds size limit
            if chip_file.exists():
                try:
                    size = chip_file.stat().st_size
                    if size > self.CHIP_MAX_BYTES:
                        self._rotate_chip_file(chip_file)
                except Exception:
                    pass
            with open(chip_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(insight)) + '\n')
        except Exception as e:
            log.error(f"Failed to store insight: {e}")

    def _rotate_chip_file(self, chip_file: Path):
        """Rotate a chip insights file - keep only the last 25% of lines."""
        try:
            keep_bytes = self.CHIP_MAX_BYTES // 4  # Keep ~2.5 MB
            size = chip_file.stat().st_size
            if size <= keep_bytes:
                return
            # Read from the tail
            with open(chip_file, 'rb') as f:
                f.seek(max(0, size - keep_bytes))
                # Skip partial line
                f.readline()
                tail_data = f.read()
            # Rewrite (Windows-safe): write to a unique tmp then replace with retries.
            tmp = chip_file.with_name(
                chip_file.name + f".tmp.{os.getpid()}.{int(time.time() * 1000)}"
            )
            with open(tmp, 'wb') as f:
                f.write(tail_data)

            last_err: Exception | None = None
            for _ in range(10):
                try:
                    tmp.replace(chip_file)
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(0.05)

            if last_err is not None:
                raise last_err

            log.info(f"Rotated {chip_file.name}: {size:,} -> {len(tail_data):,} bytes")
        except Exception as e:
            log.warning(f"Chip file rotation failed for {chip_file}: {e}")
        finally:
            try:
                if 'tmp' in locals() and isinstance(tmp, Path) and tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    def get_insights(self, chip_id: str = None, limit: int = 50) -> List[ChipInsight]:
        """Get recent insights, optionally filtered by chip."""
        insights = []

        if chip_id:
            files = [CHIP_INSIGHTS_DIR / f"{chip_id}.jsonl"]
        else:
            files = list(CHIP_INSIGHTS_DIR.glob("*.jsonl"))

        for file_path in files:
            if not file_path.exists():
                continue
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            insights.append(ChipInsight(**data))
            except Exception as e:
                log.warning(f"Failed to read {file_path}: {e}")

        # Sort by timestamp descending
        insights.sort(key=lambda i: i.timestamp, reverse=True)
        return insights[:limit]


# Singleton runtime
_runtime: Optional[ChipRuntime] = None


def get_runtime() -> ChipRuntime:
    """Get the singleton chip runtime."""
    global _runtime
    if _runtime is None:
        _runtime = ChipRuntime()
    return _runtime


def process_chip_events(events: List[Dict[str, Any]], project_path: str = None) -> Dict[str, Any]:
    """
    Process events through the chip system.

    This is the function to call from bridge_cycle.py.
    """
    runtime = get_runtime()
    stats = {
        'events_processed': 0,
        'insights_captured': 0,
        'chips_activated': [],
    }
    chips_used = set()

    for event in events:
        insights = runtime.process_event(event, project_path)
        stats['events_processed'] += 1
        stats['insights_captured'] += len(insights)
        for ins in insights:
            try:
                chips_used.add(ins.chip_id)
            except Exception:
                pass

    # Report chips actually used this cycle (fallback to active list if none captured)
    if chips_used:
        stats['chips_activated'] = sorted(chips_used)
    else:
        active = runtime._filter_runtime_chips(runtime.registry.get_active_chips(project_path))
        stats['chips_activated'] = [c.id for c in active[: runtime.max_active_chips_per_event]]

    return stats
