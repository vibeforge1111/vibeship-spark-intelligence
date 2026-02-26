"""Tests for lib/tuneables_schema.py

Covers:
- _validate_value(): all type branches (int, float, bool, str, dict, list,
  unknown), coercion, clamping, enum validation, invalid fallback to default
- validate_tuneables(): clean pass, missing sections/keys filled with defaults,
  out-of-bounds clamping, unknown sections/keys warned, non-dict sections
  replaced by defaults, updated_at always preserved, _doc_key_sections
  exemption, underscore-prefixed keys silenced, ValidationResult.ok property
- get_section_defaults(): correct structure and values for known/unknown sections
- get_full_defaults(): complete dict matching SCHEMA structure
"""

from __future__ import annotations

import pytest

from lib.tuneables_schema import (
    SCHEMA,
    TuneableSpec,
    ValidationResult,
    _validate_value,
    get_full_defaults,
    get_section_defaults,
    validate_tuneables,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(typ, default, min_val=None, max_val=None, enum_values=None):
    return TuneableSpec(typ, default, min_val, max_val, "", enum_values)


# ---------------------------------------------------------------------------
# _validate_value — int
# ---------------------------------------------------------------------------

def test_validate_value_int_valid():
    spec = _make_spec("int", 5, 1, 10)
    val, warn = _validate_value("s", "k", 7, spec)
    assert val == 7
    assert warn is None


def test_validate_value_int_coerce_from_string():
    spec = _make_spec("int", 5, 1, 10)
    val, warn = _validate_value("s", "k", "3", spec)
    assert val == 3
    assert warn is None


def test_validate_value_int_coerce_from_float():
    spec = _make_spec("int", 5, 1, 10)
    val, warn = _validate_value("s", "k", 4.9, spec)
    assert val == 4
    assert warn is None


def test_validate_value_int_below_min_clamped():
    spec = _make_spec("int", 5, 1, 10)
    val, warn = _validate_value("s", "k", 0, spec)
    assert val == 1
    assert warn is not None
    assert "clamped" in warn.lower()


def test_validate_value_int_above_max_clamped():
    spec = _make_spec("int", 5, 1, 10)
    val, warn = _validate_value("s", "k", 99, spec)
    assert val == 10
    assert warn is not None
    assert "clamped" in warn.lower()


def test_validate_value_int_invalid_falls_back_to_default():
    spec = _make_spec("int", 5, 1, 10)
    val, warn = _validate_value("s", "k", "not_a_number", spec)
    assert val == 5
    assert warn is not None
    assert "default" in warn.lower()


def test_validate_value_int_at_boundary_min():
    spec = _make_spec("int", 5, 1, 10)
    val, warn = _validate_value("s", "k", 1, spec)
    assert val == 1
    assert warn is None


def test_validate_value_int_at_boundary_max():
    spec = _make_spec("int", 5, 1, 10)
    val, warn = _validate_value("s", "k", 10, spec)
    assert val == 10
    assert warn is None


# ---------------------------------------------------------------------------
# _validate_value — float
# ---------------------------------------------------------------------------

def test_validate_value_float_valid():
    spec = _make_spec("float", 0.5, 0.0, 1.0)
    val, warn = _validate_value("s", "k", 0.7, spec)
    assert val == pytest.approx(0.7)
    assert warn is None


def test_validate_value_float_coerce_from_string():
    spec = _make_spec("float", 0.5, 0.0, 1.0)
    val, warn = _validate_value("s", "k", "0.3", spec)
    assert val == pytest.approx(0.3)
    assert warn is None


def test_validate_value_float_coerce_from_int():
    spec = _make_spec("float", 0.5, 0.0, 1.0)
    val, warn = _validate_value("s", "k", 1, spec)
    assert val == pytest.approx(1.0)
    assert warn is None


def test_validate_value_float_below_min_clamped():
    spec = _make_spec("float", 0.5, 0.0, 1.0)
    val, warn = _validate_value("s", "k", -0.1, spec)
    assert val == pytest.approx(0.0)
    assert warn is not None
    assert "clamped" in warn.lower()


def test_validate_value_float_above_max_clamped():
    spec = _make_spec("float", 0.5, 0.0, 1.0)
    val, warn = _validate_value("s", "k", 1.5, spec)
    assert val == pytest.approx(1.0)
    assert warn is not None
    assert "clamped" in warn.lower()


def test_validate_value_float_invalid_falls_back_to_default():
    spec = _make_spec("float", 0.5, 0.0, 1.0)
    val, warn = _validate_value("s", "k", "nan_junk", spec)
    assert val == pytest.approx(0.5)
    assert warn is not None


def test_validate_value_float_no_bounds():
    spec = _make_spec("float", 0.5)
    val, warn = _validate_value("s", "k", 999.9, spec)
    assert val == pytest.approx(999.9)
    assert warn is None


# ---------------------------------------------------------------------------
# _validate_value — bool
# ---------------------------------------------------------------------------

def test_validate_value_bool_native_true():
    spec = _make_spec("bool", False)
    val, warn = _validate_value("s", "k", True, spec)
    assert val is True
    assert warn is None


def test_validate_value_bool_native_false():
    spec = _make_spec("bool", True)
    val, warn = _validate_value("s", "k", False, spec)
    assert val is False
    assert warn is None


def test_validate_value_bool_from_int_one():
    spec = _make_spec("bool", False)
    val, warn = _validate_value("s", "k", 1, spec)
    assert val is True
    assert warn is None


def test_validate_value_bool_from_int_zero():
    spec = _make_spec("bool", True)
    val, warn = _validate_value("s", "k", 0, spec)
    assert val is False
    assert warn is None


@pytest.mark.parametrize("truthy", ["1", "true", "yes", "on", "True", "YES", "ON"])
def test_validate_value_bool_truthy_strings(truthy):
    spec = _make_spec("bool", False)
    val, warn = _validate_value("s", "k", truthy, spec)
    assert val is True
    assert warn is None


@pytest.mark.parametrize("falsy", ["0", "false", "no", "off", "False", "NO", "OFF"])
def test_validate_value_bool_falsy_strings(falsy):
    spec = _make_spec("bool", True)
    val, warn = _validate_value("s", "k", falsy, spec)
    assert val is False
    assert warn is None


def test_validate_value_bool_invalid_string_falls_back():
    spec = _make_spec("bool", True)
    val, warn = _validate_value("s", "k", "maybe", spec)
    assert val is True  # default
    assert warn is not None


# ---------------------------------------------------------------------------
# _validate_value — str
# ---------------------------------------------------------------------------

def test_validate_value_str_plain():
    spec = _make_spec("str", "")
    val, warn = _validate_value("s", "k", "hello", spec)
    assert val == "hello"
    assert warn is None


def test_validate_value_str_strips_whitespace():
    spec = _make_spec("str", "")
    val, warn = _validate_value("s", "k", "  hello  ", spec)
    assert val == "hello"
    assert warn is None


def test_validate_value_str_enum_valid():
    spec = _make_spec("str", "auto", enum_values=["auto", "manual", "off"])
    val, warn = _validate_value("s", "k", "manual", spec)
    assert val == "manual"
    assert warn is None


def test_validate_value_str_enum_invalid_falls_back():
    spec = _make_spec("str", "auto", enum_values=["auto", "manual", "off"])
    val, warn = _validate_value("s", "k", "invalid_choice", spec)
    assert val == "auto"
    assert warn is not None
    assert "not in" in warn.lower()


def test_validate_value_str_no_enum_any_value_accepted():
    spec = _make_spec("str", "")
    val, warn = _validate_value("s", "k", "anything_goes", spec)
    assert val == "anything_goes"
    assert warn is None


def test_validate_value_str_coerce_from_int():
    spec = _make_spec("str", "")
    val, warn = _validate_value("s", "k", 42, spec)
    assert val == "42"
    assert warn is None


# ---------------------------------------------------------------------------
# _validate_value — dict
# ---------------------------------------------------------------------------

def test_validate_value_dict_valid():
    spec = _make_spec("dict", {})
    val, warn = _validate_value("s", "k", {"x": 1}, spec)
    assert val == {"x": 1}
    assert warn is None


def test_validate_value_dict_wrong_type():
    spec = _make_spec("dict", {})
    val, warn = _validate_value("s", "k", [1, 2], spec)
    assert val == {}
    assert warn is not None


def test_validate_value_dict_empty():
    spec = _make_spec("dict", {})
    val, warn = _validate_value("s", "k", {}, spec)
    assert val == {}
    assert warn is None


# ---------------------------------------------------------------------------
# _validate_value — list
# ---------------------------------------------------------------------------

def test_validate_value_list_valid():
    spec = _make_spec("list", [])
    val, warn = _validate_value("s", "k", [1, 2, 3], spec)
    assert val == [1, 2, 3]
    assert warn is None


def test_validate_value_list_wrong_type():
    spec = _make_spec("list", [])
    val, warn = _validate_value("s", "k", {"a": 1}, spec)
    assert val == []
    assert warn is not None


def test_validate_value_list_empty():
    spec = _make_spec("list", [])
    val, warn = _validate_value("s", "k", [], spec)
    assert val == []
    assert warn is None


# ---------------------------------------------------------------------------
# _validate_value — unknown / passthrough type
# ---------------------------------------------------------------------------

def test_validate_value_unknown_type_passthrough():
    spec = _make_spec("custom_type", None)
    val, warn = _validate_value("s", "k", "anything", spec)
    assert val == "anything"
    assert warn is None


# ---------------------------------------------------------------------------
# validate_tuneables — clean data passes
# ---------------------------------------------------------------------------

def test_validate_tuneables_clean_dict_ok():
    data = {"values": {"min_occurrences": 1, "confidence_threshold": 0.6,
                       "gate_threshold": 0.45, "max_retries_per_error": 3,
                       "max_file_touches": 5, "no_evidence_steps": 6,
                       "max_steps": 40, "advice_cache_ttl": 180,
                       "queue_batch_size": 100,
                       "min_occurrences_critical": 1}}
    result = validate_tuneables(data)
    assert result.ok is True
    assert result.data["values"]["min_occurrences"] == 1


def test_validate_tuneables_empty_input_fills_all_defaults():
    result = validate_tuneables({})
    assert result.ok is True
    assert set(result.data.keys()) == set(SCHEMA.keys())
    for section_name, section_spec in SCHEMA.items():
        for key, spec in section_spec.items():
            assert result.data[section_name][key] == spec.default


def test_validate_tuneables_result_ok_true_no_warnings():
    result = validate_tuneables({})
    assert result.warnings == []
    assert result.ok is True


# ---------------------------------------------------------------------------
# validate_tuneables — missing sections / keys get defaults
# ---------------------------------------------------------------------------

def test_validate_tuneables_missing_section_filled():
    result = validate_tuneables({})
    assert "semantic" in result.defaults_applied or any(
        "section:semantic" in d for d in result.defaults_applied
    )
    assert "semantic" in result.data


def test_validate_tuneables_missing_key_in_known_section_filled():
    # Provide values section but omit min_occurrences
    data = {"values": {"confidence_threshold": 0.6,
                       "gate_threshold": 0.45,
                       "max_retries_per_error": 3,
                       "max_file_touches": 5,
                       "no_evidence_steps": 6,
                       "max_steps": 40,
                       "advice_cache_ttl": 180,
                       "queue_batch_size": 100,
                       "min_occurrences_critical": 1}}
    result = validate_tuneables(data)
    # missing key gets default
    assert result.data["values"]["min_occurrences"] == SCHEMA["values"]["min_occurrences"].default
    assert "values.min_occurrences" in result.defaults_applied


# ---------------------------------------------------------------------------
# validate_tuneables — clamping
# ---------------------------------------------------------------------------

def test_validate_tuneables_int_below_min_clamped():
    data = {"values": {"min_occurrences": 0}}  # min is 1
    result = validate_tuneables(data)
    assert result.data["values"]["min_occurrences"] == 1
    assert "values.min_occurrences" in result.clamped
    assert result.ok is False


def test_validate_tuneables_int_above_max_clamped():
    data = {"values": {"min_occurrences": 999}}  # max is 100
    result = validate_tuneables(data)
    assert result.data["values"]["min_occurrences"] == 100
    assert "values.min_occurrences" in result.clamped


def test_validate_tuneables_float_clamped():
    data = {"values": {"confidence_threshold": 2.5}}  # max is 1.0
    result = validate_tuneables(data)
    assert result.data["values"]["confidence_threshold"] == pytest.approx(1.0)
    assert "values.confidence_threshold" in result.clamped


# ---------------------------------------------------------------------------
# validate_tuneables — unknown sections
# ---------------------------------------------------------------------------

def test_validate_tuneables_unknown_section_warned():
    data = {"nonexistent_section": {"foo": "bar"}}
    result = validate_tuneables(data)
    assert result.ok is False
    assert any("nonexistent_section" in w for w in result.warnings)
    assert "section:nonexistent_section" in result.unknown_keys


def test_validate_tuneables_unknown_section_preserved_in_data():
    data = {"nonexistent_section": {"foo": "bar"}}
    result = validate_tuneables(data)
    assert result.data["nonexistent_section"] == {"foo": "bar"}


def test_validate_tuneables_unknown_section_with_underscore_no_warning():
    data = {"_internal_section": {"meta": True}}
    result = validate_tuneables(data)
    # Underscore-prefixed unknown sections should not produce warnings
    section_warnings = [w for w in result.warnings if "_internal_section" in w]
    assert section_warnings == []


# ---------------------------------------------------------------------------
# validate_tuneables — unknown keys within known sections
# ---------------------------------------------------------------------------

def test_validate_tuneables_unknown_key_in_known_section_warned():
    data = {"values": {"totally_unknown_key": 42}}
    result = validate_tuneables(data)
    assert any("totally_unknown_key" in w for w in result.warnings)
    assert "values.totally_unknown_key" in result.unknown_keys


def test_validate_tuneables_unknown_key_preserved():
    data = {"values": {"totally_unknown_key": 42}}
    result = validate_tuneables(data)
    assert result.data["values"]["totally_unknown_key"] == 42


def test_validate_tuneables_underscore_key_not_warned():
    data = {"values": {"_private_key": "secret"}}
    result = validate_tuneables(data)
    underscore_warnings = [w for w in result.warnings if "_private_key" in w]
    assert underscore_warnings == []


# ---------------------------------------------------------------------------
# validate_tuneables — _doc key in source_roles (doc-key section)
# ---------------------------------------------------------------------------

def test_validate_tuneables_doc_key_in_source_roles_no_warning():
    data = {"source_roles": {
        "distillers": {},
        "direct_advisory": {},
        "disabled_from_advisory": {},
        "_doc": "This is documentation"
    }}
    result = validate_tuneables(data)
    doc_warnings = [w for w in result.warnings if "_doc" in w]
    assert doc_warnings == []


# ---------------------------------------------------------------------------
# validate_tuneables — non-dict section values
# ---------------------------------------------------------------------------

def test_validate_tuneables_non_dict_section_replaced_with_defaults():
    data = {"values": "not_a_dict"}
    result = validate_tuneables(data)
    assert result.ok is False
    assert any("not_a_dict" not in w or "values" in w for w in result.warnings)
    # Section replaced with defaults
    assert isinstance(result.data["values"], dict)
    assert "min_occurrences" in result.data["values"]


def test_validate_tuneables_non_dict_section_warning_contains_section_name():
    data = {"values": 42}
    result = validate_tuneables(data)
    assert any("values" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# validate_tuneables — updated_at always preserved
# ---------------------------------------------------------------------------

def test_validate_tuneables_updated_at_preserved():
    data = {"updated_at": "2026-01-15T12:00:00"}
    result = validate_tuneables(data)
    assert result.data["updated_at"] == "2026-01-15T12:00:00"


def test_validate_tuneables_updated_at_not_in_unknown_keys():
    data = {"updated_at": "2026-01-15T12:00:00"}
    result = validate_tuneables(data)
    assert "updated_at" not in result.unknown_keys
    assert not any("updated_at" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# validate_tuneables — custom schema override
# ---------------------------------------------------------------------------

def test_validate_tuneables_custom_schema():
    custom_schema = {
        "mysection": {
            "mykey": TuneableSpec("int", 10, 0, 100, "A test key"),
        }
    }
    data = {"mysection": {"mykey": 50}}
    result = validate_tuneables(data, schema=custom_schema)
    assert result.ok is True
    assert result.data["mysection"]["mykey"] == 50


def test_validate_tuneables_custom_schema_clamps():
    custom_schema = {
        "s": {
            "n": TuneableSpec("int", 5, 1, 10, "Bounded int"),
        }
    }
    data = {"s": {"n": 999}}
    result = validate_tuneables(data, schema=custom_schema)
    assert result.data["s"]["n"] == 10
    assert "s.n" in result.clamped


# ---------------------------------------------------------------------------
# validate_tuneables — ValidationResult.ok property
# ---------------------------------------------------------------------------

def test_validation_result_ok_true_when_no_warnings():
    result = ValidationResult(data={}, warnings=[])
    assert result.ok is True


def test_validation_result_ok_false_when_warnings_exist():
    result = ValidationResult(data={}, warnings=["something went wrong"])
    assert result.ok is False


# ---------------------------------------------------------------------------
# validate_tuneables — enum validation end-to-end
# ---------------------------------------------------------------------------

def test_validate_tuneables_enum_valid_value():
    data = {"synthesizer": {"mode": "ai_only"}}
    result = validate_tuneables(data)
    assert result.data["synthesizer"]["mode"] == "ai_only"


def test_validate_tuneables_enum_invalid_uses_default():
    data = {"synthesizer": {"mode": "invalid_mode"}}
    result = validate_tuneables(data)
    assert result.data["synthesizer"]["mode"] == "auto"  # default
    assert result.ok is False


# ---------------------------------------------------------------------------
# get_section_defaults
# ---------------------------------------------------------------------------

def test_get_section_defaults_known_section():
    defaults = get_section_defaults("values")
    assert "min_occurrences" in defaults
    assert defaults["min_occurrences"] == SCHEMA["values"]["min_occurrences"].default


def test_get_section_defaults_all_keys_present():
    for section_name, section_spec in SCHEMA.items():
        defaults = get_section_defaults(section_name)
        for key in section_spec:
            assert key in defaults, f"Missing key {key} in {section_name} defaults"


def test_get_section_defaults_unknown_section_returns_empty():
    defaults = get_section_defaults("completely_nonexistent")
    assert defaults == {}


def test_get_section_defaults_values_match_spec():
    defaults = get_section_defaults("semantic")
    for key, spec in SCHEMA["semantic"].items():
        assert defaults[key] == spec.default


# ---------------------------------------------------------------------------
# get_full_defaults
# ---------------------------------------------------------------------------

def test_get_full_defaults_contains_all_sections():
    defaults = get_full_defaults()
    assert set(defaults.keys()) == set(SCHEMA.keys())


def test_get_full_defaults_each_section_has_correct_keys():
    defaults = get_full_defaults()
    for section_name, section_spec in SCHEMA.items():
        for key in section_spec:
            assert key in defaults[section_name], (
                f"Missing key {key} in section {section_name}"
            )


def test_get_full_defaults_values_match_schema_defaults():
    defaults = get_full_defaults()
    for section_name, section_spec in SCHEMA.items():
        for key, spec in section_spec.items():
            assert defaults[section_name][key] == spec.default


def test_get_full_defaults_returns_new_dict_each_call():
    d1 = get_full_defaults()
    d2 = get_full_defaults()
    assert d1 is not d2
