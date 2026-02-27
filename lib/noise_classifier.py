"""Unified noise classifier with optional shadow telemetry.

Default behavior is shadow-only. Existing module-specific filters remain
authoritative unless SPARK_NOISE_CLASSIFIER_ENFORCE is enabled.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

from .noise_patterns import is_common_noise, is_session_boilerplate
from .primitive_filter import is_primitive_text

SHADOW_LOG = Path.home() / ".spark" / "noise_classifier_shadow.jsonl"


@dataclass(frozen=True)
class NoiseDecision:
    is_noise: bool
    rule: str


_CONVERSATIONAL_STARTS: Tuple[str, ...] = (
    "do you think",
    "can you ",
    "let's ",
    "lets ",
    "by the way",
    "i think we",
    "what about",
    "how about",
)

_CODE_BLOCK_RE = re.compile(
    r"(^\s{4,}(if |for |def |class |return |import |from |try:|except|raise )|"
    r"^[A-Z][A-Z_]+\s*=\s*\S+)",
    re.IGNORECASE | re.MULTILINE,
)
_XML_RE = re.compile(r"<task-notification>|<task-id>|<output-file>|<status>|<summary>", re.I)
_MARKDOWN_HEADER_RE = re.compile(r"^#{1,4}\s+", re.M)
_TOOL_USAGE_RE = re.compile(r"\bheavy\s+\w+\s+usage\b|\busage\s*\(\d+\s*calls?\)", re.I)
_WORKFLOW_EXEC_RE = re.compile(r"^workflow execution\s+\d{1,2}/\d{1,2}/\d{4}", re.I)
_TOOL_CHAIN_RE = re.compile(r"\b\w+\s*(?:->|→)\s*\w+\b", re.I)
_SHORT_METRIC_RE = re.compile(r"^\d+%?\s+(success|failure|error)\b", re.I)
_QUESTION_START_RE = re.compile(
    r"^\s*(what|why|how|when|where|who)\b|"
    r"^\s*(do|does|did|should|would|could|can|is|are|am)\s+(we|you|i|they|it|this|that)\b",
    re.I,
)


def enforce_enabled() -> bool:
    raw = str(os.getenv("SPARK_NOISE_CLASSIFIER_ENFORCE", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def classify(text: str | None, *, context: str = "generic") -> NoiseDecision:
    sample = str(text or "").strip()
    if not sample:
        return NoiseDecision(True, "empty")

    lower = sample.lower()

    if is_session_boilerplate(sample):
        return NoiseDecision(True, "session_boilerplate")
    if is_primitive_text(sample):
        return NoiseDecision(True, "primitive_pattern")
    if is_common_noise(sample):
        return NoiseDecision(True, "common_noise")
    if _XML_RE.search(sample):
        return NoiseDecision(True, "xml_telemetry")
    if _WORKFLOW_EXEC_RE.search(lower):
        return NoiseDecision(True, "workflow_execution_telemetry")
    if _TOOL_USAGE_RE.search(lower):
        return NoiseDecision(True, "usage_telemetry")
    if _TOOL_CHAIN_RE.search(sample) and ("sequence" in lower or "pattern" in lower):
        return NoiseDecision(True, "tool_sequence")
    if _SHORT_METRIC_RE.search(lower):
        return NoiseDecision(True, "metric_line")
    if _CODE_BLOCK_RE.search(sample):
        return NoiseDecision(True, "code_artifact")
    if _MARKDOWN_HEADER_RE.search(sample):
        return NoiseDecision(True, "markdown_header")
    if "?" in sample and len(sample.split()) <= 25:
        return NoiseDecision(True, "question_fragment")
    if _QUESTION_START_RE.match(sample) and len(sample.split()) <= 18:
        return NoiseDecision(True, "conversational_fragment")
    if len(sample) < 20:
        return NoiseDecision(True, "too_short")
    if any(lower.startswith(prefix) for prefix in _CONVERSATIONAL_STARTS):
        return NoiseDecision(True, "conversational_fragment")
    if context == "promoter" and sample.startswith("- `") and "/" in sample:
        return NoiseDecision(True, "file_reference_list")

    return NoiseDecision(False, "none")


def record_shadow(
    *,
    module: str,
    text: str,
    legacy_is_noise: bool,
    unified: NoiseDecision,
    extra: Dict[str, object] | None = None,
) -> None:
    if bool(legacy_is_noise) == bool(unified.is_noise):
        return
    try:
        SHADOW_LOG.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": time.time(),
            "module": module,
            "legacy_is_noise": bool(legacy_is_noise),
            "unified_is_noise": bool(unified.is_noise),
            "unified_rule": unified.rule,
            "snippet": str(text or "").strip()[:240],
        }
        if extra:
            payload["extra"] = dict(extra)
        with SHADOW_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass


def summarize_shadow_disagreements(
    rows: Iterable[Dict[str, object]],
) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows:
        module = str(row.get("module") or "unknown")
        out[module] = out.get(module, 0) + 1
    return out
