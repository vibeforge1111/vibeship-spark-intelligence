"""TasteBank: store and retrieve 'things you like'

MVP domains (Meta):
- social_posts
- ui_design
- art

Design constraints:
- lightweight + stable: JSONL storage, keyword retrieval
- compatible everywhere: driven by Spark queue events and/or explicit intent events
- natural-language-first: capture from phrases like "I like this post/UI/art" + URL/text

"""

from __future__ import annotations

import json
import re
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


TASTE_DIR = Path.home() / ".spark" / "taste"
DOMAINS = {"social_posts", "ui_design", "art"}  # art includes graphics/visual design


@dataclass
class TasteItem:
    item_id: str
    created_at: float
    domain: str
    label: str
    source: str  # url/path/or pasted text snippet
    notes: str
    tags: List[str]
    signals: List[str]
    scope: str = "global"
    project_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "created_at": self.created_at,
            "domain": self.domain,
            "label": self.label,
            "source": self.source,
            "notes": self.notes,
            "tags": self.tags,
            "signals": self.signals,
            "scope": self.scope,
            "project_key": self.project_key,
        }


def _ensure() -> None:
    TASTE_DIR.mkdir(parents=True, exist_ok=True)


def _file(domain: str) -> Path:
    _ensure()
    d = domain.strip().lower()
    if d not in DOMAINS:
        raise ValueError(f"Unknown domain: {domain}")
    return TASTE_DIR / f"{d}.jsonl"


def _hash_id(*parts: str) -> str:
    raw = "|".join([p or "" for p in parts]).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def add_item(domain: str, source: str, notes: str = "", label: str = "", tags: Optional[List[str]] = None,
             signals: Optional[List[str]] = None, scope: str = "global", project_key: Optional[str] = None) -> TasteItem:
    d = domain.strip().lower()
    if d not in DOMAINS:
        raise ValueError(f"Unknown domain: {domain}")

    source = (source or "").strip()
    notes = (notes or "").strip()
    label = (label or "").strip()

    # Strip channel prefixes / message_id if a caller passed raw transcript text as label
    label = re.sub(r"^\s*\[[^\]]+\]\s*", "", label)
    label = re.sub(r"\n?\[message_id:.*?\]\s*$", "", label, flags=re.IGNORECASE | re.DOTALL).strip()

    if not label:
        label = source[:60]

    tags = tags or []
    signals = signals or []

    # Dedupe by (domain + normalized source). If already present, return existing
    # without appending (prevents duplicates from repeated capture loops).
    item_id = _hash_id(d, (source or '').strip().lower()[:180])

    path = _file(d)
    if path.exists():
        try:
            for line in reversed(path.read_text(encoding="utf-8").splitlines()[-800:]):
                try:
                    existing = json.loads(line)
                except Exception:
                    continue
                if existing.get("item_id") == item_id:
                    return TasteItem(
                        item_id=existing.get("item_id"),
                        created_at=float(existing.get("created_at") or time.time()),
                        domain=str(existing.get("domain") or d),
                        label=str(existing.get("label") or label),
                        source=str(existing.get("source") or source),
                        notes=str(existing.get("notes") or notes),
                        tags=list(existing.get("tags") or []),
                        signals=list(existing.get("signals") or []),
                        scope=str(existing.get("scope") or scope),
                        project_key=existing.get("project_key"),
                    )
        except Exception:
            pass

    item = TasteItem(
        item_id=item_id,
        created_at=time.time(),
        domain=d,
        label=label,
        source=source,
        notes=notes,
        tags=tags,
        signals=signals,
        scope=scope,
        project_key=project_key,
    )

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    return item


def recent(domain: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    _ensure()

    paths: List[Path] = []
    if domain:
        paths = [_file(domain)]
    else:
        paths = [TASTE_DIR / f"{d}.jsonl" for d in sorted(DOMAINS)]

    items: List[Dict[str, Any]] = []
    for p in paths:
        if not p.exists():
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line in reversed(lines[-400:]):
            try:
                items.append(json.loads(line))
            except Exception:
                continue

    items.sort(key=lambda x: float(x.get("created_at") or 0), reverse=True)
    return items[:limit]


def stats() -> Dict[str, int]:
    _ensure()
    out = {d: 0 for d in DOMAINS}
    for d in DOMAINS:
        p = TASTE_DIR / f"{d}.jsonl"
        if not p.exists():
            continue
        try:
            out[d] = sum(1 for _ in p.open("r", encoding="utf-8"))
        except Exception:
            out[d] = 0
    return out


def retrieve(domain: str, query: str, limit: int = 6) -> List[Dict[str, Any]]:
    """Lightweight keyword retrieval inside a domain."""
    q = (query or "").lower().strip()
    if not q:
        return []

    items = recent(domain=domain, limit=500)
    words = [w for w in re.split(r"\W+", q) if len(w) > 2][:10]

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for it in items:
        text = (it.get("label", "") + "\n" + it.get("source", "") + "\n" + it.get("notes", "")).lower()
        s = 0.0
        if q in text:
            s += 2.0
        for w in words:
            if w in text:
                s += 0.25
        if s > 0.25:
            scored.append((s, it))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [it for _, it in scored[:limit]]


# -------------------------
# Natural language capture
# -------------------------

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def infer_domain(text: str) -> Optional[str]:
    t = (text or "").lower()
    if "post" in t or "thread" in t or "tweet" in t or "viral" in t:
        return "social_posts"
    if "ui" in t or "website" in t or "dashboard" in t or "design" in t:
        return "ui_design"
    if "art" in t or "poster" in t or "illustration" in t or "render" in t or "graphic" in t or "graphics" in t:
        return "art"
    return None


def parse_like_message(text: str) -> Optional[Dict[str, Any]]:
    """Parse a user message into a TasteItem payload.

    Supported patterns (MVP):
    - "I like this post: <url or text>"
    - "I like this UI: <url>"
    - "I like this art/graphic: <url>"

    Also strips channel prefixes like "[Telegram ...]".

    Returns dict(domain, source, notes, label) or None.
    """

    raw = (text or "").strip()
    raw = re.sub(r"^\s*\[[^\]]+\]\s*", "", raw)
    # Also strip any trailing message_id suffix that Clawdbot may include
    raw = re.sub(r"\n?\[message_id:.*?\]\s*$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
    t = raw.lower()

    if not ("i like" in t or "i love" in t):
        return None

    # Find a URL if present
    url = None
    m = _URL_RE.search(raw)
    if m:
        url = m.group(0)

    # Domain
    domain = None
    if "post" in t or "thread" in t:
        domain = "social_posts"
    elif "ui" in t or "website" in t or "dashboard" in t:
        domain = "ui_design"
    elif "art" in t or "illustration" in t or "graphic" in t or "graphics" in t:
        domain = "art"
    else:
        domain = infer_domain(raw)

    if not domain:
        return None

    # Source is URL if present, else the remainder after ':'
    source = url
    if not source:
        parts = raw.split(":", 1)
        if len(parts) == 2:
            source = parts[1].strip()
        else:
            # fallback: whole message
            source = raw

    # Notes: if the user included 'because/for' clause
    notes = ""
    if "because" in t:
        notes = raw.split("because", 1)[1].strip()

    label = ""
    # if URL, label from lead-in
    if url:
        label = raw.split(url, 1)[0].strip().strip(":")

    return {
        "domain": domain,
        "source": source,
        "notes": notes,
        "label": label,
    }
