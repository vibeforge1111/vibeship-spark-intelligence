#!/usr/bin/env python3
"""Report potentially orphaned runtime modules (report-only by default)."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}

RUNTIME_ROOT_MODULES = {
    "sparkd",
    "bridge_worker",
    "spark.cli",
    "hooks.observe",
    "lib.bridge_cycle",
    "lib.advisory_engine_alpha",
    "lib.service_control",
    "lib.doctor",
}

ALLOWLIST = {
    "lib.__init__",
    "lib.observatory.__init__",
}


def _py_files() -> List[Path]:
    out: List[Path] = []
    for p in ROOT.rglob("*.py"):
        parts = set(p.parts)
        if parts.intersection(SKIP_DIRS):
            continue
        out.append(p)
    return out


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT)
    no_suffix = rel.with_suffix("")
    parts = list(no_suffix.parts)
    return ".".join(parts)


def _imports_for(path: Path) -> Set[str]:
    try:
        src = path.read_text(encoding="utf-8-sig", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except Exception:
        return set()
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue
            mod = (node.module or "").strip()
            if mod:
                out.add(mod)
    return out


def build_import_graph(files: List[Path]) -> Tuple[Dict[str, Set[str]], Dict[str, Path]]:
    module_to_path: Dict[str, Path] = {}
    for p in files:
        module_to_path[_module_name(p)] = p
    graph: Dict[str, Set[str]] = {m: set() for m in module_to_path}
    known = set(module_to_path)
    for mod, p in module_to_path.items():
        for imp in _imports_for(p):
            if imp in known:
                graph[mod].add(imp)
                continue
            parent = imp
            while "." in parent:
                parent = parent.rsplit(".", 1)[0]
                if parent in known:
                    graph[mod].add(parent)
                    break
    return graph, module_to_path


def reachable(graph: Dict[str, Set[str]], roots: Set[str]) -> Set[str]:
    seen: Set[str] = set()
    stack: List[str] = [r for r in roots if r in graph]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for nxt in graph.get(cur, set()):
            if nxt not in seen:
                stack.append(nxt)
    return seen


def audit_orphans() -> Dict[str, object]:
    files = _py_files()
    graph, module_to_path = build_import_graph(files)
    runtime_reachable = reachable(graph, set(RUNTIME_ROOT_MODULES))

    lib_modules = sorted(m for m in module_to_path if m.startswith("lib."))
    runtime_orphans = [
        m
        for m in lib_modules
        if m not in runtime_reachable and m not in ALLOWLIST
    ]

    return {
        "ok": True,
        "runtime_roots": sorted(RUNTIME_ROOT_MODULES),
        "lib_module_count": len(lib_modules),
        "runtime_reachable_count": len([m for m in lib_modules if m in runtime_reachable]),
        "runtime_orphan_count": len(runtime_orphans),
        "runtime_orphans": runtime_orphans[:200],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Report potential orphan runtime modules.")
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--fail-over", type=int, default=-1, help="Fail if orphan count exceeds this value.")
    args = ap.parse_args()

    payload = audit_orphans()
    if args.json_only:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload, indent=2))
    if int(args.fail_over) >= 0 and int(payload.get("runtime_orphan_count", 0)) > int(args.fail_over):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
