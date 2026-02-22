"""Outcome Predictor (world-model-lite) for Spark.

Goal
----
Provide a *very cheap* predictor that estimates failure probability for the next
tool action, based on recent historical outcomes.

This is not a neural world model. It's a small, smoothed counter table:
- key = (phase, intent_family, tool)
- counts = success/failure

Used to:
- boost the gate score for cautionary advice when risk is high
- decide when to escalate or intervene earlier

Design constraints
------------------
- must be fast (used on pre-tool advisory path)
- must be durable (JSON file)
- bounded growth (cap keys)
- safe defaults (disabled unless explicitly enabled)

Flags
-----
- SPARK_OUTCOME_PREDICTOR=1 enables use by advisory gate.

"""

from __future__ import annotations

import json
import os
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .diagnostics import log_debug


PREDICTOR_ENABLED = os.getenv("SPARK_OUTCOME_PREDICTOR", "0") == "1"
STORE_PATH = Path.home() / ".spark" / "outcome_predictor.json"

# Cache reads so a single hook invocation doesn't hit disk multiple times.
_CACHE_TTL_S = 30.0
_cache: Optional[Dict[str, Any]] = None
_cache_ts: float = 0.0

# Bounded table size
MAX_KEYS = 2000

# Beta prior (defaults to "usually succeeds")
PRIOR_FAIL = 1.0
PRIOR_SUCC = 3.0


@dataclass
class Prediction:
    p_fail: float
    confidence: float
    samples: int
    key_used: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "p_fail": float(self.p_fail),
            "confidence": float(self.confidence),
            "samples": int(self.samples),
            "key_used": str(self.key_used),
            "reason": str(self.reason),
        }


def _now() -> float:
    return time.time()


def _stable_hash(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _load_store() -> Dict[str, Any]:
    global _cache, _cache_ts

    ts = _now()
    if _cache is not None and (ts - _cache_ts) < _CACHE_TTL_S:
        return _cache

    if not STORE_PATH.exists():
        _cache = {"version": 1, "updated_at": ts, "keys": {}}
        _cache_ts = ts
        return _cache

    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        log_debug("outcome_predictor", "failed to read outcome predictor store", e)
        data = {}

    keys = data.get("keys")
    if not isinstance(keys, dict):
        keys = {}

    _cache = {
        "version": int(data.get("version") or 1),
        "updated_at": float(data.get("updated_at") or ts),
        "keys": keys,
    }
    _cache_ts = ts
    return _cache


def _save_store(store: Dict[str, Any]) -> None:
    global _cache, _cache_ts
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_PATH.with_suffix(".json.tmp")
        payload = json.dumps(store, indent=2, ensure_ascii=False)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(STORE_PATH)
        _cache = store
        _cache_ts = _now()
    except Exception:
        return


def _make_key(phase: str, intent_family: str, tool: str) -> str:
    p = (phase or "*").strip().lower() or "*"
    i = (intent_family or "*").strip().lower() or "*"
    t = (tool or "*").strip().lower() or "*"
    return f"{p}|{i}|{t}"


def _bump(store: Dict[str, Any], key: str, success: bool) -> None:
    keys = store.setdefault("keys", {})
    row = keys.get(key)
    if not isinstance(row, dict):
        row = {"succ": 0, "fail": 0, "updated_at": 0.0}

    if success:
        row["succ"] = int(row.get("succ") or 0) + 1
    else:
        row["fail"] = int(row.get("fail") or 0) + 1

    row["updated_at"] = _now()
    keys[key] = row


def record_outcome(
    *,
    tool_name: str,
    intent_family: str,
    phase: str,
    success: bool,
) -> bool:
    """Record an outcome (success/failure) for the predictor table."""
    store = _load_store()
    key = _make_key(phase, intent_family, tool_name)

    try:
        _bump(store, key, success)

        # Also update a few coarser fallback buckets.
        _bump(store, _make_key(phase, "*", tool_name), success)
        _bump(store, _make_key("*", intent_family, tool_name), success)
        _bump(store, _make_key("*", "*", tool_name), success)

        store["updated_at"] = _now()

        # Bounded growth: keep most recently updated keys.
        keys = store.get("keys") or {}
        if isinstance(keys, dict) and len(keys) > MAX_KEYS:
            items = list(keys.items())
            items.sort(key=lambda kv: float((kv[1] or {}).get("updated_at") or 0.0), reverse=True)
            store["keys"] = dict(items[:MAX_KEYS])

        _save_store(store)
        return True
    except Exception:
        return False


def _row_stats(store: Dict[str, Any], key: str) -> Optional[Tuple[int, int, float]]:
    keys = store.get("keys")
    if not isinstance(keys, dict):
        return None
    row = keys.get(key)
    if not isinstance(row, dict):
        return None
    succ = int(row.get("succ") or 0)
    fail = int(row.get("fail") or 0)
    updated_at = float(row.get("updated_at") or 0.0)
    return succ, fail, updated_at


def predict(
    *,
    tool_name: str,
    intent_family: str,
    phase: str,
) -> Prediction:
    """Predict failure probability for a forthcoming tool action."""
    store = _load_store()

    keys_to_try = [
        _make_key(phase, intent_family, tool_name),
        _make_key(phase, "*", tool_name),
        _make_key("*", intent_family, tool_name),
        _make_key("*", "*", tool_name),
    ]

    used = keys_to_try[-1]
    succ = 0
    fail = 0
    for key in keys_to_try:
        stats = _row_stats(store, key)
        if not stats:
            continue
        s, f, _ts = stats
        if (s + f) <= 0:
            continue
        used = key
        succ = s
        fail = f
        break

    total = succ + fail

    # Smoothed probability of failure.
    p_fail = (fail + PRIOR_FAIL) / (total + PRIOR_FAIL + PRIOR_SUCC)

    # Confidence: saturates at ~20 samples.
    confidence = min(1.0, total / 20.0)

    reason = f"counts succ={succ} fail={fail} key={used}"
    return Prediction(p_fail=float(p_fail), confidence=float(confidence), samples=int(total), key_used=used, reason=reason)


def get_stats() -> Dict[str, Any]:
    store = _load_store()
    keys = store.get("keys") if isinstance(store.get("keys"), dict) else {}
    return {
        "enabled": bool(PREDICTOR_ENABLED),
        "path": str(STORE_PATH),
        "updated_at": float(store.get("updated_at") or 0.0),
        "key_count": len(keys),
        "cache_ttl_s": float(_CACHE_TTL_S),
        "prior": {"fail": PRIOR_FAIL, "succ": PRIOR_SUCC},
    }
