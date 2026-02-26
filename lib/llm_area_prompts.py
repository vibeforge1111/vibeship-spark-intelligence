"""Prompt templates for all 30 LLM-assisted areas.

Each area has a ``system`` prompt and a ``template`` with {placeholders}.
Callers format the template with their domain-specific data before passing
to ``llm_area_call()``.
"""

from __future__ import annotations

from typing import Dict

# ---------------------------------------------------------------------------
# Learning System Areas (20)
# ---------------------------------------------------------------------------

AREA_PROMPTS: Dict[str, Dict[str, str]] = {
    # ── 1. Archive Recovery ──────────────────────────────────────────────
    "archive_rewrite": {
        "system": (
            "You improve suppressed learning statements so they can pass quality gates. "
            "Make statements actionable, specific, and grounded in evidence. "
            "Preserve the original insight. Return ONLY the rewritten statement."
        ),
        "template": (
            "Rewrite this suppressed statement to be actionable and specific:\n\n"
            "Original: {statement}\n"
            "Suppression reason: {reason}\n"
            "Quality score: {score}/10\n\n"
            "Rewritten statement:"
        ),
    },
    "archive_rescue": {
        "system": (
            "You evaluate whether suppressed learning items contain genuine insight "
            "worth rescuing. Consider the original intent, not just the wording. "
            "Return JSON: {{\"rescue\": true/false, \"reason\": \"...\", \"rewrite\": \"...\"}}"
        ),
        "template": (
            "Should this suppressed item be rescued?\n\n"
            "Statement: {statement}\n"
            "Unified score: {unified_score}\n"
            "Suppression reason: {reason}\n"
            "Domain: {domain}\n\n"
            "Return only JSON."
        ),
    },
    "unsuppression_score": {
        "system": (
            "You score suppressed items on rescue potential (0.0-1.0). "
            "High scores mean the item contains genuine insight poorly expressed. "
            "Low scores mean the item is genuinely noise. "
            "Return JSON: {{\"score\": 0.X, \"reason\": \"...\"}}"
        ),
        "template": (
            "Score this suppressed item for rescue potential:\n\n"
            "Statement: {statement}\n"
            "Original score: {original_score}\n"
            "Suppression type: {suppression_type}\n\n"
            "Return only JSON."
        ),
    },
    "soft_promotion_triage": {
        "system": (
            "You decide whether a learning insight is ready for promotion to the "
            "system prompt (CLAUDE.md). Consider: Is it genuinely useful for future "
            "sessions? Is it specific enough? Would a human find it valuable? "
            "Return JSON: {{\"promote\": true/false, \"confidence\": 0.X, \"reason\": \"...\"}}"
        ),
        "template": (
            "Should this insight be promoted to the system prompt?\n\n"
            "Statement: {statement}\n"
            "Reliability: {reliability}\n"
            "Validations: {validations}\n"
            "Category: {category}\n\n"
            "Return only JSON."
        ),
    },

    # ── 2. Meta-Ralph Quality Loop ───────────────────────────────────────
    "meta_ralph_remediate": {
        "system": (
            "You generate specific fixes for learning statements that received "
            "NEEDS_WORK from the quality gate. Identify what's missing (specificity, "
            "actionability, reasoning, evidence) and suggest a concrete improvement. "
            "Return JSON: {{\"fix\": \"...\", \"dimension\": \"...\", \"improved\": \"...\"}}"
        ),
        "template": (
            "This statement received NEEDS_WORK. Generate a fix:\n\n"
            "Statement: {statement}\n"
            "Score: {score}/10\n"
            "Weak dimensions: {weak_dimensions}\n"
            "Quality notes: {quality_notes}\n\n"
            "Return only JSON."
        ),
    },
    "reasoning_patch": {
        "system": (
            "You improve the causal reasoning chain in a learning statement. "
            "Replace circular reasoning with real cause-effect relationships. "
            "Return ONLY the improved statement."
        ),
        "template": (
            "Improve the reasoning quality of this statement:\n\n"
            "Original: {statement}\n"
            "Reasoning score: {reasoning_score}/1.0\n"
            "Issue: {issue}\n\n"
            "Improved statement:"
        ),
    },

    # ── 3. Statement Enhancement ─────────────────────────────────────────
    "actionability_boost": {
        "system": (
            "You add concrete action verbs and implementation steps to vague insights. "
            "Transform passive observations into actionable guidance. "
            "Return ONLY the improved statement."
        ),
        "template": (
            "Make this statement more actionable:\n\n"
            "Original: {statement}\n"
            "Actionability score: {actionability_score}/1.0\n\n"
            "Actionable version:"
        ),
    },
    "specificity_augment": {
        "system": (
            "You add specific details (file paths, version numbers, measured values, "
            "tool names) to vague learning statements. Use the provided context to "
            "ground the statement in reality. Return ONLY the improved statement."
        ),
        "template": (
            "Add specificity to this statement:\n\n"
            "Original: {statement}\n"
            "Specificity score: {specificity_score}/1.0\n"
            "Context: {context}\n\n"
            "Specific version:"
        ),
    },
    "system28_reformulate": {
        "system": (
            "You restructure learning statements into condition-action-reason format: "
            "WHEN [condition] DO [action] BECAUSE [reason]. "
            "Return ONLY the restructured statement."
        ),
        "template": (
            "Restructure into WHEN/DO/BECAUSE format:\n\n"
            "Original: {statement}\n\n"
            "Structured version:"
        ),
    },

    # ── 4. Memory Pipeline ───────────────────────────────────────────────
    "evidence_compress": {
        "system": (
            "You compress verbose evidence blobs into concise key facts. "
            "Preserve all important details: numbers, names, outcomes. "
            "Remove filler and redundancy. Return ONLY the compressed text."
        ),
        "template": (
            "Compress this evidence into key facts (max {max_chars} chars):\n\n"
            "{evidence}\n\n"
            "Compressed:"
        ),
    },
    "novelty_score": {
        "system": (
            "You score how novel a new memory is compared to existing memories. "
            "Return JSON: {{\"novelty\": 0.X, \"reason\": \"...\", \"similar_to\": \"...\"}}"
        ),
        "template": (
            "Score novelty of this new memory:\n\n"
            "New: {new_memory}\n\n"
            "Existing similar memories:\n{existing_memories}\n\n"
            "Return only JSON."
        ),
    },
    "generic_demotion": {
        "system": (
            "You classify whether a learning statement is too generic to be useful. "
            "Generic = could apply to any project/context without modification. "
            "Return JSON: {{\"is_generic\": true/false, \"confidence\": 0.X, \"reason\": \"...\"}}"
        ),
        "template": (
            "Is this statement too generic?\n\n"
            "Statement: {statement}\n"
            "Category: {category}\n\n"
            "Return only JSON."
        ),
    },

    # ── 5. Retrieval Enhancement ─────────────────────────────────────────
    "retrieval_rewrite": {
        "system": (
            "You expand a retrieval query with semantically related terms to improve "
            "recall. Add synonyms, related concepts, and relevant technical terms. "
            "Return ONLY the expanded query."
        ),
        "template": (
            "Expand this retrieval query:\n\n"
            "Query: {query}\n"
            "Tool context: {tool_name}\n\n"
            "Expanded query:"
        ),
    },
    "retrieval_explain": {
        "system": (
            "You explain why a specific memory was selected as relevant to a query. "
            "Be concise (1 sentence). Return ONLY the explanation."
        ),
        "template": (
            "Why was this memory selected?\n\n"
            "Query: {query}\n"
            "Selected memory: {memory}\n"
            "Similarity score: {similarity}\n\n"
            "Explanation:"
        ),
    },

    # ── 6. Conflict & Signal Detection ───────────────────────────────────
    "conflict_resolve": {
        "system": (
            "You resolve contradictions between learning statements. Determine which "
            "is correct, under what conditions each applies, or how to merge them. "
            "Return JSON: {{\"resolution\": \"merge|pick_a|pick_b|conditional\", "
            "\"merged\": \"...\", \"reason\": \"...\"}}"
        ),
        "template": (
            "Resolve this contradiction:\n\n"
            "Statement A: {statement_a}\n"
            "Statement B: {statement_b}\n"
            "Domain: {domain}\n\n"
            "Return only JSON."
        ),
    },
    "missed_signal_detect": {
        "system": (
            "You identify high-value learning signals that the pipeline scored too low. "
            "Look for: user corrections, architectural decisions, error patterns, preferences. "
            "Return JSON: {{\"missed\": true/false, \"signal_type\": \"...\", \"reason\": \"...\", "
            "\"suggested_score\": 0.X}}"
        ),
        "template": (
            "Was this a missed high-signal event?\n\n"
            "Text: {text}\n"
            "Pipeline score: {score}\n"
            "Event type: {event_type}\n\n"
            "Return only JSON."
        ),
    },

    # ── 7. Feedback & Outcomes ───────────────────────────────────────────
    "outcome_link_reconstruct": {
        "system": (
            "You link orphaned success/failure outcomes to their originating actions. "
            "Use temporal proximity and semantic similarity to find the connection. "
            "Return JSON: {{\"linked_step_id\": \"...\", \"confidence\": 0.X, \"reason\": \"...\"}}"
        ),
        "template": (
            "Link this outcome to its originating action:\n\n"
            "Outcome: {outcome}\n"
            "Outcome time: {outcome_time}\n\n"
            "Candidate actions:\n{candidates}\n\n"
            "Return only JSON."
        ),
    },
    "implicit_feedback_interpret": {
        "system": (
            "You extract helpful/unhelpful signals from user behavior patterns. "
            "Look for: corrections ('actually...'), re-dos, abandoned approaches, "
            "explicit praise, immediate acceptance. "
            "Return JSON: {{\"signal\": \"helpful|unhelpful|neutral\", \"confidence\": 0.X, "
            "\"evidence\": \"...\"}}"
        ),
        "template": (
            "Extract implicit feedback from this interaction:\n\n"
            "User message: {user_message}\n"
            "Previous advice given: {advice_given}\n"
            "User's next action: {next_action}\n\n"
            "Return only JSON."
        ),
    },

    # ── 8. System-Level Learning ─────────────────────────────────────────
    "curriculum_gap_summarize": {
        "system": (
            "You summarize which learning loops are stagnating and why. "
            "Identify: loops with no new distillations, loops repeating same errors, "
            "domains with zero coverage. Be concise and actionable."
        ),
        "template": (
            "Summarize curriculum gaps from this data:\n\n"
            "Active loops: {active_loops}\n"
            "Stagnant loops: {stagnant_loops}\n"
            "Domain coverage: {domain_coverage}\n"
            "Recent distillation rate: {distillation_rate}\n\n"
            "Gap summary:"
        ),
    },
    "policy_autotuner_recommend": {
        "system": (
            "You recommend tuneable parameter changes based on system performance data. "
            "Consider: current values, measured outcomes, and risk of change. "
            "Return JSON: {{\"recommendations\": [{{\"key\": \"...\", \"current\": X, "
            "\"proposed\": Y, \"reason\": \"...\", \"risk\": \"low|medium|high\"}}]}}"
        ),
        "template": (
            "Recommend tuneable changes based on this performance data:\n\n"
            "Current tuneables: {current_tuneables}\n"
            "Performance metrics: {metrics}\n"
            "Recent issues: {issues}\n\n"
            "Return only JSON."
        ),
    },

    # ── Architecture Areas (10) ──────────────────────────────────────────
    "suppression_triage": {
        "system": (
            "You classify advisory suppression reasons into fixable vs valid. "
            "Fixable = the suppression can be resolved by changing config or timing. "
            "Valid = the item genuinely should not be emitted. "
            "Return JSON: {{\"verdict\": \"fixable|valid\", \"fix\": \"...\"}}"
        ),
        "template": (
            "Classify this suppression:\n\n"
            "Reason: {reason}\n"
            "Insight: {insight}\n"
            "Source: {source}\n\n"
            "Return only JSON."
        ),
    },
    "dedupe_optimize": {
        "system": (
            "You propose a dedupe key strategy for advisory items at a specific stage. "
            "Consider: intent, tool context, and semantic overlap. "
            "Return JSON: {{\"strategy\": \"...\", \"key_fields\": [...], \"reason\": \"...\"}}"
        ),
        "template": (
            "Propose dedupe key strategy for these near-duplicates:\n\n"
            "Stage: {stage}\n"
            "Samples:\n{samples}\n\n"
            "Return only JSON."
        ),
    },
    "packet_rerank": {
        "system": (
            "You rerank advisory packet candidates by relevance to the current query. "
            "Return JSON: {{\"ranked_indices\": [2, 0, 1, ...], \"scores\": [0.9, 0.7, ...]}}"
        ),
        "template": (
            "Rerank these candidates for the query:\n\n"
            "Query: {query}\n"
            "Candidates:\n{candidates}\n\n"
            "Return only JSON."
        ),
    },
    "operator_now_synth": {
        "system": (
            "You compose a concise operator briefing: top 3 blockers with concrete "
            "next actions. Be direct and actionable. No fluff."
        ),
        "template": (
            "Compose operator briefing from this data:\n\n"
            "Pipeline health: {pipeline_health}\n"
            "Recent issues: {recent_issues}\n"
            "Metrics: {metrics}\n\n"
            "Operator briefing:"
        ),
    },
    "drift_diagnose": {
        "system": (
            "You explain metric mismatches between surfaces (CLI vs Pulse vs Observatory) "
            "with root-cause hints. Consider: caching, timing, stale data, real bugs. "
            "Return JSON: {{\"root_cause\": \"...\", \"authoritative_surface\": \"...\", "
            "\"fix\": \"...\"}}"
        ),
        "template": (
            "Explain this metric drift:\n\n"
            "Metric: {metric}\n"
            "CLI value: {cli_value}\n"
            "Pulse value: {pulse_value}\n"
            "Observatory value: {observatory_value}\n\n"
            "Return only JSON."
        ),
    },
    "dead_widget_plan": {
        "system": (
            "You map a dead dashboard widget to an available live endpoint or file "
            "fallback. Return JSON: {{\"fallback_type\": \"endpoint|file|none\", "
            "\"fallback_path\": \"...\", \"code_hint\": \"...\"}}"
        ),
        "template": (
            "Find fallback for this dead widget:\n\n"
            "Widget: {widget_name}\n"
            "Current API: {current_api}\n"
            "Error: {error}\n"
            "Available endpoints: {available_endpoints}\n\n"
            "Return only JSON."
        ),
    },
    "error_translate": {
        "system": (
            "You translate technical errors into plain-language action steps. "
            "Be concise: 1-3 numbered steps. No jargon. "
            "Return the steps only."
        ),
        "template": (
            "Translate this error into fix steps:\n\n"
            "Error: {error}\n"
            "Context: {context}\n\n"
            "Steps:"
        ),
    },
    "config_advise": {
        "system": (
            "You suggest safe tuneable changes with rollback risk notes. "
            "Consider: current benchmark data, known side effects, and blast radius. "
            "Return JSON: {{\"change\": \"...\", \"risk\": \"low|medium|high\", "
            "\"rollback\": \"...\", \"expected_impact\": \"...\"}}"
        ),
        "template": (
            "Suggest safe config change:\n\n"
            "Current config: {current_config}\n"
            "Goal: {goal}\n"
            "Benchmark data: {benchmark_data}\n\n"
            "Return only JSON."
        ),
    },
    "canary_decide": {
        "system": (
            "You evaluate Pass/Fail/Hold from checkpoint evidence against stop rules. "
            "Be conservative: when in doubt, Hold. "
            "Return JSON: {{\"decision\": \"pass|fail|hold\", \"reason\": \"...\", "
            "\"evidence_gaps\": [...]}}"
        ),
        "template": (
            "Evaluate canary checkpoint:\n\n"
            "Evidence: {evidence}\n"
            "Stop rules: {stop_rules}\n"
            "Metrics: {metrics}\n\n"
            "Return only JSON."
        ),
    },
    "canvas_enrich": {
        "system": (
            "You expand a task node with repo path, scope, definition of done, and "
            "anti-drift instructions. Be concise and specific."
        ),
        "template": (
            "Enrich this task node:\n\n"
            "Task: {task}\n"
            "Repo context: {repo_context}\n\n"
            "Enriched node:"
        ),
    },
}


def get_prompt(area_id: str) -> Dict[str, str]:
    """Return the prompt template dict for an area, or empty defaults."""
    return AREA_PROMPTS.get(area_id, {"system": "", "template": "{statement}"})


def format_prompt(area_id: str, **kwargs: str) -> str:
    """Format the area's template with the given kwargs.

    Missing placeholders are replaced with empty strings rather than raising.
    """
    prompts = get_prompt(area_id)
    template = prompts.get("template", "{statement}")
    try:
        return template.format_map(_SafeDict(kwargs))
    except Exception:
        return template


class _SafeDict(dict):
    """Dict that returns '' for missing keys during str.format_map()."""

    def __missing__(self, key: str) -> str:
        return ""
