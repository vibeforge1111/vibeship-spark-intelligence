from __future__ import annotations

import importlib.util
import json
import sys
import time
import types
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
        {"ts": now - 9, "event": "gate_no_emit", "route": "packet_miss"},
        {"ts": now - 8, "event": "context_repeat_blocked", "route": "packet_relaxed"},
    ]
    engine_path.write_text(
        "\n".join(json.dumps(r) for r in engine_rows) + "\n",
        encoding="utf-8",
    )

    eng = mod.summarize_engine(engine_path, window_s=3600, now_ts=now)
    assert eng["rows"] == 3
    assert eng["events"]["gate_no_emit"] == 1
    assert eng["events"]["context_repeat_blocked"] == 1
    assert eng["suppression_events"] == 2
    assert eng["suppression_share_pct"] > 60.0

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


def test_generate_summary_nonbench_excludes_replay_and_delta(tmp_path, monkeypatch):
    mod = _load_module()
    now = time.time()
    spark_dir = tmp_path / "spark"
    advisor_dir = spark_dir / "advisor"
    advisor_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {"ts": now - 20, "trace_id": "arena:run-1", "sources": ["workflow"], "advice_texts": ["a1"]},
        {"ts": now - 15, "trace_id": "delta-smoke-1", "sources": ["eidos"], "advice_texts": ["a2"]},
        {"ts": now - 10, "trace_id": "live-trace-1", "sources": ["semantic"], "advice_texts": ["a3"]},
    ]
    (advisor_dir / "recent_advice.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )

    engine_log = spark_dir / "advisory_engine_alpha.jsonl"
    engine_log.write_text("", encoding="utf-8")
    (spark_dir / "meta_ralph").mkdir(parents=True, exist_ok=True)
    (spark_dir / "meta_ralph" / "outcome_tracking.json").write_text(
        json.dumps({"records": []}),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "SPARK_DIR", spark_dir)
    monkeypatch.setattr(mod, "ADVISORY_ENGINE_LOG", engine_log)

    summary = mod.generate_summary(window_hours=1.0)
    assert summary["recent_advice"]["rows"] == 3
    assert summary["recent_advice_nonbench"]["rows"] == 1
    assert summary["recent_advice_nonbench"]["excluded"] == 2


def test_generate_summary_includes_context_and_prompt(tmp_path, monkeypatch):
    mod = _load_module()
    now = time.time()
    spark_dir = tmp_path / "spark"
    (spark_dir / "advisor").mkdir(parents=True, exist_ok=True)
    (spark_dir / "logs").mkdir(parents=True, exist_ok=True)
    (spark_dir / "queue").mkdir(parents=True, exist_ok=True)
    (spark_dir / "meta_ralph").mkdir(parents=True, exist_ok=True)

    (spark_dir / "advisor" / "recent_advice.jsonl").write_text(
        json.dumps(
            {
                "ts": now - 20,
                "trace_id": "live-trace-x",
                "sources": ["cognitive"],
                "advice_texts": ["Prefer strict trace joins."],
                "tool": "Edit",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (spark_dir / "advisor" / "advisory_quality_events.jsonl").write_text(
        json.dumps(
            {
                "emitted_ts": now - 18,
                "trace_id": "live-trace-x",
                "advice_id": "aid-1",
                "provider": "codex",
                "tool": "Edit",
                "helpfulness_label": "helpful",
                "impact_score": 0.83,
                "timing_bucket": "right_on_time",
                "advice_text": "Prefer strict trace joins.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (spark_dir / "advisory_engine_alpha.jsonl").write_text(
        json.dumps({"ts": now - 19, "trace_id": "live-trace-x", "event": "emitted"}) + "\n",
        encoding="utf-8",
    )
    (spark_dir / "meta_ralph" / "outcome_tracking.json").write_text(
        json.dumps({"records": []}),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "SPARK_DIR", spark_dir)
    monkeypatch.setattr(mod, "ADVISORY_ENGINE_LOG", spark_dir / "advisory_engine_alpha.jsonl")

    summary = mod.generate_summary(window_hours=1.0)
    assert "stage_context" in summary
    assert "trace_storybook" in summary
    assert "passed_surpassed" in summary
    prompt = str(summary.get("hard_question_prompt") or "")
    assert "Hard questions you must answer" in prompt
    assert "Stages 1..9" in prompt


def test_external_review_marks_execution_error_as_not_ok(monkeypatch):
    mod = _load_module()
    monkeypatch.setitem(
        sys.modules,
        "lib.llm",
        types.SimpleNamespace(ask_claude=lambda *_args, **_kwargs: "Execution error"),
    )
    out = mod.run_external_context_review(
        prompt="review this",
        providers="claude",
        timeout_s=10.0,
    )
    assert out["results"]
    row = out["results"][0]
    assert row["provider"] == "claude"
    assert row["ok"] is False
    assert row["error"] == "response_error:provider_execution_error"


def test_evaluate_integrity_gates_detects_missing_surfaces(tmp_path):
    mod = _load_module()
    spark_dir = tmp_path / "spark"
    (spark_dir / "advisor").mkdir(parents=True, exist_ok=True)
    now = time.time()
    (spark_dir / "advisor" / "advisory_quality_events.jsonl").write_text(
        json.dumps({"emitted_ts": now - 30, "provider": "codex", "helpfulness_label": "unknown"}) + "\n",
        encoding="utf-8",
    )
    summary = {
        "window_hours": 4.0,
        "generated_at": mod._to_iso(now),
        "stage_context": {
            "stage_8_advisory": {
                "known_helpfulness": 0,
                "quality_events": 1,
            }
        },
    }
    report = mod.evaluate_integrity_gates(summary=summary, spark_dir=spark_dir)
    failed = set(report.get("failed_gate_ids") or [])
    assert "decision_ledger_present" in failed
    assert "helpfulness_events_present" in failed
    assert "explicit_feedback_present" in failed
    assert "quality_trace_coverage_floor" in failed
    assert "known_helpfulness_coverage_floor" in failed


def test_apply_gate_persistence_alerts_on_second_consecutive_window(tmp_path):
    mod = _load_module()
    state_file = tmp_path / "state.json"
    alert_file = tmp_path / "alerts" / "advisory_context_alerts.jsonl"
    gate_report = {
        "window_hours": 4.0,
        "failed_gate_ids": ["decision_ledger_present"],
        "blind_spots": ["decision ledger missing or empty"],
    }

    first = mod.apply_gate_persistence(
        gate_report=gate_report,
        state_file=state_file,
        persist_windows=2,
        alert_file=alert_file,
        alerts_enabled=True,
        now_ts=1000.0,
    )
    assert first["persistent_failed_gate_ids"] == []
    assert first["alert_written"] is False

    second = mod.apply_gate_persistence(
        gate_report=gate_report,
        state_file=state_file,
        persist_windows=2,
        alert_file=alert_file,
        alerts_enabled=True,
        now_ts=1000.0 + 5 * 3600.0,
    )
    assert second["persistent_failed_gate_ids"] == ["decision_ledger_present"]
    assert second["alert_written"] is True
    assert alert_file.exists()
