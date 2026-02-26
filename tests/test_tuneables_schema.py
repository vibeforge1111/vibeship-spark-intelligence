"""Tests for lib/tuneables_schema.py — validation, defaults, and reference doc."""

import pytest

from lib.tuneables_schema import (
    TuneableSpec,
    ValidationResult,
    SCHEMA,
    SECTION_CONSUMERS,
    validate_tuneables,
    get_section_defaults,
    get_full_defaults,
    generate_reference_doc,
    _validate_value,
)


# ---------------------------------------------------------------------------
# TuneableSpec namedtuple
# ---------------------------------------------------------------------------

class TestTuneableSpec:
    def test_basic_fields(self):
        spec = TuneableSpec("int", 10, 1, 100, "A value")
        assert spec.type == "int"
        assert spec.default == 10
        assert spec.min_val == 1
        assert spec.max_val == 100
        assert spec.description == "A value"

    def test_enum_values_default_none(self):
        spec = TuneableSpec("str", "auto", None, None, "Mode")
        assert spec.enum_values is None

    def test_enum_values_provided(self):
        spec = TuneableSpec("str", "auto", None, None, "Mode", ["auto", "manual"])
        assert spec.enum_values == ["auto", "manual"]

    def test_min_max_defaults_none(self):
        spec = TuneableSpec("bool", True, None, None, "Flag")
        assert spec.min_val is None
        assert spec.max_val is None


# ---------------------------------------------------------------------------
# ValidationResult dataclass
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_ok_when_no_warnings(self):
        r = ValidationResult(data={})
        assert r.ok is True

    def test_not_ok_when_warnings_present(self):
        r = ValidationResult(data={}, warnings=["something wrong"])
        assert r.ok is False

    def test_default_empty_lists(self):
        r = ValidationResult(data={})
        assert r.clamped == []
        assert r.defaults_applied == []
        assert r.unknown_keys == []

    def test_data_stored(self):
        r = ValidationResult(data={"x": 1})
        assert r.data == {"x": 1}


# ---------------------------------------------------------------------------
# SCHEMA contents
# ---------------------------------------------------------------------------

class TestSchema:
    def test_schema_is_dict(self):
        assert isinstance(SCHEMA, dict)

    def test_schema_has_values_section(self):
        assert "values" in SCHEMA

    def test_schema_has_semantic_section(self):
        assert "semantic" in SCHEMA

    def test_schema_has_advisor_section(self):
        assert "advisor" in SCHEMA

    def test_all_values_are_dicts(self):
        for k, v in SCHEMA.items():
            assert isinstance(v, dict), f"Section {k!r} is not a dict"

    def test_all_specs_are_tuneable_spec(self):
        for section, keys in SCHEMA.items():
            for key, spec in keys.items():
                assert isinstance(spec, TuneableSpec), f"{section}.{key} is not TuneableSpec"

    def test_values_section_has_min_occurrences(self):
        assert "min_occurrences" in SCHEMA["values"]

    def test_values_min_occurrences_type_is_int(self):
        assert SCHEMA["values"]["min_occurrences"].type == "int"

    def test_advisor_section_has_min_reliability(self):
        assert "min_reliability" in SCHEMA["advisor"]

    def test_synthesizer_mode_has_enum(self):
        assert SCHEMA["synthesizer"]["mode"].enum_values is not None

    def test_auto_tuner_section_exists(self):
        assert "auto_tuner" in SCHEMA

    def test_chip_merge_section_exists(self):
        assert "chip_merge" in SCHEMA

    def test_production_gates_section_exists(self):
        assert "production_gates" in SCHEMA


# ---------------------------------------------------------------------------
# _validate_value
# ---------------------------------------------------------------------------

