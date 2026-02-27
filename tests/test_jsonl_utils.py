from __future__ import annotations

import json

from lib.jsonl_utils import append_jsonl_capped, tail_jsonl_objects


def test_tail_jsonl_objects_returns_requested_tail(tmp_path):
    path = tmp_path / "tail.jsonl"
    rows = [{"n": i} for i in range(5)]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    out = tail_jsonl_objects(path, 3)

    assert [r["n"] for r in out] == [2, 3, 4]


def test_append_jsonl_capped_trims_to_max_lines(tmp_path):
    path = tmp_path / "cap.jsonl"
    for i in range(4):
        append_jsonl_capped(path, {"n": i}, max_lines=2, ensure_ascii=False)

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["n"] for row in lines] == [2, 3]
