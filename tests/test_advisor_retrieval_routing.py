from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import lib.advisor as advisor_mod
import lib.semantic_retriever as semantic_retriever_mod


class _DummyCognitive:
    def __init__(self) -> None:
        self.insights = {
            "insight-1": SimpleNamespace(insight="Rotate auth tokens safely", reliability=0.8, context="auth"),
            "insight-2": SimpleNamespace(insight="Diagnose memory transport timeouts", reliability=0.75, context="memory"),
            "insight-3": SimpleNamespace(insight="Verify session scope before retrieval", reliability=0.7, context="session"),
        }

    def is_noise_insight(self, _text: str) -> bool:
        return False

    def get_insights_for_context(self, *_args, **_kwargs):
        return []


class _FakeRetriever:
    def __init__(self, *, primary_count: int = 3, primary_score: float = 0.86, facet_score: float = 0.74) -> None:
        self.primary_count = primary_count
        self.primary_score = primary_score
        self.facet_score = facet_score
        self.calls = []

    def retrieve(self, query: str, _insights, limit: int = 8):
        self.calls.append(query)
        if "failure pattern and fix" in query:
            token = query.split()[0]
            return [
                SimpleNamespace(
                    insight_key=f"facet:{token}",
                    insight_text=f"{token} fallback fix",
                    semantic_sim=self.facet_score,
                    trigger_conf=0.0,
                    fusion_score=self.facet_score,
                    source_type="semantic",
                    why="Facet retrieval",
                )
            ][:limit]

        rows = []
        for idx in range(self.primary_count):
            score = max(0.05, self.primary_score - (0.02 * idx))
            rows.append(
                SimpleNamespace(
                    insight_key=f"primary:{idx}",
                    insight_text=f"primary retrieval result {idx}",
                    semantic_sim=score,
                    trigger_conf=0.0,
                    fusion_score=score,
                    source_type="semantic",
                    why="Primary retrieval",
                )
            )
        return rows[:limit]


def _patch_advisor_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(advisor_mod, "ADVISOR_DIR", tmp_path)
    monkeypatch.setattr(advisor_mod, "ADVICE_LOG", tmp_path / "advice_log.jsonl")
    monkeypatch.setattr(advisor_mod, "EFFECTIVENESS_FILE", tmp_path / "effectiveness.json")
    monkeypatch.setattr(advisor_mod, "ADVISOR_METRICS", tmp_path / "metrics.json")
    monkeypatch.setattr(advisor_mod, "RECENT_ADVICE_LOG", tmp_path / "recent_advice.jsonl")
    monkeypatch.setattr(advisor_mod, "RETRIEVAL_ROUTE_LOG", tmp_path / "retrieval_router.jsonl")
    monkeypatch.setattr(advisor_mod, "get_cognitive_learner", lambda: _DummyCognitive())
    monkeypatch.setattr(advisor_mod, "get_mind_bridge", lambda: None)


def _policy_with(advisor: advisor_mod.SparkAdvisor, **updates):
    policy = copy.deepcopy(advisor.retrieval_policy)
    policy.update(updates)
    return policy


def _load_last_route(path: Path):
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    return json.loads(lines[-1])


def _disable_advice_sources(monkeypatch, advisor: advisor_mod.SparkAdvisor) -> None:
    noop = lambda *_a, **_kw: []
    for name in (
        "_get_cognitive_advice",
        "_get_chip_advice",
        "_get_mind_advice",
        "_get_opportunity_advice",
        "_get_surprise_advice",
        "_get_skill_advice",
        "_get_eidos_advice",
        "_get_convo_advice",
        "_get_engagement_advice",
        "_get_niche_advice",
        "_get_replay_counterfactual_advice",
        "_get_workflow_advice",
    ):
        monkeypatch.setattr(advisor, name, noop)


