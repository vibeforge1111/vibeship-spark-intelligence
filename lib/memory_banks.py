"""Layered Memory Banks (portable)

Goal
----
Support layered memory without platform coupling:
- Global user preferences (likes/dislikes, comms style, hard boundaries)
- Project-scoped memories (decisions, constraints, project-specific rules)
- Session/ephemeral (optional later)

Design constraints
------------------
- Lightweight + stable: local JSONL files, simple keyword retrieval
- Compatible everywhere: driven by Spark queue + SparkEventV1 payloads
- Natural-language-first UX: users should not need CLI; CLI is for dev/debug

"""

from __future__ import annotations

import json
import re
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib.queue import read_recent_events, EventType


BANK_DIR = Path.home() / ".spark" / "banks"
GLOBAL_FILE = BANK_DIR / "global_user.jsonl"
PROJECTS_DIR = BANK_DIR / "projects"


@dataclass
class BankEntry:
    entry_id: str
    created_at: float
    scope: str                 # global|project|session
    project_key: Optional[str]
    category: str
    text: str
    session_id: Optional[str] = None
    source: Optional[str] = None
    meta: Dict[str, Any] = None
    share_scope: Optional[str] = None       # main_only|safe_general
    sensitivity: Optional[str] = None       # low|medium|high

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "created_at": self.created_at,
            "scope": self.scope,
            "project_key": self.project_key,
            "category": self.category,
            "text": self.text,
            "session_id": self.session_id,
            "source": self.source,
            "share_scope": self.share_scope,
            "sensitivity": self.sensitivity,
            "meta": self.meta or {},
        }


def _ensure_dirs():
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _hash_id(*parts: str) -> str:
    raw = "|".join([p or "" for p in parts]).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def infer_project_key(max_events: int = 60) -> Optional[str]:
    """Infer the active project key from recent events.

    We intentionally avoid trusting repo name alone.
    Evidence-based heuristic:
    - Prefer cwd/workdir (if present)
    - Else look for file paths in tool input/results

    Returns a stable-ish project key (folder basename), or None.
    """

    try:
        events = read_recent_events(max_events)
    except Exception:
        return None

    paths: List[str] = []

    def _norm_path(p: str) -> str:
        return (p or "").replace("\\", "/")

    for e in reversed(events):
        data = e.data or {}
        cwd = data.get("cwd")
        if isinstance(cwd, str) and ("/" in cwd or "\\" in cwd):
            paths.append(_norm_path(cwd))

        payload = data.get("payload") or {}
        # Some adapters can put extra meta here
        meta = payload.get("meta") or {}
        for k in ("cwd", "workdir", "workspace"):
            v = meta.get(k)
            if isinstance(v, str) and ("/" in v or "\\" in v):
                paths.append(_norm_path(v))

        tool_input = e.tool_input or {}
        for k in ("path", "file_path", "filePath", "workdir", "cwd"):
            v = tool_input.get(k)
            if isinstance(v, str) and ("/" in v or "\\" in v):
                paths.append(_norm_path(v))

    if not paths:
        return None

    # Prefer something inside a repo-like structure
    def score(p: str) -> int:
        s = 0
        if "/Users/" in p or p.startswith("/"):
            s += 1
        if "/Desktop/" in p or "/clawd/" in p:
            s += 1
        if p.endswith(".py") or p.endswith(".md") or "/src/" in p:
            s += 2
        return s

    best = max(paths, key=score)
    # normalize to directory
    best = best.rstrip("/")
    if "." in Path(best).name:
        best = str(Path(best).parent)

    name = Path(best).name
    if not name:
        return None

    # Small sanitize: keep alnum, dash, underscore
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    return name.lower()


def choose_scope(text: str, category: str, project_key: Optional[str]) -> Tuple[str, Optional[str]]:
    """Decide storage scope for a memory entry.

    Rules (aligned with Meta's preferences):
    - 'I hate / I prefer / I love' defaults to GLOBAL
    - explicit project phrasing pushes to project
    - implementation-detail categories lean project when evidence exists
    """

    t = (text or "").lower()

    # Explicit scoping language
    if any(p in t for p in ["for this project", "in this repo", "in this codebase", "in this dashboard"]):
        return ("project", project_key)

    # Global preference defaults
    if re.search(r"\b(i hate|i prefer|i love|i don't like|i dont like)\b", t):
        return ("global", None)

    # Communication style is typically global
    if category in ("communication", "user_understanding"):
        return ("global", None)

    # Reasoning/context can be project-specific if we know project
    if category in ("reasoning", "context") and project_key:
        return ("project", project_key)

    # Meta/wisdom tend global unless explicitly project
    if category in ("meta_learning", "wisdom"):
        return ("global", None)

    # Default: project if we have strong project evidence; else global
    if project_key:
        return ("project", project_key)

    return ("global", None)


def append_entry(entry: BankEntry) -> None:
    _ensure_dirs()
    if entry.scope == "project" and entry.project_key:
        out = PROJECTS_DIR / f"{entry.project_key}.jsonl"
    else:
        out = GLOBAL_FILE

    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")


def store_memory(
    text: str,
    category: str,
    session_id: Optional[str] = None,
    source: str = "spark",
    share_scope: Optional[str] = None,
    sensitivity: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> BankEntry:
    """Store a memory entry in Spark's portable banks.

    Added fields:
      - share_scope: main_only|safe_general
      - sensitivity: low|medium|high

    These are designed to align with Clawdbot's session privacy boundaries.
    """

    _ensure_dirs()
    project_key = infer_project_key()
    scope, proj = choose_scope(text=text, category=category, project_key=project_key)

    entry_id = _hash_id(scope, proj or "", category, text.strip()[:120])
    entry = BankEntry(
        entry_id=entry_id,
        created_at=time.time(),
        scope=scope,
        project_key=proj,
        category=category,
        text=text.strip(),
        session_id=session_id,
        source=source,
        share_scope=share_scope,
        sensitivity=sensitivity,
        meta=meta or {},
    )
    append_entry(entry)
    return entry


def _read_jsonl(path: Path, limit: int = 500) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines[-limit:]):
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return out


def retrieve(query: str, project_key: Optional[str] = None, limit: int = 6) -> List[Dict[str, Any]]:
    """Retrieve relevant memories from project + global banks.

    Lightweight keyword match + recency.
    """

    q = (query or "").lower().strip()
    if not q:
        return []

    candidates: List[Dict[str, Any]] = []

    if project_key:
        candidates.extend(_read_jsonl(PROJECTS_DIR / f"{project_key}.jsonl", limit=800))

    candidates.extend(_read_jsonl(GLOBAL_FILE, limit=800))

    scored: List[Tuple[float, Dict[str, Any]]] = []
    q_words = [w for w in re.split(r"\W+", q) if len(w) > 2]

    for it in candidates:
        text = (it.get("text") or "").lower()
        if not text:
            continue

        # basic scoring
        score = 0.0
        if q in text:
            score += 2.0
        for w in q_words[:8]:
            if w in text:
                score += 0.25

        # project memories slightly boosted when in project
        if project_key and it.get("project_key") == project_key:
            score += 0.4

        # recency boost
        created = float(it.get("created_at") or 0.0)
        age = max(1.0, time.time() - created)
        score += min(0.4, 50000.0 / age / 100000.0)

        if score > 0.25:
            scored.append((score, it))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [it for _, it in scored[:limit]]
