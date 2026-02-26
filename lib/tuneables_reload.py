"""
Central tuneables reload coordinator.

Provides mtime-based hot-reload for all modules that consume tuneables.json.
Each module registers a callback via register_reload(). A single
check_and_reload() call checks the file mtime, validates via schema,
and dispatches changed sections to registered callbacks.

Usage:
    # In each module, register at import time:
    from lib.tuneables_reload import register_reload
    register_reload("meta_ralph", _reload_from_section)

    # From bridge cycle or CLI, periodically:
    from lib.tuneables_reload import check_and_reload
    changed = check_and_reload()
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

ReloadCallback = Callable[[Dict[str, Any]], None]

TUNEABLES_FILE = Path.home() / ".spark" / "tuneables.json"
_CONFIG_DEFAULTS_FILE = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"

_lock = threading.Lock()
_last_mtime: Optional[float] = None
_last_data: Dict[str, Any] = {}
_callbacks: Dict[str, List[Tuple[str, ReloadCallback]]] = {}

_reload_log: List[Dict[str, Any]] = []
_MAX_RELOAD_LOG = 20

logger = logging.getLogger("spark.tuneables_reload")

try:
    from .file_lock import file_lock_for as _file_lock_for
except Exception:  # pragma: no cover - keep reload resilient if lock helper missing
    _file_lock_for = None


@contextmanager
def _tuneables_write_lock(path: Path) -> Iterator[None]:
    if _file_lock_for is None:
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = None
        deadline = time.time() + 3.0
        stale_s = 30.0
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                break
            except FileExistsError:
                # Remove stale locks left by crashed processes.
                try:
                    age = time.time() - lock_path.stat().st_mtime
                    if age >= stale_s:
                        lock_path.unlink(missing_ok=True)
                        continue
                except Exception:
                    pass
                if time.time() >= deadline:
                    raise TimeoutError(f"timed out acquiring lock: {lock_path}")
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                try:
                    lock_path.unlink(missing_ok=True)
                except Exception:
                    pass
        return
    with _file_lock_for(path, timeout_s=3.0, stale_s=30.0, fail_open=False):
        yield


def register_reload(
    section: str,
    callback: ReloadCallback,
    *,
    label: Optional[str] = None,
) -> None:
    """Register a callback for when a tuneables section changes.

    Args:
        section: The tuneables.json section name (e.g., "meta_ralph").
        callback: Function called with the section dict when it changes.
        label: Human-readable label for diagnostics.
    """
    with _lock:
        if section not in _callbacks:
            _callbacks[section] = []
        _callbacks[section].append((
            label or f"{section}.callback_{len(_callbacks[section])}",
            callback,
        ))


def check_and_reload(*, force: bool = False) -> bool:
    """Check if tuneables.json changed and reload if so.

    Returns True if a reload happened, False if no change detected.
    Thread-safe via internal lock.
    """
    global _last_mtime, _last_data

    with _lock:
        current_mtime: Optional[float] = None
        try:
            if TUNEABLES_FILE.exists():
                current_mtime = TUNEABLES_FILE.stat().st_mtime
        except OSError:
            return False

        if not force and _last_mtime == current_mtime:
            return False

        # Read file
        try:
            if not TUNEABLES_FILE.exists():
                return False
            raw = json.loads(TUNEABLES_FILE.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                return False
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("tuneables_reload: read failed: %s", e)
            return False

        # Validate via schema (soft import to avoid circular deps)
        validated_data = raw
        try:
            from .tuneables_schema import validate_tuneables
            result = validate_tuneables(raw)
            validated_data = result.data
            for w in result.warnings:
                logger.warning("tuneables_reload: %s", w)
        except ImportError:
            pass
        except Exception as e:
            logger.warning("tuneables_reload: validation error: %s", e)

        old_data = _last_data
        _last_data = validated_data
        _last_mtime = current_mtime

        # Determine which registered sections changed
        changed_sections: List[str] = []
        for section_name in _callbacks:
            old_section = old_data.get(section_name)
            new_section = validated_data.get(section_name)
            if old_section != new_section:
                changed_sections.append(section_name)

        # First load: reload everything registered
        if not old_data:
            changed_sections = list(_callbacks.keys())

        if not changed_sections:
            _last_mtime = current_mtime
            return False

        # Dispatch callbacks
        errors: List[str] = []
        dispatched: List[str] = []
        for section_name in changed_sections:
            section_data = validated_data.get(section_name, {})
            if not isinstance(section_data, dict):
                section_data = {}
            for cb_label, cb in _callbacks.get(section_name, []):
                try:
                    cb(section_data)
                    dispatched.append(cb_label)
                except Exception as e:
                    err_msg = f"{cb_label}: {e}"
                    errors.append(err_msg)
                    logger.warning("tuneables_reload: callback error: %s", err_msg)

        # Log
        _reload_log.append({
            "ts": time.time(),
            "changed": changed_sections,
            "dispatched": dispatched,
            "errors": errors,
            "force": force,
        })
        while len(_reload_log) > _MAX_RELOAD_LOG:
            _reload_log.pop(0)

        if dispatched:
            logger.info(
                "tuneables_reload: reloaded %d sections (%s)",
                len(changed_sections), ", ".join(changed_sections),
            )

        return True


def get_validated_data() -> Dict[str, Any]:
    """Return the last validated tuneables data (may be empty before first load)."""
    with _lock:
        return dict(_last_data)


def get_section(section_name: str) -> Dict[str, Any]:
    """Return a specific validated section (empty dict if not loaded)."""
    with _lock:
        section = _last_data.get(section_name, {})
        return dict(section) if isinstance(section, dict) else {}


def get_reload_log() -> List[Dict[str, Any]]:
    """Return recent reload events for diagnostics."""
    with _lock:
        return list(_reload_log)


def get_registered_sections() -> Dict[str, List[str]]:
    """Return registered sections and their callback labels."""
    with _lock:
        return {
            section: [label for label, _ in cbs]
            for section, cbs in _callbacks.items()
        }


# ---------------------------------------------------------------------------
# Default-reconciliation: prevent stale copies of config/ defaults from
# overriding newer code defaults in ~/.spark/tuneables.json.
#
# Problem: when code changes a default (e.g. queue_budget 2→25), the runtime
# file still has the old value "2" which wins.  This happens because the
# runtime file stores ALL values, including copies of defaults.
#
# Solution: on startup, compare each key in ~/.spark/tuneables.json against
# config/tuneables.json.  If a runtime value equals the config/ default,
# it was never intentionally changed — remove it so the code default wins.
# Keys that DIFFER from config/ defaults are kept (intentional overrides).
# ---------------------------------------------------------------------------

_RECONCILE_SKIP_SECTIONS = frozenset({
    # Auto-tuner state is all intentional — never strip it
    "auto_tuner",
    # Updated_at is metadata
    "updated_at",
})

_SENTINEL = object()


def reconcile_with_defaults(*, dry_run: bool = False) -> Dict[str, Any]:
    """Strip values from ~/.spark/tuneables.json that match config/ defaults.

    Only keeps values that DIFFER from the version-controlled defaults
    (i.e. intentional overrides by user or auto-tuner).

    Args:
        dry_run: If True, report what would change without writing.

    Returns:
        Dict with keys: stripped (list of "section.key" removed),
        kept (count of intentional overrides kept), written (bool).
    """
    result: Dict[str, Any] = {"stripped": [], "kept": 0, "written": False}

    if not TUNEABLES_FILE.exists():
        return result
    if not _CONFIG_DEFAULTS_FILE.exists():
        logger.warning("reconcile: config/tuneables.json not found at %s", _CONFIG_DEFAULTS_FILE)
        return result

    try:
        lock_ctx = _tuneables_write_lock(TUNEABLES_FILE)
    except Exception as e:
        logger.warning("reconcile: lock init failed: %s", e)
        return result

    try:
        with lock_ctx:
            try:
                runtime = json.loads(TUNEABLES_FILE.read_text(encoding="utf-8-sig"))
                defaults = json.loads(_CONFIG_DEFAULTS_FILE.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("reconcile: read error: %s", e)
                return result

            if not isinstance(runtime, dict) or not isinstance(defaults, dict):
                return result

            changed = False
            for section_name in list(runtime.keys()):
                if section_name in _RECONCILE_SKIP_SECTIONS:
                    continue
                runtime_section = runtime.get(section_name)
                defaults_section = defaults.get(section_name)

                # Only reconcile dict sections (not top-level scalars)
                if not isinstance(runtime_section, dict) or not isinstance(defaults_section, dict):
                    continue

                keys_to_strip = []
                for key, runtime_val in list(runtime_section.items()):
                    if key.startswith("_"):
                        # Skip metadata/doc keys
                        continue
                    default_val = defaults_section.get(key, _SENTINEL)
                    if default_val is _SENTINEL:
                        # Key doesn't exist in defaults — it's an intentional addition, keep it
                        result["kept"] += 1
                        continue
                    if _values_match(runtime_val, default_val):
                        keys_to_strip.append(key)
                    else:
                        result["kept"] += 1

                for key in keys_to_strip:
                    result["stripped"].append(f"{section_name}.{key}")
                    if not dry_run:
                        del runtime_section[key]
                        changed = True

            if changed and not dry_run:
                try:
                    from .tuneables_schema import validate_tuneables

                    validated = validate_tuneables(runtime).data
                    tmp = TUNEABLES_FILE.with_suffix(
                        TUNEABLES_FILE.suffix + f".tmp.{os.getpid()}.{time.time_ns()}"
                    )
                    tmp.write_text(json.dumps(validated, indent=2, ensure_ascii=False), encoding="utf-8")
                    tmp.replace(TUNEABLES_FILE)
                    result["written"] = True
                    logger.info(
                        "reconcile: stripped %d stale defaults, kept %d overrides",
                        len(result["stripped"]), result["kept"],
                    )
                except Exception as e:
                    logger.warning("reconcile: write failed: %s", e)
    except TimeoutError as e:
        logger.warning("reconcile: lock timeout: %s", e)
        return result

    return result


def _values_match(runtime_val: Any, default_val: Any) -> bool:
    """Compare values loosely (int 8 == float 8.0, etc.)."""
    if runtime_val == default_val:
        return True
    # Handle int/float comparison (common source of drift)
    try:
        if isinstance(runtime_val, (int, float)) and isinstance(default_val, (int, float)):
            return float(runtime_val) == float(default_val)
    except (TypeError, ValueError):
        pass
    return False
