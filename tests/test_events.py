"""Tests for lib/events.py

Covers:
- SparkEventKind: all four enum values present, is a str-enum
- SparkEventV1.to_dict(): all keys present, kind serialized as string value
- SparkEventV1.from_dict(): round-trip, coercion of missing/None fields,
  optional trace_id handling, wrong version raises ValueError
- validate_event_dict(): happy-path returns (True, ""), each required field
  missing returns (False, "missing_<field>"), invalid source/kind/session_id/
  ts/payload all return specific error codes, strict=False allows None payload
"""

from __future__ import annotations

import pytest

from lib.events import SparkEventKind, SparkEventV1, validate_event_dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_dict(**overrides) -> dict:
    base = {
        "v": 1,
        "source": "clawdbot",
        "kind": "message",
        "ts": 1_700_000_000.0,
        "session_id": "sess-abc",
        "payload": {"text": "hello"},
    }
    base.update(overrides)
    return base


def _valid_event(**overrides) -> SparkEventV1:
    kwargs = {
        "v": 1,
        "source": "clawdbot",
        "kind": SparkEventKind.MESSAGE,
        "ts": 1_700_000_000.0,
        "session_id": "sess-abc",
        "payload": {"text": "hello"},
    }
    kwargs.update(overrides)
    return SparkEventV1(**kwargs)


# ---------------------------------------------------------------------------
# SparkEventKind
# ---------------------------------------------------------------------------

def test_kind_message_value():
    assert SparkEventKind.MESSAGE.value == "message"


def test_kind_tool_value():
    assert SparkEventKind.TOOL.value == "tool"


def test_kind_command_value():
    assert SparkEventKind.COMMAND.value == "command"


def test_kind_system_value():
    assert SparkEventKind.SYSTEM.value == "system"


def test_kind_is_str_subclass():
    assert isinstance(SparkEventKind.MESSAGE, str)


def test_kind_has_four_members():
    assert len(SparkEventKind) == 4


def test_kind_from_string():
    assert SparkEventKind("tool") is SparkEventKind.TOOL


def test_kind_invalid_raises():
    with pytest.raises(ValueError):
        SparkEventKind("unknown")


# ---------------------------------------------------------------------------
# SparkEventV1.to_dict()
# ---------------------------------------------------------------------------

def test_to_dict_returns_dict():
    assert isinstance(_valid_event().to_dict(), dict)


def test_to_dict_has_v_key():
    assert _valid_event().to_dict()["v"] == 1


def test_to_dict_has_source():
    assert _valid_event().to_dict()["source"] == "clawdbot"


def test_to_dict_has_kind_as_string():
    assert _valid_event().to_dict()["kind"] == "message"


def test_to_dict_kind_is_string_not_enum():
    result = _valid_event().to_dict()
    assert isinstance(result["kind"], str)
    assert not isinstance(result["kind"], SparkEventKind)


def test_to_dict_has_ts():
    assert _valid_event().to_dict()["ts"] == 1_700_000_000.0


def test_to_dict_has_session_id():
    assert _valid_event().to_dict()["session_id"] == "sess-abc"


def test_to_dict_has_payload():
    assert _valid_event().to_dict()["payload"] == {"text": "hello"}


def test_to_dict_trace_id_none_by_default():
    assert _valid_event().to_dict()["trace_id"] is None


def test_to_dict_trace_id_included_when_set():
    e = _valid_event(trace_id="abc-123")
    assert e.to_dict()["trace_id"] == "abc-123"


def test_to_dict_has_all_seven_keys():
    keys = set(_valid_event().to_dict().keys())
    assert keys == {"v", "source", "kind", "ts", "session_id", "payload", "trace_id"}


# ---------------------------------------------------------------------------
# SparkEventV1.from_dict() — happy path
# ---------------------------------------------------------------------------

def test_from_dict_returns_event():
    assert isinstance(SparkEventV1.from_dict(_valid_dict()), SparkEventV1)


def test_from_dict_v_is_1():
    assert SparkEventV1.from_dict(_valid_dict()).v == 1


