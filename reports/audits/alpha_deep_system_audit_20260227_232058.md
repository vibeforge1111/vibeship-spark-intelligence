# Alpha Deep System Audit (2026-02-27T23:20:58.469092Z)

- Workspace: `C:\Users\USER\Desktop\vibeship-spark-intelligence`
- Observatory path: `C:\Users\USER\Desktop\vibeship-spark-intelligence\_observatory`
- Files audited: `784`
- Python files: `541`
- Ruff issues: `1206`
- Circular dependency groups: `1`

## Status Counts
- healthy: 659
- degraded: 47
- needs-migration: 40
- orphaned: 38

## Priority Counts
- low: 659
- medium: 66
- high: 59

## Circular Dependencies
- (2) lib.research.mastery, lib.research.web_research

## File-by-File Status
CHANGELOG.md - needs-migration
  - Issues: missing_code_refs:8
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
CODE_OF_CONDUCT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
CONTRIBUTING.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
EIDOS_GUIDE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
EIDOS_QUICKSTART.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
Intelligence_Flow.md - needs-migration
  - Issues: missing_code_refs:64
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
Intelligence_Flow_Map.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
LICENSE - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
META_RALPH.md - needs-migration
  - Issues: missing_code_refs:1
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
MoE_Plan.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
OPENCLAW_FULL_SYSTEM_BRIEF.md - needs-migration
  - Issues: missing_code_refs:1
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
OPENCLAW_IMPLEMENTATION_TASKS.md - needs-migration
  - Issues: missing_code_refs:1
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
OPENCLAW_TREND_FLOW_BRIEF.md - needs-migration
  - Issues: missing_code_refs:2
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
OPTIMIZATION_CHECKER.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
OSS_ONLY_MANIFEST.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
PRODUCTION_READINESS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
PROJECT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
README.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
REPO_HYGIENE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
SCHEDULER.md - needs-migration
  - Issues: missing_code_refs:1
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
SECURITY.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
SEMANTIC_ADVISOR_DESIGN.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
SKILL.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
SPARK_EMOTIONS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
SPARK_LEARNING_GUIDE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
STUCK_STATE_PLAYBOOK.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
TREND_FLOW_SCHEMA.md - needs-migration
  - Issues: missing_code_refs:2
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
TUNEABLES.md - needs-migration
  - Issues: missing_code_refs:6
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
VIBESHIP_OPTIMIZER.md - needs-migration
  - Issues: missing_code_refs:4
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
adapters/__init__.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_adapter_token_resolution, tests.test_openclaw_tailer_capture_policy, tests.test_openclaw_tailer_hook_events, tests.test_openclaw_tailer_telemetry, tests.test_openclaw_tailer_workflow_summary] | relies_on=[none]
adapters/_common.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[adapters.clawdbot_tailer, adapters.openclaw_tailer, adapters.stdin_ingest] | relies_on=[none]
adapters/clawdbot_tailer.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[adapters._common]
adapters/codex_hook_bridge.py - degraded
  - Issues: oversized:1223, long_func:201, lint_top:I001:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[lib.jsonl_utils]
adapters/openclaw_tailer.py - degraded
  - Issues: oversized:1332, long_func:281, lint_top:W293:5,I001:1,F401:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[adapters._common, lib.config_authority]
adapters/stdin_ingest.py - healthy
  - Issues: lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[adapters._common]
bridge_worker.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.bridge_cycle, lib.diagnostics, lib.pipeline]
cleanup_insights.py - healthy
  - Issues: lint_top:E401:1,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
cli.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[spark.cli]
config/learning_sources.yaml - healthy
  - Issues: config_surface
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
config/opportunity_scanner.env.example - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
config/release_sast_baseline.json - healthy
  - Issues: config_surface
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
config/tuneables.json - healthy
  - Issues: config_surface
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ADVISORY_AND_LEARNING_BENCHMARKS.md - needs-migration
  - Issues: missing_code_refs:1
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ADVISORY_BENCHMARK_SYSTEM.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ADVISORY_DAY_TRIAL.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ADVISORY_FLOW_SCORECARD.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ADVISORY_FLOW_TASKS.md - needs-migration
  - Issues: missing_code_refs:5
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ADVISORY_OBSIDIAN_PLAYBOOK.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ADVISORY_REALISM_PLAYBOOK.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ADVISORY_RENEWAL_SYSTEM.md - needs-migration
  - Issues: missing_code_refs:2
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ADVISORY_SYSTEM.md - needs-migration
  - Issues: missing_code_refs:6
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ADVISORY_SYSTEM_FLOWCHART.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/AI_MANIFESTO.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/CHANGE_AND_UPGRADE_WORKFLOW.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/CHIPS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/CHIPS_SCHEMA_FIRST_PLAYBOOK.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/CHIP_VIBECODING.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/CHIP_WORKFLOW.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/CODEX_HOOK_BRIDGE_ROLLOUT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/CODEX_REVIEW_PROMPT.md - needs-migration
  - Issues: missing_code_refs:1
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/CONFIG_AUTHORITY.md - needs-migration
  - Issues: missing_code_refs:10
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/CONSCIOUSNESS_BRIDGE_V1.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/DEEPSEEK_ISOLATION_RULES.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/DOCS_INDEX.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/DOCUMENTATION_SYSTEM.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/FASTTRACK_12PR_PARALLEL_RUNBOOK.md - needs-migration
  - Issues: missing_code_refs:6
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/GETTING_STARTED_5_MIN.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/GLOSSARY.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/INTELLIGENCE_FLOW_EVOLUTION.md - needs-migration
  - Issues: missing_code_refs:7
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/LAUNCH_DOCUMENTATION_MAP.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/LEARNING_SYSTEMS_EXECUTION_LOOP_COMPREHENSIVE_GUIDE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/LEARNING_SYSTEMS_EXECUTION_LOOP_RUNBOOK_TEMPLATE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/LEARNING_SYSTEMS_NEW_SPARK_INTEGRATION_MAP.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/LLM_AREAS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/LLM_INTEGRATION.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/MEMORY_ACTIONABILITY_FRAMEWORK.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/MINIMAX_INTEGRATION.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/OBSIDIAN_OBSERVATORY_GUIDE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/ONBOARDING.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/OPENCLAW_INTEGRATION.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/OPENCLAW_OPERATIONS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/OPENCLAW_PATCH_CHECKLIST.md - needs-migration
  - Issues: missing_code_refs:4
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/OPENCLAW_PATHS_AND_DATA_BOUNDARIES.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/OPENCLAW_RESEARCH_AND_UPDATES.md - needs-migration
  - Issues: missing_code_refs:15
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/OPEN_CORE_FREEMIUM_MODEL.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/OPPORTUNITIES.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/OSS_BOUNDARY.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/PIPELINE_AUDIT_AND_FIXES.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/PROGRAM_STATUS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/PROJECT_INTELLIGENCE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/QUICKSTART.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/REMEDIATION_PLAN_2026-02-22.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/REPO_CONTENT_POLICY.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/RESPONSIBLE_PUBLIC_RELEASE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/RETRIEVAL_IMPROVEMENT_PLAN.md - needs-migration
  - Issues: missing_code_refs:2
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/RETRIEVAL_LEVELS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SELF_IMPROVEMENT_SYSTEMS.md - needs-migration
  - Issues: missing_code_refs:54
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_2H_LAUNCH_READINESS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_8PR_EXECUTION_PLAN.md - needs-migration
  - Issues: missing_code_refs:1
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_ARCHITECTURE_NOW.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_DEBT_REGISTER.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_FORWARD_RECOMMENDATIONS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_FUSION_10PR_PLAN.md - needs-migration
  - Issues: missing_code_refs:35
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_IMPLEMENTATION_STATUS.md - needs-migration
  - Issues: missing_code_refs:99
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_MIGRATION_PLAYBOOK.md - needs-migration
  - Issues: missing_code_refs:3
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_PHASED_STABILITY_PLAN.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_PR06_LEGACY_DELETION_CANDIDATES.md - needs-migration
  - Issues: missing_code_refs:10
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_PR10_DELETION_SWEEP_REPORT.md - needs-migration
  - Issues: missing_code_refs:15
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_REBUILD_PLAN.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_REDUCTION_WAVES_PLAN.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_RUNTIME_CONTRACT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_START_EXECUTION_PLAN.md - needs-migration
  - Issues: missing_code_refs:1
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ALPHA_TRANSFORMATION_REPORT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ASSESSMENT_CHECKLIST.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_CHIPS_ARCHITECTURE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_CLI_SYSTEM_BLUEPRINT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_EMOTIONS_IMPLEMENTATION.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_EMOTIONS_V2.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_LIGHTWEIGHT_OPERATING_MODE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_ONBOARDING_COMPLETE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_V2_FASTTRACK_IMPLEMENTATION_PLAN.md - needs-migration
  - Issues: missing_code_refs:6
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_V2_RISK_BALANCED_ADOPTION_PLAN.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/SPARK_V2_SIMPLIFICATION_PLAN.md - needs-migration
  - Issues: missing_code_refs:13
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/TUNEABLES_REFERENCE.md - needs-migration
  - Issues: missing_code_refs:18
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/VIBEFORGE_LOOP.md - needs-migration
  - Issues: missing_code_refs:6
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/VISION.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/adapters.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/architecture/ADR-2026-02-28-alpha-transition-precision-execution.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/architecture/ADVISORY_PHASE2_DEDUP_ROLLOUT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/architecture/CONSCIOUSNESS_INTELLIGENCE_ALIGNMENT_TASK_SYSTEM.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/architecture/OPENCLAW_EMOTION_MEMORY_INTELLIGENCE_UNITY.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/architecture/PREDICTION_OUTCOME_LOOP.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/architecture/PREDICTIVE_ADVISORY_IMPLEMENTATION_BACKLOG.md - needs-migration
  - Issues: missing_code_refs:59
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/architecture/PREDICTIVE_ADVISORY_SYSTEM_BLUEPRINT.md - needs-migration
  - Issues: missing_code_refs:20
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/claude_code.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/cursor.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/launch/ANNOUNCEMENT_PACK.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/launch/LAUNCH_ASSETS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/launch/LAUNCH_SCOPE_AND_GATES.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/launch/POST_LAUNCH_MONITORING.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/memory-retrieval-status.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/observability/HEALTH_CONTRACT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/observability/ONCALL_AND_INCIDENTS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/observability/SLOS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/openclaw/INTEGRATION_BACKLOG.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/openclaw/INTEGRATION_CHANGELOG.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/openclaw/OPENCLAW_CONFIG_SNIPPETS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/openclaw/OPERATIONS_WORKFLOW.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/openclaw/README.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/openclaw/REALTIME_E2E_PROMPT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/openclaw/VERIFICATION_LOG.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/pr-automation/PR_REVIEW_AUTOMATION.md - needs-migration
  - Issues: missing_code_refs:3
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/release/RELEASE_CANDIDATE.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/research/AGI_GUARDRAILS_IMMUTABILITY.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/research/AGI_SCIENTIST_MATRIX.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/research/CARMACK_AND_AGI_ENGINEERING_ALIGNMENT.md - needs-migration
  - Issues: missing_code_refs:2
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/security/THREAT_MODEL.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/social_psychology_patterns.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/support/DAILY_SUPPORT_TRACKING.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/support/ESCALATION.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/support/MACROS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/support/SUPPORT_PLAYBOOK.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
docs/support/TROUBLESHOOTING_KB.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
examples/README.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
examples/health_check.ps1 - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
extensions/openclaw-spark-telemetry/README.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
extensions/openclaw-spark-telemetry/index.ts - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
extensions/openclaw-spark-telemetry/openclaw.plugin.json - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
header.png - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
hooks/__init__.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_observe_hook_telemetry] | relies_on=[none]
hooks/observe.py - degraded
  - Issues: lint_density:37, oversized:1367, long_func:515, lint_top:W293:25,I001:7,F401:4
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[scripts.spark_sandbox] | relies_on=[lib.advice_feedback, lib.advisor, lib.advisory_engine_alpha, lib.aha_tracker, lib.auto_promote, lib.cognitive_learner]
install.ps1 - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
install.sh - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/__init__.py - healthy
  - Issues: lint_top:I001:1,W291:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.context_sync, lib.prefetch_worker, scripts.advisory_packet_compaction, scripts.spark_sandbox, scripts.verify_queue, tests.test_advisory_intent_taxonomy] | relies_on=[none]
