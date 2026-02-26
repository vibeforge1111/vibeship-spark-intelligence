"""Clean up cognitive_insights.json — remove noise, tag sources, compact."""
import json, re, shutil, sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '.')

INSIGHTS_FILE = Path.home() / ".spark" / "cognitive_insights.json"

# Noise patterns — insights matching these get removed
NOISE_PATTERNS = [
    r"Strong reasoning on '",
    r"Weak reasoning on '",
    r"strong_reasoning_on_'",
    r"strong_socratic_depth",
    r"\[depth:",
    r"\[DEPTH:",
    r"DEPTH score on",
    r"DEPTH meta-analysis",
    r"depth_score_on_'",
    r"Profile: [\*\+#%]",
    r"Strongest at depths",
    r"mcp__x-twitter__",
    r"mcp__h70-skills__",
    r"mcp__spawner__",
    r"tool_\d+_error",
    r"grade [A-F]\b",
    r"free-tier",
    r"content strategy on X",
    r"\[benchmark_core",
    r"\[game_dev_intelligence\]",
    r"\[moltbook_social_intelligence\]",
    r"\[market_intelligence\]",
    r"\[marketing_intelligence\]",
    r"\[business_ops_intelligence\]",
    r"shallow_reasoning_on_'",
    r"weak_socratic_lenses",
    r"^\s*\{",  # JSON blobs stored as insights
    r"^#!/usr/bin",  # code stored as insights
    r"^import\s",  # code stored as insights
    r"^from\s\w+\simport",
    r"^\s*def\s",
    r"^\s*class\s",
    r"bash_failed_\d+/\d+",
    r"bash_has_\d+%",
    r"glob_failed_\d+/\d+",
    r"glob_has_\d+%",
    r"read_failed_\d+/\d+",
    r"read_fails_",
    r"webfetch_fails_",
    r"edit_fails_",
    r"success_rate",
    r"consecutive_failures",
    r"overconfident:",
    r"^\d+_session\(s\)_had",
]

# Source inference — tag untagged insights based on content
SOURCE_HINTS = {
    "depth_forge": [r"\[depth:", r"depth_score", r"socratic", r"depth_training", r"bench_core"],
    "x_social": [r"x-twitter", r"\[X Strategy\]", r"tweet", r"twitter"],
    "cursor": [r"\.cursorrules", r"cursor"],
    "windsurf": [r"\.windsurfrules", r"windsurf"],
}


def is_noise(key, insight_data):
    """Check if this insight is noise."""
    text = insight_data.get("insight", "") + " " + key
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    # Very short insights with low validation
    if len(insight_data.get("insight", "")) < 15 and insight_data.get("times_validated", 0) < 3:
        return True
    # Code blocks
    if "```" in insight_data.get("insight", ""):
        return True
    return False


def infer_source(key, insight_data):
    """Try to infer source from content."""
    text = key + " " + insight_data.get("insight", "") + " " + insight_data.get("context", "")
    for source, patterns in SOURCE_HINTS.items():
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                return source
    return ""


def main():
    if not INSIGHTS_FILE.exists():
        print("No insights file found")
        return

    raw = INSIGHTS_FILE.read_text(encoding="utf-8", errors="surrogatepass")
    # Strip surrogate characters that break JSON serialization
    raw = raw.encode("utf-8", errors="replace").decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: insights file contains invalid JSON — {exc}")
        print("Aborting. Fix or restore the file before running cleanup.")
        return
    total = len(data)
    print(f"Total insights: {total}")

    # Backup
    backup = INSIGHTS_FILE.parent / f"cognitive_insights.pre_cleanup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy2(INSIGHTS_FILE, backup)
    print(f"Backup: {backup.name}")

    removed = 0
    tagged = 0
    kept = {}

    for key, val in data.items():
        if not isinstance(val, dict):
            continue

        if is_noise(key, val):
            removed += 1
            continue

        # Tag source if missing
        if not val.get("source"):
            source = infer_source(key, val)
            if source:
                val["source"] = source
                tagged += 1

        kept[key] = val

    print(f"Removed: {removed} noise insights")
    print(f"Tagged: {tagged} with inferred source")
    print(f"Kept: {len(kept)} ({len(kept)/total*100:.0f}%)")

    # Category breakdown
    cats = {}
    for v in kept.values():
        c = v.get("category", "?")
        cats[c] = cats.get(c, 0) + 1
    print("\nCategory breakdown:")
    for k, v in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

    if "--dry-run" not in sys.argv:
        cleaned_json = json.dumps(kept, indent=2, ensure_ascii=True)
        INSIGHTS_FILE.write_text(cleaned_json, encoding="utf-8")
        new_size = INSIGHTS_FILE.stat().st_size // 1024
        print(f"\nWritten: {new_size}KB (was {backup.stat().st_size // 1024}KB)")
    else:
        print("\n(dry run — no changes written)")


if __name__ == "__main__":
    main()
