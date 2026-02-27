from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[1]
    mod_path = root / "scripts" / "advisory_self_review.py"
    spec = importlib.util.spec_from_file_location("advisory_self_review", mod_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summarize_recent_advice_counts_trace_and_repeats(tmp_path):
    mod = _load_module()
    now = time.time()
    p = tmp_path / "recent_advice.jsonl"
    rows = [
        {
            "ts": now - 60,
            "trace_id": "abc123",
            "sources": ["cognitive", "self_awareness"],
            "advice_texts": ["repeat me", "repeat me"],
            "tool": "Edit",
        },
        {
            "ts": now - 30,
            "trace_id": None,
            "sources": ["mind"],
            "advice_texts": ["other"],
            "tool": "Read",
        },
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    out = mod.summarize_recent_advice(p, window_s=3600, now_ts=now)
    assert out["rows"] == 2
    assert out["excluded"] == 0
    assert out["trace_rows"] == 1
    assert out["item_total"] == 3
    assert out["sources"]["cognitive"] == 1
    assert out["sources"]["mind"] == 1
    assert out["repeated_texts"][0]["text"] == "repeat me"
    assert out["repeated_texts"][0]["count"] == 2

    # Exclude rows by trace prefix (used to remove benchmark traffic).
    out2 = mod.summarize_recent_advice(
        p,
        window_s=3600,
        now_ts=now,
        exclude_trace_prefixes=["abc"],
    )
    assert out2["rows"] == 1
    assert out2["excluded"] == 1


def test_summarize_engine_and_outcomes(tmp_path):
    mod = _load_module()
    now = time.time()

    engine_path = tmp_path / "advisory_engine.jsonl"
    engine_rows = [
        {"ts": now - 10, "event": "emitted", "route": "live", "trace_id": "t1"},
        {"ts": now - 9, "event": "fallback_emit", "route": "packet_relaxed_fallback"},
        {"ts": now - 8, "event": "fallback_emit", "route": "packet_relaxed_fallback"},
    ]
    engine_path.write_text(
        "\n".join(json.dumps(r) for r in engine_rows) + "\n",
        encoding="utf-8",
    )

    eng = mod.summarize_engine(engine_path, window_s=3600, now_ts=now)
    assert eng["rows"] == 3
    assert eng["events"]["fallback_emit"] == 2
    assert eng["fallback_share_pct"] > 60.0
    assert eng["suppression_events"] == 0
    assert eng["suppression_share_pct"] == 0.0

    outcome_path = tmp_path / "outcome_tracking.json"
    records = [
        {
            "retrieved_at": now - 20,
            "source": "cognitive",
            "outcome": "good",
            "trace_id": "x1",
            "outcome_trace_id": "x1",
            "insight_key": "k1",
            "learning_content": "good content",
        },
        {
            "retrieved_at": now - 20,
            "source": "auto_created",
            "outcome": "bad",
            "trace_id": "x2",
            "outcome_trace_id": "x2",
            "insight_key": None,
            "learning_content": "tool:WebFetch",
        },
        {
            "retrieved_at": now - 20,
            "source": "cognitive",
            "outcome": "good",
            "trace_id": "x3",
            "outcome_trace_id": "mismatch",
            "insight_key": "k3",
            "learning_content": "mismatch content",
        },
    ]
    outcome_path.write_text(json.dumps({"records": records}), encoding="utf-8")
    out = mod.summarize_outcomes(outcome_path, window_s=3600, now_ts=now)
    assert out["records"] == 3
    assert out["trace_mismatch_count"] == 1
    assert out["strict_action_rate"] == 0.6667
    assert len(out["bad_records"]) == 1