lib/action_matcher.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.advisory_auto_scorer, scripts.advisory_day_trial, tests.test_advisory_auto_scorer] | relies_on=[none]
lib/advice_feedback.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[hooks.observe, lib.advisor, scripts.advisory_day_trial, scripts.advisory_tag_outcome, tests.test_advice_feedback_correlation] | relies_on=[lib.diagnostics, lib.file_lock]
lib/advisor.py - degraded
  - Issues: oversized:6136, long_func:442, lint_top:I001:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[hooks.observe, lib.advisory_engine_alpha, lib.bridge, lib.preferences, lib.production_gates, scripts.advise_act] | relies_on=[lib.advice_feedback, lib.advisory_synthesizer, lib.aha_tracker, lib.cognitive_learner, lib.config_authority, lib.convo_analyzer]
lib/advisory_engine_alpha.py - degraded
  - Issues: long_func:284, lint_top:I001:2
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[hooks.observe, lib.preferences, scripts.spark_alpha_replay_arena, sparkd, tests.test_advisory_engine_alpha, tests.test_advisory_orchestrator] | relies_on=[lib.advisor, lib.advisory_gate, lib.advisory_packet_store, lib.advisory_synthesizer, lib.cognitive_learner, lib.config_authority]
lib/advisory_gate.py - degraded
  - Issues: long_func:198, lint_top:F401:1,N806:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.advisory_engine_alpha, scripts.verify_advisory_emissions, tests.test_advisory_calibration, tests.test_advisory_engine_alpha, tests.test_advisory_gate_config, tests.test_advisory_gate_evaluate] | relies_on=[lib.config_authority, lib.outcome_predictor, lib.runtime_session_state, lib.tuneables_reload]
lib/advisory_packet_store.py - degraded
  - Issues: oversized:3543, long_func:433, lint_top:I001:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.advisory_engine_alpha, lib.integration_status, lib.production_gates, scripts.advisory_tag_outcome, scripts.check_obsidian_watchtower, scripts.reconcile_advisory_packet_spine] | relies_on=[lib.config_authority, lib.packet_spine, lib.tuneables_reload]
lib/advisory_synthesizer.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.advisory_engine_alpha, lib.eidos_refiner, lib.llm, lib.llm_dispatch, lib.meta_ralph] | relies_on=[lib.config_authority, lib.consciousness_bridge, lib.diagnostics, lib.soul_metrics, lib.soul_upgrade, lib.spark_emotions]
lib/agent_feedback.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.test_feedback] | relies_on=[none]
lib/aha_tracker.py - healthy
  - Issues: lint_top:W293:2,I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[hooks.observe, lib.advisor, lib.bridge, lib.prediction_loop, lib.resonance, lib.validation_loop] | relies_on=[none]
lib/auto_promote.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[hooks.observe, tests.test_promotion_config_authority] | relies_on=[lib.config_authority, lib.diagnostics, lib.promoter, lib.tuneables_reload]
lib/auto_tuner.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, scripts.tune_replay] | relies_on=[lib.llm_area_prompts, lib.llm_dispatch, lib.spark_memory_spine, lib.tuneables_drift, lib.tuneables_schema]
lib/bridge.py - degraded
  - Issues: lint_density:38, long_func:252, lint_top:W293:31,I001:3,W291:2
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[scripts.mem_profile2, scripts.mem_profile3, tests.test_bridge_context_sources] | relies_on=[lib.advisor, lib.aha_tracker, lib.cognitive_learner, lib.config_authority, lib.diagnostics, lib.exposure_tracker]
lib/bridge_cycle.py - degraded
  - Issues: oversized:1262, long_func:471, lint_top:I001:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[bridge_worker, lib.doctor, lib.output_adapters.openclaw, lib.service_control, scripts.mem_profile, scripts.spark_sandbox] | relies_on=[lib.auto_tuner, lib.chip_merger, lib.cognitive_learner, lib.config_authority, lib.content_learner, lib.context_sync]
lib/canary_assistant.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/capture_cli.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/carmack_kpi.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.carmack_kpi_scorecard, scripts.tune_replay, scripts.vibeforge] | relies_on=[lib.service_control]
lib/chip_merger.py - healthy
  - Issues: lint_top:I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, scripts.mem_profile3, tests.test_chips_quality_integration, tests.test_remaining_config_authority] | relies_on=[lib.config_authority, lib.exposure_tracker, lib.queue, lib.tuneables_reload, lib.validate_and_store]
lib/clawdbot_memory_setup.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/cognitive_learner.py - degraded
  - Issues: oversized:2332, long_func:411, lint_top:I001:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[hooks.observe, lib.advisor, lib.advisory_engine_alpha, lib.bridge, lib.bridge_cycle, lib.cognitive_signals] | relies_on=[lib.config_authority, lib.context_envelope, lib.distillation_transformer, lib.exposure_tracker, lib.feature_flags, lib.llm_area_prompts]
lib/cognitive_signals.py - healthy
  - Issues: lint_top:F401:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[hooks.observe, tests.test_10_improvements] | relies_on=[lib.cognitive_learner, lib.diagnostics, lib.importance_scorer, lib.validate_and_store]
lib/config_authority.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[adapters.openclaw_tailer, hooks.observe, lib.advisor, lib.advisory_engine_alpha, lib.advisory_gate, lib.advisory_packet_store] | relies_on=[lib.tuneables_schema]
lib/consciousness_bridge.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisory_synthesizer, scripts.consciousness_bridge_smoke, tests.test_advisory_synthesizer_consciousness_bridge] | relies_on=[none]
lib/content_learner.py - healthy
  - Issues: lint_top:I001:1,F401:1,E741:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, scripts.mem_profile3, tests.test_content_learner] | relies_on=[lib.cognitive_learner, lib.diagnostics]
lib/context_envelope.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.cognitive_learner, scripts.backfill_context_envelopes, tests.test_context_envelope] | relies_on=[none]
lib/context_sync.py - degraded
  - Issues: oversized:1508, long_func:217, lint_top:I001:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.bridge_cycle, lib.orchestration, scripts.mem_profile2, scripts.mem_profile3, tests.test_production_hardening] | relies_on=[lib, lib.cognitive_learner, lib.config_authority, lib.exposure_tracker, lib.memory_compaction, lib.mind_bridge]
lib/contradiction_detector.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator] | relies_on=[lib.cognitive_learner, lib.embeddings]
lib/conversation_core.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.run_conversation_calibration] | relies_on=[none]
lib/convo_analyzer.py - healthy
  - Issues: lint_top:I001:2,F401:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, tests.test_convo_iq] | relies_on=[lib.x_voice]
