from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "tuneables_usage_audit.py"
    name = "tuneables_usage_audit_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_key_usage_count_matches_quotes_get_and_index():
    mod = _load_module()
    text_map = {
        "a.py": 'cfg.get("alpha_key")\nrow["alpha_key"]\n',
        "b.py": "'alpha_key'\n",
        "c.py": "nope\n",
    }
    hits, files = mod._key_usage_count(text_map, "alpha_key")
    assert hits >= 3
    assert files == ["a.py", "b.py"]


def test_key_usage_count_zero_for_missing_key():
    mod = _load_module()
    hits, files = mod._key_usage_count({"x.py": "value = 1\n"}, "missing_key")
    assert hits == 0
    assert files == []

