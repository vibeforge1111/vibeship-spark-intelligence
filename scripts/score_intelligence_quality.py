"""Score all stored intelligence through the keepability gate.

Reads:
  - ~/.spark/cognitive_insights.json
  - ~/.spark/advisory_emit.jsonl (last 200)
  - ~/.spark/promotion_log.jsonl

Writes:
  - ~/.spark/intelligence_quality.json

Can be run standalone or called from bridge_cycle.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Allow running from scripts/ or repo root
_repo = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo))

from lib.keepability_gate import evaluate_structural_keepability

SPARK_HOME = Path.home() / ".spark"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _read_jsonl_tail(path: Path, max_rows: int = 200) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception:
        return []
    return rows[-max_rows:]


def _extract_text(key: str, entry: dict) -> str:
    """Extract the human-readable text from a cognitive insight entry."""
    # The insight text is sometimes in 'text', sometimes the key IS the text
    for field in ("text", "insight", "content", "summary"):
        val = entry.get(field)
        if val and isinstance(val, str) and len(val) > 5:
            return val
    # Fall back to the key itself (common pattern in cognitive store)
    if len(key) > 10 and not key.startswith("_"):
        return key
    return ""


def _extract_advisory_text(row: dict) -> str:
    """Extract text from an advisory emission row. Prefer full_text over truncated text."""
    # Try full_text first (untruncated), then fall back to text
    for field in ("full_text", "text", "advice", "content", "summary", "message"):
        val = row.get(field)
        if val and isinstance(val, str) and len(val) > 5:
            return val
    return ""


def score_all() -> dict:
    """Score everything and return the quality summary."""
    now = time.time()

    # --- Score cognitive insights ---
    insights = _read_json(SPARK_HOME / "cognitive_insights.json")
    cog_total = 0
    cog_keepable = 0
    false_wisdom: list[dict] = []
    compounding: list[dict] = []
    reason_counts: dict[str, int] = {}

    for key, entry in insights.items():
        if not isinstance(entry, dict):
            continue
        text = _extract_text(key, entry)
        if not text:
            continue

        cog_total += 1
        gate = evaluate_structural_keepability(text)
        passed = bool(gate.get("passed"))
        reasons = gate.get("reasons", [])
        validations = entry.get("times_validated", 0)
        reliability = entry.get("reliability", 0.0)

        if passed:
            cog_keepable += 1
            compounding.append({
                "text": text[:120],
                "validations": validations,
                "reliability": round(reliability, 3),
                "keepable": True,
            })
        else:
            for r in reasons:
                reason_counts[r] = reason_counts.get(r, 0) + 1
            # Track high-confidence noise as false wisdom
            if validations >= 10 or reliability >= 0.8:
                false_wisdom.append({
                    "text": text[:120],
                    "validations": validations,
                    "reliability": round(reliability, 3),
                    "keepable": False,
                    "fail_reasons": reasons,
                })

    # Sort: false wisdom by validations desc, compounding by validations desc
    false_wisdom.sort(key=lambda x: x["validations"], reverse=True)
    compounding.sort(key=lambda x: x["validations"], reverse=True)

    # --- Score advisory emissions ---
    advisory_rows = _read_jsonl_tail(SPARK_HOME / "advisory_emit.jsonl", 200)
    adv_total = len(advisory_rows)
    adv_keepable = 0
    recent_adjudications: list[dict] = []

    for row in reversed(advisory_rows[-30:]):
        text = _extract_advisory_text(row)
        if not text:
            continue
        gate = evaluate_structural_keepability(text)
        passed = bool(gate.get("passed"))
        if passed:
            adv_keepable += 1
        recent_adjudications.append({
            "text": text,
            "ts": row.get("ts", row.get("timestamp", 0)),
            "passed": passed,
            "reasons": gate.get("reasons", []),
            "source": row.get("source") or None,
            "advice_id": row.get("advice_id") or None,
        })

    adv_keepable_full = sum(
        1 for row in advisory_rows
        if bool(evaluate_structural_keepability(_extract_advisory_text(row)).get("passed"))
        and _extract_advisory_text(row)
    )

    # --- Score promotions ---
    promo_rows = _read_jsonl_tail(SPARK_HOME / "promotion_log.jsonl", 500)
    promo_total = 0
    promo_keepable = 0
    for row in promo_rows:
        if row.get("action") != "promote":
            continue
        text = row.get("text", row.get("content", ""))
        if not text:
            continue
        promo_total += 1
        gate = evaluate_structural_keepability(text)
        if bool(gate.get("passed")):
            promo_keepable += 1

    # --- Build output ---
    result = {
        "last_updated": now,
        "last_updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "keepability_rate": {
            "cognitive": {
                "total": cog_total,
                "keepable": cog_keepable,
                "rate": round(cog_keepable / max(cog_total, 1), 4),
            },
            "advisory": {
                "total": adv_total,
                "keepable": adv_keepable_full,
                "rate": round(adv_keepable_full / max(adv_total, 1), 4),
            },
            "promoted": {
                "total": promo_total,
                "keepable": promo_keepable,
                "rate": round(promo_keepable / max(promo_total, 1), 4),
            },
        },
        "gate_funnel": {
            "cognitive_incoming": cog_total,
            "cognitive_passed": cog_keepable,
            "cognitive_rejected": cog_total - cog_keepable,
        },
        "reason_distribution": dict(
            sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
        ),
        "false_wisdom": false_wisdom[:15],
        "compounding": compounding[:15],
        "recent_adjudications": recent_adjudications[:20],
    }

    return result


def write_quality_file(result: dict | None = None) -> Path:
    """Score and write to ~/.spark/intelligence_quality.json."""
    if result is None:
        result = score_all()
    out = SPARK_HOME / "intelligence_quality.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    result = score_all()
    out = write_quality_file(result)

    kr = result["keepability_rate"]
    print(f"Intelligence Quality Score")
    print(f"  Cognitive:  {kr['cognitive']['keepable']}/{kr['cognitive']['total']} "
          f"({kr['cognitive']['rate']:.1%})")
    print(f"  Advisory:   {kr['advisory']['keepable']}/{kr['advisory']['total']} "
          f"({kr['advisory']['rate']:.1%})")
    print(f"  Promoted:   {kr['promoted']['keepable']}/{kr['promoted']['total']} "
          f"({kr['promoted']['rate']:.1%})")
    print(f"\n  False Wisdom:        {len(result['false_wisdom'])} items")
    print(f"  Compounding Insights: {len(result['compounding'])} items")
    print(f"\n  Reason distribution:")
    for reason, count in result["reason_distribution"].items():
        print(f"    {reason}: {count}")
    print(f"\n  Written to: {out}")