lib/convo_events.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_convo_iq] | relies_on=[none]
lib/cross_encoder_reranker.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor] | relies_on=[lib.diagnostics]
lib/depth_forge_scorer.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.depth_trainer] | relies_on=[none]
lib/depth_trainer.py - degraded
  - Issues: lint_density:32, oversized:4036, long_func:161, lint_top:F541:19,E701:5,I001:4
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[scripts.run_depth_training, scripts.run_depth_v3] | relies_on=[lib.cognitive_learner, lib.depth_forge_scorer, lib.eidos, lib.eidos.models, lib.meta_ralph]
lib/diagnostics.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[bridge_worker, hooks.observe, lib.advice_feedback, lib.advisory_engine_alpha, lib.advisory_synthesizer, lib.auto_promote] | relies_on=[none]
lib/distillation_transformer.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.cognitive_learner, lib.eidos.store, lib.eidos_intake, lib.eidos_refiner, tests.test_distillation_transformer] | relies_on=[lib.llm_area_prompts, lib.llm_dispatch, lib.noise_patterns]
lib/doctor.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:2,F541:2
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.bridge_cycle, lib.cognitive_learner, lib.ports, lib.queue, lib.service_control]
lib/effect_evaluator.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.advisory_auto_scorer] | relies_on=[none]
lib/eidos/__init__.py - healthy
  - Issues: lint_top:F811:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.depth_trainer, lib.production_gates, scripts.eidos_dashboard, scripts.trace_backfill, scripts.trace_query] | relies_on=[none]
lib/eidos/acceptance_compiler.py - orphaned
  - Issues: runtime_orphan, lint_top:F401:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.models]
lib/eidos/control_plane.py - healthy
  - Issues: lint_top:F401:3,I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.integration] | relies_on=[lib.config_authority, lib.eidos.models]
lib/eidos/distillation_engine.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.integration, tests.test_distillation_advisory] | relies_on=[none]
lib/eidos/elevated_control.py - healthy
  - Issues: lint_top:F401:4,I001:2,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.integration] | relies_on=[lib.config_authority, lib.eidos.models, lib.eidos.store]
lib/eidos/escalation.py - degraded
  - Issues: lint_issues:18, lint_top:F541:14,F401:3,I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[lib.eidos.integration] | relies_on=[lib.eidos.models]
lib/eidos/evidence_store.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.integration, tests.test_eidos_sql_hardening] | relies_on=[lib.eidos.store]
lib/eidos/guardrails.py - healthy
  - Issues: lint_top:I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.integration, tests.test_safety_guardrails] | relies_on=[lib.config_authority, lib.eidos.models]
lib/eidos/integration.py - degraded
  - Issues: lint_issues:13, long_func:145, lint_top:F401:11,I001:1,F541:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[hooks.observe] | relies_on=[lib.eidos.control_plane, lib.eidos.distillation_engine, lib.eidos.elevated_control, lib.eidos.escalation, lib.eidos.evidence_store, lib.eidos.guardrails]
lib/eidos/memory_gate.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.integration] | relies_on=[lib.eidos.models]
lib/eidos/metrics.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/eidos/migration.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.models, lib.eidos.store]
lib/eidos/minimal_mode.py - healthy
  - Issues: lint_top:F401:3,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.integration] | relies_on=[lib.eidos.models]
lib/eidos/models.py - healthy
  - Issues: lint_top:F401:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[hooks.observe, lib.depth_trainer, lib.eidos.acceptance_compiler, lib.eidos.control_plane, lib.eidos.elevated_control, lib.eidos.escalation] | relies_on=[lib.config_authority, lib.tuneables_reload]
lib/eidos/policy_patches.py - orphaned
  - Issues: runtime_orphan, lint_top:F401:3,I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.models]
lib/eidos/retriever.py - healthy
  - Issues: lint_top:I001:1,F401:1,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.integration, tests.e2e_memory_to_advisory_v2, tests.test_retriever_keyword_matching] | relies_on=[lib.eidos.models, lib.eidos.store]
lib/eidos/store.py - degraded
  - Issues: oversized:1411, long_func:161, lint_top:I001:1,F841:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[hooks.observe, lib.advisor, lib.eidos.elevated_control, lib.eidos.evidence_store, lib.eidos.integration, lib.eidos.migration] | relies_on=[lib.distillation_transformer, lib.eidos.models, lib.eidos_refiner, lib.primitive_filter, lib.promoter]
lib/eidos/truth_ledger.py - orphaned
  - Issues: runtime_orphan, lint_top:F401:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.store]
lib/eidos/validation.py - healthy
  - Issues: lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.integration] | relies_on=[lib.eidos.models]
lib/eidos_curriculum.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.llm_area_prompts, lib.llm_dispatch]
lib/eidos_curriculum_autofix.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/eidos_intake.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, tests.test_eidos_intake] | relies_on=[lib.distillation_transformer, lib.noise_patterns]
lib/eidos_refiner.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.store] | relies_on=[lib.advisory_synthesizer, lib.config_authority, lib.distillation_transformer, lib.elevation, lib.llm, lib.llm_area_prompts]
lib/elevation.py - healthy
  - Issues: lint_top:N806:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos_refiner, lib.meta_ralph, tests.test_elevation] | relies_on=[none]
lib/embeddings.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.contradiction_detector, lib.importance_scorer, lib.memory_store, lib.prediction_loop, lib.semantic_retriever, tests.test_embeddings] | relies_on=[none]
lib/emit_metrics.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.cross_surface_drift_checker, scripts.memory_quality_observatory] | relies_on=[none]
lib/emitter.py - healthy
  - Issues: lint_top:I001:2,F401:2,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisory_engine_alpha, scripts.verify_advisory_emissions, tests.test_advisory_calibration, tests.test_advisory_engine_alpha, tests.test_pr1_config_authority] | relies_on=[lib.config_authority, lib.diagnostics, lib.tuneables_reload]
lib/engagement_tracker.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.bridge_cycle, spark_scheduler, tests.test_engagement_pulse] | relies_on=[none]
lib/error_taxonomy.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_error_taxonomy] | relies_on=[none]
lib/error_translator.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/evaluation.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.outcome_log, lib.prediction_loop]
lib/events.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[sparkd, tests.test_event_validation, tests.test_sparkd_openclaw_runtime_bridge] | relies_on=[none]
lib/exposure_tracker.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge, lib.chip_merger, lib.cognitive_learner, lib.context_sync, lib.feedback, lib.orchestration] | relies_on=[lib.primitive_filter, lib.queue]
lib/feature_flags.py - healthy
  - Issues: lint_top:F401:3,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, lib.cognitive_learner, tests.test_pr1_config_authority] | relies_on=[lib.config_authority, lib.tuneables_reload]
lib/feedback.py - healthy
  - Issues: lint_top:I001:1,F401:1,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[hooks.observe, tests.test_feedback] | relies_on=[lib.cognitive_learner, lib.exposure_tracker, lib.outcome_log, lib.skills_router]
lib/feedback_effectiveness_cache.py - healthy
  - Issues: lint_top:F401:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor] | relies_on=[lib.diagnostics]
lib/feedback_loop.py - healthy
  - Issues: lint_top:F401:3,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, scripts.test_feedback, scripts.test_feedback2] | relies_on=[lib.cognitive_learner, lib.diagnostics, lib.outcome_log, lib.self_report, lib.validate_and_store]
lib/file_lock.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advice_feedback, lib.implicit_outcome_tracker, lib.learning_systems_bridge, lib.outcome_log, lib.tuneables_reload] | relies_on=[none]
lib/growth_tracker.py - degraded
  - Issues: lint_density:56, runtime_orphan, lint_top:W293:48,F541:4,W291:2
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/helpfulness_llm_adjudicator.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/helpfulness_watcher.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/hypothesis_tracker.py - healthy
  - Issues: lint_top:I001:1,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator] | relies_on=[lib.cognitive_learner, lib.validate_and_store]
lib/implicit_outcome_tracker.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[hooks.observe, lib.advisory_engine_alpha] | relies_on=[lib.diagnostics, lib.file_lock]
lib/importance_scorer.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.cognitive_signals, lib.pattern_detection.aggregator, tests.test_10_improvements] | relies_on=[lib.cognitive_learner, lib.embeddings]
lib/ingest_validation.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.diagnostics, lib.queue]
lib/integration_status.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.alpha_preflight_bundle] | relies_on=[lib.advisory_packet_store]
lib/intelligence_llm_preferences.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.intelligence_llm_setup, tests.test_intelligence_llm_preferences] | relies_on=[lib.config_authority, lib.llm_dispatch]
lib/jsonl_utils.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[adapters.codex_hook_bridge, hooks.observe, lib.advisory_engine_alpha, lib.noise_classifier, lib.runtime_quarantine, scripts.advisory_spine_parity_gate] | relies_on=[none]
lib/learning_systems_bridge.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.learning_systems_bridge, tests.test_learning_systems_bridge] | relies_on=[lib.cognitive_learner, lib.config_authority, lib.file_lock, lib.validate_and_store]
lib/llm.py - healthy
  - Issues: lint_top:I001:3
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos_refiner, lib.llm_dispatch, lib.meta_ralph, scripts.test_advisory, scripts.test_llm, scripts.test_llm_live] | relies_on=[lib.advisory_synthesizer, lib.config_authority, lib.diagnostics, lib.queue]
lib/llm_area_prompts.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.advisory_engine_alpha, lib.auto_tuner, lib.cognitive_learner, lib.distillation_transformer, lib.eidos_curriculum] | relies_on=[none]
lib/llm_dispatch.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.advisory_engine_alpha, lib.auto_tuner, lib.cognitive_learner, lib.distillation_transformer, lib.eidos_curriculum] | relies_on=[lib.advisory_synthesizer, lib.config_authority, lib.diagnostics, lib.llm, lib.tuneables_reload]
lib/markdown_writer.py - degraded
  - Issues: lint_density:36, lint_top:W293:32,F401:2,I001:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[scripts.spark_sandbox] | relies_on=[lib.cognitive_learner]
