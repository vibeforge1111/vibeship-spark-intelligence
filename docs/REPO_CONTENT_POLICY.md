# Repo Content Policy

This file defines what belongs in this public repository and what should stay in private/internal storage.

## 1) Public + Versioned (keep in Git)

- Runtime code used by end users (`lib/`, entrypoints, config schema)
- Tests that validate public/runtime behavior
- Setup and usage documentation needed by contributors/users
- Security, safety, and reliability controls that affect shipped behavior

## 2) Internal + Private (do not commit to this public repo)

- Team-only operations playbooks and internal scorecards
- Self-interrogation workflows and internal coaching templates
- Private governance scripts (branch admin, private observability orchestration)
- Internal canary strategy notes not needed for external contributors

Recommended storage:
- Private ops repository, or
- Private fork with controlled access

## 3) Local + Generated (ignore via `.gitignore`)

- Daily reports and snapshots
- Local dashboards and observatory exports
- Scratch artifacts, debug dumps, and run outputs

## Rollback Guidance

- `gitignore` is only for preventing new files from being tracked.
- If a file is already committed, `gitignore` does not hide or protect it.
- For rollback of internal tools, keep those tools versioned in a private repo; otherwise there is no reliable rollback history.

## PR Checklist (scope gate)

Before opening a public PR, confirm:

1. No internal-only docs/scripts are included.
2. No generated report artifacts are included.
3. Every non-doc change has a runtime or contributor-facing reason.
