from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "benchmarks" / "memory_retrieval_ab.py"
    spec = importlib.util.spec_from_file_location("memory_retrieval_ab", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load memory_retrieval_ab module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_classify_error_kind_mapping():
    mod = _load_module()

    assert mod.classify_error_kind("HTTP 401 unauthorized token missing") == "auth"
    assert mod.classify_error_kind("request timeout after 30s") == "timeout"
    assert mod.classify_error_kind("blocked by policy guardrail") == "policy"
    assert mod.classify_error_kind("connection refused by upstream") == "transport"
    assert mod.classify_error_kind("unhandled exception") == "unknown"


def test_compute_case_metrics_with_labels():
    mod = _load_module()

    case = mod.EvalCase(
        case_id="c1",
        query="auth token rotation",
        relevant_insight_keys=["key-2"],
        relevant_contains=[],
        notes="",
    )
    items = [
        mod.RetrievedItem(
            insight_key="key-1",
            text="first result",
            source="hybrid",
            semantic_score=0.9,
            fusion_score=0.9,
            score=0.9,
            why="",
        ),
        mod.RetrievedItem(
            insight_key="key-2",
            text="matching result",
            source="hybrid",
            semantic_score=0.8,
            fusion_score=0.8,
            score=0.8,
            why="",
        ),
    ]

    metrics = mod.compute_case_metrics(case, items, 2)
    assert metrics.hits == 1
    assert metrics.label_count == 1
    assert metrics.precision_at_k == 0.5
    assert metrics.recall_at_k == 1.0
    assert metrics.mrr == 0.5
    assert metrics.top1_hit is False


def test_compute_case_metrics_without_labels():
    mod = _load_module()
    case = mod.EvalCase(case_id="c2", query="any", notes="")
    items = []

    metrics = mod.compute_case_metrics(case, items, 5)
    assert metrics.precision_at_k is None
    assert metrics.recall_at_k is None
    assert metrics.mrr is None
    assert metrics.top1_hit is None
    assert metrics.hits == 0
    assert metrics.label_count == 0


def test_hybrid_lexical_scores_boost_term_frequency():
    mod = _load_module()
    scores = mod.hybrid_lexical_scores(
        "auth token session rollback",
        [
            "auth token session rollback",
            "auth token session rollback rollback",
        ],
        bm25_mix=0.9,
    )
    assert len(scores) == 2
    assert scores[1] > scores[0]


def test_reciprocal_rank_fusion_scores_rewards_cross_signal():
    mod = _load_module()
    scores = mod.reciprocal_rank_fusion_scores(
        semantic_scores=[0.90, 0.80, 0.30],
        lexical_scores=[0.20, 0.95, 0.10],
        support_scores=[1.0, 2.0, 1.0],
    )
    assert len(scores) == 3
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[1] > scores[0]
    assert scores[2] < scores[0]


def test_retrieve_hybrid_filters_low_signal_candidates():
    mod = _load_module()

    class _Retriever:
        def retrieve(self, _query: str, _insights, limit: int = 8):
            return [
                SimpleNamespace(
                    insight_key="noise-1",
                    insight_text="I struggle with WebFetch_error tasks",
                    semantic_sim=0.86,
                    trigger_conf=0.0,
                    fusion_score=0.86,
                    source_type="semantic",
                    why="noise",
                ),
                SimpleNamespace(
                    insight_key="good-1",
                    insight_text="Use jittered retries to stabilize WebFetch transport timeouts.",
                    semantic_sim=0.83,
                    trigger_conf=0.0,
                    fusion_score=0.83,
                    source_type="semantic",
                    why="good",
                ),
            ][:limit]

    insights = {
        "noise-1": SimpleNamespace(insight="I struggle with WebFetch_error tasks", reliability=0.4),
        "good-1": SimpleNamespace(insight="Use jittered retries to stabilize WebFetch transport timeouts.", reliability=0.7),
    }
    out = mod.retrieve_hybrid(
        retriever=_Retriever(),
        insights=insights,
        query="webfetch transport timeout retries",
        top_k=3,
        candidate_k=8,
        lexical_weight=0.3,
        intent_coverage_weight=0.25,
        support_boost_weight=0.12,
        reliability_weight=0.1,
        semantic_intent_min=0.0,
        strict_filter=True,
        agentic=False,
    )
    keys = [row.insight_key for row in out]
    assert "noise-1" not in keys
    assert "good-1" in keys


def test_retrieve_hybrid_support_boost_rewards_cross_query_consistency():
    mod = _load_module()

    class _Retriever:
        def retrieve(self, query: str, _insights, limit: int = 8):
            if "failure pattern and fix" in query:
                return [
                    SimpleNamespace(
                        insight_key="shared",
                        insight_text="auth token session rollback fallback checklist",
                        semantic_sim=0.72,
                        trigger_conf=0.0,
                        fusion_score=0.72,
                        source_type="semantic",
                        why="facet",
                    )
                ][:limit]
            return [
                SimpleNamespace(
                    insight_key="shared",
                    insight_text="auth token session rollback fallback checklist",
                    semantic_sim=0.72,
                    trigger_conf=0.0,
                    fusion_score=0.72,
                    source_type="semantic",
                    why="primary",
                ),
                SimpleNamespace(
                    insight_key="one-off",
                    insight_text="auth token rollback note",
                    semantic_sim=0.78,
                    trigger_conf=0.0,
                    fusion_score=0.78,
                    source_type="semantic",
                    why="primary",
                ),
            ][:limit]

    insights = {
        "shared": SimpleNamespace(insight="auth token session rollback fallback checklist", reliability=0.6),
        "one-off": SimpleNamespace(insight="auth token rollback note", reliability=0.6),
    }
    out = mod.retrieve_hybrid(
        retriever=_Retriever(),
        insights=insights,
        query="auth token session rollback investigation",
        top_k=2,
        candidate_k=10,
        lexical_weight=0.0,
        intent_coverage_weight=0.0,
        support_boost_weight=0.35,
        reliability_weight=0.0,
        semantic_intent_min=0.0,
        strict_filter=True,
        agentic=True,
    )
    assert out
    assert out[0].insight_key == "shared"


def test_resolve_case_knobs_uses_runtime_policy_when_enabled(monkeypatch):
    mod = _load_module()
    case = mod.EvalCase(case_id="c", query="memory retrieval stale index")

    monkeypatch.setattr(
        mod,
        "runtime_policy_overrides_for_case",
        lambda case, tool_name="Bash": {
            "candidate_k": 44,
            "lexical_weight": 0.4,
            "intent_coverage_weight": 0.1,
            "support_boost_weight": 0.1,
            "reliability_weight": 0.05,
            "semantic_intent_min": 0.03,
            "runtime_active_domain": "memory",
            "runtime_profile_domain": "memory",
        },
    )

    knobs = mod.resolve_case_knobs(
        case=case,
        use_runtime_policy=True,
        tool_name="Bash",
        candidate_k=None,
        lexical_weight=None,
        intent_coverage_weight=None,
        support_boost_weight=None,
        reliability_weight=None,
        semantic_intent_min=None,
    )
    assert knobs["candidate_k"] == 44
    assert knobs["lexical_weight"] == 0.4
    assert knobs["runtime_active_domain"] == "memory"


def test_resolve_case_knobs_cli_overrides_runtime(monkeypatch):
    mod = _load_module()
    case = mod.EvalCase(case_id="c2", query="coding traceback")

    monkeypatch.setattr(
        mod,
        "runtime_policy_overrides_for_case",
        lambda case, tool_name="Bash": {
            "candidate_k": 44,
            "lexical_weight": 0.4,
            "intent_coverage_weight": 0.1,
            "support_boost_weight": 0.1,
            "reliability_weight": 0.05,
            "semantic_intent_min": 0.03,
        },
    )

    knobs = mod.resolve_case_knobs(
        case=case,
        use_runtime_policy=True,
        tool_name="Bash",
        candidate_k=33,
        lexical_weight=0.25,
        intent_coverage_weight=0.2,
        support_boost_weight=0.0,
        reliability_weight=0.0,
        semantic_intent_min=0.01,
    )
    assert knobs["candidate_k"] == 33
    assert knobs["lexical_weight"] == 0.25
    assert knobs["intent_coverage_weight"] == 0.2
    assert knobs["semantic_intent_min"] == 0.01


def test_resolve_case_knobs_includes_emotion_state_weight(monkeypatch):
    mod = _load_module()
    case = mod.EvalCase(case_id="c3", query="emotion memory retrieval")

    monkeypatch.setattr(
        mod,
        "runtime_policy_overrides_for_case",
        lambda case, tool_name="Bash": {
            "emotion_state_weight": 0.22,
        },
    )

    knobs = mod.resolve_case_knobs(
        case=case,
        use_runtime_policy=True,
        tool_name="Bash",
        candidate_k=None,
        lexical_weight=None,
        intent_coverage_weight=None,
        support_boost_weight=None,
        reliability_weight=None,
        emotion_state_weight=None,
        semantic_intent_min=None,
    )
    assert knobs["emotion_state_weight"] == 0.22

    cli_knobs = mod.resolve_case_knobs(
        case=case,
        use_runtime_policy=True,
        tool_name="Bash",
        candidate_k=None,
        lexical_weight=None,
        intent_coverage_weight=None,
        support_boost_weight=None,
        reliability_weight=None,
        emotion_state_weight=0.6,
        semantic_intent_min=None,
    )
    assert cli_knobs["emotion_state_weight"] == 0.6


def test_retrieve_hybrid_emotion_weight_promotes_state_match():
    mod = _load_module()

    class _Retriever:
        def retrieve(self, _query: str, _insights, limit: int = 8):
            return [
                SimpleNamespace(
                    insight_key="calm",
                    insight_text="rollback deploy fix plan",
                    semantic_sim=0.7,
                    trigger_conf=0.0,
                    fusion_score=0.7,
                    source_type="semantic",
                    why="base",
                ),
                SimpleNamespace(
                    insight_key="strained",
                    insight_text="rollback deploy fix plan",
                    semantic_sim=0.7,
                    trigger_conf=0.0,
                    fusion_score=0.7,
                    source_type="semantic",
                    why="base",
                ),
            ][:limit]

    insights = {
        "calm": SimpleNamespace(
            insight="rollback deploy fix plan",
            reliability=0.5,
            meta={"emotion": {"primary_emotion": "steady", "strain": 0.2, "calm": 0.8}},
        ),
        "strained": SimpleNamespace(
            insight="rollback deploy fix plan",
            reliability=0.5,
            meta={"emotion": {"primary_emotion": "careful", "strain": 0.85, "calm": 0.5}},
        ),
    }
    out = mod.retrieve_hybrid(
        retriever=_Retriever(),
        insights=insights,
        query="rollback deploy fix plan",
        top_k=2,
        candidate_k=8,
        lexical_weight=0.0,
        intent_coverage_weight=0.0,
        support_boost_weight=0.0,
        reliability_weight=0.0,
        emotion_state_weight=0.7,
        semantic_intent_min=0.0,
        strict_filter=False,
        agentic=False,
        emotion_state={"primary_emotion": "careful", "strain": 0.82, "calm": 0.52},
    )
    assert out
    assert out[0].insight_key == "strained"