lib/memory_banks.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.advisory_engine_alpha, lib.bridge, lib.memory_capture, lib.memory_migrate, lib.mind_bridge] | relies_on=[lib.config_authority, lib.memory_store, lib.queue, lib.spark_emotions, lib.tuneables_reload]
lib/memory_capture.py - degraded
  - Issues: long_func:142
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.bridge_cycle, scripts.mem_profile2, scripts.memory_quality_observatory, scripts.spark_sandbox, tests.test_memory_capture_safety, tests.test_remaining_config_authority] | relies_on=[lib.cognitive_learner, lib.config_authority, lib.llm_area_prompts, lib.llm_dispatch, lib.memory_banks, lib.outcome_checkin]
lib/memory_compaction.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.context_sync, scripts.cognitive_memory_compaction, tests.test_memory_compaction] | relies_on=[none]
lib/memory_migrate.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.memory_banks, lib.memory_store]
lib/memory_spine_parity.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.memory_spine_parity_gate, scripts.memory_spine_parity_report, tests.test_memory_spine_parity] | relies_on=[none]
lib/memory_store.py - degraded
  - Issues: oversized:1368, long_func:305, lint_top:I001:2,F401:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.memory_banks, lib.memory_migrate, tests.test_memory_emotion_integration] | relies_on=[lib.config_authority, lib.embeddings, lib.spark_emotions, lib.tuneables_reload]
lib/meta_alpha_scorer.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.meta_ralph, tests.test_meta_alpha_scorer_guardrails] | relies_on=[none]
lib/meta_ralph.py - degraded
  - Issues: oversized:2875, long_func:291, lint_top:I001:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.advisor, lib.advisory_engine_alpha, lib.bridge_cycle, lib.depth_trainer, lib.opportunity_scanner, lib.pipeline] | relies_on=[lib.advisory_synthesizer, lib.cognitive_learner, lib.config_authority, lib.eidos.store, lib.elevation, lib.llm]
lib/metalearning/__init__.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/metalearning/evaluator.py - healthy
  - Issues: lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.metalearning.reporter, lib.metalearning.strategist] | relies_on=[none]
lib/metalearning/reporter.py - orphaned
  - Issues: runtime_orphan, lint_top:F541:4,F401:2,I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.metalearning.evaluator, lib.metalearning.strategist]
lib/metalearning/strategist.py - healthy
  - Issues: lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.metalearning.reporter, tests.test_10_improvements] | relies_on=[lib.metalearning.evaluator]
lib/metric_contract.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.production_gates, scripts.cross_surface_drift_checker, scripts.memory_quality_observatory, tests.test_metric_contract] | relies_on=[none]
lib/mind_bridge.py - degraded
  - Issues: lint_density:39, lint_top:W293:37,I001:2
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.advisor, lib.bridge, lib.bridge_cycle, lib.context_sync, tests.test_mind_bridge_auth] | relies_on=[lib.cognitive_learner, lib.memory_banks, lib.ports]
lib/niche_mapper.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, spark_scheduler, tests.test_niche_net] | relies_on=[lib.x_voice]
lib/noise_classifier.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.cognitive_learner, lib.meta_ralph, lib.promoter, tests.test_noise_classifier, tests.test_promoter_noise_classifier] | relies_on=[lib.jsonl_utils, lib.noise_patterns, lib.primitive_filter]
lib/noise_patterns.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.distillation_transformer, lib.eidos_intake, lib.noise_classifier, lib.pattern_detection.why] | relies_on=[none]
lib/observatory/__init__.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, scripts.generate_observatory] | relies_on=[none]
lib/observatory/advisory_reverse_engineering.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.config]
lib/observatory/canvas_generator.py - orphaned
  - Issues: runtime_orphan, lint_top:F841:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/observatory/config.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.observatory.advisory_reverse_engineering, lib.observatory.explorer, lib.observatory.readers, lib.observatory.system_flow_comprehensive, lib.observatory.system_flow_operator_playbook, lib.observatory.tuneables_deep_dive] | relies_on=[lib.config_authority, lib.tuneables_reload]
lib/observatory/explorer.py - degraded
  - Issues: oversized:1668, long_func:217
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[tests.test_observatory_helpfulness_explorer, tests.test_observatory_meta_ralph_totals] | relies_on=[lib.observatory.config, lib.observatory.linker, lib.observatory.readers, lib.spark_memory_spine]
lib/observatory/flow_dashboard.py - degraded
  - Issues: lint_density:44, runtime_orphan, lint_top:F541:42,I001:1,F841:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.linker]
lib/observatory/linker.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.observatory.explorer, lib.observatory.flow_dashboard, lib.observatory.stage_pages] | relies_on=[none]
lib/observatory/llm_areas_status.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/observatory/readability_pack.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/observatory/readers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.observatory.explorer, tests.test_observatory_advisory_feedback_metrics, tests.test_observatory_eidos_curriculum_metrics, tests.test_observatory_meta_ralph_totals] | relies_on=[lib.observatory.config, lib.spark_memory_spine]
lib/observatory/recovery_metrics.py - healthy
  - Issues: lint_top:F541:2,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_workflow_evidence] | relies_on=[lib.workflow_evidence]
lib/observatory/stage_pages.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_observatory_stage7_curriculum_page] | relies_on=[lib.observatory.linker]
lib/observatory/system_flow_comprehensive.py - degraded
  - Issues: long_func:242, runtime_orphan, lint_top:F401:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.config]
lib/observatory/system_flow_operator_playbook.py - degraded
  - Issues: long_func:223, runtime_orphan
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.config]
lib/observatory/tuneables_deep_dive.py - degraded
  - Issues: long_func:440
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[tests.test_observatory_tuneables_deep_dive] | relies_on=[lib.observatory.config, lib.tuneables_schema]
lib/onboard.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:2,F401:2,F841:2
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner, lib.queue, lib.service_control]
lib/onboarding/__init__.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/onboarding/context.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.onboarding.detector]
lib/onboarding/detector.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.onboarding.context] | relies_on=[none]
lib/onboarding/questions.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/openclaw_notify.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, spark_scheduler] | relies_on=[lib.diagnostics, lib.openclaw_paths]
lib/openclaw_paths.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, lib.openclaw_notify, lib.output_adapters.openclaw, scripts.openclaw_realtime_e2e_benchmark] | relies_on=[none]
lib/opportunity_inbox.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.opportunity_scanner_adapter] | relies_on=[none]
lib/opportunity_scanner.py - degraded
  - Issues: oversized:1625, long_func:228, lint_top:I001:2,F401:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.opportunity_scanner_adapter, tests.test_opportunity_scanner, tests.test_pr2_config_authority] | relies_on=[lib.config_authority, lib.diagnostics, lib.meta_ralph, lib.primitive_filter, lib.soul_upgrade, lib.tuneables_reload]
lib/opportunity_scanner_adapter.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.bridge, lib.bridge_cycle, tests.test_opportunity_scanner] | relies_on=[lib.opportunity_inbox, lib.opportunity_scanner]
lib/orchestration.py - healthy
  - Issues: lint_top:I001:3
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[sparkd, tests.test_orchestration] | relies_on=[lib.config_authority, lib.context_sync, lib.exposure_tracker, lib.outcome_log, lib.skills_router]
lib/outcome_checkin.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[hooks.observe, lib.bridge, lib.context_sync, lib.memory_capture] | relies_on=[lib.diagnostics]
lib/outcome_log.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.evaluation, lib.feedback, lib.feedback_loop, lib.memory_capture, lib.orchestration, lib.outcomes.linker] | relies_on=[lib.cognitive_learner, lib.exposure_tracker, lib.file_lock]
lib/outcome_predictor.py - healthy
  - Issues: lint_top:I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisory_engine_alpha, lib.advisory_gate, scripts.tune_replay] | relies_on=[lib.config_authority]
lib/outcomes/__init__.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
lib/outcomes/linker.py - healthy
  - Issues: lint_top:F401:3,I001:1,E741:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.outcomes.tracker] | relies_on=[lib.outcome_log, lib.outcomes.signals]
lib/outcomes/signals.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.outcomes.linker, lib.outcomes.tracker] | relies_on=[none]
lib/outcomes/tracker.py - orphaned
  - Issues: runtime_orphan, lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.outcomes.linker, lib.outcomes.signals]
lib/output_adapters/__init__.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.context_sync] | relies_on=[none]
lib/output_adapters/claude_code.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.output_adapters.common]
lib/output_adapters/clawdbot.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.output_adapters.common]
lib/output_adapters/codex.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.output_adapters.common]
lib/output_adapters/common.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.output_adapters.claude_code, lib.output_adapters.clawdbot, lib.output_adapters.codex, lib.output_adapters.cursor, lib.output_adapters.exports, lib.output_adapters.openclaw] | relies_on=[lib.diagnostics]
lib/output_adapters/cursor.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.output_adapters.common]
lib/output_adapters/exports.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.output_adapters.common]
lib/output_adapters/openclaw.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.bridge_cycle, lib.openclaw_paths, lib.output_adapters.common]
lib/output_adapters/windsurf.py - orphaned
  - Issues: runtime_orphan
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.output_adapters.common]
lib/packet_compaction.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.context_sync, scripts.advisory_packet_compaction, tests.test_packet_compaction] | relies_on=[none]
lib/packet_spine.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisory_packet_store, scripts.reconcile_advisory_packet_spine, scripts.refresh_packet_freshness, tests.test_advisory_packet_store, tests.test_advisory_packet_store_compaction_meta, tests.test_reconcile_advisory_packet_spine_helpers] | relies_on=[none]
lib/packet_spine_parity.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.advisory_spine_parity_gate, scripts.advisory_spine_parity_report, tests.test_advisory_spine_parity] | relies_on=[none]
lib/pattern_detection/__init__.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, tests.test_pattern_detection, tests.test_pipeline_health] | relies_on=[none]
lib/pattern_detection/aggregator.py - degraded
  - Issues: lint_issues:11, long_func:164, lint_top:F401:4,F841:4,I001:2
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.bridge_cycle, lib.pattern_detection.worker, lib.pipeline] | relies_on=[lib.cognitive_learner, lib.contradiction_detector, lib.eidos.store, lib.hypothesis_tracker, lib.importance_scorer, lib.pattern_detection.base]
lib/pattern_detection/base.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator, lib.pattern_detection.correction, lib.pattern_detection.engagement_surprise, lib.pattern_detection.repetition, lib.pattern_detection.semantic, lib.pattern_detection.sentiment] | relies_on=[none]
lib/pattern_detection/correction.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator] | relies_on=[lib.pattern_detection.base]
lib/pattern_detection/distiller.py - healthy
  - Issues: lint_top:F401:3,I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator, tests.test_10_improvements] | relies_on=[lib.config_authority, lib.eidos.models, lib.eidos.store, lib.primitive_filter, lib.promoter]
