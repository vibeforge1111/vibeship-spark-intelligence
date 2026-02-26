"""
Sync Tracker: Track what learnings have been synced to which adapters.

This provides visibility into the output pipeline:
- Which insights were synced
- To which adapters (CLAUDE.md, .cursorrules, .windsurfrules, etc.)
- When the sync happened
- Whether it succeeded

The dashboard can then show real output stats instead of unused MarkdownWriter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


SYNC_STATS_FILE = Path.home() / ".spark" / "sync_stats.json"


@dataclass
class AdapterStatus:
    """Status of a single adapter."""
    name: str
    tier: str = "optional"  # core | optional
    last_sync: Optional[str] = None
    status: str = "never"  # never, success, error, skipped
    items_synced: int = 0
    file_path: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SyncTracker:
    """Tracks sync status across all adapters."""

    adapters: Dict[str, AdapterStatus] = field(default_factory=dict)
    last_full_sync: Optional[str] = None
    total_syncs: int = 0

    # Define known adapters
    KNOWN_ADAPTERS = {
        "claude_code": {"name": "CLAUDE.md", "file": "CLAUDE.md", "tier": "optional"},
        "cursor": {"name": "Cursor Rules", "file": ".cursorrules", "tier": "optional"},
        "windsurf": {"name": "Windsurf Rules", "file": ".windsurfrules", "tier": "optional"},
        "clawdbot": {"name": "Clawdbot", "file": "~/.clawdbot/", "tier": "optional"},
        "exports": {"name": "Exports", "file": "~/.spark/exports/", "tier": "core"},
        "openclaw": {"name": "OpenClaw", "file": "~/.openclaw/workspace/", "tier": "core"},
    }

    def __post_init__(self) -> None:
        # Initialize known adapters
        for key, info in self.KNOWN_ADAPTERS.items():
            if key not in self.adapters:
                self.adapters[key] = AdapterStatus(
                    name=info["name"],
                    tier=str(info.get("tier") or "optional"),
                    file_path=info["file"],
                )

    def _tier_for(self, adapter_key: str) -> str:
        info = self.KNOWN_ADAPTERS.get(adapter_key, {})
        tier = str(info.get("tier") or "optional").strip().lower()
        return "core" if tier == "core" else "optional"

    def record_sync(self, adapter_key: str, status: str, items: int = 0, error: Optional[str] = None) -> None:
        """Record a sync attempt."""
        now = datetime.now().isoformat(timespec="seconds")

        if adapter_key not in self.adapters:
            self.adapters[adapter_key] = AdapterStatus(
                name=adapter_key,
                tier=self._tier_for(adapter_key),
            )

        adapter = self.adapters[adapter_key]
        adapter.last_sync = now
        adapter.status = status
        adapter.items_synced = items
        adapter.error = error if status == "error" else None

        self.last_full_sync = now
        self.total_syncs += 1

        self._save()

    def record_full_sync(self, results: Dict[str, str], items_per_adapter: int = 0) -> None:
        """Record results from a full sync operation."""
        now = datetime.now().isoformat(timespec="seconds")

        for adapter_key, status in results.items():
            if adapter_key not in self.adapters:
                info = self.KNOWN_ADAPTERS.get(
                    adapter_key,
                    {"name": adapter_key, "file": None, "tier": self._tier_for(adapter_key)},
                )
                self.adapters[adapter_key] = AdapterStatus(
                    name=info["name"],
                    tier=str(info.get("tier") or "optional"),
                    file_path=info.get("file"),
                )

            adapter = self.adapters[adapter_key]
            adapter.last_sync = now
            adapter.status = "success" if status == "written" else status
            adapter.items_synced = items_per_adapter if status == "written" else 0

        self.last_full_sync = now
        self.total_syncs += 1
        self._save()

    def get_stats(self) -> Dict[str, Any]:
        """Get stats for dashboard display."""
        successful = sum(1 for a in self.adapters.values() if a.status == "success")
        failed = sum(1 for a in self.adapters.values() if a.status == "error")
        never = sum(1 for a in self.adapters.values() if a.status == "never")
        core_ok = 0
        core_error = 0
        core_never = 0
        optional_ok = 0
        optional_error = 0
        optional_never = 0

        adapter_list = []
        for key, adapter in self.adapters.items():
            tier = str(adapter.tier or self._tier_for(key)).lower()
            if tier == "core":
                if adapter.status == "success":
                    core_ok += 1
                elif adapter.status == "error":
                    core_error += 1
                elif adapter.status == "never":
                    core_never += 1
            else:
                if adapter.status == "success":
                    optional_ok += 1
                elif adapter.status == "error":
                    optional_error += 1
                elif adapter.status == "never":
                    optional_never += 1
            adapter_list.append({
                "key": key,
                "name": adapter.name,
                "tier": tier,
                "status": adapter.status,
                "last_sync": adapter.last_sync,
                "items": adapter.items_synced,
                "file": adapter.file_path,
            })

        return {
            "last_sync": self.last_full_sync,
            "total_syncs": self.total_syncs,
            "adapters_ok": successful,
            "adapters_error": failed,
            "adapters_never": never,
            "core_ok": core_ok,
            "core_error": core_error,
            "core_never": core_never,
            "optional_ok": optional_ok,
            "optional_error": optional_error,
            "optional_never": optional_never,
            "core_healthy": core_error == 0,
            "adapters": adapter_list,
        }

    def _save(self) -> None:
        """Save to disk."""
        SYNC_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_full_sync": self.last_full_sync,
            "total_syncs": self.total_syncs,
            "adapters": {
                k: {
                    "name": v.name,
                    "tier": v.tier,
                    "last_sync": v.last_sync,
                    "status": v.status,
                    "items_synced": v.items_synced,
                    "file_path": v.file_path,
                    "error": v.error,
                }
                for k, v in self.adapters.items()
            }
        }
        SYNC_STATS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "SyncTracker":
        """Load from disk or create new."""
        tracker = cls()

        if SYNC_STATS_FILE.exists():
            try:
                data = json.loads(SYNC_STATS_FILE.read_text(encoding="utf-8"))
                tracker.last_full_sync = data.get("last_full_sync")
                tracker.total_syncs = data.get("total_syncs", 0)

                for key, info in data.get("adapters", {}).items():
                    known = tracker.KNOWN_ADAPTERS.get(key, {})
                    tracker.adapters[key] = AdapterStatus(
                        name=info.get("name", key),
                        tier=str(info.get("tier") or known.get("tier") or "optional"),
                        last_sync=info.get("last_sync"),
                        status=info.get("status", "never"),
                        items_synced=info.get("items_synced", 0),
                        file_path=info.get("file_path"),
                        error=info.get("error"),
                    )
            except Exception:
                pass

        # Ensure all known adapters exist
        tracker.__post_init__()
        return tracker


# Singleton
_tracker: Optional[SyncTracker] = None


def get_sync_tracker() -> SyncTracker:
    """Get the global sync tracker."""
    global _tracker
    if _tracker is None:
        _tracker = SyncTracker.load()
    return _tracker
