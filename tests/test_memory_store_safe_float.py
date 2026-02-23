"""Regression tests for memory_store._safe_float exception specificity.

Before the fix, _safe_float caught bare `except Exception`, which would mask
AttributeError and other programming bugs. Narrowed to (ValueError, TypeError).
"""
from __future__ import annotations

import lib.memory_store as ms


def test_safe_float_returns_float_for_numeric_string():
    assert ms._safe_float("1.5", 0.0) == 1.5


def test_safe_float_returns_default_for_non_numeric_string():
    assert ms._safe_float("bad", 0.5) == 0.5


def test_safe_float_returns_default_for_none():
    # float(None) raises TypeError — must return default
    assert ms._safe_float(None, 0.9) == 0.9


def test_safe_float_returns_default_for_empty_string():
    assert ms._safe_float("", 0.3) == 0.3