lib/pattern_detection/engagement_surprise.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator, tests.test_engagement_pulse] | relies_on=[lib.pattern_detection.base]
lib/pattern_detection/memory_gate.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator] | relies_on=[lib.eidos.models]
lib/pattern_detection/repetition.py - healthy
  - Issues: lint_top:F401:3
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator] | relies_on=[lib.pattern_detection.base]
lib/pattern_detection/request_tracker.py - healthy
  - Issues: lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator, tests.test_remaining_config_authority, tests.test_runtime_tuneable_sections] | relies_on=[lib.config_authority, lib.eidos.models, lib.tuneables_reload]
lib/pattern_detection/semantic.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator] | relies_on=[lib.pattern_detection.base]
lib/pattern_detection/sentiment.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator] | relies_on=[lib.pattern_detection.base]
lib/pattern_detection/why.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pattern_detection.aggregator] | relies_on=[lib.noise_patterns, lib.pattern_detection.base]
lib/pattern_detection/worker.py - healthy
  - Issues: lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.pipeline, scripts.spark_sandbox, scripts.status_local, spark_watchdog, sparkd] | relies_on=[lib.pattern_detection.aggregator, lib.queue]
lib/personality_evolver.py - healthy
  - Issues: lint_top:I001:3
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.personality_evolution, tests.test_personality_evolver] | relies_on=[lib.config_authority]
lib/pipeline.py - degraded
  - Issues: oversized:1229, long_func:239, lint_top:I001:3,N806:2,F401:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[bridge_worker, lib.bridge_cycle, scripts.mem_profile2, sparkd, tests.test_bridge_starvation, tests.test_pipeline_config_authority] | relies_on=[lib.cognitive_learner, lib.config_authority, lib.diagnostics, lib.meta_ralph, lib.pattern_detection.aggregator, lib.pattern_detection.worker]
lib/ports.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.doctor, lib.mind_bridge, lib.service_control, mind_server, spark_watchdog, sparkd] | relies_on=[none]
lib/prediction_loop.py - healthy
  - Issues: lint_top:I001:3,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, lib.evaluation, scripts.mem_profile3, scripts.spark_sandbox, tests.test_pr2_config_authority] | relies_on=[lib.aha_tracker, lib.cognitive_learner, lib.config_authority, lib.diagnostics, lib.embeddings, lib.exposure_tracker]
lib/preferences.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.advisory_setup, tests.test_advisory_preferences] | relies_on=[lib.advisor, lib.advisory_engine_alpha, lib.advisory_synthesizer, lib.config_authority, lib.tuneables_reload]
lib/prefetch_worker.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisory_engine_alpha, tests.test_packet_prefetch_config_authority, tests.test_prefetch_worker] | relies_on=[lib, lib.config_authority, lib.tuneables_reload]
lib/primitive_filter.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.eidos.store, lib.exposure_tracker, lib.noise_classifier, lib.opportunity_scanner, lib.pattern_detection.aggregator, lib.pattern_detection.distiller] | relies_on=[none]
lib/production_gates.py - degraded
  - Issues: long_func:215
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[scripts.advisory_day_trial, scripts.alpha_cutover_evidence_pack, scripts.alpha_gate_burn_in, scripts.alpha_observatory_expand, scripts.alpha_preflight_bundle, scripts.openclaw_realtime_e2e_benchmark] | relies_on=[lib.advisor, lib.advisory_packet_store, lib.config_authority, lib.eidos, lib.meta_ralph, lib.metric_contract]
lib/project_context.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.context_sync, lib.project_profile] | relies_on=[none]
lib/project_profile.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge, lib.context_sync, lib.prediction_loop, lib.promoter, scripts.spark_sandbox] | relies_on=[lib.diagnostics, lib.memory_banks, lib.project_context]
lib/promoter.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.auto_promote, lib.bridge, lib.context_sync, lib.eidos.store, lib.meta_ralph] | relies_on=[lib.cognitive_learner, lib.config_authority, lib.llm_area_prompts, lib.llm_dispatch, lib.noise_classifier, lib.project_profile]
lib/queue.py - degraded
  - Issues: lint_issues:16, lint_top:W293:13,I001:1,F401:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[hooks.observe, lib.bridge, lib.bridge_cycle, lib.chip_merger, lib.context_sync, lib.doctor] | relies_on=[lib.config_authority, lib.diagnostics, lib.tuneables_reload]
lib/research/__init__.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_research_pipeline] | relies_on=[none]
lib/research/domains.py - healthy
  - Issues: lint_top:F401:2,F541:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.research.holistic_intents] | relies_on=[none]
lib/research/holistic_intents.py - orphaned
  - Issues: runtime_orphan, lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.research.domains, lib.research.intents, lib.research.mastery]
lib/research/intents.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.research.holistic_intents, lib.research.spark_research] | relies_on=[lib.research.mastery]
lib/research/mastery.py - needs-migration
  - Issues: circular_dependency, lint_top:I001:1,F401:1
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[lib.research.holistic_intents, lib.research.intents, lib.research.spark_research, lib.research.web_research] | relies_on=[lib.research.web_research]
lib/research/spark_research.py - orphaned
  - Issues: runtime_orphan, lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.research.intents, lib.research.mastery, lib.research.web_research]
lib/research/web_research.py - needs-migration
  - Issues: circular_dependency, lint_top:I001:1
  - Migration needed: yes
  - Priority: high
  - Dependencies: relied_by=[lib.research.mastery, lib.research.spark_research] | relies_on=[lib.research.mastery]
lib/resonance.py - degraded
  - Issues: lint_density:40, runtime_orphan, lint_top:W293:26,W291:8,F401:3
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[lib.aha_tracker, lib.cognitive_learner, lib.spark_voice]
lib/runtime_feedback_parser.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.advisory_auto_scorer, scripts.advisory_day_trial, tests.test_advisory_auto_scorer] | relies_on=[none]
lib/runtime_hygiene.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle] | relies_on=[none]
lib/runtime_intent_taxonomy.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.advisory_engine_alpha] | relies_on=[none]
lib/runtime_quarantine.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.bridge_cycle, lib.validate_and_store] | relies_on=[lib.jsonl_utils]
lib/runtime_session_state.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[hooks.observe, lib.advisory_engine_alpha, lib.advisory_gate, lib.bridge_cycle, scripts.verify_advisory_emissions, tests.test_advisory_calibration] | relies_on=[lib.config_authority, lib.diagnostics, lib.tuneables_reload]
lib/score_reporter.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.advisory_auto_scorer, tests.test_advisory_auto_scorer] | relies_on=[none]
lib/self_report.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.feedback_loop] | relies_on=[none]
lib/semantic_index.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.semantic_reindex, spark.index_embeddings] | relies_on=[lib.semantic_retriever]
lib/semantic_retriever.py - degraded
  - Issues: long_func:221, lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.advisor, lib.semantic_index, scripts.semantic_eval, scripts.semantic_harness, tests.test_advisor_retrieval_routing, tests.test_semantic_retriever] | relies_on=[lib.cognitive_learner, lib.config_authority, lib.diagnostics, lib.embeddings, lib.meta_ralph, lib.tuneables_reload]
lib/service_control.py - healthy
  - Issues: lint_top:I001:1,N806:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.carmack_kpi, lib.doctor, lib.onboard, scripts.alpha_preflight_bundle, scripts.carmack_kpi_scorecard, scripts.openclaw_realtime_e2e_benchmark] | relies_on=[lib.bridge_cycle, lib.diagnostics, lib.ports]
lib/skills_registry.py - healthy
  - Issues: lint_top:I001:1,E741:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.skills_router, scripts.spark_sandbox, tests.test_feedback, tests.test_skills_registry] | relies_on=[none]
lib/skills_router.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.bridge, lib.feedback, lib.orchestration, scripts.spark_sandbox, tests.test_skills_router] | relies_on=[lib.skills_registry]
lib/soul_metrics.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisory_synthesizer] | relies_on=[none]
lib/soul_upgrade.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisory_synthesizer, lib.opportunity_scanner, tests.test_opportunity_scanner] | relies_on=[none]
lib/spark_emotions.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.advisory_synthesizer, lib.cognitive_learner, lib.memory_banks, lib.memory_store, sparkd] | relies_on=[none]
lib/spark_memory_spine.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.auto_tuner, lib.cognitive_learner, lib.observatory.explorer, lib.observatory.readers, lib.production_gates, scripts.memory_quality_observatory] | relies_on=[none]
lib/spark_voice.py - degraded
  - Issues: lint_density:41, lint_top:W293:38,I001:1,F401:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[lib.bridge, lib.resonance, tests.test_convo_iq, tests.test_niche_net] | relies_on=[none]
