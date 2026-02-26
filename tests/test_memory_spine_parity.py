from lib.memory_spine_parity import compare_snapshots
from lib.memory_spine_parity import evaluate_parity_gate


def test_compare_snapshots_exact_match():
    payload = {
        "reasoning:k1": {"insight": "Use schema checks", "confidence": 0.8},
        "context:k2": {"insight": "Batch related edits", "confidence": 0.7},
    }
    out = compare_snapshots(payload, payload)
    assert out["json_count"] == 2
    assert out["spine_count"] == 2
    assert out["missing_in_spine_count"] == 0
    assert out["payload_mismatch_count"] == 0
    assert out["payload_parity_ratio"] == 1.0


def test_compare_snapshots_detects_missing_extra_and_mismatch():
    json_payload = {
        "a": {"insight": "one", "confidence": 0.9},
        "b": {"insight": "two", "confidence": 0.8},
    }
    spine_payload = {
        "a": {"insight": "one", "confidence": 0.9},
        "b": {"insight": "changed", "confidence": 0.8},
        "c": {"insight": "extra", "confidence": 0.6},
    }
    out = compare_snapshots(json_payload, spine_payload)
    assert out["json_count"] == 2
    assert out["spine_count"] == 3
    assert out["extra_in_spine_count"] == 1
    assert out["payload_mismatch_count"] == 1
    assert out["payload_parity_ratio"] == 0.5


def test_evaluate_parity_gate():
    parity = {
        "json_count": 100,
        "payload_parity_ratio": 0.997,
    }
    gate = evaluate_parity_gate(parity, min_payload_parity=0.995, min_rows=10)
    assert gate["pass"] is True
    gate_fail = evaluate_parity_gate(parity, min_payload_parity=0.999, min_rows=10)
    assert gate_fail["pass"] is False