class TestValidateValue:
    # int
    def test_int_valid(self):
        spec = TuneableSpec("int", 5, 1, 100, "")
        val, warn = _validate_value("sec", "key", 42, spec)
        assert val == 42
        assert warn is None

    def test_int_coerce_from_string(self):
        spec = TuneableSpec("int", 5, 1, 100, "")
        val, warn = _validate_value("sec", "key", "7", spec)
        assert val == 7
        assert warn is None

    def test_int_below_min_clamped(self):
        spec = TuneableSpec("int", 5, 1, 100, "")
        val, warn = _validate_value("sec", "key", 0, spec)
        assert val == 1
        assert warn is not None
        assert "clamped" in warn.lower()

    def test_int_above_max_clamped(self):
        spec = TuneableSpec("int", 5, 1, 100, "")
        val, warn = _validate_value("sec", "key", 200, spec)
        assert val == 100
        assert warn is not None

    def test_int_invalid_string_uses_default(self):
        spec = TuneableSpec("int", 5, 1, 100, "")
        val, warn = _validate_value("sec", "key", "not_a_number", spec)
        assert val == 5
        assert warn is not None

    # float
    def test_float_valid(self):
        spec = TuneableSpec("float", 0.5, 0.0, 1.0, "")
        val, warn = _validate_value("sec", "key", 0.8, spec)
        assert val == pytest.approx(0.8)
        assert warn is None

    def test_float_below_min_clamped(self):
        spec = TuneableSpec("float", 0.5, 0.0, 1.0, "")
        val, warn = _validate_value("sec", "key", -0.5, spec)
        assert val == pytest.approx(0.0)
        assert warn is not None

    def test_float_above_max_clamped(self):
        spec = TuneableSpec("float", 0.5, 0.0, 1.0, "")
        val, warn = _validate_value("sec", "key", 1.5, spec)
        assert val == pytest.approx(1.0)
        assert warn is not None

    def test_float_coerce_from_int(self):
        spec = TuneableSpec("float", 0.5, 0.0, 1.0, "")
        val, warn = _validate_value("sec", "key", 1, spec)
        assert isinstance(val, float)
        assert warn is None

    def test_float_invalid_uses_default(self):
        spec = TuneableSpec("float", 0.5, 0.0, 1.0, "")
        val, warn = _validate_value("sec", "key", "bad", spec)
        assert val == 0.5
        assert warn is not None

    # bool
    def test_bool_true_literal(self):
        spec = TuneableSpec("bool", True, None, None, "")
        val, warn = _validate_value("sec", "key", True, spec)
        assert val is True
        assert warn is None

    def test_bool_false_literal(self):
        spec = TuneableSpec("bool", True, None, None, "")
        val, warn = _validate_value("sec", "key", False, spec)
        assert val is False
        assert warn is None

    def test_bool_from_string_true(self):
        spec = TuneableSpec("bool", False, None, None, "")
        for s in ("true", "1", "yes", "on"):
            val, warn = _validate_value("sec", "key", s, spec)
            assert val is True, f"failed for {s!r}"
            assert warn is None

    def test_bool_from_string_false(self):
        spec = TuneableSpec("bool", True, None, None, "")
        for s in ("false", "0", "no", "off"):
            val, warn = _validate_value("sec", "key", s, spec)
            assert val is False, f"failed for {s!r}"
            assert warn is None

    def test_bool_from_int_nonzero(self):
        spec = TuneableSpec("bool", False, None, None, "")
        val, warn = _validate_value("sec", "key", 1, spec)
        assert val is True
        assert warn is None

    def test_bool_invalid_uses_default(self):
        spec = TuneableSpec("bool", True, None, None, "")
        val, warn = _validate_value("sec", "key", "maybe", spec)
        assert val is True
        assert warn is not None

    # str
    def test_str_valid_no_enum(self):
        spec = TuneableSpec("str", "", None, None, "")
        val, warn = _validate_value("sec", "key", "hello", spec)
        assert val == "hello"
        assert warn is None

    def test_str_strips_whitespace(self):
        spec = TuneableSpec("str", "", None, None, "")
        val, warn = _validate_value("sec", "key", "  hi  ", spec)
        assert val == "hi"
        assert warn is None

    def test_str_valid_enum(self):
        spec = TuneableSpec("str", "auto", None, None, "", ["auto", "manual"])
        val, warn = _validate_value("sec", "key", "manual", spec)
        assert val == "manual"
        assert warn is None

    def test_str_invalid_enum_uses_default(self):
        spec = TuneableSpec("str", "auto", None, None, "", ["auto", "manual"])
        val, warn = _validate_value("sec", "key", "unknown", spec)
        assert val == "auto"
        assert warn is not None

    # dict
    def test_dict_valid(self):
        spec = TuneableSpec("dict", {}, None, None, "")
        val, warn = _validate_value("sec", "key", {"a": 1}, spec)
        assert val == {"a": 1}
        assert warn is None

    def test_dict_wrong_type_uses_default(self):
        spec = TuneableSpec("dict", {}, None, None, "")
        val, warn = _validate_value("sec", "key", [1, 2], spec)
        assert val == {}
        assert warn is not None

    # list
    def test_list_valid(self):
        spec = TuneableSpec("list", [], None, None, "")
        val, warn = _validate_value("sec", "key", [1, 2, 3], spec)
        assert val == [1, 2, 3]
        assert warn is None

    def test_list_wrong_type_uses_default(self):
        spec = TuneableSpec("list", [], None, None, "")
        val, warn = _validate_value("sec", "key", {"a": 1}, spec)
        assert val == []
        assert warn is not None


