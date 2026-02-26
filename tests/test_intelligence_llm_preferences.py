from __future__ import annotations

import json
from pathlib import Path

from lib.intelligence_llm_preferences import apply_runtime_llm_preferences


def test_apply_runtime_llm_preferences_updates_sections(tmp_path: Path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "eidos": {},
                "meta_ralph": {},
                "opportunity_scanner": {"llm_enabled": False},
                "advisory_packet_store": {},
            }
        ),
        encoding="utf-8",
    )

    out = apply_runtime_llm_preferences(
        eidos_runtime_llm=True,
        meta_ralph_runtime_llm=True,
        opportunity_scanner_llm=True,
        packet_lookup_llm=False,
        provider="ollama",
        path=tuneables,
        source="test",
    )
    assert out["ok"] is True
    data = json.loads(tuneables.read_text(encoding="utf-8"))
    assert data["eidos"]["runtime_refiner_llm_enabled"] is True
    assert data["eidos"]["runtime_refiner_llm_provider"] == "ollama"
    assert data["meta_ralph"]["runtime_refiner_llm_enabled"] is True
    assert data["meta_ralph"]["runtime_refiner_llm_provider"] == "ollama"
    assert data["opportunity_scanner"]["llm_enabled"] is True
    assert data["advisory_packet_store"]["packet_lookup_llm_enabled"] is False
    assert "_llm_runtime_setup" in data