lib/sync_tracker.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.context_sync, tests.test_sync_tracker_tiers] | relies_on=[none]
lib/tastebank.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge, lib.bridge_cycle, scripts.mem_profile3] | relies_on=[none]
lib/tuneables_drift.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.auto_tuner] | relies_on=[none]
lib/tuneables_reload.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.advisory_engine_alpha, lib.advisory_gate, lib.advisory_packet_store, lib.advisory_synthesizer, lib.auto_promote] | relies_on=[lib.file_lock, lib.tuneables_schema]
lib/tuneables_schema.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.auto_tuner, lib.config_authority, lib.observatory.tuneables_deep_dive, lib.tuneables_reload, scripts.alpha_gap_audit, scripts.prune_runtime_tuneables] | relies_on=[none]
lib/validate_and_store.py - healthy
  - Issues: lint_top:I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.chip_merger, lib.cognitive_signals, lib.feedback_loop, lib.hypothesis_tracker, lib.learning_systems_bridge, lib.memory_capture] | relies_on=[lib.cognitive_learner, lib.config_authority, lib.diagnostics, lib.meta_ralph, lib.runtime_quarantine, lib.tuneables_reload]
lib/validation_loop.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.bridge_cycle, scripts.mem_profile3, scripts.spark_sandbox, scripts.status_local, sparkd] | relies_on=[lib.aha_tracker, lib.cognitive_learner, lib.diagnostics, lib.outcome_log, lib.queue]
lib/workflow_evidence.py - healthy
  - Issues: lint_top:F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.advisor, lib.observatory.recovery_metrics, tests.test_advisor, tests.test_workflow_evidence] | relies_on=[lib.config_authority]
lib/x_voice.py - healthy
  - Issues: lint_top:F401:3
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[lib.convo_analyzer, lib.niche_mapper, tests.test_convo_iq, tests.test_niche_net] | relies_on=[none]
logo.png - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
mind_server.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.ports]
prompts/ADVISORY_DAILY_SELF_REVIEW_PROMPT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
prompts/CARMACK_SPARK_REVIEW_PROMPT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
prompts/CARMACK_SPARK_REVIEW_PROMPT_V2_ADVANCED.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
prompts/CREATION_BANNER_PROMPTS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
prompts/MIDJOURNEY_SPARK_PROMPTS.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
prompts/SPARK_INTELLIGENCE_PROMPT_LIBRARY.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
prompts/TOMORROW_CHIP_ADVISORY_CONTINUATION_PROMPT.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
pyproject.toml - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
reports/audits/alpha_deep_system_audit_20260227_211146.json - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
reports/audits/alpha_deep_system_audit_20260227_211146.md - needs-migration
  - Issues: missing_code_refs:1
  - Migration needed: yes
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
reports/recheck_2026-02-22_against_final_report_2.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
reports/runtime/advisory_deep_diagnosis_category_patch.json - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
reports/runtime/advisory_deep_diagnosis_category_patch.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
reports/runtime/advisory_deep_diagnosis_global_dedupe_tuneable.json - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
reports/runtime/advisory_deep_diagnosis_global_dedupe_tuneable.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/advise_act.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
scripts/advisory_auto_scorer.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.action_matcher, lib.effect_evaluator, lib.runtime_feedback_parser, lib.score_reporter]
scripts/advisory_controlled_delta.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/advisory_day_trial.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.action_matcher, lib.advice_feedback, lib.production_gates, lib.runtime_feedback_parser]
scripts/advisory_packet_compaction.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib, lib.packet_compaction]
scripts/advisory_self_review.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/advisory_setup.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.preferences]
scripts/advisory_spine_parity_gate.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.jsonl_utils, lib.packet_spine_parity]
scripts/advisory_spine_parity_report.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.packet_spine_parity]
scripts/advisory_tag_outcome.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advice_feedback, lib.advisory_packet_store]
scripts/alpha_cutover_evidence_pack.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.production_gates]
scripts/alpha_docs_legacy_ref_sweep.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/alpha_gap_audit.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.tuneables_schema]
scripts/alpha_gate_burn_in.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.models, lib.eidos.store, lib.meta_ralph, lib.production_gates]
scripts/alpha_guardrail_ci.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/alpha_intelligence_flow_status.py - healthy
  - Issues: lint_top:E402:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.config, scripts.alpha_preflight_bundle]
scripts/alpha_observatory_expand.py - healthy
  - Issues: lint_top:E402:3,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.config, lib.production_gates, scripts.alpha_preflight_bundle]
scripts/alpha_preflight_bundle.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[scripts.alpha_intelligence_flow_status, scripts.alpha_observatory_expand] | relies_on=[lib.integration_status, lib.production_gates, lib.service_control]
scripts/alpha_start_readiness.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/apply_advisory_wow_tuneables.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/apply_chip_profile_r3.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/archive_self_reviews.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/arxiv_title.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/backfill_context_envelopes.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_backfill_context_envelopes] | relies_on=[lib.context_envelope]
scripts/backfill_eidos_advisory_quality.py - healthy
  - Issues: lint_top:F541:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.store]
scripts/bootstrap_windows.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/build_eidos_curriculum.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/build_multidomain_memory_retrieval_cases.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/build_rc.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/carmack_kpi_scorecard.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.carmack_kpi, lib.service_control]
scripts/check_obsidian_watchtower.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/check_obsidian_watchtower.py - healthy
  - Issues: lint_top:I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_packet_store]
scripts/claude_ask.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/claude_bridge.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/claude_call.cmd - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/claude_call.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/claude_hook_smoke_test.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/clean_cognitive_noise.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/clean_primitive_learnings.py - healthy
  - Issues: lint_top:F541:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/cleanup_eidos_distillations.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/codex_hooks_observatory.py - degraded
  - Issues: long_func:129, lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[scripts.workflow_fidelity_observatory, tests.test_codex_hooks_observatory] | relies_on=[lib.observatory.config]
scripts/cognitive_memory_compaction.py - healthy
  - Issues: lint_top:I001:1,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner, lib.memory_compaction]
scripts/compact_chip_insights.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/consciousness_bridge_smoke.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_synthesizer, lib.consciousness_bridge]
scripts/cross_surface_drift_checker.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_cross_surface_drift_checker] | relies_on=[lib.emit_metrics, lib.metric_contract]
scripts/edge_case_harness.py - healthy
  - Issues: lint_top:I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
scripts/eidos_dashboard.py - healthy
  - Issues: lint_top:E402:1,I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos]
scripts/emit_event.py - healthy
  - Issues: lint_top:W291:1,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/ensure_spark.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/ensure_spark.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/experimental/manual_llm/test_cmd.py - healthy
  - Issues: lint_top:E401:1,I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/experimental/manual_llm/test_ps.py - healthy
  - Issues: lint_top:E401:1,I001:1,W291:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/experimental/manual_llm/test_start.py - healthy
  - Issues: lint_top:E401:1,I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/experimental/manual_llm/test_start2.py - healthy
  - Issues: lint_top:E401:1,I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/generate_observatory.py - healthy
  - Issues: lint_top:F541:3
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory, lib.observatory.config]
scripts/install.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/install_autostart_windows.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/install_claude_hooks.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/install_claude_hooks.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/install_cursor_tasks.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/intelligence_llm_setup.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.intelligence_llm_preferences]
scripts/jsonl_surface_audit.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/learning_systems_bridge.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.learning_systems_bridge]
scripts/local_ai_stress_suite.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/logs.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/maintenance/one_time/clean_cognitive_noise.py - healthy
  - Issues: lint_top:I001:1,F541:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/maintenance/one_time/cleanup_eidos_distillations.py - healthy
  - Issues: lint_top:F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/mem_profile.py - healthy
  - Issues: lint_top:I001:3,E402:2,E401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.bridge_cycle]
scripts/mem_profile2.py - degraded
  - Issues: lint_issues:16, lint_top:I001:6,E402:5,F541:4
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.bridge, lib.context_sync, lib.memory_capture, lib.pipeline]
scripts/mem_profile3.py - degraded
  - Issues: lint_issues:19, lint_top:E402:11,F401:4,I001:3
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.bridge, lib.chip_merger, lib.cognitive_learner, lib.content_learner, lib.context_sync, lib.prediction_loop]
scripts/memory_json_consumer_audit.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/memory_json_consumer_gate.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.jsonl_utils]
scripts/memory_quality_observatory.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_memory_quality_observatory] | relies_on=[lib.emit_metrics, lib.memory_capture, lib.metric_contract, lib.queue, lib.spark_memory_spine]
scripts/memory_spine_parity_gate.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.jsonl_utils, lib.memory_spine_parity]
scripts/memory_spine_parity_report.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.memory_spine_parity]
scripts/metaralph_calibrate_quality.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.meta_ralph]
scripts/openclaw_integration_audit.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/openclaw_realtime_e2e_benchmark.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_openclaw_realtime_e2e_benchmark] | relies_on=[lib.openclaw_paths, lib.production_gates, lib.service_control]
scripts/opportunity_scanner_soak.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/personality_evolution.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.personality_evolver]
scripts/post_restart_smoke_check.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/post_run_comment_github.py - healthy
  - Issues: lint_top:F401:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/print_paths.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/production_loop_report.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.production_gates]
scripts/prune_chip_observer_rows.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/prune_runtime_tuneables.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.tuneables_schema]
scripts/public_release_safety_check.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/rebind_outcome_traces.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_rebind_outcome_traces] | relies_on=[none]
scripts/reconcile_advisory_packet_spine.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_reconcile_advisory_packet_spine_helpers] | relies_on=[lib.advisory_packet_store, lib.packet_spine]
scripts/refresh_packet_freshness.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_refresh_packet_freshness] | relies_on=[lib.advisory_packet_store, lib.packet_spine]
scripts/rehydrate_alpha_baseline.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_rehydrate_alpha_baseline] | relies_on=[none]
scripts/remove_autostart_windows.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/repair_effectiveness_counters.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
scripts/reset_alpha_observatory.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.config]
scripts/run_advisory_chip_experiments.py - healthy
  - Issues: lint_top:E402:2,F401:1,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_advisory_realism_contract.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_advisory_realism_domain_matrix.py - healthy
  - Issues: lint_top:E402:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_advisory_retrieval_canary.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_advisory_selective_ai_live_probe_loop.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_advisory_selective_ai_tune_loop.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_alpha_replay_evidence.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_chip_learning_diagnostics.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_chip_observer_policy.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_chip_schema_experiments.py - healthy
  - Issues: lint_top:E402:2,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_chip_schema_multiseed.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_conversation_calibration.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.conversation_core]
