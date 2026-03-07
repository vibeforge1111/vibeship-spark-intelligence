"""Tests for lib/events.py — SparkEventV1 schema and validation."""
from __future__ import annotations

import time

import pytest

from lib.events import (
    SparkEventKind,
    SparkEventV1,
    validate_event_dict,
)


# ---------------------------------------------------------------------------
# SparkEventKind
# ---------------------------------------------------------------------------

class TestSparkEventKind:
    def test_four_members(self):
        assert len(SparkEventKind) == 4

    def test_message_value(self):
        assert SparkEventKind.MESSAGE.value == "message"

    def test_tool_value(self):
        assert SparkEventKind.TOOL.value == "tool"

    def test_command_value(self):
        assert SparkEventKind.COMMAND.value == "command"

    def test_system_value(self):
        assert SparkEventKind.SYSTEM.value == "system"

    def test_is_str_subclass(self):
        # str Enum — kind can be compared directly to strings
        assert SparkEventKind.MESSAGE == "message"

    def test_lookup_by_value(self):
        assert SparkEventKind("tool") is SparkEventKind.TOOL


# ---------------------------------------------------------------------------
# SparkEventV1.to_dict
# ---------------------------------------------------------------------------

class TestSparkEventV1ToDict:
    def _event(self, **kwargs):
        defaults = dict(
            v=1, source="clawdbot", kind=SparkEventKind.MESSAGE,
            ts=1700000000.0, session_id="sess-1", payload={"text": "hi"},
        )
        defaults.update(kwargs)
        return SparkEventV1(**defaults)

    def test_has_required_keys(self):
        d = self._event().to_dict()
        for key in ("v", "source", "kind", "ts", "session_id", "payload", "trace_id"):
            assert key in d

    def test_kind_serialized_as_string(self):
        d = self._event(kind=SparkEventKind.TOOL).to_dict()
        assert d["kind"] == "tool"
        assert isinstance(d["kind"], str)

    def test_version_is_1(self):
        assert self._event().to_dict()["v"] == 1

    def test_trace_id_none_by_default(self):
        assert self._event().to_dict()["trace_id"] is None

    def test_trace_id_included_when_set(self):
        d = self._event(trace_id="tid-42").to_dict()
        assert d["trace_id"] == "tid-42"

    def test_payload_preserved(self):
        d = self._event(payload={"foo": "bar"}).to_dict()
        assert d["payload"] == {"foo": "bar"}

    def test_source_preserved(self):
        d = self._event(source="claude_code").to_dict()
        assert d["source"] == "claude_code"


# ---------------------------------------------------------------------------
# SparkEventV1.from_dict
# ---------------------------------------------------------------------------

class TestSparkEventV1FromDict:
    def _base(self, **kwargs):
        d = dict(v=1, source="clawdbot", kind="message",
                 ts=1700000000.0, session_id="sess-1", payload={"k": 1})
        d.update(kwargs)
        return d

    def test_round_trip(self):
        ev = SparkEventV1(v=1, source="webhook", kind=SparkEventKind.COMMAND,
                          ts=1700000000.0, session_id="s", payload={"x": 2})
        ev2 = SparkEventV1.from_dict(ev.to_dict())
        assert ev2.source == ev.source
        assert ev2.kind == ev.kind
        assert ev2.session_id == ev.session_id

    def test_unsupported_version_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            SparkEventV1.from_dict(self._base(v=2))

    def test_zero_version_raises(self):
        with pytest.raises(ValueError):
            SparkEventV1.from_dict(self._base(v=0))

    def test_missing_source_defaults_unknown(self):
        d = self._base()
        del d["source"]
        ev = SparkEventV1.from_dict(d)
        assert ev.source == "unknown"

    def test_missing_session_id_defaults_unknown(self):
        d = self._base()
        del d["session_id"]
        ev = SparkEventV1.from_dict(d)
        assert ev.session_id == "unknown"

    def test_missing_ts_defaults_zero(self):
        d = self._base()
        del d["ts"]
        ev = SparkEventV1.from_dict(d)
        assert ev.ts == 0.0

    def test_missing_payload_defaults_empty(self):
        d = self._base()
        del d["payload"]
        ev = SparkEventV1.from_dict(d)
        assert ev.payload == {}

    def test_trace_id_none_when_absent(self):
        ev = SparkEventV1.from_dict(self._base())
        assert ev.trace_id is None

    def test_trace_id_set_when_present(self):
        ev = SparkEventV1.from_dict(self._base(trace_id="t99"))
        assert ev.trace_id == "t99"

    def test_all_kinds_parsed(self):
        for kind_str in ("message", "tool", "command", "system"):
            ev = SparkEventV1.from_dict(self._base(kind=kind_str))
            assert ev.kind.value == kind_str