def test_advise_skips_bank_source_when_disabled(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    advisor = advisor_mod.SparkAdvisor()
    _disable_advice_sources(monkeypatch, advisor)
    advisor.retrieval_policy = _policy_with(
        advisor,
        include_bank_advice=False,
        include_tool_specific_advice=False,
    )

    def _raise_if_called(_context: str):
        raise AssertionError("bank source should be disabled")

    monkeypatch.setattr(advisor, "_get_bank_advice", _raise_if_called)
    monkeypatch.setattr(advisor, "_get_tool_specific_advice", lambda _tool: [])
    out = advisor.advise(
        "Edit",
        {"file_path": "lib/advisor.py"},
        "tighten retrieval gating",
        include_mind=False,
        track_retrieval=False,
        log_recent=False,
    )
    assert out == []


def test_advise_skips_tool_specific_source_when_disabled(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    advisor = advisor_mod.SparkAdvisor()
    _disable_advice_sources(monkeypatch, advisor)
    advisor.retrieval_policy = _policy_with(
        advisor,
        include_bank_advice=False,
        include_tool_specific_advice=False,
    )

    def _raise_if_called(_tool_name: str):
        raise AssertionError("tool-specific source should be disabled")

    monkeypatch.setattr(advisor, "_get_bank_advice", lambda _ctx: [])
    monkeypatch.setattr(advisor, "_get_tool_specific_advice", _raise_if_called)
    out = advisor.advise(
        "Bash",
        {"command": "pytest -q"},
        "debug retrieval latency",
        include_mind=False,
        track_retrieval=False,
        log_recent=False,
    )
    assert out == []


def test_embeddings_only_mode_skips_agentic_queries(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    fake = _FakeRetriever(primary_count=3, primary_score=0.9)
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: fake)

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="embeddings_only",
        max_queries=4,
        agentic_query_limit=4,
        min_results_no_escalation=1,
        min_top_score_no_escalation=0.2,
    )

    advice = advisor._get_semantic_cognitive_advice("Edit", "memory retrieval diagnostics and session checks")

    assert advice
    assert len(fake.calls) == 1
    assert all(item.source in {"semantic", "trigger"} for item in advice)


def test_auto_mode_uses_primary_route_for_strong_simple_query(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    fake = _FakeRetriever(primary_count=4, primary_score=0.9)
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: fake)

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="auto",
        gate_strategy="minimal",
        complexity_threshold=4,
        max_queries=4,
        agentic_query_limit=4,
        domain_profile_enabled=False,
        domain_profiles={},
        escalate_on_high_risk=False,
        min_results_no_escalation=3,
        min_top_score_no_escalation=0.8,
    )

    advice = advisor._get_semantic_cognitive_advice("Read", "fix memory indexing issue")
    route = _load_last_route(tmp_path / "retrieval_router.jsonl")

    assert advice
    assert len(fake.calls) == 1
    assert all(item.source in {"semantic", "trigger"} for item in advice)
    assert route["escalated"] is False
    assert route["route"] == "semantic"


def test_auto_mode_escalates_for_complex_high_risk_query(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    fake = _FakeRetriever(primary_count=4, primary_score=0.88, facet_score=0.72)
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: fake)

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="auto",
        complexity_threshold=2,
        escalate_on_high_risk=True,
        max_queries=4,
        agentic_query_limit=3,
        min_results_no_escalation=1,
        min_top_score_no_escalation=0.2,
    )

    advice = advisor._get_semantic_cognitive_advice(
        "Bash",
        "What root cause pattern should we compare across auth token session failures in production memory retrieval?",
    )

    assert advice
    assert len(fake.calls) > 1
    assert any(item.source == "semantic-agentic" for item in advice)


def test_auto_mode_denies_high_risk_escalation_when_over_budget(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _SlowPrimaryRetriever:
        def __init__(self):
            self.calls = []

        def retrieve(self, query: str, _insights, limit: int = 8):
            import time as _time
            self.calls.append(query)
            # Force primary route over its fast-path budget.
            _time.sleep(0.02)
            if "failure pattern and fix" in query:
                return [
                    SimpleNamespace(
                        insight_key="facet:auth",
                        insight_text="facet fallback fix",
                        semantic_sim=0.7,
                        trigger_conf=0.0,
                        fusion_score=0.7,
                        source_type="semantic",
                        why="facet retrieval",
                    )
                ][:limit]
            return [
                SimpleNamespace(
                    insight_key="primary:auth",
                    insight_text="primary retrieval result",
                    semantic_sim=0.9,
                    trigger_conf=0.0,
                    fusion_score=0.9,
                    source_type="semantic",
                    why="primary retrieval",
                )
            ][:limit]

    slow = _SlowPrimaryRetriever()
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: slow)

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="auto",
        escalate_on_high_risk=True,
        max_queries=4,
        agentic_query_limit=3,
        fast_path_budget_ms=1,
        deny_escalation_when_over_budget=True,
        allow_high_risk_over_budget_escalation=False,
        min_results_no_escalation=10,
        min_top_score_no_escalation=0.95,
    )

    advice = advisor._get_semantic_cognitive_advice(
        "Bash",
        "auth token session retrieval failure in production",
    )
    route = _load_last_route(tmp_path / "retrieval_router.jsonl")

    assert advice
    assert len(slow.calls) == 1  # primary only, no facet fanout
    assert route["escalated"] is False
    assert "deny_over_budget" in (route.get("reasons") or [])


