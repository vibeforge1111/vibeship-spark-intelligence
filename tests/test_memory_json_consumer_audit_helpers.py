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


def test_iter_repo_files_skips_pycache_and_pyc(tmp_path):
    mod = _load_module()
    (tmp_path / "lib").mkdir(parents=True)
    (tmp_path / "lib" / "__pycache__").mkdir(parents=True)
    keep = tmp_path / "lib" / "x.py"
    skip_cache = tmp_path / "lib" / "__pycache__" / "x.cpython-313.pyc"
    skip_pyc = tmp_path / "lib" / "y.pyc"
    keep.write_text("ok", encoding="utf-8")
    skip_cache.write_text("cache", encoding="utf-8")
    skip_pyc.write_text("bytecode", encoding="utf-8")
    paths = [str(p) for p in mod._iter_repo_files(tmp_path)]
    assert str(keep) in paths
    assert str(skip_cache) not in paths
    assert str(skip_pyc) not in paths
