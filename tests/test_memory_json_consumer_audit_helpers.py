from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "memory_json_consumer_audit.py"
    name = "memory_json_consumer_audit_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_surface_group_classification():
    mod = _load_module()
    assert mod._surface_group("lib/advisor.py") == "runtime_lib"
    assert mod._surface_group("hooks/observe.py") == "runtime_hooks"
    assert mod._surface_group("scripts/tool.py") == "tooling_scripts"
    assert mod._surface_group("tests/test_x.py") == "tests"
    assert mod._surface_group("docs/x.md") == "docs"


def test_build_report_aggregates_hits():
    mod = _load_module()
    hits = [
        mod.Hit(path="lib/a.py", line=1, token="cognitive_insights.json", line_text="x"),
        mod.Hit(path="docs/a.md", line=2, token="cognitive_insights.json", line_text="y"),
    ]
    report = mod._build_report(hits)
    totals = report.get("totals") or {}
    assert totals.get("hits") == 2
    assert totals.get("runtime_hits") == 1
    assert totals.get("docs_hits") == 1