# ---------------------------------------------------------------------------
# validate_event_dict
# ---------------------------------------------------------------------------

class TestValidateEventDict:
    def _valid(self, **kwargs):
        d = dict(v=1, source="clawdbot", kind="message",
                 ts=1700000000.0, session_id="sess-1", payload={"x": 1})
        d.update(kwargs)
        return d

    def test_valid_dict_returns_true(self):
        ok, reason = validate_event_dict(self._valid())
        assert ok is True
        assert reason == ""

    def test_non_dict_returns_false(self):
        ok, reason = validate_event_dict("not a dict")  # type: ignore[arg-type]
        assert ok is False
        assert reason == "not_object"

    def test_missing_v(self):
        d = self._valid()
        del d["v"]
        ok, reason = validate_event_dict(d)
        assert ok is False
        assert "missing_v" in reason

    def test_missing_source(self):
        d = self._valid()
        del d["source"]
        ok, reason = validate_event_dict(d)
        assert ok is False
        assert "missing_source" in reason

    def test_missing_kind(self):
        d = self._valid()
        del d["kind"]
        ok, reason = validate_event_dict(d)
        assert ok is False
        assert "missing_kind" in reason

    def test_missing_ts(self):
        d = self._valid()
        del d["ts"]
        ok, reason = validate_event_dict(d)
        assert ok is False
        assert "missing_ts" in reason

    def test_missing_session_id(self):
        d = self._valid()
        del d["session_id"]
        ok, reason = validate_event_dict(d)
        assert ok is False
        assert "missing_session_id" in reason

    def test_missing_payload(self):
        d = self._valid()
        del d["payload"]
        ok, reason = validate_event_dict(d)
        assert ok is False
        assert "missing_payload" in reason

    def test_unsupported_version(self):
        ok, reason = validate_event_dict(self._valid(v=2))
        assert ok is False
        assert reason == "unsupported_version"

    def test_invalid_version_non_numeric(self):
        ok, reason = validate_event_dict(self._valid(v="bad"))
        assert ok is False

    def test_invalid_source_empty_string(self):
        ok, reason = validate_event_dict(self._valid(source=""))
        assert ok is False
        assert reason == "invalid_source"

    def test_invalid_source_non_string(self):
        ok, reason = validate_event_dict(self._valid(source=123))
        assert ok is False
        assert reason == "invalid_source"

    def test_invalid_kind(self):
        ok, reason = validate_event_dict(self._valid(kind="unknown_kind"))
        assert ok is False
        assert reason == "invalid_kind"

    def test_valid_kinds_accepted(self):
        for kind in ("message", "tool", "command", "system"):
            ok, _ = validate_event_dict(self._valid(kind=kind))
            assert ok is True, f"Expected kind={kind!r} to be valid"

    def test_invalid_ts_zero(self):
        ok, reason = validate_event_dict(self._valid(ts=0))
        assert ok is False
        assert reason == "invalid_ts"

    def test_invalid_ts_negative(self):
        ok, reason = validate_event_dict(self._valid(ts=-1.0))
        assert ok is False
        assert reason == "invalid_ts"

    def test_invalid_ts_string(self):
        ok, reason = validate_event_dict(self._valid(ts="not_a_float"))
        assert ok is False
        assert reason == "invalid_ts"

    def test_invalid_payload_non_dict(self):
        ok, reason = validate_event_dict(self._valid(payload=[1, 2, 3]))
        assert ok is False
        assert reason == "invalid_payload"

    def test_strict_true_rejects_none_payload(self):
        ok, reason = validate_event_dict(self._valid(payload=None), strict=True)
        assert ok is False
        assert reason == "missing_payload"

    def test_strict_false_accepts_none_payload(self):
        # strict=False allows payload=None (key present, value None)
        ok, reason = validate_event_dict(self._valid(payload=None), strict=False)
        assert ok is True

    def test_missing_payload_key_always_fails(self):
        # Missing key fails regardless of strict flag
        d = self._valid()
        del d["payload"]
        ok, reason = validate_event_dict(d, strict=False)
        assert ok is False
        assert "missing_payload" in reason

    def test_empty_payload_dict_valid(self):
        ok, _ = validate_event_dict(self._valid(payload={}))
        assert ok is True

    def test_invalid_session_id_empty(self):
        ok, reason = validate_event_dict(self._valid(session_id="  "))
        assert ok is False
        assert reason == "invalid_session_id"
