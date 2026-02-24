# Spark OSS Documentation Index

Canonical navigation hub. Start here.

## First Read Order
- `docs/SPARK_ONBOARDING_COMPLETE.md` - Canonical first-time onboarding (install -> first insight -> troubleshooting).
- `docs/GETTING_STARTED_5_MIN.md` - Minimal quick path.
- `docs/QUICKSTART.md` - CLI and runtime operations quickstart.

## Core launch docs
- `README.md`
- `docs/SPARK_ONBOARDING_COMPLETE.md`
- `docs/LAUNCH_DOCUMENTATION_MAP.md`
- `OSS_ONLY_MANIFEST.md`
- `docs/GLOSSARY.md`
- `docs/GETTING_STARTED_5_MIN.md`
- `docs/QUICKSTART.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `CHANGELOG.md`

## Intelligence model
- `Intelligence_Flow.md` — Full architecture (pipeline, subsystems, tuneables, env vars)
- `Intelligence_Flow_Map.md` — Visual flow map
- `docs/PROJECT_INTELLIGENCE.md`
- `docs/CONSCIOUSNESS_BRIDGE_V1.md`
- `docs/MEMORY_ACTIONABILITY_FRAMEWORK.md`
- `docs/RETRIEVAL_LEVELS.md`
- `docs/RETRIEVAL_IMPROVEMENT_PLAN.md`

## Subsystem deep dives
- `META_RALPH.md` — Quality gate scoring, thresholds, telemetry
- `SEMANTIC_ADVISOR_DESIGN.md` — Semantic retrieval + hybrid ranking design
- `EIDOS_GUIDE.md` — Episodic intelligence (comprehensive reference)
- `EIDOS_QUICKSTART.md` — EIDOS quick-start (30-sec onboarding, CLI, troubleshooting)
- `STUCK_STATE_PLAYBOOK.md` — Rabbit-hole detection (loss of progress signal)
- `docs/ADVISORY_AND_LEARNING_BENCHMARKS.md`
- `docs/ADVISORY_BENCHMARK_SYSTEM.md`
- `docs/ADVISORY_FLOW_SCORECARD.md`
- `docs/SELF_IMPROVEMENT_SYSTEMS.md`

## Tuneables and routing
- `docs/CONFIG_AUTHORITY.md` — Canonical precedence model, env var reference, hot-reload matrix
- `docs/TUNEABLES_REFERENCE.md` — Auto-generated schema reference (231 keys, 31 sections) with code examples
- `docs/QUICKSTART.md#configuring-tuneables` — User-facing guide: how to change, precedence, troubleshooting
- `lib/tuneables_schema.py` — Central schema validator (type, bounds, defaults)
- `lib/tuneables_reload.py` — Hot-reload coordinator (mtime-based callback dispatch)
- `lib/tuneables_drift.py` — Drift distance from baseline (`config/tuneables.json`)

## Chips (domain learning modules)
- `docs/CHIPS.md`
- `docs/CHIP_WORKFLOW.md`
- `docs/CHIP_VIBECODING.md`
- `docs/CHIPS_SCHEMA_FIRST_PLAYBOOK.md`
- `docs/SPARK_CHIPS_ARCHITECTURE.md`

## Integrations
- `docs/claude_code.md`
- `docs/cursor.md`
- `docs/adapters.md`
- `docs/LEARNING_SYSTEMS_NEW_SPARK_INTEGRATION_MAP.md`
- `docs/OPENCLAW_INTEGRATION.md`
- `docs/OPENCLAW_OPERATIONS.md`
- `docs/OPENCLAW_PATHS_AND_DATA_BOUNDARIES.md`
- `docs/openclaw/` — OpenClaw operational docs (config snippets, verification, workflow)
- `docs/MINIMAX_INTEGRATION.md`
- `docs/LLM_INTEGRATION.md`
- `docs/DEEPSEEK_ISOLATION_RULES.md`

## Operations and observability
- `PRODUCTION_READINESS.md` — Loop gates, open items
- `OPTIMIZATION_CHECKER.md` — Rollback map + optimization changelog
- `SCHEDULER.md` — Scheduler tasks (mention poll, engagement, research, niche scan)
- `docs/OBSIDIAN_OBSERVATORY_GUIDE.md` — Observatory setup and usage
- `docs/PIPELINE_AUDIT_AND_FIXES.md`
- `docs/observability/HEALTH_CONTRACT.md`
- `docs/observability/SLOS.md`
- `docs/observability/ONCALL_AND_INCIDENTS.md`
- `docs/PROGRAM_STATUS.md`

## Safety and boundaries
- `docs/OSS_BOUNDARY.md`
- `docs/OPEN_CORE_FREEMIUM_MODEL.md`
- `docs/RESPONSIBLE_PUBLIC_RELEASE.md`
- `docs/SPARK_LIGHTWEIGHT_OPERATING_MODE.md`
- `docs/security/THREAT_MODEL.md`

## Emotions and personality
- `docs/SPARK_EMOTIONS_V2.md` — Canonical emotion model
- `docs/SPARK_EMOTIONS_IMPLEMENTATION.md`

## Launch
- `docs/launch/LAUNCH_SCOPE_AND_GATES.md`
- `docs/launch/ANNOUNCEMENT_PACK.md`
- `docs/launch/LAUNCH_ASSETS.md`
- `docs/launch/POST_LAUNCH_MONITORING.md`
- `docs/release/RELEASE_CANDIDATE.md`

## Support
- `docs/support/SUPPORT_PLAYBOOK.md`
- `docs/support/TROUBLESHOOTING_KB.md`
- `docs/support/ESCALATION.md`
- `docs/support/MACROS.md`

## Research
- `docs/research/CARMACK_AND_AGI_ENGINEERING_ALIGNMENT.md`
- `docs/research/AGI_GUARDRAILS_IMMUTABILITY.md`
- `docs/research/AGI_SCIENTIST_MATRIX.md`

## Prompts
- `prompts/SPARK_INTELLIGENCE_PROMPT_LIBRARY.md` — 10 operator prompts
- `prompts/ADVISORY_DAILY_SELF_REVIEW_PROMPT.md`
- `prompts/CARMACK_SPARK_REVIEW_PROMPT.md`

## Learning guide
- `SPARK_LEARNING_GUIDE.md` - Primitive vs valuable learning, tiers, chips
- `docs/ONBOARDING.md` - Legacy onboarding notes (superseded by `docs/SPARK_ONBOARDING_COMPLETE.md`)
- `docs/CHANGE_AND_UPGRADE_WORKFLOW.md`
