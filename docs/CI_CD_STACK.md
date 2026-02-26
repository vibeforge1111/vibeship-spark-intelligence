# CI/CD Stack (Initial)

This repo now includes workflow foundations for:
- CI (Ruff + Pytest matrix + safety checks)
- PR Sentinel triage
- CodeQL
- Semgrep
- Dependabot + Dependency Review

## Workflows
- `.github/workflows/ci.yml`
- `.github/workflows/pr-sentinel.yml`
- `.github/workflows/codeql.yml`
- `.github/workflows/semgrep.yml`
- `.github/workflows/dependency-review.yml`
- `.github/dependabot.yml`

## One-click branch protection script

Script added:
- `scripts/apply_branch_protection.py`

Apply (example):

```bash
python scripts/apply_branch_protection.py --repo vibeforge1111/vibeship-spark-intelligence --branch main
```

Optional dry-run:

```bash
python scripts/apply_branch_protection.py --repo vibeforge1111/vibeship-spark-intelligence --branch main --dry-run
```

## Merge Queue setup (GitHub UI)
Merge Queue must be enabled in GitHub settings (cannot be fully enabled via YAML alone).

1. Go to **Settings → Branches → Branch protection rules** (for `main`)
2. Enable:
   - Require pull request before merging
   - Require approvals
   - Require status checks to pass
   - **Require merge queue**
3. Add required checks (recommended minimum):
   - `CI / lint-and-test (3.10)`
   - `CI / lint-and-test (3.11)`
   - `CI / lint-and-test (3.12)`
   - `PR Sentinel / triage`
   - `CodeQL / Analyze (Python)`
   - `Semgrep / semgrep`

## Dependabot
- Config file: `.github/dependabot.yml`
- Enabled ecosystems:
  - `pip`
  - `github-actions`
- Schedule: weekly (Asia/Dubai)

## Notes
- Workflows include `merge_group` triggers so Merge Queue jobs execute correctly.
- PR Sentinel artifacts are uploaded per run for review routing and audit.
