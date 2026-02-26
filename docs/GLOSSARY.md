# Glossary and Documentation Launch Map

Updated: 2026-02-21

Use this file as the single, stable documentation entrypoint for public OSS onboarding.

## 1) Core documentation path

- `docs/DOCS_INDEX.md` (comprehensive navigation hub)
- `docs/LAUNCH_DOCUMENTATION_MAP.md`
- `docs/GLOSSARY.md`
- `docs/GETTING_STARTED_5_MIN.md`
- `docs/QUICKSTART.md`
- `README.md`

## 2) Intelligence and tuning

- `Intelligence_Flow.md` — Full architecture
- `docs/PROJECT_INTELLIGENCE.md`
- `docs/CONSCIOUSNESS_BRIDGE_V1.md`
- `docs/MEMORY_ACTIONABILITY_FRAMEWORK.md`
- `docs/RETRIEVAL_LEVELS.md`
- `TUNEABLES.md` — All tuneable parameters + hot-reload matrix
- `docs/TUNEABLES_REFERENCE.md` — Auto-generated schema reference from `lib/tuneables_schema.py`
- `docs/SPARK_LIGHTWEIGHT_OPERATING_MODE.md`

## 3) Subsystem references

- `META_RALPH.md` — Quality gate
- `EIDOS_GUIDE.md` — Episodic intelligence
- `SEMANTIC_ADVISOR_DESIGN.md` — Retrieval + ranking
- `docs/ADVISORY_AND_LEARNING_BENCHMARKS.md`
- `docs/SELF_IMPROVEMENT_SYSTEMS.md`

## 4) Integrations

- `docs/claude_code.md`
- `docs/cursor.md`
- `docs/adapters.md`
- `docs/OPENCLAW_INTEGRATION.md`
- `docs/OPENCLAW_OPERATIONS.md`
- `docs/OPENCLAW_PATHS_AND_DATA_BOUNDARIES.md`
- `docs/LLM_INTEGRATION.md`
- `docs/DEEPSEEK_ISOLATION_RULES.md`

## 5) Boundary, safety, and launch posture

- `docs/OSS_BOUNDARY.md`
- `docs/OPEN_CORE_FREEMIUM_MODEL.md`
- `docs/RESPONSIBLE_PUBLIC_RELEASE.md`
- `docs/security/THREAT_MODEL.md`

## 6) Terms (open docs glossary)

- **Advisor**: Decision-time guidance produced from memory, retrieval, and event context.
- **Auto-tuner**: Feedback-driven optimizer that adjusts source boosts in tuneables based on effectiveness data. Validates via schema and tracks drift before writing.
- **Bridge cycle**: Periodic event capture + learning cycle. Hot-reloads tuneables at start of each cycle.
- **Chip**: Domain module for trigger/observer/mapping logic (present but premium-gated in OSS).
- **Cognitive insight**: Confidence-scored, actionability-annotated learned advice.
- **Context sync**: Process that publishes verified insights to runtime-facing context artifacts.
- **Drift (tuneables)**: Normalized distance between runtime `~/.spark/tuneables.json` and version-controlled `config/tuneables.json` baseline. Tracked by `lib/tuneables_drift.py`, alerts when >0.3.
- **EIDOS**: Episodic intelligence with mandatory prediction->outcome->evaluation loop. Budget-constrained episodes with phase-driven state machine.
- **Evidence gate**: Tunable confidence/quality threshold path for storing or rejecting learnings.
- **Hot-reload**: Mtime-based change detection for tuneables. Coordinator (`lib/tuneables_reload.py`) dispatches changed sections to registered module callbacks each bridge cycle.
- **Meta-Ralph**: Quality gate that scores insights 0-10. Threshold configurable via tuneables (default 4.5). Rejects noise, tautologies, platitudes.
- **Retrievers**: Routes incoming prompts/events to memory and domain-specific evidence.
- **Schema (tuneables)**: Central validation in `lib/tuneables_schema.py` with type/default/min/max/description metadata. Clamps out-of-bounds values rather than rejecting.
- **Tuneables**: Runtime knobs in `~/.spark/tuneables.json`. Schema-validated, hot-reloaded each bridge cycle, drift-tracked against baseline. Reference: `TUNEABLES.md` and `docs/TUNEABLES_REFERENCE.md`.
- **validate_and_store_insight()**: Unified write gate (`lib/validate_and_store.py`) that routes every cognitive insight through Meta-Ralph before storage. Fail-open: quarantines on error, then stores anyway. Controllable via `flow.validate_and_store_enabled` tuneable.
- **Fallback budget**: Rate-limiter on quick/packet fallback emissions in advisory_engine (`fallback_budget_cap` / `fallback_budget_window`). Prevents noise from dominating when retrieval fails.
- **Noise patterns**: Shared module (`lib/noise_patterns.py`) consolidating noise detection regex from 5 locations into one importable set.
- **Rejection telemetry**: Per-reason counters at every advisory exit path, flushed to `~/.spark/advisory_rejection_telemetry.json`. Used by observatory and pulse for diagnostics.
- **Fail-open quarantine**: When Meta-Ralph raises an exception during validate_and_store, the insight is logged to `~/.spark/insight_quarantine.jsonl` AND still stored in cognitive (true fail-open, not fail-closed).
- **Source boosts**: Auto-tuner multipliers per advice source. Effective bounds come from `auto_tuner.min_boost` / `auto_tuner.max_boost` (baseline currently 0.2-2.0). Stored in `auto_tuner.source_boosts`.
