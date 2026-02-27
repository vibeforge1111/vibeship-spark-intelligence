from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "jsonl_surface_audit.py"
    name = "jsonl_surface_audit_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_count_hits_detects_jsonl_patterns(tmp_path: Path):
    mod = _load_module()
    p = tmp_path / "x.py"
    p.write_text("a='foo.jsonl'\\n# jsonl comment\\n", encoding="utf-8")
    assert mod._count_hits(p) >= 2


def test_count_hits_handles_missing_file():
    mod = _load_module()
    missing = Path("Z:/definitely/missing/file.py")
    assert mod._count_hits(missing) == 0

