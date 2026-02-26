from __future__ import annotations

import json

from adapters import openclaw_tailer as tailer


def _tool_result_event(text: str, *, is_error: bool = False) -> dict:
    return {
        "type": "message",
        "message": {
            "role": "toolResult",
            "isError": is_error,
            "content": text,
        },
    }


def _assistant_read_only_event() -> dict:
    return {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "toolCall", "name": "Read", "arguments": {"file_path": "README.md"}},
            ],
        },
    }


def test_should_skip_successful_large_tool_result_when_enabled(monkeypatch):
    monkeypatch.setattr(tailer, "SKIP_SUCCESSFUL_TOOL_RESULTS", True)
    monkeypatch.setattr(tailer, "KEEP_LARGE_TOOL_RESULTS_ON_ERROR_ONLY", True)
    monkeypatch.setattr(tailer, "MAX_TOOL_RESULT_CHARS", 10)
    monkeypatch.setattr(tailer, "MIN_TOOL_RESULT_CHARS_FOR_CAPTURE", 0)

    assert tailer._should_skip_event(_tool_result_event("x" * 24)) is True
    assert tailer._should_skip_event(_tool_result_event("short")) is False


def test_should_keep_successful_large_tool_result_when_skip_disabled(monkeypatch):
    monkeypatch.setattr(tailer, "SKIP_SUCCESSFUL_TOOL_RESULTS", False)
    monkeypatch.setattr(tailer, "KEEP_LARGE_TOOL_RESULTS_ON_ERROR_ONLY", True)
    monkeypatch.setattr(tailer, "MAX_TOOL_RESULT_CHARS", 10)
    monkeypatch.setattr(tailer, "MIN_TOOL_RESULT_CHARS_FOR_CAPTURE", 0)

    assert tailer._should_skip_event(_tool_result_event("x" * 24)) is False


def test_should_skip_read_only_calls_based_on_toggle(monkeypatch):
    monkeypatch.setattr(tailer, "SKIP_READ_ONLY_TOOL_CALLS", True)
    assert tailer._should_skip_event(_assistant_read_only_event()) is True

    monkeypatch.setattr(tailer, "SKIP_READ_ONLY_TOOL_CALLS", False)
    assert tailer._should_skip_event(_assistant_read_only_event()) is False


def test_min_tool_result_chars_for_capture_applies_to_success_only(monkeypatch):
    monkeypatch.setattr(tailer, "SKIP_SUCCESSFUL_TOOL_RESULTS", False)
    monkeypatch.setattr(tailer, "KEEP_LARGE_TOOL_RESULTS_ON_ERROR_ONLY", True)
    monkeypatch.setattr(tailer, "MAX_TOOL_RESULT_CHARS", 100)
    monkeypatch.setattr(tailer, "MIN_TOOL_RESULT_CHARS_FOR_CAPTURE", 8)

    assert tailer._should_skip_event(_tool_result_event("tiny")) is True
    assert tailer._should_skip_event(_tool_result_event("tiny", is_error=True)) is False


def test_openclaw_tailer_load_config_reads_runtime(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "openclaw_tailer": {
                    "skip_successful_tool_results": False,
                    "skip_read_only_tool_calls": False,
                    "max_tool_result_chars": 2222,
                    "keep_large_tool_results_on_error_only": False,
                    "min_tool_result_chars_for_capture": 12,
                    "workflow_summary_enabled": False,
                    "workflow_summary_min_interval_s": 45,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(tailer, "TUNEABLES_FILE", tuneables)

    cfg = tailer._load_openclaw_tailer_config()

    assert cfg["skip_successful_tool_results"] is False
    assert cfg["skip_read_only_tool_calls"] is False
    assert cfg["max_tool_result_chars"] == 2222
    assert cfg["keep_large_tool_results_on_error_only"] is False
    assert cfg["min_tool_result_chars_for_capture"] == 12
    assert cfg["workflow_summary_enabled"] is False
    assert cfg["workflow_summary_min_interval_s"] == 45