def test_auto_mode_can_override_high_risk_escalation_when_over_budget(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _SlowPrimaryRetriever:
        def __init__(self):
            self.calls = []

        def retrieve(self, query: str, _insights, limit: int = 8):
            import time as _time
            self.calls.append(query)
            _time.sleep(0.02)
            if "failure pattern and fix" in query:
                return [
                    SimpleNamespace(
                        insight_key="facet:auth",
                        insight_text="facet fallback fix",
                        semantic_sim=0.72,
                        trigger_conf=0.0,
                        fusion_score=0.72,
                        source_type="semantic",
                        why="facet retrieval",
                    )
                ][:limit]
            return [
                SimpleNamespace(
                    insight_key="primary:auth",
                    insight_text="primary retrieval result",
                    semantic_sim=0.9,
                    trigger_conf=0.0,
                    fusion_score=0.9,
                    source_type="semantic",
                    why="primary retrieval",
                )
            ][:limit]

    slow = _SlowPrimaryRetriever()
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: slow)

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="auto",
        escalate_on_high_risk=True,
        max_queries=4,
        agentic_query_limit=3,
        fast_path_budget_ms=1,
        deny_escalation_when_over_budget=True,
        allow_high_risk_over_budget_escalation=True,
        min_results_no_escalation=10,
        min_top_score_no_escalation=0.95,
    )

    advice = advisor._get_semantic_cognitive_advice(
        "Bash",
        "auth token session retrieval failure in production",
    )
    route = _load_last_route(tmp_path / "retrieval_router.jsonl")

    assert advice
    assert len(slow.calls) > 1  # primary + facets
    assert route["escalated"] is True


def test_auto_mode_allows_empty_primary_rescue_even_when_over_budget(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _SlowEmptyPrimaryRetriever:
        def __init__(self):
            self.calls = []

        def retrieve(self, query: str, _insights, limit: int = 8):
            import time as _time

            self.calls.append(query)
            _time.sleep(0.02)
            if "failure pattern and fix" in query:
                return [
                    SimpleNamespace(
                        insight_key="facet:rescue",
                        insight_text="facet rescue result",
                        semantic_sim=0.74,
                        trigger_conf=0.0,
                        fusion_score=0.74,
                        source_type="semantic",
                        why="facet retrieval",
                    )
                ][:limit]
            return []

    slow = _SlowEmptyPrimaryRetriever()
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: slow)

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="auto",
        escalate_on_high_risk=False,
        max_queries=3,
        agentic_query_limit=2,
        fast_path_budget_ms=1,
        deny_escalation_when_over_budget=True,
        allow_high_risk_over_budget_escalation=False,
        min_results_no_escalation=3,
        min_top_score_no_escalation=0.7,
    )

    advice = advisor._get_semantic_cognitive_advice(
        "Edit",
        "auth token refresh failure with memory retrieval mismatch",
    )
    route = _load_last_route(tmp_path / "retrieval_router.jsonl")

    assert advice
    assert len(slow.calls) > 1  # primary + rescue facet
    assert route["escalated"] is True
    assert "deny_over_budget" not in (route.get("reasons") or [])


def test_hybrid_agentic_mode_always_escalates(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    fake = _FakeRetriever(primary_count=3, primary_score=0.9)
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: fake)

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="hybrid_agentic",
        max_queries=4,
        agentic_query_limit=3,
        min_results_no_escalation=5,
        min_top_score_no_escalation=0.99,
    )

    advice = advisor._get_semantic_cognitive_advice(
        "Edit",
        "memory retrieval diagnostics compare timeline and transport behavior",
    )

    assert advice
    assert len(fake.calls) > 1
    assert any(item.source == "semantic-agentic" for item in advice)