# ---------------------------------------------------------------------------
# validate_tuneables
# ---------------------------------------------------------------------------

class TestValidateTuneables:
    def test_empty_input_fills_all_defaults(self):
        result = validate_tuneables({})
        assert result.ok
        # Every schema section should appear in data
        for section in SCHEMA:
            assert section in result.data

    def test_defaults_applied_for_missing_section(self):
        result = validate_tuneables({})
        assert len(result.defaults_applied) > 0
        assert any(d.startswith("section:") for d in result.defaults_applied)

    def test_valid_int_accepted(self):
        data = {"values": {"min_occurrences": 5}}
        result = validate_tuneables(data)
        assert result.data["values"]["min_occurrences"] == 5

    def test_out_of_bounds_int_clamped(self):
        data = {"values": {"min_occurrences": 999}}
        result = validate_tuneables(data)
        spec = SCHEMA["values"]["min_occurrences"]
        assert result.data["values"]["min_occurrences"] == spec.max_val
        assert len(result.clamped) > 0

    def test_out_of_bounds_float_clamped(self):
        data = {"values": {"confidence_threshold": 5.0}}
        result = validate_tuneables(data)
        assert result.data["values"]["confidence_threshold"] == pytest.approx(1.0)

    def test_unknown_key_in_known_section_preserved_with_warning(self):
        data = {"values": {"totally_made_up_key": 99}}
        result = validate_tuneables(data)
        assert result.data["values"]["totally_made_up_key"] == 99
        assert any("totally_made_up_key" in w for w in result.warnings)
        assert any("totally_made_up_key" in k for k in result.unknown_keys)

    def test_unknown_section_preserved_with_warning(self):
        data = {"my_custom_section": {"foo": "bar"}}
        result = validate_tuneables(data)
        assert result.data["my_custom_section"] == {"foo": "bar"}
        assert any("my_custom_section" in w for w in result.warnings)

    def test_updated_at_always_preserved(self):
        data = {"updated_at": "2026-01-01T00:00:00"}
        result = validate_tuneables(data)
        assert result.data["updated_at"] == "2026-01-01T00:00:00"

    def test_updated_at_no_warning(self):
        data = {"updated_at": "2026-01-01"}
        result = validate_tuneables(data)
        # updated_at should not appear in unknown_keys
        assert not any("updated_at" in k for k in result.unknown_keys)

    def test_non_dict_section_warns_and_uses_defaults(self):
        data = {"values": "not_a_dict"}
        result = validate_tuneables(data)
        assert len(result.warnings) > 0
        # defaults should still be in place
        assert "min_occurrences" in result.data["values"]

    def test_ok_property_true_when_clean(self):
        result = validate_tuneables({"values": {"min_occurrences": 3}})
        assert result.ok

    def test_ok_property_false_when_warnings(self):
        data = {"values": {"min_occurrences": 9999}}
        result = validate_tuneables(data)
        assert not result.ok

    def test_bool_coercion_accepted(self):
        data = {"semantic": {"enabled": "true"}}
        result = validate_tuneables(data)
        assert result.data["semantic"]["enabled"] is True

    def test_str_enum_invalid_warns(self):
        data = {"synthesizer": {"mode": "invalid_mode"}}
        result = validate_tuneables(data)
        assert any("mode" in w for w in result.warnings)

    def test_str_enum_valid_accepted(self):
        data = {"synthesizer": {"mode": "ai_only"}}
        result = validate_tuneables(data)
        assert result.data["synthesizer"]["mode"] == "ai_only"

    def test_custom_schema_used(self):
        mini_schema = {
            "custom": {
                "limit": TuneableSpec("int", 10, 1, 50, ""),
            }
        }
        result = validate_tuneables({"custom": {"limit": 25}}, schema=mini_schema)
        assert result.data["custom"]["limit"] == 25

    def test_underscore_key_not_warned(self):
        data = {"values": {"_comment": "ignored"}}
        result = validate_tuneables(data)
        # _comment should not produce unknown-key warning
        assert not any("_comment" in k for k in result.unknown_keys)

    def test_full_valid_section_no_warnings(self):
        # Supply the whole 'advisor' section with valid defaults
        defaults = get_section_defaults("advisor")
        result = validate_tuneables({"advisor": defaults})
        assert result.ok or len([w for w in result.warnings if "advisor" in w]) == 0


