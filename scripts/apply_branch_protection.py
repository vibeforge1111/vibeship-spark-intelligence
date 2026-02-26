#!/usr/bin/env python3
"""Apply branch protection required checks using GitHub CLI.

Usage:
  python scripts/apply_branch_protection.py --repo vibeforge1111/vibeship-spark-intelligence --branch main

Requires:
  - gh CLI authenticated with admin rights on target repo
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import List


DEFAULT_CHECKS = [
    "CI / lint-and-test (3.10)",
    "CI / lint-and-test (3.11)",
    "CI / lint-and-test (3.12)",
    "PR Sentinel / triage",
    "CodeQL / Analyze (Python)",
    "Semgrep / semgrep",
    "Dependency Review / dependency-review",
]


def run(cmd: List[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "command failed").strip())
    return (p.stdout or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply GitHub branch protection checks")
    ap.add_argument("--repo", required=True, help="owner/repo")
    ap.add_argument("--branch", default="main", help="Branch to protect")
    ap.add_argument(
        "--checks",
        default=",".join(DEFAULT_CHECKS),
        help="Comma-separated required status check contexts",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print payload without applying")
    args = ap.parse_args()

    checks = [c.strip() for c in args.checks.split(",") if c.strip()]

    payload = {
        "required_status_checks": {
            "strict": True,
            "contexts": checks,
        },
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": True,
            "required_approving_review_count": 1,
        },
        "restrictions": None,
        "required_linear_history": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "required_conversation_resolution": True,
        "lock_branch": False,
        "allow_fork_syncing": True,
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    endpoint = f"repos/{args.repo}/branches/{args.branch}/protection"
    cmd = [
        "gh",
        "api",
        "--method",
        "PUT",
        endpoint,
        "--input",
        "-",
    ]

    p = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)
    if p.returncode != 0:
        print("Failed to apply branch protection:", file=sys.stderr)
        print((p.stderr or p.stdout).strip(), file=sys.stderr)
        return p.returncode

    print(f"Branch protection applied to {args.repo}:{args.branch}")
    print("Required checks:")
    for c in checks:
        print(f"- {c}")
    print("\n⚠️ Merge Queue still needs to be enabled in GitHub Settings -> Branch protection/rulesets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
