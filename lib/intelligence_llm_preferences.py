"""Runtime LLM preference helpers for intelligence subsystems."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .config_authority import resolve_section

TUNEABLES_PATH = Path.home() / ".spark" / "tuneables.json"
WRITE_LOCK_TIMEOUT_S = 5.0
WRITE_LOCK_POLL_S = 0.05
WRITE_LOCK_STALE_S = 30.0
VALID_PROVIDERS = {"auto", "ollama", "minimax", "openai", "anthropic", "gemini", "claude"}


def detect_local_ollama(timeout_s: float = 2.5) -> bool:
    try:
        ollama_bin = shutil.which("ollama")
        if not ollama_bin:
            return False
        proc = subprocess.run(  # noqa: S603
            [ollama_bin, "list"],
            capture_output=True,
            text=True,
            timeout=max(0.5, float(timeout_s)),
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _acquire_file_lock(lock_path: Path, timeout_s: float = WRITE_LOCK_TIMEOUT_S) -> int:
    deadline = time.time() + max(0.1, float(timeout_s))
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, f"{os.getpid()} {time.time()}".encode("utf-8"))
            return fd
        except FileExistsError:
            try:
                age_s = time.time() - float(lock_path.stat().st_mtime)
                if age_s > WRITE_LOCK_STALE_S:
                    lock_path.unlink(missing_ok=True)
                    continue
            except Exception:
                pass
            if time.time() >= deadline:
                raise TimeoutError(f"timed out acquiring lock: {lock_path}")
            time.sleep(WRITE_LOCK_POLL_S)


def _release_file_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_fd = _acquire_file_lock(lock_path)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        _release_file_lock(lock_fd, lock_path)


def _norm_provider(value: Any) -> str:
    provider = str(value or "").strip().lower() or "auto"
    return provider if provider in VALID_PROVIDERS else "auto"


def _norm_bool(value: Any, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def get_current_preferences(path: Path = TUNEABLES_PATH) -> Dict[str, Any]:
    eidos = resolve_section("eidos", runtime_path=path).data
    meta = resolve_section("meta_ralph", runtime_path=path).data
    scanner = resolve_section("opportunity_scanner", runtime_path=path).data
    packets = resolve_section("advisory_packet_store", runtime_path=path).data
    llm_areas = resolve_section("llm_areas", runtime_path=path).data

    prefs: Dict[str, Any] = {
        "eidos_runtime_refiner_llm_enabled": bool((eidos or {}).get("runtime_refiner_llm_enabled", False)),
        "eidos_runtime_refiner_llm_provider": str((eidos or {}).get("runtime_refiner_llm_provider", "auto")),
        "meta_ralph_runtime_refiner_llm_enabled": bool((meta or {}).get("runtime_refiner_llm_enabled", False)),
        "meta_ralph_runtime_refiner_llm_provider": str((meta or {}).get("runtime_refiner_llm_provider", "auto")),
        "opportunity_scanner_llm_enabled": bool((scanner or {}).get("llm_enabled", True)),
        "packet_lookup_llm_enabled": bool((packets or {}).get("packet_lookup_llm_enabled", False)),
        "packet_lookup_llm_provider": str((packets or {}).get("packet_lookup_llm_provider", "minimax")),
    }

    # Include LLM area preferences (30 areas)
    if isinstance(llm_areas, dict):
        from .llm_dispatch import ALL_AREAS
        enabled_count = 0
        for area_id in ALL_AREAS:
            is_enabled = bool(llm_areas.get(f"{area_id}_enabled", False))
            provider = str(llm_areas.get(f"{area_id}_provider", "minimax"))
            prefs[f"llm_area_{area_id}_enabled"] = is_enabled
            prefs[f"llm_area_{area_id}_provider"] = provider
            if is_enabled:
                enabled_count += 1
        prefs["llm_areas_enabled_count"] = enabled_count
        prefs["llm_areas_total_count"] = len(ALL_AREAS)

    return prefs


def apply_runtime_llm_preferences(
    *,
    eidos_runtime_llm: Any = None,
    meta_ralph_runtime_llm: Any = None,
    opportunity_scanner_llm: Any = None,
    packet_lookup_llm: Any = None,
    llm_areas_enable: Any = None,
    llm_areas_list: Any = None,
    provider: Any = "auto",
    path: Path = TUNEABLES_PATH,
    source: str = "cli_setup",
) -> Dict[str, Any]:
    current = get_current_preferences(path=path)
    selected_provider = _norm_provider(provider)
    data = _read_json(path)

    eidos = data.setdefault("eidos", {})
    meta = data.setdefault("meta_ralph", {})
    scanner = data.setdefault("opportunity_scanner", {})
    packets = data.setdefault("advisory_packet_store", {})

    if not isinstance(eidos, dict):
        eidos = {}
        data["eidos"] = eidos
    if not isinstance(meta, dict):
        meta = {}
        data["meta_ralph"] = meta
    if not isinstance(scanner, dict):
        scanner = {}
        data["opportunity_scanner"] = scanner
    if not isinstance(packets, dict):
        packets = {}
        data["advisory_packet_store"] = packets

    eidos_enabled = _norm_bool(eidos_runtime_llm, current["eidos_runtime_refiner_llm_enabled"])
    meta_enabled = _norm_bool(meta_ralph_runtime_llm, current["meta_ralph_runtime_refiner_llm_enabled"])
    scanner_enabled = _norm_bool(opportunity_scanner_llm, current["opportunity_scanner_llm_enabled"])
    packet_enabled = _norm_bool(packet_lookup_llm, current["packet_lookup_llm_enabled"])

    eidos["runtime_refiner_llm_enabled"] = eidos_enabled
    meta["runtime_refiner_llm_enabled"] = meta_enabled
    scanner["llm_enabled"] = scanner_enabled
    packets["packet_lookup_llm_enabled"] = packet_enabled

    if eidos_enabled:
        eidos["runtime_refiner_llm_provider"] = selected_provider
    if meta_enabled:
        meta["runtime_refiner_llm_provider"] = selected_provider
    if packet_enabled:
        packets["packet_lookup_llm_provider"] = selected_provider

    # Apply LLM areas bulk enable/disable
    llm_areas_changed = 0
    if llm_areas_enable is not None or llm_areas_list is not None:
        from .llm_dispatch import ALL_AREAS
        areas_sec = data.setdefault("llm_areas", {})
        if not isinstance(areas_sec, dict):
            areas_sec = {}
            data["llm_areas"] = areas_sec

        target_areas = ALL_AREAS
        if isinstance(llm_areas_list, (list, tuple)):
            target_areas = [a for a in llm_areas_list if a in ALL_AREAS]

        bulk_state = _norm_bool(llm_areas_enable, False)
        for area_id in target_areas:
            areas_sec[f"{area_id}_enabled"] = bulk_state
            if bulk_state:
                areas_sec[f"{area_id}_provider"] = selected_provider
            llm_areas_changed += 1

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["updated_at"] = now
    data["_llm_runtime_setup"] = {
        "source": str(source or "cli_setup"),
        "updated_at": now,
        "provider": selected_provider,
        "eidos_runtime_refiner_llm_enabled": eidos_enabled,
        "meta_ralph_runtime_refiner_llm_enabled": meta_enabled,
        "opportunity_scanner_llm_enabled": scanner_enabled,
        "packet_lookup_llm_enabled": packet_enabled,
        "llm_areas_changed": llm_areas_changed,
    }

    _write_json_atomic(path, data)
    return {
        "ok": True,
        "path": str(path),
        "provider": selected_provider,
        "eidos_runtime_refiner_llm_enabled": eidos_enabled,
        "meta_ralph_runtime_refiner_llm_enabled": meta_enabled,
        "opportunity_scanner_llm_enabled": scanner_enabled,
        "packet_lookup_llm_enabled": packet_enabled,
        "llm_areas_changed": llm_areas_changed,
    }

