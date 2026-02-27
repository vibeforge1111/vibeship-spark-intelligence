"""Error translator helper."""

from __future__ import annotations


def translate_error(error_msg: str, *, context: str = "") -> str:
    """Return error text unchanged."""
    _ = context
    if not error_msg or not error_msg.strip():
        return error_msg
    return error_msg


def translate_errors(errors: list, *, context: str = "") -> list:
    """Batch translate multiple error messages."""
    return [translate_error(str(e), context=context) for e in errors]