def test_from_dict_source():
    assert SparkEventV1.from_dict(_valid_dict()).source == "clawdbot"


def test_from_dict_kind_is_enum():
    e = SparkEventV1.from_dict(_valid_dict())
    assert e.kind is SparkEventKind.MESSAGE


def test_from_dict_ts():
    e = SparkEventV1.from_dict(_valid_dict())
    assert e.ts == 1_700_000_000.0


def test_from_dict_session_id():
    assert SparkEventV1.from_dict(_valid_dict()).session_id == "sess-abc"


def test_from_dict_payload():
    e = SparkEventV1.from_dict(_valid_dict())
    assert e.payload == {"text": "hello"}


def test_from_dict_trace_id_none_when_absent():
    e = SparkEventV1.from_dict(_valid_dict())
    assert e.trace_id is None


def test_from_dict_trace_id_present():
    e = SparkEventV1.from_dict(_valid_dict(trace_id="x-99"))
    assert e.trace_id == "x-99"


# ---------------------------------------------------------------------------
# SparkEventV1.from_dict() — round-trip
# ---------------------------------------------------------------------------

def test_from_dict_roundtrip_source():
    original = _valid_event()
    restored = SparkEventV1.from_dict(original.to_dict())
    assert restored.source == original.source


def test_from_dict_roundtrip_kind():
    original = _valid_event(kind=SparkEventKind.TOOL)
    restored = SparkEventV1.from_dict(original.to_dict())
    assert restored.kind is SparkEventKind.TOOL


def test_from_dict_roundtrip_ts():
    original = _valid_event()
    restored = SparkEventV1.from_dict(original.to_dict())
    assert restored.ts == original.ts


def test_from_dict_roundtrip_payload():
    original = _valid_event()
    restored = SparkEventV1.from_dict(original.to_dict())
    assert restored.payload == original.payload


def test_from_dict_roundtrip_trace_id():
    original = _valid_event(trace_id="tid-42")
    restored = SparkEventV1.from_dict(original.to_dict())
    assert restored.trace_id == "tid-42"


# ---------------------------------------------------------------------------
# SparkEventV1.from_dict() — coercion of missing / None fields
# ---------------------------------------------------------------------------

def test_from_dict_missing_source_coerces_to_unknown():
    d = _valid_dict()
    del d["source"]
    e = SparkEventV1.from_dict(d)
    assert e.source == "unknown"


def test_from_dict_none_source_coerces_to_unknown():
    e = SparkEventV1.from_dict(_valid_dict(source=None))
    assert e.source == "unknown"


def test_from_dict_missing_session_id_coerces():
    d = _valid_dict()
    del d["session_id"]
    e = SparkEventV1.from_dict(d)
    assert e.session_id == "unknown"


def test_from_dict_missing_ts_coerces_to_zero():
    d = _valid_dict()
    del d["ts"]
    e = SparkEventV1.from_dict(d)
    assert e.ts == 0.0


def test_from_dict_missing_payload_coerces_to_empty_dict():
    d = _valid_dict()
    del d["payload"]
    e = SparkEventV1.from_dict(d)
    assert e.payload == {}


def test_from_dict_missing_kind_coerces_to_system():
    d = _valid_dict()
    del d["kind"]
    e = SparkEventV1.from_dict(d)
    assert e.kind is SparkEventKind.SYSTEM


# ---------------------------------------------------------------------------
# SparkEventV1.from_dict() — version validation
# ---------------------------------------------------------------------------

def test_from_dict_wrong_version_raises():
    with pytest.raises(ValueError):
        SparkEventV1.from_dict(_valid_dict(v=2))


def test_from_dict_version_0_raises():
    with pytest.raises(ValueError):
        SparkEventV1.from_dict(_valid_dict(v=0))


def test_from_dict_missing_version_raises():
    d = _valid_dict()
    del d["v"]
    with pytest.raises(ValueError):
        SparkEventV1.from_dict(d)


