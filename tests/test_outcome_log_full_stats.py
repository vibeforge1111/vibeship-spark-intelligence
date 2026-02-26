import json
import threading
import time

from lib import outcome_log


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_get_outcome_stats_full_scan_not_capped(tmp_path, monkeypatch):
    outcomes_file = tmp_path / "outcomes.jsonl"
    links_file = tmp_path / "outcome_links.jsonl"

    outcomes = []
    for i in range(1505):
        outcomes.append(
            {
                "outcome_id": f"o{i}",
                "polarity": "pos" if i % 2 == 0 else "neg",
                "created_at": float(i),
            }
        )
    links = []
    for i in range(1203):
        links.append(
            {
                "link_id": f"l{i}",
                "outcome_id": f"o{i}",
                "validated": i % 2 == 0,
                "created_at": float(i),
            }
        )

    _write_jsonl(outcomes_file, outcomes)
    _write_jsonl(links_file, links)
    monkeypatch.setattr(outcome_log, "OUTCOMES_FILE", outcomes_file)
    monkeypatch.setattr(outcome_log, "OUTCOME_LINKS_FILE", links_file)

    stats = outcome_log.get_outcome_stats()
    assert stats["total_outcomes"] == 1505
    assert stats["total_links"] == 1203
    assert stats["validated_links"] == 602
    assert stats["unlinked"] == 302
    assert stats["by_polarity"]["pos"] == 753
    assert stats["by_polarity"]["neg"] == 752


def test_read_and_link_limits_support_none(tmp_path, monkeypatch):
    outcomes_file = tmp_path / "outcomes.jsonl"
    links_file = tmp_path / "outcome_links.jsonl"

    _write_jsonl(
        outcomes_file,
        [{"outcome_id": f"o{i}", "polarity": "neutral", "created_at": float(i)} for i in range(25)],
    )
    _write_jsonl(
        links_file,
        [{"link_id": f"l{i}", "outcome_id": f"o{i}", "validated": False} for i in range(12)],
    )
    monkeypatch.setattr(outcome_log, "OUTCOMES_FILE", outcomes_file)
    monkeypatch.setattr(outcome_log, "OUTCOME_LINKS_FILE", links_file)

    assert len(outcome_log.read_outcomes(limit=None)) == 25
    assert len(outcome_log.read_outcomes(limit=10)) == 10
    assert len(outcome_log.get_outcome_links(limit=None)) == 12
    assert len(outcome_log.get_outcome_links(limit=5)) == 5


def test_append_outcome_lock_prevents_rotate_append_loss(tmp_path, monkeypatch):
    outcomes_file = tmp_path / "outcomes.jsonl"
    monkeypatch.setattr(outcome_log, "OUTCOMES_FILE", outcomes_file)
    monkeypatch.setattr(outcome_log, "OUTCOMES_FILE_MAX", 3)

    # Seed large lines so the size heuristic reliably triggers rotation.
    seed = [
        {"outcome_id": f"seed-{i}", "text": "x" * 360, "created_at": float(i)}
        for i in range(4)
    ]
    _write_jsonl(outcomes_file, seed)

    start_late_append = threading.Event()
    late_done = threading.Event()
    original_rotate = outcome_log._rotate_jsonl

    def _rotate_with_interleave(path, max_lines):
        if not start_late_append.is_set():
            start_late_append.set()

            def _late_writer():
                outcome_log.append_outcome(
                    {"outcome_id": "late", "text": "late_marker", "created_at": time.time()}
                )
                late_done.set()

            t = threading.Thread(target=_late_writer, daemon=True)
            t.start()
            time.sleep(0.05)
            original_rotate(path, max_lines)
            return
        original_rotate(path, max_lines)

    monkeypatch.setattr(outcome_log, "_rotate_jsonl", _rotate_with_interleave)

    outcome_log.append_outcome({"outcome_id": "main", "text": "main_marker", "created_at": time.time()})
    assert late_done.wait(timeout=2.0)

    rows = outcome_log.read_outcomes(limit=None)
    ids = {str(r.get("outcome_id") or "") for r in rows}
    assert "late" in ids