def test_bm25_rerank_prefers_term_dense_candidate(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _FixedRetriever:
        def retrieve(self, _query: str, _insights, limit: int = 8):
            rows = [
                SimpleNamespace(
                    insight_key="dense-a",
                    insight_text="auth token session rotation guide",
                    semantic_sim=0.82,
                    trigger_conf=0.0,
                    fusion_score=0.8,
                    source_type="semantic",
                    why="semantic baseline",
                ),
                SimpleNamespace(
                    insight_key="dense-b",
                    insight_text="auth token session token token token rollback pattern",
                    semantic_sim=0.82,
                    trigger_conf=0.0,
                    fusion_score=0.8,
                    source_type="semantic",
                    why="semantic baseline",
                ),
            ]
            return rows[:limit]

    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: _FixedRetriever())

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="embeddings_only",
        lexical_weight=0.4,
        bm25_mix=0.8,
        max_queries=1,
        agentic_query_limit=1,
        min_results_no_escalation=1,
        min_top_score_no_escalation=0.1,
    )

    advice = advisor._get_semantic_cognitive_advice("Read", "auth token session rollback")

    assert advice
    assert advice[0].insight_key == "dense-b"


def test_auto_mode_respects_agentic_rate_cap(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    fake = _FakeRetriever(primary_count=3, primary_score=0.85)
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: fake)

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="auto",
        gate_strategy="minimal",
        escalate_on_high_risk=True,
        agentic_rate_limit=0.0,
        agentic_rate_window=20,
        max_queries=4,
        agentic_query_limit=3,
        min_results_no_escalation=10,
        min_top_score_no_escalation=0.95,
    )

    advice = advisor._get_semantic_cognitive_advice("Bash", "auth token session retrieval failure in production")
    route = _load_last_route(tmp_path / "retrieval_router.jsonl")

    assert advice
    assert len(fake.calls) == 1  # primary only; no facet queries
    assert route["escalated"] is False
    assert "agentic_rate_cap" in (route.get("reasons") or [])


def test_agentic_deadline_prevents_facet_fanout(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _SlowFacetRetriever:
        def __init__(self):
            self.calls = []

        def retrieve(self, query: str, _insights, limit: int = 8):
            self.calls.append(query)
            if "failure pattern and fix" in query:
                # Simulate expensive facet retrieval call.
                import time as _time
                _time.sleep(0.03)
            return [
                SimpleNamespace(
                    insight_key=f"row:{len(self.calls)}",
                    insight_text=f"result {len(self.calls)}",
                    semantic_sim=0.8,
                    trigger_conf=0.0,
                    fusion_score=0.8,
                    source_type="semantic",
                    why="retrieval",
                )
            ][:limit]

    slow = _SlowFacetRetriever()
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: slow)

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="auto",
        gate_strategy="minimal",
        escalate_on_high_risk=True,
        agentic_deadline_ms=10,
        max_queries=4,
        agentic_query_limit=3,
        min_results_no_escalation=10,
        min_top_score_no_escalation=0.95,
    )

    advice = advisor._get_semantic_cognitive_advice("Edit", "auth token session retrieval issue in production")
    route = _load_last_route(tmp_path / "retrieval_router.jsonl")

    assert advice
    assert route["facets_planned"] >= 1
    assert route["facets_used"] <= 1
    assert route["agentic_timed_out"] is True


def test_prefilter_limits_active_insight_set(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _InspectingRetriever:
        def __init__(self):
            self.insight_sizes = []

        def retrieve(self, _query: str, insights, limit: int = 8):
            self.insight_sizes.append(len(insights))
            return [
                SimpleNamespace(
                    insight_key="focus-key",
                    insight_text="auth memory retrieval fix",
                    semantic_sim=0.9,
                    trigger_conf=0.0,
                    fusion_score=0.9,
                    source_type="semantic",
                    why="prefilter test",
                )
            ][:limit]

    fake = _InspectingRetriever()
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: fake)

    advisor = advisor_mod.SparkAdvisor()
    large = {}
    for i in range(120):
        txt = "auth token session retrieval fix" if i < 5 else f"misc note {i}"
        large[f"k{i}"] = SimpleNamespace(insight=txt, reliability=0.5, context="ctx")
    advisor.cognitive.insights = large
    advisor.retrieval_policy = _policy_with(
        advisor,
        prefilter_enabled=True,
        prefilter_max_insights=30,
        mode="embeddings_only",
    )

    advice = advisor._get_semantic_cognitive_advice("Read", "auth token retrieval")
    assert advice
    assert fake.insight_sizes
    assert fake.insight_sizes[0] <= 30


