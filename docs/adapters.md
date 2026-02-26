# Spark Adapters (Input Integrations)
Navigation hub: `docs/GLOSSARY.md`

Spark is **runtime-agnostic**.

Spark Core only understands **SparkEventV1** (see `lib/events.py`).
Everything else is an **adapter** that converts some platform’s logs/events into Spark events.

## Event schema (v1)

```json
{
  "v": 1,
  "source": "clawdbot|claude_code|cursor|vscode|webhook|stdin|chatgpt_export",
  "kind": "message|tool|command|system",
  "ts": 1730000000.0,
  "session_id": "some-session-key",
  "payload": { "...": "..." },
  "trace_id": "optional-dedupe-id"
}
```

### Portable explicit memory capture (recommended)

Any environment can trigger reliable memory capture with a `command` event:

```json
{
  "v": 1,
  "source": "cursor",
  "kind": "command",
  "ts": 1730000000.0,
  "session_id": "my-project",
  "payload": {
    "intent": "remember",
    "text": "Build everything with compatibility across environments",
    "category": "meta_learning"
  },
  "trace_id": "..."
}
```

- `trace_id` should be stable for the original event (hash of the raw line works).
- `session_id` can be any stable thread/session identifier for that platform.

## Built-in adapters

### 1) Clawdbot tailer (local)

File: `adapters/clawdbot_tailer.py`

- Reads Clawdbot session JSONL transcript.
- Sends events to `sparkd`.

Safe defaults:
- Tail-from-end (no backfill)
- Rate limited

Run:
```bash
python3 sparkd.py
python3 adapters/clawdbot_tailer.py --agent main
```

`sparkd` enforces bearer auth on mutating `POST` endpoints by default.
Adapters resolve tokens in this order: `--token`, `SPARKD_TOKEN`, then `~/.spark/sparkd.token`.

### 2) Claude Code hooks (local)

File: `hooks/observe.py`

Claude Code can call this hook on tool events.
This is great for IDE-style tool telemetry.

### 3) Universal stdin adapter (local)

File: `adapters/stdin_ingest.py`

- Reads newline-delimited JSON SparkEventV1 objects from stdin.
- Posts to `sparkd /ingest`.

This lets any tool (Cursor/VSCode tasks, shell scripts, CI) feed Spark
without needing a platform-specific adapter.

Example:
```bash
echo '{"v":1,"source":"stdin","kind":"message","ts":1730000000,"session_id":"demo","payload":{"role":"user","text":"hello"}}' | \
  python3 adapters/stdin_ingest.py --sparkd ${SPARKD_URL:-http://127.0.0.1:${SPARKD_PORT:-8787}}
```

Notes:
- `adapters/stdin_ingest.py` defaults to `SPARKD_URL` or `SPARKD_PORT`.

### 4) Codex hook bridge (shadow-first)

File: `adapters/codex_hook_bridge.py`

This adapter tails `~/.codex/sessions/**/*.jsonl` and maps Codex events into
hook-like events (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`PostToolUseFailure`, `Stop`).

Modes:
- `shadow` (default): parse + map + telemetry only (no live hook forwarding)
- `observe`: forward mapped events into `hooks/observe.py`

Recommended validation-first run:
```bash
python3 adapters/codex_hook_bridge.py --mode shadow --backfill --once
```

Continuous shadow canary:
```bash
python3 adapters/codex_hook_bridge.py --mode shadow --poll 2 --max-per-tick 200
```

Telemetry is written to:
- `~/.spark/logs/codex_hook_bridge_telemetry.jsonl`

### 5) OpenClaw tailer capture policy + workflow summary lane

File: `adapters/openclaw_tailer.py`

Capture/skip behavior is configurable via the `openclaw_tailer` tuneables section:

- `skip_successful_tool_results` (default: `true`)
- `skip_read_only_tool_calls` (default: `true`)
- `max_tool_result_chars` (default: `4000`)
- `keep_large_tool_results_on_error_only` (default: `true`)
- `min_tool_result_chars_for_capture` (default: `0`)
- `workflow_summary_enabled` (default: `true`)
- `workflow_summary_min_interval_s` (default: `120`)

Additional behavior:
- Oversized tool results now keep a compact inline payload plus a stable local reference:
  - `~/.spark/workflow_refs/openclaw_tool_results/<sha256>.txt`
- Workflow summaries are emitted as report artifacts under:
  - `<report_dir>/workflow/workflow_<ts>_<session-hash>.json`
- Report ingestion scans subdirectories recursively and archives processed reports into sibling `.processed/` folders.

Runtime override example (`~/.spark/tuneables.json`):

```json
{
  "openclaw_tailer": {
    "skip_successful_tool_results": true,
    "max_tool_result_chars": 6000,
    "workflow_summary_enabled": true,
    "workflow_summary_min_interval_s": 120
  }
}
```

## Cursor / VS Code integration (recommended approach)

Cursor and VS Code are best integrated using either:

1) **Claude Code hooks** (if you’re using Claude Code inside Cursor)
2) **Tasks** that pipe JSON into `adapters/stdin_ingest.py`

Practical pattern:
- Put a small script in your repo that emits SparkEventV1 when you run a task.
- Bind it to a keyboard shortcut or run it on demand.

## ChatGPT (hosted) integration

ChatGPT can’t run local scripts directly.
Options:
- Copy/paste “high signal” learnings manually into `spark learn ...`
- Export conversation and run an offline importer that emits SparkEventV1 events.

---

## Design rule
Adapters are allowed to be messy.
**Spark core must stay clean and stable.**
