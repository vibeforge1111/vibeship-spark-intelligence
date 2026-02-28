from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_smoke_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "import_wiring_smoke.py"
    spec = importlib.util.spec_from_file_location("import_wiring_smoke", script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_forbidden_import_detected(tmp_path: Path):
    smoke = _load_smoke_module()
    target = tmp_path / "mod.py"
    target.write_text(
        "from lib.advisory_engine import on_pre_tool\n",
        encoding="utf-8",
    )
    violations = smoke.find_forbidden_imports([target], forbidden_modules=smoke.FORBIDDEN_MODULES)
    assert len(violations) == 1
    assert violations[0].module == "lib.advisory_engine"


def test_alpha_module_name_not_flagged(tmp_path: Path):
    smoke = _load_smoke_module()
    target = tmp_path / "mod.py"
    target.write_text(
        "import lib.advisory_engine_alpha as alpha\n",
        encoding="utf-8",
    )
    violations = smoke.find_forbidden_imports([target], forbidden_modules=smoke.FORBIDDEN_MODULES)
    assert violations == []


def test_import_smoke_reports_import_errors():
    smoke = _load_smoke_module()
    errors = smoke.run_import_smoke(["json", "definitely_not_a_real_module_12345"])
    assert any("definitely_not_a_real_module_12345" in e for e in errors)
