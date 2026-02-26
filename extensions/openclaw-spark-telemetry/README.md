# Spark Telemetry Hooks Plugin

This OpenClaw plugin captures `llm_input` and `llm_output` lifecycle hooks and writes
redacted telemetry to a local JSONL spool file consumed by `adapters/openclaw_tailer.py`.

## Config

OpenClaw `openclaw.json` snippet:

```json
{
  "plugins": {
    "allow": ["spark-telemetry-hooks"],
    "load": {
      "paths": [
        "/path/to/vibeship-spark-intelligence\\extensions\\openclaw-spark-telemetry"
      ]
    },
    "entries": {
      "spark-telemetry-hooks": {
        "enabled": true,
        "config": {
          "spoolFile": "<USER_HOME>\\.spark\\openclaw_hook_events.jsonl",
          "includePromptPreview": false,
          "includeOutputPreview": false,
          "previewChars": 240,
          "buildIntegrityEnabled": true,
          "injectNoHallucinationGuard": true,
          "stallSeconds": 300
        }
      }
    }
  }
}
```

## Runtime contract

- Hook rows are written to JSONL with `hook` = `llm_input` or `llm_output`.
- Build integrity rows are emitted with `hook` = `build_integrity` and kinds like:
  - `contract_declared`
  - `start_proof`
  - `stall_alert`
  - `final_state_done|failed|paused`
- Optional guardrail injection appends a build-integrity policy to the system prompt
  before model calls (`injectNoHallucinationGuard`).
- Prompt/output previews are off by default.
- `adapters/openclaw_tailer.py` ingests the spool with `--hook-events-file`.