# ---------------------------------------------------------------------------
# get_section_defaults
# ---------------------------------------------------------------------------

class TestGetSectionDefaults:
    def test_values_section_defaults(self):
        defaults = get_section_defaults("values")
        assert "min_occurrences" in defaults
        assert defaults["min_occurrences"] == SCHEMA["values"]["min_occurrences"].default

    def test_unknown_section_returns_empty(self):
        assert get_section_defaults("nonexistent_section") == {}

    def test_returns_dict(self):
        assert isinstance(get_section_defaults("semantic"), dict)

    def test_all_keys_present(self):
        section = "advisor"
        defaults = get_section_defaults(section)
        for key in SCHEMA[section]:
            assert key in defaults

    def test_semantic_enabled_default_true(self):
        defaults = get_section_defaults("semantic")
        assert defaults["enabled"] is True


# ---------------------------------------------------------------------------
# get_full_defaults
# ---------------------------------------------------------------------------

class TestGetFullDefaults:
    def test_returns_dict(self):
        assert isinstance(get_full_defaults(), dict)

    def test_all_sections_present(self):
        defaults = get_full_defaults()
        for section in SCHEMA:
            assert section in defaults

    def test_sections_are_dicts(self):
        defaults = get_full_defaults()
        for k, v in defaults.items():
            assert isinstance(v, dict), f"Section {k!r} value is not a dict"

    def test_values_count_matches_schema(self):
        full = get_full_defaults()
        for section, keys in SCHEMA.items():
            assert len(full[section]) == len(keys)

    def test_validate_full_defaults_is_ok(self):
        # Full defaults should produce a clean result
        full = get_full_defaults()
        result = validate_tuneables(full)
        # No clamping expected
        assert result.clamped == []


# ---------------------------------------------------------------------------
# generate_reference_doc
# ---------------------------------------------------------------------------

class TestGenerateReferenceDoc:
    def test_returns_string(self):
        assert isinstance(generate_reference_doc(), str)

    def test_contains_header(self):
        doc = generate_reference_doc()
        assert "# Tuneables Reference" in doc

    def test_contains_section_names(self):
        doc = generate_reference_doc()
        for section in ("values", "semantic", "advisor", "chip_merge"):
            assert section in doc

    def test_contains_key_names(self):
        doc = generate_reference_doc()
        assert "min_occurrences" in doc
        assert "confidence_threshold" in doc

    def test_section_count_mentioned(self):
        doc = generate_reference_doc()
        assert f"**Sections:** {len(SCHEMA)}" in doc

    def test_total_keys_mentioned(self):
        total = sum(len(v) for v in SCHEMA.values())
        doc = generate_reference_doc()
        assert f"**Total keys:** {total}" in doc