scripts/run_depth_training.py - healthy
  - Issues: lint_top:I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.depth_trainer]
scripts/run_depth_v3.py - degraded
  - Issues: lint_issues:11, lint_top:F401:4,F541:4,E402:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.depth_trainer]
scripts/run_indirect_intelligence_flow_matrix.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/run_local.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/semantic_eval.py - healthy
  - Issues: lint_top:I001:2,F401:2,F841:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.cognitive_learner, lib.meta_ralph, lib.semantic_retriever]
scripts/semantic_harness.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner, lib.semantic_retriever]
scripts/semantic_reindex.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner, lib.semantic_index]
scripts/semantic_runbook.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/set_obsidian_watchtower.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/set_obsidian_watchtower.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/set_obsidian_watchtower.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/soak_health.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-claude.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-claude.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-clawdbot.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-clawdbot.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-codex-bridge.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-codex-bridge.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-codex.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-codex.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-cursor.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-cursor.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-windsurf.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark-windsurf.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark.cmd - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/spark_alpha_replay_arena.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_engine_alpha]
scripts/spark_dashboard.py - degraded
  - Issues: lint_issues:8, lint_top:F401:3,E722:3,I001:2
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner]
scripts/spark_sandbox.py - degraded
  - Issues: lint_issues:9, lint_top:I001:7,F401:2
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[hooks.observe, lib, lib.bridge_cycle, lib.cognitive_learner, lib.exposure_tracker, lib.markdown_writer]
scripts/start_alpha.py - healthy
  - Issues: lint_top:F541:2,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/start_mind.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/start_openclaw_spark.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/status_local.bat - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/status_local.py - healthy
  - Issues: lint_top:I001:3
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.pattern_detection.worker, lib.queue, lib.service_control, lib.validation_loop]
scripts/status_local.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/status_openclaw_spark.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/stop_local.sh - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/stop_openclaw_spark.ps1 - healthy
  - Issues: operational_entrypoint
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/strict_attribution_smoke.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.meta_ralph, lib.production_gates]
scripts/test_advisory.py - healthy
  - Issues: lint_top:E401:1,I001:1,E402:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.llm]
scripts/test_baseline_optional_targets.txt - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/test_baseline_targets.txt - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/test_bat.py - healthy
  - Issues: lint_top:E401:1,I001:1,F541:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/test_feedback.py - healthy
  - Issues: lint_top:I001:3,E402:2,E401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.agent_feedback, lib.feedback_loop]
scripts/test_feedback2.py - degraded
  - Issues: lint_issues:9, lint_top:I001:5,E401:1,E402:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.feedback_loop]
scripts/test_llm.py - healthy
  - Issues: lint_top:I001:2,E401:1,E402:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[tests.test_workflow_fidelity_observatory] | relies_on=[lib.llm]
scripts/test_llm_live.py - degraded
  - Issues: lint_issues:11, lint_top:I001:4,E402:3,F401:2
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner, lib.llm]
scripts/test_llm_live2.py - healthy
  - Issues: lint_top:I001:2,E402:2,E401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner]
scripts/test_pty.py - healthy
  - Issues: lint_top:E401:1,I001:1,E722:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/test_subprocess.py - healthy
  - Issues: lint_top:E401:1,I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/trace_backfill.py - healthy
  - Issues: lint_top:I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos, lib.outcome_log]
scripts/trace_query.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos]
scripts/tune_replay.py - healthy
  - Issues: lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.auto_tuner, lib.carmack_kpi, lib.outcome_predictor]
scripts/tuneables_usage_audit.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.tuneables_schema]
scripts/url_meta_title.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/verify_advisory_emissions.py - degraded
  - Issues: long_func:224, lint_top:F541:2
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_gate, lib.emitter, lib.runtime_session_state]
scripts/verify_queue.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
scripts/verify_test_baseline.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/vibeforge.py - degraded
  - Issues: oversized:1558, lint_top:I001:1
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[lib.carmack_kpi, lib.production_gates, lib.tuneables_schema]
scripts/watchdog.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
scripts/workflow_fidelity_observatory.py - healthy
  - Issues: lint_top:E402:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.config, scripts.codex_hooks_observatory]
spark/__init__.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
spark/cli.py - degraded
  - Issues: lint_density:102, oversized:3741, lint_top:W293:42,F541:36,F401:12
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[cli, tests.test_cli_advisory] | relies_on=[none]
spark/index_embeddings.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner, lib.semantic_index]
spark_pulse.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.service_control]
spark_scheduler.py - healthy
  - Issues: lint_top:I001:3
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.diagnostics, lib.engagement_tracker, lib.niche_mapper, lib.openclaw_notify]
spark_watchdog.py - degraded
  - Issues: long_func:261
  - Migration needed: no
  - Priority: high
  - Dependencies: relied_by=[none] | relies_on=[lib.bridge_cycle, lib.pattern_detection.worker, lib.ports, lib.queue, lib.service_control]
sparkd.py - healthy
  - Issues: lint_top:I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_engine_alpha, lib.bridge_cycle, lib.diagnostics, lib.events, lib.orchestration, lib.pattern_detection.worker]
start_depth_training.bat - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
start_spark.bat - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
stop_spark.bat - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
templates/landing_copy.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
templates/openapi.yaml - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
templates/skill.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
templates/supabase_schema.sql - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/e2e_memory_to_advisory_v2.py - healthy
  - Issues: lint_top:I001:2,F401:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.models, lib.eidos.retriever, lib.eidos.store]
tests/fixtures/adapters/claude_code_message.json - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/fixtures/adapters/claude_code_tool.json - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/fixtures/adapters/invalid_event.json - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/fixtures/adapters/scanner_system.json - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/fixtures/adapters/webhook_command.json - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_10_improvements.py - healthy
  - Issues: lint_top:I001:5
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.cognitive_learner, lib.cognitive_signals, lib.eidos, lib.importance_scorer, lib.meta_ralph]
tests/test_adapter_token_resolution.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[adapters]
tests/test_advice_feedback_correlation.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advice_feedback]
tests/test_advice_id_stability.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
tests/test_advisor.py - healthy
  - Issues: lint_top:F401:3,I001:1,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.workflow_evidence]
tests/test_advisor_config_loader.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
tests/test_advisor_effectiveness.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
tests/test_advisor_mind_gate.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
tests/test_advisor_replay.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
tests/test_advisor_retrieval_routing.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.semantic_retriever]
tests/test_advisor_tool_specific_matching.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
tests/test_advisory_auto_scorer.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.action_matcher, lib.runtime_feedback_parser, lib.score_reporter]
tests/test_advisory_calibration.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_gate, lib.advisory_synthesizer, lib.emitter, lib.runtime_session_state]
tests/test_advisory_day_trial.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_advisory_engine_alpha.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.advisory_engine_alpha, lib.advisory_gate, lib.advisory_packet_store, lib.advisory_synthesizer, lib.emitter]
tests/test_advisory_gate_config.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_gate]
tests/test_advisory_gate_evaluate.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_gate]
tests/test_advisory_gate_suppression.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_gate]
tests/test_advisory_intent_taxonomy.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_advisory_orchestrator.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_engine_alpha]
tests/test_advisory_packet_compaction_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_advisory_packet_store.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_packet_store, lib.packet_spine]
tests/test_advisory_packet_store_compaction_meta.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_packet_store, lib.packet_spine]
tests/test_advisory_preferences.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.advisory_engine_alpha, lib.advisory_synthesizer, lib.preferences]
tests/test_advisory_profile_sweeper.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_advisory_quality_ab.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
tests/test_advisory_realism_bench.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_advisory_self_review.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_advisory_spine_parity.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.packet_spine_parity]
tests/test_advisory_spine_parity_gate_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_advisory_state.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.runtime_session_state]
tests/test_advisory_synthesizer_consciousness_bridge.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_synthesizer, lib.consciousness_bridge]
tests/test_advisory_synthesizer_emotions.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_synthesizer]
tests/test_advisory_synthesizer_env.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_synthesizer]
tests/test_alpha_cutover_evidence_pack_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_alpha_gap_audit_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_alpha_guardrail_ci_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_alpha_start_readiness_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_apply_advisory_wow_tuneables.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_apply_chip_profile_r3.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_backfill_context_envelopes.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[scripts.backfill_context_envelopes]
tests/test_bridge_context_sources.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.bridge]
tests/test_bridge_cycle_safety.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.bridge_cycle]
tests/test_bridge_starvation.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.pipeline, lib.queue]
tests/test_build_advisory_cases_from_logs.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_build_multidomain_memory_retrieval_cases.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_carmack_kpi.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_chip_merger.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib, lib.validate_and_store]
tests/test_chips_multiformat.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_chips_quality_integration.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib, lib.advisor, lib.chip_merger, lib.cognitive_learner]
tests/test_chips_runtime_filters.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_cli_advisory.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_engine_alpha, spark.cli]
tests/test_codex_hook_bridge.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_codex_hooks_observatory.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[scripts.codex_hooks_observatory]
tests/test_cognitive_capture.py - healthy
  - Issues: lint_top:I001:1,E402:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.meta_ralph]
tests/test_cognitive_emotion_capture.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner]
tests/test_cognitive_learner.py - healthy
  - Issues: lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner]
