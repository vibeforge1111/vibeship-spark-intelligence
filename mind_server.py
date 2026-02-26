#!/usr/bin/env python3
"""Mind Lite+ (minimal) server for Spark

This is a lightweight, dependency-free implementation of the Mind API expected by
Spark's MindBridge.

Endpoints:
  GET  /health
  POST /v1/memories/          (create memory)
  POST /v1/memories/retrieve  (simple keyword retrieval)

Storage:
  SQLite at ~/.mind/lite/memories.db (shared with Mind Lite)

Note: Retrieval is intentionally simple (keyword scoring) to keep this
server zero-dependency. We can upgrade to embeddings later.
"""

import json
import hmac
import os
import re
import secrets
import sqlite3
import uuid
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from lib.ports import MIND_PORT

PORT = MIND_PORT
DB_PATH = Path.home() / ".mind" / "lite" / "memories.db"
TOKEN_FILE = Path.home() / ".spark" / "mind_server.token"
_ALLOWED_POST_HOSTS = {
    f"127.0.0.1:{PORT}",
    f"localhost:{PORT}",
    f"[::1]:{PORT}",
}
TOKEN = os.environ.get("MIND_TOKEN")
MAX_BODY_BYTES = int(os.environ.get("MIND_MAX_BODY_BYTES", "262144"))
MAX_CONTENT_CHARS = int(os.environ.get("MIND_MAX_CONTENT_CHARS", "4000"))
MAX_QUERY_CHARS = int(os.environ.get("MIND_MAX_QUERY_CHARS", "1000"))
_FTS_AVAILABLE = None
_FTS_SCHEMA = None  # legacy | extended
_FTS_TRIGGERS = None
_RRF_K = 60
_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _read_token_file(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return raw if raw else None
    except Exception:
        return None


def _resolve_token() -> str:
    if env_token := os.environ.get("MIND_TOKEN"):
        return env_token.strip()

    existing = _read_token_file(TOKEN_FILE)
    if existing:
        return existing

    generated = secrets.token_urlsafe(24)
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(str(TOKEN_FILE), flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(generated)
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except Exception:
            pass
    except Exception:
        pass
    return generated


def _normalize_origin(raw: str) -> str | None:
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.netloc:
        return parsed.netloc
    return None


def _is_allowed_origin(headers) -> bool:
    if headers is None:
        return False
    for header_name in ("Origin", "Referer"):
        raw = headers.get(header_name)
        if not raw:
            continue
        normalized = _normalize_origin(raw)
        if normalized is None:
            return False
        if normalized in _ALLOWED_POST_HOSTS:
            return True
        return False
    host = (headers.get("Host") or "").strip()
    return host in _ALLOWED_POST_HOSTS


def _is_csrf_safe(headers) -> bool:
    fetch_site = (headers.get("Sec-Fetch-Site") or "").strip().lower() if headers is not None else ""
    if not fetch_site:
        return True
    return fetch_site in {"same-origin", "same-site", "none"}


def _is_authorized(headers) -> bool:
    token = (headers.get("Authorization") or "").strip() if headers is not None else ""
    return hmac.compare_digest(token, f"Bearer {TOKEN}")


TOKEN = _resolve_token()


def _ensure_db(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
          memory_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          content TEXT NOT NULL,
          content_type TEXT,
          temporal_level INTEGER,
          salience REAL,
          created_at TEXT NOT NULL
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);")
    _ensure_fts(conn)
    conn.commit()


def _tokenize(q: str):
    return [t for t in (q or "").lower().replace("\n", " ").split() if t]


def _score(content: str, tokens):
    if not tokens:
        return 0
    c = (content or "").lower()
    return sum(c.count(t) for t in tokens)


def _safe_sql_identifier(name: str) -> str | None:
    ident = str(name or "").strip()
    if not ident:
        return None
    if _SQL_IDENTIFIER_RE.fullmatch(ident) is None:
        return None
    return ident


def _ensure_fts(conn: sqlite3.Connection) -> bool:
    global _FTS_AVAILABLE, _FTS_SCHEMA, _FTS_TRIGGERS
    if _FTS_AVAILABLE is False:
        return False
    if _FTS_AVAILABLE is True:
        return True
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(content);
            """
        )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(memories_fts)").fetchall()]
        if "memory_id" in cols and "user_id" in cols:
            _FTS_SCHEMA = "extended"
        else:
            _FTS_SCHEMA = "legacy"
        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='memories'"
        ).fetchall()
        if triggers:
            for name, in triggers:
                safe_name = _safe_sql_identifier(name)
                if not safe_name:
                    continue
                try:
                    conn.execute(f'DROP TRIGGER IF EXISTS "{safe_name}"')
                except Exception:
                    pass
            _FTS_TRIGGERS = False
        else:
            _FTS_TRIGGERS = False
        # Rebuild FTS to keep search consistent when triggers are removed.
        try:
            conn.execute("DELETE FROM memories_fts")
            if _FTS_SCHEMA == "extended":
                conn.execute(
                    "INSERT INTO memories_fts (content, memory_id, user_id) SELECT content, memory_id, user_id FROM memories"
                )
            else:
                conn.execute(
                    "INSERT INTO memories_fts (rowid, content) SELECT rowid, content FROM memories"
                )
        except Exception:
            pass
        _FTS_AVAILABLE = True
    except sqlite3.OperationalError:
        _FTS_AVAILABLE = False
    return _FTS_AVAILABLE


def _normalize_scores(scores):
    if not scores:
        return {}
    max_val = max(scores.values()) if scores else 0
    if max_val <= 0:
        return {k: 0.0 for k in scores}
    return {k: v / max_val for k, v in scores.items()}


def _rrf_merge(rank_lists, k: int = _RRF_K):
    out = {}
    for ranked in rank_lists:
        for idx, mid in enumerate(ranked):
            out[mid] = out.get(mid, 0.0) + 1.0 / (k + idx + 1)
    return out


def _sanitize_fts_token(token: str) -> str:
    return "".join(ch for ch in token if ch.isalnum())


def _build_fts_query(tokens):
    terms = [_sanitize_fts_token(t) for t in tokens]
    terms = [t for t in terms if t]
    if not terms:
        return ""
    return " OR ".join(terms)


def _sanitize_text(value: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.encode("utf-8", errors="replace").decode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _text(self, code: int, body: str):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        # quiet
        return

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._text(200, "ok")
        if path == "/v1/stats":
            return self._get_stats()
        if path == "/":
            return self._json(200, {
                "service": "Mind Lite+",
                "version": "1.0.0",
                "status": "running"
            })
        return self._text(404, "not found")

    def _get_stats(self):
        conn = self._db()
        try:
            row = conn.execute("SELECT COUNT(*) as total FROM memories").fetchone()
            total = row["total"] if row else 0
            users = conn.execute("SELECT COUNT(DISTINCT user_id) as users FROM memories").fetchone()
            user_count = users["users"] if users else 0
        finally:
            conn.close()
        return self._json(200, {
            "total_memories": total,
            "total": total,
            "count": total,
            "total_learnings": total,
            "users": user_count,
            "status": "healthy"
        })

    def do_POST(self):
        path = urlparse(self.path).path

        # Safety: only accept POSTs from localhost by default.
        remote = str(self.client_address[0]) if getattr(self, 'client_address', None) else ''
        allow_remote = (os.environ.get('MIND_ALLOW_REMOTE_POST') or '').strip().lower() in {'1','true','yes','on'}
        if not allow_remote and remote not in {'127.0.0.1', '::1'}:
            return self._json(403, {'error': 'remote_post_forbidden'})

        if not _is_allowed_origin(self.headers):
            return self._json(403, {'error': 'origin_not_allowed'})

        if not _is_csrf_safe(self.headers):
            return self._json(403, {'error': 'cross-site post blocked'})

        if not _is_authorized(self.headers):
            return self._json(401, {"error": "unauthorized"})

        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_BODY_BYTES:
            return self._json(413, {"error": "payload_too_large"})
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            return self._json(400, {"error": "invalid_json"})

        if path == "/v1/memories/":
            return self._create_memory(data)
        if path == "/v1/memories/retrieve":
            return self._retrieve(data)

        return self._text(404, "not found")

    def _db(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        _ensure_db(conn)
        return conn

    def _create_memory(self, data):
        user_id = data.get("user_id")
        content = _sanitize_text(data.get("content"))
        if not user_id or not content:
            return self._json(400, {"error": "missing_user_id_or_content"})
        if len(str(content)) > MAX_CONTENT_CHARS:
            return self._json(413, {"error": "content_too_large"})

        memory_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat() + "Z"

        content_type = data.get("content_type")
        temporal_level = data.get("temporal_level")
        salience = data.get("salience")
        try:
            if temporal_level is not None:
                temporal_level = max(1, min(4, int(temporal_level)))
        except Exception:
            temporal_level = None
        try:
            if salience is not None:
                salience = max(0.0, min(1.0, float(salience)))
        except Exception:
            salience = None

        conn = self._db()
        try:
            conn.execute(
                "INSERT INTO memories (memory_id, user_id, content, content_type, temporal_level, salience, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (memory_id, user_id, content, content_type, temporal_level, salience, created_at),
            )
            if _ensure_fts(conn) and not _FTS_TRIGGERS:
                if _FTS_SCHEMA == "extended":
                    conn.execute(
                        "INSERT INTO memories_fts (content, memory_id, user_id) VALUES (?, ?, ?)",
                        (content, memory_id, user_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO memories_fts (rowid, content) VALUES (?, ?)",
                        (conn.execute("SELECT last_insert_rowid()").fetchone()[0], content),
                    )
            conn.commit()
        finally:
            conn.close()

        return self._json(201, {"memory_id": memory_id})

    def _retrieve(self, data):
        user_id = data.get("user_id")
        query = _sanitize_text(data.get("query", ""))
        limit = int(data.get("limit") or 5)
        limit = max(1, min(limit, 50))

        if not user_id:
            return self._json(400, {"error": "missing_user_id"})

        query = str(query)[:MAX_QUERY_CHARS]
        tokens = _tokenize(query)
        fts_query = _build_fts_query(tokens)

        conn = self._db()
        try:
            rows = conn.execute(
                "SELECT rowid as rid, memory_id, user_id, content, content_type, temporal_level, salience, created_at FROM memories WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            fts_rows = []
            if fts_query and _ensure_fts(conn):
                if _FTS_SCHEMA == "extended":
                    fts_rows = conn.execute(
                        """
                        SELECT memory_id, bm25(memories_fts) AS bm25
                        FROM memories_fts
                        WHERE memories_fts MATCH ? AND user_id = ?
                        ORDER BY bm25
                        LIMIT ?
                        """,
                        (fts_query, user_id, max(limit * 5, 20)),
                    ).fetchall()
                else:
                    fts_rows = conn.execute(
                        """
                        SELECT rowid, bm25(memories_fts) AS bm25
                        FROM memories_fts
                        WHERE memories_fts MATCH ?
                        ORDER BY bm25
                        LIMIT ?
                        """,
                        (fts_query, max(limit * 5, 20)),
                    ).fetchall()
        finally:
            conn.close()

        row_by_id = {r["memory_id"]: r for r in rows}
        row_by_rid = {r["rid"]: r for r in rows}
        legacy_scores = {}
        for r in rows:
            s = _score(r["content"], tokens)
            if tokens and s == 0:
                continue
            # small boost for salience
            sal = r["salience"] if r["salience"] is not None else 0.5
            legacy_scores[r["memory_id"]] = s + (sal * 0.1)

        fts_scores = {}
        for r in fts_rows:
            if _FTS_SCHEMA == "extended":
                mid = r["memory_id"]
                bm = r["bm25"]
            else:
                rid = r["rowid"]
                row = row_by_rid.get(rid)
                if not row:
                    continue
                mid = row["memory_id"]
                bm = r["bm25"]
            if bm is None:
                continue
            fts_scores[mid] = 1.0 / (1.0 + float(bm))

        if fts_scores:
            legacy_ranked = sorted(
                legacy_scores.items(), key=lambda x: x[1], reverse=True
            )[: max(limit * 5, 20)]
            fts_ranked = sorted(
                fts_scores.items(), key=lambda x: x[1], reverse=True
            )[: max(limit * 5, 20)]

            rrf_scores = _rrf_merge(
                [
                    [mid for mid, _ in legacy_ranked],
                    [mid for mid, _ in fts_ranked],
                ]
            )
            legacy_norm = _normalize_scores(legacy_scores)
            fts_norm = _normalize_scores(fts_scores)

            fused = {}
            for mid in set(list(legacy_scores.keys()) + list(fts_scores.keys())):
                fused[mid] = (
                    rrf_scores.get(mid, 0.0)
                    + (0.2 * legacy_norm.get(mid, 0.0))
                    + (0.2 * fts_norm.get(mid, 0.0))
                )

            scored = sorted(fused.items(), key=lambda x: x[1], reverse=True)
            top = [
                {
                    "memory_id": row_by_id[mid]["memory_id"],
                    "content": row_by_id[mid]["content"],
                    "content_type": row_by_id[mid]["content_type"],
                    "temporal_level": row_by_id[mid]["temporal_level"],
                    "salience": row_by_id[mid]["salience"],
                    "created_at": row_by_id[mid]["created_at"],
                    "score": float(score),
                }
                for mid, score in scored[:limit]
                if mid in row_by_id
            ]
            return self._json(200, {"memories": top})

        scored = sorted(legacy_scores.items(), key=lambda x: x[1], reverse=True)
        top = [
            {
                "memory_id": row_by_id[mid]["memory_id"],
                "content": row_by_id[mid]["content"],
                "content_type": row_by_id[mid]["content_type"],
                "temporal_level": row_by_id[mid]["temporal_level"],
                "salience": row_by_id[mid]["salience"],
                "created_at": row_by_id[mid]["created_at"],
                "score": float(score),
            }
            for mid, score in scored[:limit]
            if mid in row_by_id
        ]

        return self._json(200, {"memories": top})


def main():
    print(f"Mind Lite+ listening on http://127.0.0.1:{PORT}")
    print(f"DB: {DB_PATH}")
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
