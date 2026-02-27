from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "alpha_gap_audit.py"
    name = "alpha_gap_audit_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_count_regex_hits_counts_all_matches(tmp_path: Path):
    mod = _load_module()
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("jsonl one\nand .jsonl path\n", encoding="utf-8")
    b.write_text("no match\njsonl again\n", encoding="utf-8")
    count = mod._count_regex_hits([a, b], r"jsonl|\.jsonl")
    assert count >= 3


def test_all_files_filters_suffixes(tmp_path: Path):
    mod = _load_module()
    x = tmp_path / "x.py"
    y = tmp_path / "y.txt"
    z = tmp_path / "sub" / "z.py"
    z.parent.mkdir(parents=True, exist_ok=True)
    x.write_text("print('x')\n", encoding="utf-8")
    y.write_text("skip\n", encoding="utf-8")
    z.write_text("print('z')\n", encoding="utf-8")
    files = mod._all_files([tmp_path], suffixes=(".py",))
    names = sorted(p.name for p in files)
    assert names == ["x.py", "z.py"]
