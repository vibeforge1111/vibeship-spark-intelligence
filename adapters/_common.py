"""Shared adapter utilities."""

import os
from pathlib import Path
from urllib.parse import urlparse

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TOKEN_FILE = Path.home() / ".spark" / "sparkd.token"
DEFAULT_SPARKD = (
    os.environ.get("SPARKD_URL")
    or f"http://127.0.0.1:{os.environ.get('SPARKD_PORT', '8787')}"
)


def resolve_token(cli_token: str | None) -> str | None:
    """Resolve sparkd auth token from CLI arg, env var, or file."""
    if cli_token:
        return cli_token
    env_token = os.environ.get("SPARKD_TOKEN")
    if env_token:
        return env_token
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return token or None


def normalize_sparkd_base_url(raw_url: str, *, allow_remote: bool = False) -> str:
    """Validate and normalize the sparkd base URL.

    By default only localhost URLs are accepted. Pass allow_remote=True
    (or the CLI --allow-remote flag) to permit remote hosts.
    """
    text = str(raw_url or "").strip()
    if not text:
        raise ValueError("missing sparkd URL")
    if "://" not in text:
        text = f"http://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("sparkd URL must use http/https")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("sparkd URL must include host")
    if not allow_remote and host not in _LOCAL_HOSTS:
        raise ValueError(
            "remote sparkd host blocked by default; pass --allow-remote to override"
        )
    return text.rstrip("/")