def test_prefilter_drops_low_signal_struggle_rows(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _InspectingRetriever:
        def __init__(self):
            self.insight_texts = []

        def retrieve(self, _query: str, insights, limit: int = 8):
            self.insight_texts.append([str(getattr(v, "insight", "") or "") for v in insights.values()])
            return [
                SimpleNamespace(
                    insight_key="good-key",
                    insight_text="Use jittered retries for WebFetch timeout recovery.",
                    semantic_sim=0.88,
                    trigger_conf=0.0,
                    fusion_score=0.88,
                    source_type="semantic",
                    why="prefilter",
                )
            ][:limit]

    fake = _InspectingRetriever()
    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: fake)

    advisor = advisor_mod.SparkAdvisor()
    large = {
        "noise-key": SimpleNamespace(
            insight="I struggle with WebFetch_error tasks",
            reliability=0.9,
            context="webfetch",
        ),
        "good-key": SimpleNamespace(
            insight="Use jittered retries for WebFetch timeout recovery.",
            reliability=0.8,
            context="webfetch timeout",
        ),
    }
    for i in range(50):
        large[f"k{i}"] = SimpleNamespace(insight=f"misc context note {i}", reliability=0.5, context="misc")
    advisor.cognitive.insights = large
    advisor.retrieval_policy = _policy_with(
        advisor,
        prefilter_enabled=True,
        prefilter_max_insights=20,
        prefilter_drop_low_signal=True,
        mode="embeddings_only",
        semantic_context_min=0.0,
        semantic_lexical_min=0.0,
        semantic_intent_min=0.0,
        semantic_strong_override=0.0,
    )

    advice = advisor._get_semantic_cognitive_advice("Read", "webfetch timeout retries")
    assert advice
    assert fake.insight_texts
    flat = " | ".join(fake.insight_texts[0]).lower()
    assert "webfetch_error tasks" not in flat


def test_semantic_rerank_boosts_multi_query_support(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _SupportRetriever:
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

    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: _SupportRetriever())

    advisor = advisor_mod.SparkAdvisor()
    advisor.cognitive.insights = {
        "shared": SimpleNamespace(insight="auth token session rollback fallback checklist", reliability=0.6, context="auth"),
        "one-off": SimpleNamespace(insight="auth token rollback note", reliability=0.6, context="auth"),
    }
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="hybrid_agentic",
        max_queries=4,
        agentic_query_limit=3,
        lexical_weight=0.0,
        intent_coverage_weight=0.0,
        support_boost_weight=0.35,
        reliability_weight=0.0,
        semantic_context_min=0.0,
        semantic_lexical_min=0.0,
        semantic_intent_min=0.0,
        semantic_strong_override=0.0,
    )

    advice = advisor._get_semantic_cognitive_advice("Read", "auth token session rollback investigation")
    assert advice
    assert advice[0].insight_key == "shared"


def test_semantic_rerank_boosts_emotion_state_match(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _EmotionRetriever:
        def retrieve(self, _query: str, _insights, limit: int = 8):
            return [
                SimpleNamespace(
                    insight_key="steady",
                    insight_text="rollback deploy checklist for fast recovery",
                    semantic_sim=0.72,
                    trigger_conf=0.0,
                    fusion_score=0.72,
                    source_type="semantic",
                    why="semantic baseline",
                ),
                SimpleNamespace(
                    insight_key="careful",
                    insight_text="rollback deploy checklist for fast recovery",
                    semantic_sim=0.72,
                    trigger_conf=0.0,
                    fusion_score=0.72,
                    source_type="semantic",
                    why="semantic baseline",
                ),
            ][:limit]

    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: _EmotionRetriever())

    advisor = advisor_mod.SparkAdvisor()
    advisor.cognitive.insights = {
        "steady": SimpleNamespace(
            insight="rollback deploy checklist for fast recovery",
            reliability=0.5,
            context="deploy",
            meta={"emotion": {"primary_emotion": "steady", "mode": "real_talk", "strain": 0.20, "calm": 0.85}},
        ),
        "careful": SimpleNamespace(
            insight="rollback deploy checklist for fast recovery",
            reliability=0.5,
            context="deploy",
            meta={"emotion": {"primary_emotion": "careful", "mode": "real_talk", "strain": 0.82, "calm": 0.58}},
        ),
    }
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="embeddings_only",
        lexical_weight=0.0,
        intent_coverage_weight=0.0,
        support_boost_weight=0.0,
        reliability_weight=0.0,
        semantic_context_min=0.0,
        semantic_lexical_min=0.0,
        semantic_intent_min=0.0,
        semantic_strong_override=0.0,
    )
    monkeypatch.setattr(
        advisor,
        "_load_memory_emotion_cfg",
        lambda: {
            "enabled": True,
            "advisory_rerank_weight": 0.4,
            "advisory_min_state_similarity": 0.1,
        },
    )
    monkeypatch.setattr(
        advisor,
        "_current_emotion_state_for_rerank",
        lambda: {"primary_emotion": "careful", "mode": "real_talk", "strain": 0.84, "calm": 0.56},
    )

    advice = advisor._get_semantic_cognitive_advice("Read", "rollback deploy recovery checklist")
    assert advice
    assert advice[0].insight_key == "careful"


