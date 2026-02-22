"""
Spark Auto-Promotion: Run promotion checks automatically at session end.

Rate-limited to avoid redundant work -- checks a timestamp file to ensure
promotion runs at most once per configured interval (default: 1 hour).

Called from hooks/observe.py on session end events (Stop, SessionEnd).
"""

import json
import time
from pathlib import Path
from typing import Dict, Optional

from .diagnostics import log_debug

LAST_PROMOTION_FILE = Path.home() / ".spark" / "last_promotion.txt"
DEFAULT_INTERVAL_S = 3600  # 1 hour


def _load_promotion_config_interval() -> int:
    """Load promotion interval from tuneables.json."""
    try:
        tuneables = Path.home() / ".spark" / "tuneables.json"
        if tuneables.exists():
            # Accept UTF-8 with BOM (common on Windows).
            data = json.loads(tuneables.read_text(encoding="utf-8-sig"))
            cfg = data.get("promotion") or {}
            return int(cfg.get("auto_interval_s", DEFAULT_INTERVAL_S))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError, TypeError) as e:
        log_debug("auto_promote", "failed to load promotion config from tuneables.json", e)
    return DEFAULT_INTERVAL_S


def _should_run() -> bool:
    """Check if enough time has passed since last promotion run."""
    interval_s = _load_promotion_config_interval()
    try:
        if LAST_PROMOTION_FILE.exists():
            last_ts = float(LAST_PROMOTION_FILE.read_text(encoding="utf-8").strip())
            if time.time() - last_ts < interval_s:
                return False
    except (OSError, ValueError, TypeError):
        pass  # If file is missing or corrupted, just run
    return True


def _mark_run():
    """Record that promotion ran now."""
    try:
        LAST_PROMOTION_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_PROMOTION_FILE.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass


def maybe_promote_on_session_end(project_dir: Optional[Path] = None) -> Optional[Dict[str, int]]:
    """Run promotion check if rate limit allows.

    Returns promotion stats if run, None if skipped due to rate limit.
    Safe to call from hooks -- all errors are caught.
    """
    if not _should_run():
        return None

    try:
        from .promoter import check_and_promote
        stats = check_and_promote(
            project_dir=project_dir,
            dry_run=False,
            include_project=True,
        )
        _mark_run()
        total = stats.get("promoted", 0)
        if total > 0:
            log_debug("auto_promote", f"Promoted {total} insights at session end", None)
        return stats
    except Exception as e:
        log_debug("auto_promote", "auto-promotion failed", e)
        _mark_run()  # Still mark to prevent retry-storms
        return None
