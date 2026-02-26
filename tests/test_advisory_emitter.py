"""Tests for lib/advisory_emitter.py — 50 tests."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import lib.advisory_emitter as ae


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision(advice_id: str, authority: str, reason: str = ""):
    return SimpleNamespace(advice_id=advice_id, authority=authority, reason=reason)


def _make_gate_result(emitted: list, phase: str = "pre"):
    return SimpleNamespace(emitted=emitted, phase=phase)


# ---------------------------------------------------------------------------
# format_advisory
# ---------------------------------------------------------------------------

class TestFormatAdvisory:
    def test_warning_produces_spark_advisory_prefix(self):
        out = ae.format_advisory("something important", "warning")
        assert out.startswith("[SPARK ADVISORY]")

    def test_note_produces_spark_prefix(self):
        out = ae.format_advisory("regular note", "note")
        assert out.startswith("[SPARK]")

    def test_whisper_produces_parenthetical(self):
        out = ae.format_advisory("quiet note", "whisper")
        assert out.startswith("(spark:")
        assert out.endswith(")")

    def test_silent_returns_empty_string(self):
        out = ae.format_advisory("hidden", "silent")
        assert out == ""

    def test_unknown_authority_returns_empty_string(self):
        out = ae.format_advisory("text", "block")
        assert out == ""

    def test_empty_text_returns_empty_string(self):
        assert ae.format_advisory("", "warning") == ""
        assert ae.format_advisory("   ", "note") == ""

    def test_text_truncated_to_max_chars(self, monkeypatch):
        monkeypatch.setattr(ae, "MAX_EMIT_CHARS", 50)
        long_text = "X" * 200
        out = ae.format_advisory(long_text, "note")
        # The prefix + content should be ≤ 50 + prefix overhead, content truncated
        assert "..." in out

    def test_whisper_truncated_at_150(self):
        long = "W" * 300
        out = ae.format_advisory(long, "whisper")
        # Extract content between parens
        inner = out[len("(spark: "):-1]
        assert inner.endswith("...")
        assert len(inner) <= 150

    def test_warning_content_in_output(self):
        out = ae.format_advisory("Watch out!", "warning")
        assert "Watch out!" in out

    def test_note_content_in_output(self):
        out = ae.format_advisory("FYI", "note")
        assert "FYI" in out

    def test_strips_whitespace_from_text(self):
        out = ae.format_advisory("  hello  ", "note")
        assert "hello" in out
        assert out == "[SPARK] hello"


# ---------------------------------------------------------------------------
# _highest_authority
# ---------------------------------------------------------------------------

class TestHighestAuthority:
    def test_block_beats_everything(self):
        decisions = [_make_decision("a", "warning"), _make_decision("b", "block")]
        assert ae._highest_authority(decisions) == "block"

    def test_warning_beats_note_and_whisper(self):
        decisions = [_make_decision("a", "note"), _make_decision("b", "whisper"),
                     _make_decision("c", "warning")]
        assert ae._highest_authority(decisions) == "warning"

    def test_note_beats_whisper(self):
        decisions = [_make_decision("a", "whisper"), _make_decision("b", "note")]
        assert ae._highest_authority(decisions) == "note"

    def test_all_silent_returns_silent(self):
        decisions = [_make_decision("a", "silent"), _make_decision("b", "silent")]
        assert ae._highest_authority(decisions) == "silent"

    def test_empty_list_returns_silent(self):
        assert ae._highest_authority([]) == "silent"

    def test_single_whisper(self):
        assert ae._highest_authority([_make_decision("a", "whisper")]) == "whisper"


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------

class TestEmit:
    def test_writes_to_stdout(self, monkeypatch):
        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        monkeypatch.setattr(ae, "EMIT_ENABLED", True)
        monkeypatch.setattr(ae, "EMIT_LOG", Path("/tmp/noop_emit.jsonl"))
        monkeypatch.setattr(ae, "_log_emission", lambda *a, **kw: None)
        result = ae.emit("Hello Claude")
        assert result is True
        assert "Hello Claude" in captured.getvalue()

    def test_returns_false_when_disabled(self, monkeypatch):
        monkeypatch.setattr(ae, "EMIT_ENABLED", False)
        assert ae.emit("Test") is False

    def test_returns_false_on_empty_text(self, monkeypatch):
        monkeypatch.setattr(ae, "EMIT_ENABLED", True)
        assert ae.emit("") is False
        assert ae.emit("   ") is False

    def test_text_truncated_to_max_chars(self, monkeypatch, tmp_path):
        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        monkeypatch.setattr(ae, "EMIT_ENABLED", True)
        monkeypatch.setattr(ae, "MAX_EMIT_CHARS", 20)
        monkeypatch.setattr(ae, "_log_emission", lambda *a, **kw: None)
        ae.emit("A" * 100)
        output = captured.getvalue().strip()
        assert len(output) <= 23  # 20 + "..."

    def test_stdout_error_returns_false(self, monkeypatch):
        class FailingIO:
            def write(self, *a): raise OSError("broken pipe")
            def flush(self): pass
        monkeypatch.setattr(sys, "stdout", FailingIO())
        monkeypatch.setattr(ae, "EMIT_ENABLED", True)
        monkeypatch.setattr(ae, "log_debug", lambda *a: None)
        result = ae.emit("test")
        assert result is False


# ---------------------------------------------------------------------------
# _log_emission / _rotate_log
# ---------------------------------------------------------------------------

class TestLogEmission:
    def test_creates_jsonl_entry(self, tmp_path, monkeypatch):
        log = tmp_path / "emit.jsonl"
        monkeypatch.setattr(ae, "EMIT_LOG", log)
        ae._log_emission("hello")
        entry = json.loads(log.read_text().splitlines()[0])
        assert entry["text"] == "hello"
        assert entry["chars"] == 5

    def test_metadata_included(self, tmp_path, monkeypatch):
        log = tmp_path / "emit.jsonl"
        monkeypatch.setattr(ae, "EMIT_LOG", log)
        ae._log_emission("hi", metadata={"tool_name": "Bash", "authority": "note"})
        entry = json.loads(log.read_text().splitlines()[0])
        assert entry["tool_name"] == "Bash"

    def test_none_metadata_values_excluded(self, tmp_path, monkeypatch):
        log = tmp_path / "emit.jsonl"
        monkeypatch.setattr(ae, "EMIT_LOG", log)
        ae._log_emission("hi", metadata={"tool_name": None, "route": None})
        entry = json.loads(log.read_text().splitlines()[0])
        assert "tool_name" not in entry
        assert "route" not in entry


class TestRotateLog:
    def test_keeps_only_max_lines(self, tmp_path, monkeypatch):
        log = tmp_path / "emit.jsonl"
        monkeypatch.setattr(ae, "EMIT_LOG", log)
        monkeypatch.setattr(ae, "EMIT_LOG_MAX_LINES", 10)
        lines = [json.dumps({"ts": i, "text": "x", "chars": 1}) for i in range(50)]
        log.write_text("\n".join(lines) + "\n")
        ae._rotate_log()
        kept = log.read_text().strip().splitlines()
        assert len(kept) <= 10

    def test_no_op_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae, "EMIT_LOG", tmp_path / "nope.jsonl")
        ae._rotate_log()  # Should not raise


# ---------------------------------------------------------------------------
# get_emission_stats
# ---------------------------------------------------------------------------

class TestGetEmissionStats:
    def test_returns_defaults_when_no_log(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae, "EMIT_LOG", tmp_path / "nope.jsonl")
        stats = ae.get_emission_stats()
        assert stats["total_emissions"] == 0
        assert stats["recent_emissions"] == []

    def test_counts_log_lines(self, tmp_path, monkeypatch):
        log = tmp_path / "emit.jsonl"
        lines = [json.dumps({"ts": i, "text": "x", "chars": 1}) for i in range(7)]
        log.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(ae, "EMIT_LOG", log)
        stats = ae.get_emission_stats()
        assert stats["total_emissions"] == 7

    def test_recent_emissions_capped_at_5(self, tmp_path, monkeypatch):
        log = tmp_path / "emit.jsonl"
        lines = [json.dumps({"ts": i, "text": f"msg{i}", "chars": 4}) for i in range(20)]
        log.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(ae, "EMIT_LOG", log)
        stats = ae.get_emission_stats()
        assert len(stats["recent_emissions"]) <= 5

    def test_enabled_flag_in_stats(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ae, "EMIT_LOG", tmp_path / "nope.jsonl")
        monkeypatch.setattr(ae, "EMIT_ENABLED", True)
        stats = ae.get_emission_stats()
        assert stats["enabled"] is True


# ---------------------------------------------------------------------------
# format_from_gate_result
# ---------------------------------------------------------------------------

class TestFormatFromGateResult:
    def test_returns_empty_when_gate_result_none(self):
        assert ae.format_from_gate_result(None, "text") == ""

    def test_returns_empty_when_no_emitted(self):
        gr = _make_gate_result([])
        assert ae.format_from_gate_result(gr, "text") == ""

    def test_uses_synthesized_text_when_present(self, monkeypatch):
        monkeypatch.setattr(ae, "MAX_EMIT_CHARS", 500)
        gr = _make_gate_result([_make_decision("a1", "note", "reason")])
        out = ae.format_from_gate_result(gr, "Use Y instead of X")
        assert "Use Y instead of X" in out

    def test_highest_authority_used_for_formatting(self, monkeypatch):
        monkeypatch.setattr(ae, "MAX_EMIT_CHARS", 500)
        gr = _make_gate_result([
            _make_decision("a", "whisper", "quiet"),
            _make_decision("b", "warning", "loud"),
        ])
        out = ae.format_from_gate_result(gr, "Alert text")
        assert "[SPARK ADVISORY]" in out  # warning level


# ---------------------------------------------------------------------------
# emit_advisory
# ---------------------------------------------------------------------------

class TestEmitAdvisory:
    def test_returns_false_when_no_gate_result(self):
        assert ae.emit_advisory(None, "text") is False

    def test_returns_false_when_no_emitted(self):
        gr = _make_gate_result([])
        assert ae.emit_advisory(gr, "text") is False

    def test_emits_synthesized_text(self, monkeypatch):
        emitted_texts = []
        monkeypatch.setattr(ae, "emit", lambda text, **kw: (emitted_texts.append(text), True)[1])
        monkeypatch.setattr(ae, "MAX_EMIT_CHARS", 500)
        gr = _make_gate_result([_make_decision("a", "note")])
        result = ae.emit_advisory(gr, "Great advice here", trace_id="t1")
        assert result is True
        assert len(emitted_texts) == 1
        assert "Great advice here" in emitted_texts[0]

    def test_fallback_to_advice_items_when_no_synthesis(self, monkeypatch):
        emitted_texts = []
        monkeypatch.setattr(ae, "emit", lambda text, **kw: (emitted_texts.append(text), True)[1])
        monkeypatch.setattr(ae, "MAX_EMIT_CHARS", 500)

        d = _make_decision("id1", "note")
        gr = _make_gate_result([d])

        item = SimpleNamespace(advice_id="id1", text="Fallback advice text")
        result = ae.emit_advisory(gr, "", advice_items=[item])
        assert result is True
        assert any("Fallback advice text" in t for t in emitted_texts)

    def test_returns_false_when_no_matching_items(self, monkeypatch):
        monkeypatch.setattr(ae, "emit", lambda *a, **kw: True)
        monkeypatch.setattr(ae, "MAX_EMIT_CHARS", 500)

        d = _make_decision("unmatched-id", "note")
        gr = _make_gate_result([d])
        result = ae.emit_advisory(gr, "", advice_items=[])
        assert result is False