def test_semantic_route_filters_low_match_irrelevant_rows(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _LowMatchRetriever:
        def retrieve(self, _query: str, _insights, limit: int = 8):
            return [
                SimpleNamespace(
                    insight_key="low-match",
                    insight_text="multiplier granted standalone formatting for social reply cadence",
                    semantic_sim=0.12,
                    trigger_conf=0.0,
                    fusion_score=0.88,
                    source_type="semantic",
                    why="semantic baseline",
                )
            ][:limit]

    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: _LowMatchRetriever())

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="embeddings_only",
        semantic_context_min=0.2,
        semantic_lexical_min=0.05,
        semantic_strong_override=0.95,
    )

    advice = advisor._get_semantic_cognitive_advice("Read", "auth token session retrieval failure in production")
    assert advice == []


def test_semantic_route_filters_x_social_insight_for_non_social_query(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _DomainMismatchRetriever:
        def retrieve(self, _query: str, _insights, limit: int = 8):
            return [
                SimpleNamespace(
                    insight_key="x-social-1",
                    insight_text="ALWAYS put multiplier granted on its own line in tweet replies",
                    semantic_sim=0.97,
                    trigger_conf=0.0,
                    fusion_score=0.97,
                    source_type="semantic",
                    why="semantic baseline",
                )
            ][:limit]

    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: _DomainMismatchRetriever())

    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="embeddings_only",
        semantic_context_min=0.1,
        semantic_lexical_min=0.0,
        semantic_strong_override=0.5,
    )

    advice = advisor._get_semantic_cognitive_advice("Read", "auth token session retrieval failure in production")
    assert advice == []


