#!/usr/bin/env python3
"""Import/wiring smoke checks for alpha runtime paths.

Goals:
1) Fail fast if critical runtime files reintroduce deleted legacy imports.
2) Fail fast if critical alpha modules cannot be imported.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import sys
from pathlib import Path
from typing import Iterable, List, NamedTuple, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORBIDDEN_MODULES: Sequence[str] = (
    "lib.advisory_engine",
    "lib.advisory_orchestrator",
)

CHECK_FILES: Sequence[str] = (
    "sparkd.py",
    "spark/cli.py",
    "bridge_worker.py",
    "hooks/observe.py",
)

SMOKE_MODULES: Sequence[str] = (
    "sparkd",
    "spark.cli",
    "bridge_worker",
    "hooks.observe",
    "lib.advisory_engine_alpha",
    "lib.production_gates",
    "lib.doctor",
)


class Violation(NamedTuple):
    path: str
    line: int
    module: str


def _imported_modules(path: Path) -> List[tuple[int, str]]:
    source = path.read_text(encoding="utf-8-sig", errors="replace")
    tree = ast.parse(source, filename=str(path))
    found: List[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    found.append((int(getattr(node, "lineno", 0) or 0), alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue
            module = (node.module or "").strip()
            if module:
                found.append((int(getattr(node, "lineno", 0) or 0), module))
    return found


def _matches_forbidden(module_name: str, forbidden: Iterable[str]) -> bool:
    mod = str(module_name or "").strip()
    for target in forbidden:
        if mod == target or mod.startswith(target + "."):
            return True
    return False


def find_forbidden_imports(
    paths: Iterable[Path],
    forbidden_modules: Sequence[str] = FORBIDDEN_MODULES,
) -> List[Violation]:
    violations: List[Violation] = []
    for path in paths:
        if not path.exists():
            continue
        for lineno, module_name in _imported_modules(path):
            if _matches_forbidden(module_name, forbidden_modules):
                violations.append(
                    Violation(
                        path=str(path.as_posix()),
                        line=int(lineno),
                        module=module_name,
                    )
                )
    return violations


def run_import_smoke(modules: Sequence[str] = SMOKE_MODULES) -> List[str]:
    errors: List[str] = []
    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{mod}: {exc.__class__.__name__}: {exc}")
    return errors


def _report_json(
    *,
    violations: Sequence[Violation],
    import_errors: Sequence[str],
    checked_files: Sequence[str],
    smoke_modules: Sequence[str],
) -> dict:
    return {
        "ok": not violations and not import_errors,
        "checked_files": list(checked_files),
        "smoke_modules": list(smoke_modules),
        "forbidden_import_violations": [
            {"path": v.path, "line": v.line, "module": v.module}
            for v in violations
        ],
        "import_errors": list(import_errors),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Alpha import/wiring smoke checks.")
    ap.add_argument("--json-only", action="store_true", help="Emit JSON report only.")
    ap.add_argument(
        "--skip-dynamic-imports",
        action="store_true",
        help="Only run static forbidden-import checks.",
    )
    args = ap.parse_args()

    check_paths = [ROOT / rel for rel in CHECK_FILES]
    violations = find_forbidden_imports(check_paths)
    import_errors: List[str] = []
    if not args.skip_dynamic_imports:
        import_errors = run_import_smoke(SMOKE_MODULES)

    payload = _report_json(
        violations=violations,
        import_errors=import_errors,
        checked_files=CHECK_FILES,
        smoke_modules=SMOKE_MODULES,
    )
    if args.json_only:
        print(json.dumps(payload, indent=2))
    else:
        if violations:
            print("Forbidden import violations:")
            for v in violations:
                print(f"  - {v.path}:{v.line} imports {v.module}")
        if import_errors:
            print("Import smoke failures:")
            for err in import_errors:
                print(f"  - {err}")
        print(json.dumps(payload, indent=2))

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
