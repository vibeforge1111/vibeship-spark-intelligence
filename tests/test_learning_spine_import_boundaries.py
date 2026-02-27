from __future__ import annotations

import ast
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parent.parent


def _imported_modules(path: Path) -> List[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.append(f"{'.' * int(node.level or 0)}{node.module}")
    return out


def test_cognitive_learner_has_no_static_semantic_retriever_import() -> None:
    path = ROOT / "lib" / "cognitive_learner.py"
    modules = _imported_modules(path)
    assert "lib.semantic_retriever" not in modules
    assert ".semantic_retriever" not in modules


def test_memory_banks_has_no_static_cognitive_learner_import() -> None:
    path = ROOT / "lib" / "memory_banks.py"
    modules = _imported_modules(path)
    assert "lib.cognitive_learner" not in modules
    assert ".cognitive_learner" not in modules