def test_advise_level_domain_filter_blocks_x_social_noise_across_sources(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    advisor = advisor_mod.SparkAdvisor()
    rows = [
        advisor_mod.Advice(
            advice_id="a1",
            insight_key="chip:x",
            text="[Chip:x] ALWAYS put multiplier granted on its own line in tweet replies",
            confidence=0.9,
            source="chip",
            context_match=0.9,
            reason="noise",
        ),
        advisor_mod.Advice(
            advice_id="a2",
            insight_key="chip:social-proof",
            text="Ensure cryptographic proof of AI identity in social networks before replies.",
            confidence=0.9,
            source="chip",
            context_match=0.9,
            reason="noise2",
        ),
        advisor_mod.Advice(
            advice_id="a3",
            insight_key="cognitive:y",
            text="Check auth session bindings before retrieval.",
            confidence=0.8,
            source="cognitive",
            context_match=0.8,
            reason="relevant",
        ),
    ]

    filtered = advisor._filter_cross_domain_advice(rows, "diagnose auth retrieval timeout in production")
    assert len(filtered) == 1
    assert filtered[0].insight_key == "cognitive:y"


def test_detect_retrieval_domain_prefers_context_signals(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    advisor = advisor_mod.SparkAdvisor()

    assert advisor._detect_retrieval_domain("Bash", "memory retrieval stale index issue across sessions") == "memory"
    assert advisor._detect_retrieval_domain("Read", "design a clean mobile ui layout with better typography") == "ui_design"
    assert advisor._detect_retrieval_domain("Edit", "fix python module traceback for auth token flow") == "coding"


def test_domain_profile_overrides_apply_when_enabled(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)

    class _DomainRetriever:
        def retrieve(self, _query: str, _insights, limit: int = 8):
            return [
                SimpleNamespace(
                    insight_key="memory-1",
                    insight_text="Use session-scoped retrieval checks before distillation.",
                    semantic_sim=0.25,
                    trigger_conf=0.0,
                    fusion_score=0.25,
                    source_type="semantic",
                    why="domain profile check",
                )
            ][:limit]

    monkeypatch.setattr(semantic_retriever_mod, "get_semantic_retriever", lambda: _DomainRetriever())
    advisor = advisor_mod.SparkAdvisor()
    advisor.retrieval_policy = _policy_with(
        advisor,
        mode="embeddings_only",
        semantic_context_min=0.95,
        semantic_lexical_min=0.95,
        semantic_intent_min=0.95,
        semantic_strong_override=0.99,
        domain_profile_enabled=True,
        domain_profiles={
            "memory": {
                "semantic_context_min": 0.0,
                "semantic_lexical_min": 0.0,
                "semantic_intent_min": 0.0,
            }
        },
    )

    advice = advisor._get_semantic_cognitive_advice("Bash", "memory retrieval stale index checks")
    route = _load_last_route(tmp_path / "retrieval_router.jsonl")

    assert advice
    assert route["active_domain"] == "memory"
    assert route["profile_domain"] == "memory"


def test_chip_advice_uses_quality_as_confidence_fallback(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(advisor_mod, "CHIP_INSIGHTS_DIR", tmp_path)
    monkeypatch.setattr(advisor_mod, "CHIP_ADVICE_MIN_SCORE", 0.35)
    chip_file = tmp_path / "marketing.jsonl"
    chip_row = {
        "chip_id": "marketing",
        "observer_name": "campaign_observer",
        "content": "Focus on conversion quality before scaling spend.",
        "captured_data": {"quality_score": {"total": 0.62}},
        # confidence intentionally omitted to validate score fallback.
    }
    chip_file.write_text(json.dumps(chip_row) + "\n", encoding="utf-8")

    advisor = advisor_mod.SparkAdvisor()
    out = advisor._get_chip_advice("marketing campaign conversion tuning")
    assert out
    assert out[0].source == "chip"


def test_chip_advice_blocks_telemetry_chips(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(advisor_mod, "CHIP_INSIGHTS_DIR", tmp_path)
    monkeypatch.setattr(advisor_mod, "CHIP_ADVICE_MIN_SCORE", 0.35)

    telemetry = {
        "chip_id": "spark-core",
        "observer_name": "post_tool",
        "content": "[Spark Core Intelligence] user_prompt_signal: event_type: post_tool",
        "confidence": 1.0,
        "captured_data": {"quality_score": {"total": 0.92}},
    }
    actionable = {
        "chip_id": "marketing",
        "observer_name": "campaign_observer",
        "content": "Prioritize conversion quality before scaling campaign spend.",
        "confidence": 0.88,
        "captured_data": {"quality_score": {"total": 0.72}},
    }
    (tmp_path / "spark-core.jsonl").write_text(json.dumps(telemetry) + "\n", encoding="utf-8")
    (tmp_path / "marketing.jsonl").write_text(json.dumps(actionable) + "\n", encoding="utf-8")

    advisor = advisor_mod.SparkAdvisor()
    out = advisor._get_chip_advice("marketing campaign conversion tuning")
    assert out
    joined = " | ".join(a.text.lower() for a in out)
    assert "spark core intelligence" not in joined
    assert "conversion quality" in joined


def test_chip_advice_can_be_disabled_by_env(monkeypatch, tmp_path):
    _patch_advisor_runtime(monkeypatch, tmp_path)
    monkeypatch.setenv("SPARK_ADVISORY_DISABLE_CHIPS", "1")
    monkeypatch.setattr(advisor_mod, "CHIP_INSIGHTS_DIR", tmp_path)
    monkeypatch.setattr(advisor_mod, "CHIP_ADVICE_MIN_SCORE", 0.35)
    row = {
        "chip_id": "marketing",
        "observer_name": "campaign_observer",
        "content": "Prioritize conversion quality before scaling campaign spend.",
        "confidence": 0.9,
        "captured_data": {"quality_score": {"total": 0.8}},
    }
    (tmp_path / "marketing.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    advisor = advisor_mod.SparkAdvisor()
    out = advisor._get_chip_advice("marketing campaign conversion tuning")
    assert out == []