tests/test_cognitive_lock_stale.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner]
tests/test_cognitive_noise_filter.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner]
tests/test_cognitive_validation_hygiene.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner]
tests/test_cold_start_learning.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_compact_chip_insights.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_content_learner.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.content_learner]
tests/test_context_envelope.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.context_envelope]
tests/test_context_sync_mind.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib, lib.cognitive_learner]
tests/test_context_sync_policy.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_convo_iq.py - healthy
  - Issues: lint_top:I001:3,F401:3
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.convo_analyzer, lib.convo_events, lib.spark_voice, lib.x_voice]
tests/test_cross_surface_drift_checker.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[scripts.cross_surface_drift_checker]
tests/test_depth_topic_discovery.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_distillation_advisory.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.eidos.distillation_engine, lib.eidos.models, lib.eidos.store]
tests/test_distillation_refiner_runtime_llm.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_distillation_transformer.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.distillation_transformer]
tests/test_eidos.py - degraded
  - Issues: lint_issues:9, lint_top:F401:7,I001:1,F841:1
  - Migration needed: no
  - Priority: medium
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_eidos_config_authority.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.config_authority, lib.eidos.models]
tests/test_eidos_distillation_curriculum.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_eidos_intake.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos_intake]
tests/test_eidos_sql_hardening.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.evidence_store, lib.eidos.models, lib.eidos.store]
tests/test_eidos_store_distillation_dedupe.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.models, lib.eidos.store]
tests/test_elevation.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.elevation, lib.meta_ralph]
tests/test_embeddings.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.embeddings]
tests/test_emotion_memory_alignment_bench.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_engagement_pulse.py - healthy
  - Issues: lint_top:F401:2,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.engagement_tracker, lib.pattern_detection.base, lib.pattern_detection.engagement_surprise]
tests/test_error_taxonomy.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.error_taxonomy]
tests/test_event_validation.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.events, lib.outcome_log]
tests/test_exposure_tracker.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_feedback.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.feedback, lib.skills_registry]
tests/test_intelligence_llm_preferences.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.intelligence_llm_preferences]
tests/test_jsonl_surface_audit_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_jsonl_utils.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.jsonl_utils]
tests/test_learning_spine_import_boundaries.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_learning_systems_bridge.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.learning_systems_bridge, lib.validate_and_store]
tests/test_learning_utilization.py - healthy
  - Issues: lint_top:F401:3,I001:1,E722:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.meta_ralph]
tests/test_llm_dispatch.py - healthy
  - Issues: lint_top:F401:1,E402:1,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.llm_area_prompts, lib.llm_dispatch, lib.tuneables_schema]
tests/test_lock_fail_closed_writers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_memory_capture_safety.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.memory_capture]
tests/test_memory_compaction.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.memory_compaction]
tests/test_memory_emotion_integration.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.memory_banks, lib.memory_store]
tests/test_memory_json_consumer_audit_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_memory_json_consumer_gate_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_memory_quality_observatory.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[scripts.memory_quality_observatory]
tests/test_memory_retrieval_ab.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_memory_retrieval_domain_matrix.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_memory_spine_parity.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.memory_spine_parity]
tests/test_memory_spine_sqlite.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner, lib.spark_memory_spine]
tests/test_meta_alpha_scorer_guardrails.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.meta_alpha_scorer]
tests/test_meta_ralph.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.meta_ralph]
tests/test_meta_ralph_runtime_llm.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.meta_ralph]
tests/test_metaralph_integration.py - healthy
  - Issues: lint_top:I001:1,F541:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos, lib.meta_ralph]
tests/test_metric_contract.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.metric_contract]
tests/test_mind_bridge_auth.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner, lib.mind_bridge]
tests/test_niche_net.py - healthy
  - Issues: lint_top:F401:2,I001:1,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.niche_mapper, lib.spark_voice, lib.x_voice]
tests/test_noise_classifier.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.noise_classifier]
tests/test_observatory_advisory_feedback_metrics.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.readers]
tests/test_observatory_eidos_curriculum_metrics.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.readers]
tests/test_observatory_helpfulness_explorer.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.config, lib.observatory.explorer]
tests/test_observatory_meta_ralph_totals.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.explorer, lib.observatory.readers]
tests/test_observatory_stage7_curriculum_page.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.stage_pages]
tests/test_observatory_tuneables_deep_dive.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.observatory.tuneables_deep_dive, lib.tuneables_schema]
tests/test_observe_hook_telemetry.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[hooks, lib.queue]
tests/test_openclaw_integration_audit.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_openclaw_notify_security.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_openclaw_realtime_e2e_benchmark.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[scripts.openclaw_realtime_e2e_benchmark]
tests/test_openclaw_tailer_capture_policy.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[adapters]
tests/test_openclaw_tailer_hook_events.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[adapters]
tests/test_openclaw_tailer_telemetry.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[adapters]
tests/test_openclaw_tailer_workflow_summary.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[adapters]
tests/test_opportunity_scanner.py - healthy
  - Issues: lint_top:F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.opportunity_scanner, lib.opportunity_scanner_adapter, lib.queue, lib.soul_upgrade]
tests/test_orchestration.py - healthy
  - Issues: lint_top:F401:1,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.orchestration]
tests/test_outcome_log_full_stats.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_packet_compaction.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.packet_compaction]
tests/test_packet_prefetch_config_authority.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_packet_store, lib.prefetch_worker]
tests/test_pattern_detection.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib, lib.pattern_detection]
tests/test_personality_evolver.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.personality_evolver]
tests/test_pipeline_config_authority.py - healthy
  - Issues: lint_top:F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.config_authority, lib.pipeline]
tests/test_pipeline_health.py - healthy
  - Issues: lint_top:I001:3,E722:1,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos, lib.meta_ralph, lib.outcome_log, lib.pattern_detection, lib.promoter, lib.queue]
tests/test_pr1_config_authority.py - healthy
  - Issues: lint_top:F401:5,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.bridge_cycle, lib.config_authority, lib.emitter, lib.feature_flags, lib.tuneables_schema]
tests/test_pr2_config_authority.py - healthy
  - Issues: lint_top:F401:2,I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.config_authority, lib.opportunity_scanner, lib.prediction_loop, lib.tuneables_schema]
tests/test_pr3_config_authority.py - healthy
  - Issues: lint_top:I001:4,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.config_authority, lib.tuneables_schema]
tests/test_pr4_config_authority.py - healthy
  - Issues: lint_top:I001:2
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.config_authority, lib.tuneables_schema]
tests/test_prediction_loop.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib, lib.queue]
tests/test_prefetch_worker.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisory_packet_store, lib.prefetch_worker]
tests/test_production_gates_config_authority.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_production_hardening.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.cognitive_learner, lib.context_sync, lib.promoter]
tests/test_production_loop_gates.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos, lib.production_gates]
tests/test_project_context.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_promoter_markers.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.promoter]
tests/test_promoter_noise_classifier.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.noise_classifier, lib.promoter]
tests/test_promotion_config_authority.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.auto_promote, lib.promoter]
tests/test_pulse_startup.py - healthy
  - Issues: lint_top:I001:1,F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.service_control]
tests/test_queue.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.queue]
tests/test_queue_concurrency.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.queue]
tests/test_rebind_outcome_traces.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[scripts.rebind_outcome_traces]
tests/test_reconcile_advisory_packet_spine_helpers.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.packet_spine, scripts.reconcile_advisory_packet_spine]
tests/test_refresh_packet_freshness.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[scripts.refresh_packet_freshness]
tests/test_rehydrate_alpha_baseline.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[scripts.rehydrate_alpha_baseline]
tests/test_remaining_config_authority.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.chip_merger, lib.config_authority, lib.memory_banks, lib.memory_capture, lib.observatory.config, lib.pattern_detection.request_tracker]
tests/test_research_pipeline.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.research]
tests/test_retrieval_quality.py - healthy
  - Issues: lint_top:F401:3
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor]
tests/test_retriever_keyword_matching.py - healthy
  - Issues: lint_top:I001:2,F401:2,F841:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.models, lib.eidos.retriever, lib.eidos.store]
tests/test_run_advisory_chip_experiments.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_run_advisory_realism_domain_matrix.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_run_advisory_retrieval_canary.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_run_alpha_replay_evidence_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_run_chip_learning_diagnostics.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_run_chip_observer_policy.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_run_chip_schema_experiments.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_run_chip_schema_multiseed.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_runtime_hygiene.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_runtime_tuneable_sections.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.memory_capture, lib.pattern_detection.request_tracker, lib.queue]
tests/test_safety_guardrails.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.eidos.guardrails, lib.eidos.models]
tests/test_scheduler.py - healthy
  - Issues: lint_top:F841:3,F401:1,E402:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_seed_advisory_theories.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_semantic_retriever.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.semantic_retriever]
tests/test_single_path.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.bridge_cycle, lib.pipeline]
tests/test_skills_registry.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.skills_registry]
tests/test_skills_router.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.skills_router]
tests/test_spark_alpha_replay_arena.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_spark_emotions_v2.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.spark_emotions]
tests/test_sparkd_hardening.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_sparkd_openclaw_runtime_bridge.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.events, lib.queue]
tests/test_strict_attribution_integration.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.advisor, lib.meta_ralph]
tests/test_sync_tracker_tiers.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.sync_tracker]
tests/test_tuneables_alignment.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.tuneables_schema]
tests/test_tuneables_usage_audit_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_validation_loop.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib]
tests/test_vibeforge_helpers.py - healthy
  - Issues: lint_top:I001:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_watchdog_plugin_only.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
tests/test_workflow_evidence.py - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[lib.memory_capture, lib.observatory.recovery_metrics, lib.workflow_evidence]
tests/test_workflow_fidelity_observatory.py - healthy
  - Issues: lint_top:F401:1
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[scripts.test_llm]
visuals/VISUAL_RULEBOOK.md - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
visuals/src/IntelligenceFunnel.tsx - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
visuals/src/Root.tsx - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
visuals/src/fonts.ts - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
visuals/src/index.ts - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
visuals/src/theme.ts - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
visuals/tsconfig.json - healthy
  - Issues: none
  - Migration needed: no
  - Priority: low
  - Dependencies: relied_by=[none] | relies_on=[none]
