# OpenClaw Config Snippets

Use these snippets in local `<OPENCLAW_HOME>\openclaw.json` (not in repo).

## 1) Subagent depth policy

```json
{
  "agents": {
    "defaults": {
      "subagents": {
        "maxConcurrent": 8,
        "maxSpawnDepth": 2,
        "maxChildrenPerAgent": 3
      }
    }
  }
}
```

Notes:

- `maxSpawnDepth: 2` enables orchestrator pattern.
- Keep `maxChildrenPerAgent` conservative to avoid fan-out instability.
- Why `maxSpawnDepth=2`:
  - depth 1 = primary agent, depth 2 = specialized worker.
  - usually enough for research/eval delegation without recursive runaway trees.
  - keeps trace lineage and attribution joins understandable.
- Why `maxChildrenPerAgent=3`:
  - allows parallel option exploration (A/B/C) while capping token and tool burst cost.
  - reduces parent/child advisory collisions and dedupe pressure.
  - keeps scheduler/queue load bounded during spikes.
- Increase these only when:
  - queue depth and heartbeat remain healthy under load,
  - strict outcome quality is stable, and
  - you have a clear workload that needs deeper or wider trees.

## 2) Cron finished-run webhook auth

```json
{
  "cron": {
    "webhook": "https://<your-private-endpoint>/openclaw/cron-finished",
    "webhookToken": "${OPENCLAW_CRON_WEBHOOK_TOKEN}"
  }
}
```

Notes:

- Use a dedicated token.
- Do not reuse gateway auth token.

## 3) Hook telemetry enablement (llm_input / llm_output)

Use plugin-based hook capture + tailer ingestion:

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
          "previewChars": 240
        }
      }
    }
  }
}
```

Run tailer with hook spool ingestion enabled:

```powershell
python adapters\openclaw_tailer.py --agent main --hook-events-file <SPARK_HOME>\openclaw_hook_events.jsonl
```

Join fields emitted by plugin rows:

- `run_id`
- `session_id` / `session_key`
- `agent_id`
- `provider` / `model`
- prompt/output shape and hashes (redacted by default)

## 4) Secret hygiene policy

- Keep secrets in env or secret store, not raw JSON.
- Rotate existing exposed tokens immediately.
- Store only redacted operational artifacts in docs/reports.


