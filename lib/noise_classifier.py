"""Unified noise classifier with bounded shadow telemetry.

Default behavior is enforce-on. Rollout can be tuned per-path:
- SPARK_NOISE_CLASSIFIER_ENFORCE_PROMOTION
- SPARK_NOISE_CLASSIFIER_ENFORCE_RETRIEVAL

Global fallback:
- SPARK_NOISE_CLASSIFIER_ENFORCE

Emergency rollback (forces shadow/legacy behavior everywhere):
- SPARK_NOISE_CLASSIFIER_FORCE_SHADOW=1
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

from .jsonl_utils import append_jsonl_capped as _append_jsonl_capped
from .noise_patterns import is_common_noise, is_session_boilerplate
from .primitive_filter import is_primitive_text

SHADOW_LOG = Path.home() / ".spark" / "noise_classifier_shadow.jsonl"


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        value = int(raw)
    except Exception:
        return int(default)
    return max(int(lo), min(int(hi), value))


SHADOW_LOG_MAX_LINES = _env_int("SPARK_NOISE_SHADOW_MAX_LINES", 10000, 500, 200000)


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
    r"^\s*(what|why|how|where|who)\b|"
    r"^\s*when\s+(do|does|did|should|would|could|can|is|are|will)\b|"
    r"^\s*(do|does|did|should|would|could|can|is|are|am)\s+(we|you|i|they|it|this|that)\b",
    re.I,
)
_LOW_SIGNAL_DIRECTIVE_RE = re.compile(
    r"\b(do that|this too|that too|as well|whatever works|if you want|if needed)\b|"
    r"^\s*(ok|okay|sure|sounds good|lets do it|let's do it|go ahead)\b|"
    r"\b(let me know|can you|could you|would you|please)\b",
    re.I,
)
_REUSABLE_SIGNAL_RE = re.compile(
    r"\b(api|schema|trace|latency|token|retry|deploy|auth|memory|advisory|sqlite|jsonl|"
    r"queue|bridge|contract|payload|regression|benchmark|coverage|rollback|migration|"
    r"validator|threshold|gate|pytest|test|typescript|python)\b|"
    r"\b(because|so that|therefore|hence|prevents|ensures|reduces|improves)\b",
    re.I,
)
_ACTIONABLE_REQUEST_RE = re.compile(
    r"^\s*(can|could|would)\s+(you\s+)?"
    r"(enforce|add|set|run|validate|check|update|fix|remove|use|switch|enable|disable|include)\b|"
    r"^\s*please\s+"
    r"(enforce|add|set|run|validate|check|update|fix|remove|use|switch|enable|disable|include)\b",
    re.I,
)


def _parse_env_bool(name: str) -> bool | None:
    raw = str(os.getenv(name, "")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return None


def enforce_enabled(*, context: str = "default") -> bool:
    force_shadow = _parse_env_bool("SPARK_NOISE_CLASSIFIER_FORCE_SHADOW")
    if force_shadow is True:
        return False

    normalized = str(context or "default").strip().lower()
    scoped_key = ""
    if normalized in {"promotion", "promoter"}:
        scoped_key = "SPARK_NOISE_CLASSIFIER_ENFORCE_PROMOTION"
    elif normalized in {"retrieval", "advisor_retrieval", "cognitive_retrieval"}:
        scoped_key = "SPARK_NOISE_CLASSIFIER_ENFORCE_RETRIEVAL"

    if scoped_key:
        scoped = _parse_env_bool(scoped_key)
        if scoped is not None:
            return bool(scoped)

    global_default = _parse_env_bool("SPARK_NOISE_CLASSIFIER_ENFORCE")
    if global_default is not None:
        return bool(global_default)
    return True


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
    if _LOW_SIGNAL_DIRECTIVE_RE.search(lower):
        has_reusable_signal = bool(_REUSABLE_SIGNAL_RE.search(lower)) or bool(
            re.search(r"\b\d+(\.\d+)?%?\b", lower)
        )
        if not has_reusable_signal:
            return NoiseDecision(True, "conversational_fragment")
    actionable_request = bool(_ACTIONABLE_REQUEST_RE.match(sample)) and (
        bool(_REUSABLE_SIGNAL_RE.search(lower)) or bool(re.search(r"\b\d+(\.\d+)?%?\b", lower))
    )
    if actionable_request:
        return NoiseDecision(False, "none")
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
        _append_jsonl_capped(SHADOW_LOG, payload, SHADOW_LOG_MAX_LINES, ensure_ascii=False)
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