# ---------------------------------------------------------------------------
# validate_event_dict() — happy path
# ---------------------------------------------------------------------------

def test_validate_valid_returns_true():
    ok, msg = validate_event_dict(_valid_dict())
    assert ok is True


def test_validate_valid_returns_empty_message():
    ok, msg = validate_event_dict(_valid_dict())
    assert msg == ""


def test_validate_returns_tuple():
    result = validate_event_dict(_valid_dict())
    assert isinstance(result, tuple) and len(result) == 2


# ---------------------------------------------------------------------------
# validate_event_dict() — not a dict
# ---------------------------------------------------------------------------

def test_validate_not_dict_returns_false():
    ok, _ = validate_event_dict("not a dict")
    assert ok is False


def test_validate_not_dict_returns_not_object():
    _, msg = validate_event_dict([1, 2, 3])
    assert msg == "not_object"


# ---------------------------------------------------------------------------
# validate_event_dict() — missing required fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["v", "source", "kind", "ts", "session_id", "payload"])
def test_validate_missing_field(field):
    d = _valid_dict()
    del d[field]
    ok, msg = validate_event_dict(d)
    assert ok is False
    assert msg == f"missing_{field}"


# ---------------------------------------------------------------------------
# validate_event_dict() — version
# ---------------------------------------------------------------------------

def test_validate_wrong_version_returns_unsupported():
    ok, msg = validate_event_dict(_valid_dict(v=2))
    assert ok is False
    assert msg == "unsupported_version"


def test_validate_non_numeric_version_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(v="abc"))
    assert ok is False
    assert "version" in msg


# ---------------------------------------------------------------------------
# validate_event_dict() — source
# ---------------------------------------------------------------------------

def test_validate_empty_source_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(source=""))
    assert ok is False
    assert msg == "invalid_source"


def test_validate_whitespace_source_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(source="   "))
    assert ok is False
    assert msg == "invalid_source"


def test_validate_non_string_source_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(source=123))
    assert ok is False
    assert msg == "invalid_source"


# ---------------------------------------------------------------------------
# validate_event_dict() — kind
# ---------------------------------------------------------------------------

def test_validate_invalid_kind_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(kind="unknown_kind"))
    assert ok is False
    assert msg == "invalid_kind"


@pytest.mark.parametrize("kind", ["message", "tool", "command", "system"])
def test_validate_all_valid_kinds(kind):
    ok, _ = validate_event_dict(_valid_dict(kind=kind))
    assert ok is True


# ---------------------------------------------------------------------------
# validate_event_dict() — session_id
# ---------------------------------------------------------------------------

def test_validate_empty_session_id_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(session_id=""))
    assert ok is False
    assert msg == "invalid_session_id"


def test_validate_whitespace_session_id_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(session_id="   "))
    assert ok is False
    assert msg == "invalid_session_id"


# ---------------------------------------------------------------------------
# validate_event_dict() — ts
# ---------------------------------------------------------------------------

def test_validate_zero_ts_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(ts=0))
    assert ok is False
    assert msg == "invalid_ts"


def test_validate_negative_ts_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(ts=-1.0))
    assert ok is False
    assert msg == "invalid_ts"


def test_validate_non_numeric_ts_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(ts="yesterday"))
    assert ok is False
    assert msg == "invalid_ts"


# ---------------------------------------------------------------------------
# validate_event_dict() — payload
# ---------------------------------------------------------------------------

def test_validate_list_payload_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(payload=[1, 2, 3]))
    assert ok is False
    assert msg == "invalid_payload"


def test_validate_none_payload_strict_returns_invalid():
    ok, msg = validate_event_dict(_valid_dict(payload=None), strict=True)
    assert ok is False
    assert msg == "missing_payload"


def test_validate_none_payload_non_strict_returns_true():
    ok, _ = validate_event_dict(_valid_dict(payload=None), strict=False)
    assert ok is True


def test_validate_empty_dict_payload_is_valid():
    ok, _ = validate_event_dict(_valid_dict(payload={}))
    assert ok is True
