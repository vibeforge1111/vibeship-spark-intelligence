from pathlib import Path
import importlib.util


def _load_module():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "check_pr5_readiness.py"
    spec = importlib.util.spec_from_file_location("check_pr5_readiness", script)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_route_mix_summary_uses_reasons_fallback():
    mod = _load_module()
    out = mod._route_mix_summary(
        [
            {"route": "semantic", "reasons": ["empty_primary"]},
            {"route": "semantic", "reason": "primary_semantic_only"},
        ]
    )
    reason_mix = out.get("reason_mix") or {}
    assert reason_mix.get("empty_primary") == 1
    assert reason_mix.get("primary_semantic_only") == 1
    assert float(out.get("unknown_reason_rate") or 0.0) == 0.0


def test_route_mix_summary_tracks_empty_and_unknown_rates():
    mod = _load_module()
    out = mod._route_mix_summary(
        [
            {"route": "empty", "reason": ""},
            {"route": "", "reason": "known"},
            {},
        ]
    )
    assert out.get("rows") == 3
    assert out.get("empty_route_count") == 1
    assert out.get("missing_route_fields") == 2
    assert out.get("missing_reason_fields") == 2
    assert abs(float(out.get("empty_route_rate") or 0.0) - (1 / 3)) < 1e-9
    assert abs(float(out.get("unknown_reason_rate") or 0.0) - (2 / 3)) < 1e-9


def test_semantic_context_summary_buckets_rows():
    mod = _load_module()
    out = mod._semantic_context_summary(
        [
            {"embedding_available": False, "semantic_candidates_count": 0, "final_results": []},
            {"embedding_available": True, "semantic_candidates_count": 0, "final_results": []},
            {"embedding_available": False, "semantic_candidates_count": 4, "final_results": []},
            {"embedding_available": False, "semantic_candidates_count": 2, "final_results": [{"id": 1}], "rescue_used": True},
        ]
    )
    buckets = out.get("empty_context_buckets") or {}
    assert buckets.get("no_embeddings_no_keyword_overlap") == 1
    assert buckets.get("embed_enabled_no_candidates") == 1
    assert buckets.get("gated_or_filtered_after_candidates") == 1
    assert buckets.get("non_empty") == 1
    assert out.get("rescue_used_count") == 1
