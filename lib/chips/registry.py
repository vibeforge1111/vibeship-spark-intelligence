"""
Chip Registry - Track which chips are active per project.

This was the second missing piece: knowing which chips to run
for a given project context.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from datetime import datetime

from .loader import Chip, ChipLoader

log = logging.getLogger("spark.chips")

REGISTRY_FILE = Path.home() / ".spark" / "chip_registry.json"
USER_CHIPS_DIR = Path.home() / ".spark" / "chips"


class ChipRegistry:
    """
    Tracks which chips are installed and active.

    - Installed: Available in the system
    - Active: Currently enabled for a project or globally
    """

    def __init__(self, auto_discover: bool = True, user_chips_dir: Optional[Path] = None):
        self.loader = ChipLoader()
        self.user_chips_dir = user_chips_dir or USER_CHIPS_DIR
        self._installed: Dict[str, Chip] = {}
        self._active: Dict[str, Set[str]] = {}  # project_path -> chip_ids
        self._global_active: Set[str] = set()   # chips active for all projects
        self._load_registry()
        if auto_discover:
            self._discover_chips()

    def _load_registry(self):
        """Load registry from disk."""
        if REGISTRY_FILE.exists():
            try:
                with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for proj, chips in data.get('active', {}).items():
                        self._active[proj] = set(chips)
                    self._global_active = set(data.get('global_active', []))
            except Exception as e:
                log.warning(f"Failed to load registry: {e}")

    def _save_registry(self):
        """Save registry to disk."""
        try:
            REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'active': {k: list(v) for k, v in self._active.items()},
                'global_active': list(self._global_active),
                'updated_at': datetime.now().isoformat()
            }
            with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save registry: {e}")

    def _discover_chips(self):
        """Discover and install all available chips."""
        chips = self.loader.discover_chips()
        for chip in chips:
            self._installed[chip.id] = chip
        if self.user_chips_dir.exists():
            user_loader = ChipLoader(chips_dir=self.user_chips_dir)
            for chip in user_loader.discover_chips():
                self._installed[chip.id] = chip
        log.info(f"Installed {len(self._installed)} chips")

    def get_installed(self) -> List[Chip]:
        """Get all installed chips."""
        return list(self._installed.values())

    def get_chip(self, chip_id: str) -> Optional[Chip]:
        """Get an installed chip by ID."""
        return self._installed.get(chip_id)

    def is_active(self, chip_id: str, project_path: Optional[str] = None) -> bool:
        """Check if a chip is active."""
        if chip_id in self._global_active:
            return True
        if project_path and project_path in self._active:
            return chip_id in self._active[project_path]
        return False

    def install(self, path: Path) -> Optional[Chip]:
        """Install a chip (single file or multifile directory) into user chips."""
        path = Path(path)
        if not path.exists():
            return None

        chip = self.loader.load_chip(path)
        if not chip:
            return None

        self.user_chips_dir.mkdir(parents=True, exist_ok=True)

        if path.is_dir():
            dest = self.user_chips_dir / "multifile" / chip.id
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(path, dest)
            except Exception as e:
                log.error(f"Failed to install multifile chip {path}: {e}")
                return None
        else:
            dest = self.user_chips_dir / f"{chip.id}.chip.yaml"
            try:
                shutil.copy2(path, dest)
            except Exception as e:
                log.error(f"Failed to install chip {path}: {e}")
                return None

        user_loader = ChipLoader(chips_dir=self.user_chips_dir)
        installed = user_loader.load_chip(dest)
        if installed:
            self._installed[installed.id] = installed
        return installed

    def uninstall(self, chip_id: str) -> bool:
        """Uninstall a user-installed chip."""
        chip = self._installed.get(chip_id)
        if not chip or not chip.source_path:
            return False

        try:
            chip_path = chip.source_path.resolve()
            user_root = self.user_chips_dir.resolve()
            if user_root not in chip_path.parents:
                return False
            if (
                chip_path.name == "chip.yaml"
                and chip_path.parent.name == chip_id
                and chip_path.parent.parent.name in {"multifile", "hybrid"}
            ):
                shutil.rmtree(chip_path.parent, ignore_errors=False)
            else:
                chip_path.unlink()
        except Exception as e:
            log.error(f"Failed to uninstall chip {chip_id}: {e}")
            return False

        # Remove from registry and active sets
        self._installed.pop(chip_id, None)
        self._global_active.discard(chip_id)
        for active in self._active.values():
            active.discard(chip_id)
        self._save_registry()
        return True

    def activate(self, chip_id: str, project_path: str = None) -> bool:
        """Activate a chip for a project (or globally if no project)."""
        if chip_id not in self._installed:
            log.warning(f"Chip {chip_id} not installed")
            return False

        if project_path:
            if project_path not in self._active:
                self._active[project_path] = set()
            self._active[project_path].add(chip_id)
        else:
            self._global_active.add(chip_id)

        self._save_registry()
        log.info(f"Activated chip {chip_id}" + (f" for {project_path}" if project_path else " globally"))
        return True

    def deactivate(self, chip_id: str, project_path: str = None) -> bool:
        """Deactivate a chip."""
        if chip_id not in self._installed:
            return False
        if project_path and project_path in self._active:
            self._active[project_path].discard(chip_id)
        else:
            self._global_active.discard(chip_id)
        self._save_registry()
        return True

    def get_active_chips(self, project_path: str = None) -> List[Chip]:
        """Get all active chips for a project (includes global)."""
        chip_ids = set(self._global_active)
        if project_path and project_path in self._active:
            chip_ids.update(self._active[project_path])

        return [self._installed[cid] for cid in chip_ids if cid in self._installed]

    def auto_activate_for_content(self, content: str, project_path: str = None) -> List[Chip]:
        """
        Auto-activate chips based on content matching triggers.

        This is the KEY feature: when we see "lobster", "Three.js", "health",
        we automatically activate the game_dev chip.
        """
        activated = []
        content_lower = content.lower()

        for chip in self._installed.values():
            # Check if chip already active
            if chip.id in self._global_active:
                continue
            if project_path and project_path in self._active and chip.id in self._active[project_path]:
                continue
            if getattr(chip, "activation", "auto") != "auto":
                continue

            # Check triggers
            matches = chip.matches_content(content)
            if matches:
                if project_path:
                    if project_path not in self._active:
                        self._active[project_path] = set()
                    self._active[project_path].add(chip.id)
                else:
                    self._global_active.add(chip.id)

                activated.append(chip)
                log.info(f"Auto-activated chip {chip.id} (matched: {matches[:3]})")

        if activated:
            self._save_registry()

        return activated

    def get_stats(self, project_path: Optional[str] = None) -> Dict[str, Any]:
        """Get basic registry stats."""
        active = self.get_active_chips(project_path)
        return {
            "total_installed": len(self._installed),
            "total_active": len(active),
            "global_active": len(self._global_active),
            "project_active": len(self._active.get(project_path, set())) if project_path else 0,
        }

    def get_active_questions(self, phase: Optional[str] = None, project_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get questions from active chips, optionally filtered by phase."""
        questions: List[Dict[str, Any]] = []
        for chip in self.get_active_chips(project_path):
            for q in chip.questions or []:
                if not isinstance(q, dict):
                    continue
                q_phase = q.get("phase")
                if phase and q_phase and q_phase != phase:
                    continue
                entry = dict(q)
                entry["chip_id"] = chip.id
                questions.append(entry)
        return questions


_registry: Optional[ChipRegistry] = None


def get_registry() -> ChipRegistry:
    """Get singleton chip registry."""
    global _registry
    if _registry is None:
        _registry = ChipRegistry()
    return _registry
