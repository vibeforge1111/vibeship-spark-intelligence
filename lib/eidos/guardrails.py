"""
EIDOS Guardrails: Hard Gates for Quality Enforcement

These guardrails are NOT suggestions. They BLOCK actions that violate
intelligence principles.

Guardrails:
1. Progress Contract (existing in control_plane)
2. Memory Binding (existing in control_plane)
3. Outcome Enforcement (existing in control_plane)
4. Loop Watchers (existing in control_plane)
5. Phase Control (existing in control_plane)
6. Evidence Before Modification (NEW) - Forces diagnostic evidence after failed edits
7. High-Risk Tool Use (NEW) - Blocks obviously destructive or secrets-exfil patterns
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from .models import Episode, Step, Phase, Evaluation, ActionType


class ViolationType(Enum):
    """Types of guardrail violations."""
    EVIDENCE_BEFORE_MODIFICATION = "evidence_before_modification"
    PHASE_VIOLATION = "phase_violation"
    HIGH_RISK_TOOL_USE = "high_risk_tool_use"
    BUDGET_EXCEEDED = "budget_exceeded"
    MEMORY_REQUIRED = "memory_required"
    VALIDATION_REQUIRED = "validation_required"


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    violation: Optional[ViolationType] = None
    message: str = ""
    required_actions: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


# Actions allowed in each phase
PHASE_ALLOWED_ACTIONS: Dict[Phase, Set[str]] = {
    Phase.EXPLORE: {'Read', 'Glob', 'Grep', 'WebSearch', 'WebFetch', 'AskUser', 'Task'},
    Phase.DIAGNOSE: {'Read', 'Glob', 'Grep', 'Bash', 'Test', 'AskUser'},
    Phase.EXECUTE: {'Read', 'Edit', 'Write', 'Bash', 'Test', 'NotebookEdit'},
    Phase.CONSOLIDATE: {'Read', 'Reflect', 'Distill'},
    Phase.ESCALATE: {'Summarize', 'AskUser', 'AskUserQuestion'},
}

# Edit tools that modify files
EDIT_TOOLS = {'Edit', 'Write', 'NotebookEdit'}

# Diagnostic intent keywords
DIAGNOSTIC_INTENTS = {
    'diagnose', 'reproduce', 'isolate', 'narrow', 'investigate',
    'understand', 'analyze', 'debug', 'trace', 'examine'
}

class HighRiskToolUseGuard:
    """
    Defensive guardrail to block obviously dangerous actions.

    This is NOT a general "harm prevention" solution (open source can be forked),
    but it reduces accidental foot-guns and makes risky automation explicit.
    """

    def __init__(self):
        try:
            from lib.config_authority import resolve_section, env_bool
            cfg = resolve_section(
                "eidos",
                env_overrides={
                    "safety_guardrails_enabled": env_bool("SPARK_SAFETY_GUARDRAILS"),
                    "safety_allow_secrets": env_bool("SPARK_SAFETY_ALLOW_SECRETS"),
                },
            ).data
            self.enabled = bool(cfg.get("safety_guardrails_enabled", True))
            self.allow_secrets = bool(cfg.get("safety_allow_secrets", False))
        except Exception:
            self.enabled = str(os.environ.get("SPARK_SAFETY_GUARDRAILS", "1")).strip() != "0"
            self.allow_secrets = str(os.environ.get("SPARK_SAFETY_ALLOW_SECRETS", "0")).strip() == "1"

    def check(self, episode: Episode, step: Step) -> GuardrailResult:
        if not self.enabled:
            return GuardrailResult(passed=True)
        if step.action_type != ActionType.TOOL_CALL:
            return GuardrailResult(passed=True)

        tool = str(step.action_details.get("tool", "") or "")

        # 1) Bash: block destructive and "download|pipe to shell" patterns.
        if tool == "Bash":
            cmd = str(step.action_details.get("command", "") or "")
            cmd_l = cmd.lower().strip()
            if self._is_obviously_destructive_cmd(cmd_l):
                return GuardrailResult(
                    passed=False,
                    violation=ViolationType.HIGH_RISK_TOOL_USE,
                    message="Blocked high-risk shell command (obviously destructive).",
                    required_actions=["remove_or_sandbox_command", "require_human_confirmation"],
                    suggestions=[
                        "If you truly need deletion, scope it to a project subfolder and show the exact paths.",
                        "Prefer a dry-run first (e.g., list targets) before any deletion.",
                    ],
                )
            if self._is_pipe_to_shell(cmd_l):
                return GuardrailResult(
                    passed=False,
                    violation=ViolationType.HIGH_RISK_TOOL_USE,
                    message="Blocked high-risk shell command (download and execute via pipe).",
                    required_actions=["download_then_review", "pin_hash_or_signature"],
                    suggestions=[
                        "Download the script to a file, review it, and pin a commit/hash before running.",
                        "Prefer package-manager installs with checksums/signatures when available.",
                    ],
                )

        # 2) Reading likely-secret files: block unless explicitly allowed.
        if tool in {"Read", "Glob", "Grep"}:
            path = self._extract_path(step.action_details)
            if path and self._looks_like_secret_path(path):
                if not self.allow_secrets:
                    return GuardrailResult(
                        passed=False,
                        violation=ViolationType.HIGH_RISK_TOOL_USE,
                        message="Blocked likely-secret file access (set SPARK_SAFETY_ALLOW_SECRETS=1 to override).",
                        required_actions=["avoid_secret_access", "use_redacted_sample_or_env_var"],
                        suggestions=[
                            "Do not read private keys or credential stores into the agent context.",
                            "Use redacted examples or least-privilege tokens stored outside the workspace.",
                        ],
                    )

        return GuardrailResult(passed=True)

    def _extract_path(self, details: Dict[str, Any]) -> str:
        for k in ("file_path", "path", "filePath"):
            v = details.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _looks_like_secret_path(self, path: str) -> bool:
        p = path.replace("\\", "/").lower()
        # Conservative: only block very common private-key / credential store locations.
        needles = [
            "/.ssh/id_rsa",
            "/.ssh/id_ed25519",
            "/.ssh/known_hosts",
            "/.aws/credentials",
            "/.aws/config",
            "/.gnupg/",
            "/.netrc",
        ]
        if any(n in p for n in needles):
            return True
        if p.endswith((".pem", ".p12", ".pfx", ".key")):
            return True
        return False

    def _is_pipe_to_shell(self, cmd_l: str) -> bool:
        # Common "curl|sh" / "wget|bash" patterns.
        if "|" not in cmd_l:
            return False
        pipe_targets = (" sh", " bash", " zsh", " powershell", " pwsh")
        if any(t in cmd_l for t in ("curl ", "wget ")):
            return any(t in cmd_l for t in pipe_targets)
        # PowerShell IEX style remote execution.
        if "powershell" in cmd_l or "pwsh" in cmd_l:
            if "invoke-expression" in cmd_l or " iex " in cmd_l:
                return True
        return False

    def _is_obviously_destructive_cmd(self, cmd_l: str) -> bool:
        # Linux/macOS nukes
        if "rm -rf /" in cmd_l or "rm -rf /*" in cmd_l:
            return True
        if "rm -rf ~" in cmd_l or "rm -rf $home" in cmd_l or "rm -rf \"$home\"" in cmd_l:
            return True
        if "mkfs" in cmd_l or "dd if=" in cmd_l and "/dev/" in cmd_l:
            return True
        if ":(){ :|:& };:" in cmd_l:  # fork bomb
            return True
        # Windows nukes
        if "del /s /q c:\\" in cmd_l or "del /s /q c:/" in cmd_l:
            return True
        if cmd_l.startswith("format ") or " format " in cmd_l:
            return True
        if "cipher /w" in cmd_l:
            return True
        return False


class EvidenceBeforeModificationGuard:
    """
    Guardrail 6: Evidence Before Modification

    After 2 failed edit attempts on the same issue, the agent is FORBIDDEN
    to edit code until diagnostic evidence is gathered.

    Required before resuming edits:
    - Reproduce reliably
    - Narrow scope
    - Identify discriminating signal
    - Create minimal reproduction
    """

    def __init__(self, failure_threshold: int = 2):
        self.failure_threshold = failure_threshold

    def check(
        self,
        episode: Episode,
        step: Step,
        recent_steps: List[Step]
    ) -> GuardrailResult:
        """Check if edit is allowed based on evidence requirements."""
        # Only applies to tool calls
        if step.action_type != ActionType.TOOL_CALL:
            return GuardrailResult(passed=True)

        # Only applies to edit tools
        tool = step.action_details.get('tool', '')
        if tool not in EDIT_TOOLS:
            return GuardrailResult(passed=True)

        # Count failed edit attempts on same target
        file_path = step.action_details.get('file_path', '')
        failed_edits = self._count_failed_edits(recent_steps, file_path)

        if failed_edits >= self.failure_threshold:
            if not self._has_diagnostic_evidence(recent_steps):
                return GuardrailResult(
                    passed=False,
                    violation=ViolationType.EVIDENCE_BEFORE_MODIFICATION,
                    message=f"{failed_edits} failed edits on {file_path}. Must gather evidence before modifying.",
                    required_actions=[
                        "reproduce_reliably",
                        "narrow_scope",
                        "identify_discriminating_signal",
                        "create_minimal_reproduction"
                    ],
                    suggestions=[
                        "Add logging to understand the flow",
                        "Write a minimal test that fails",
                        "Isolate the specific line/function causing the issue",
                        "Document what you've tried and why it failed"
                    ]
                )

        return GuardrailResult(passed=True)

    def _count_failed_edits(self, steps: List[Step], file_path: str) -> int:
        """Count failed edit attempts on a specific file."""
        count = 0
        for step in steps:
            if step.action_type != ActionType.TOOL_CALL:
                continue
            tool = step.action_details.get('tool', '')
            if tool not in EDIT_TOOLS:
                continue
            step_path = step.action_details.get('file_path', '')
            if step_path == file_path and step.evaluation == Evaluation.FAIL:
                count += 1
        return count

    def _has_diagnostic_evidence(self, steps: List[Step]) -> bool:
        """Check if diagnostic evidence exists in recent steps."""
        for step in steps:
            # Check for diagnostic reasoning steps
            if step.action_type == ActionType.REASONING:
                intent_lower = step.intent.lower()
                if any(keyword in intent_lower for keyword in DIAGNOSTIC_INTENTS):
                    return True

            # Check for lessons that indicate understanding
            if step.lesson and len(step.lesson) > 50:
                lesson_lower = step.lesson.lower()
                if any(keyword in lesson_lower for keyword in ['root cause', 'because', 'the issue is', 'found that']):
                    return True

        return False


class PhaseViolationGuard:
    """
    Check if an action violates the current phase's allowed actions.
    """

    def check(
        self,
        episode: Episode,
        step: Step
    ) -> GuardrailResult:
        """Check if action is allowed in current phase."""
        if step.action_type != ActionType.TOOL_CALL:
            return GuardrailResult(passed=True)

        tool = step.action_details.get('tool', '')
        allowed = PHASE_ALLOWED_ACTIONS.get(episode.phase, set())

        if tool and tool not in allowed:
            return GuardrailResult(
                passed=False,
                violation=ViolationType.PHASE_VIOLATION,
                message=f"Action '{tool}' not allowed in phase '{episode.phase.value}'.",
                suggestions=[f"Allowed actions in {episode.phase.value}: {', '.join(sorted(allowed))}"]
            )

        return GuardrailResult(passed=True)


class GuardrailEngine:
    """
    Unified guardrail engine that runs all checks.
    """

    def __init__(self):
        self.evidence_guard = EvidenceBeforeModificationGuard()
        self.phase_guard = PhaseViolationGuard()
        self.risk_guard = HighRiskToolUseGuard()

    def check_all(
        self,
        episode: Episode,
        step: Step,
        recent_steps: List[Step]
    ) -> List[GuardrailResult]:
        """Run all guardrail checks and return results."""
        results = []

        # High-risk tool usage (defensive safety guard)
        result = self.risk_guard.check(episode, step)
        if not result.passed:
            results.append(result)

        # Evidence Before Modification
        result = self.evidence_guard.check(episode, step, recent_steps)
        if not result.passed:
            results.append(result)

        # Phase Violation
        result = self.phase_guard.check(episode, step)
        if not result.passed:
            results.append(result)

        return results

    def is_blocked(
        self,
        episode: Episode,
        step: Step,
        recent_steps: List[Step]
    ) -> Optional[GuardrailResult]:
        """Check if action is blocked by any guardrail."""
        violations = self.check_all(episode, step, recent_steps)
        return violations[0] if violations else None
