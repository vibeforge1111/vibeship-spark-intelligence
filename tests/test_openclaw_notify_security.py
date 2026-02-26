from __future__ import annotations

from lib import openclaw_notify


def test_safe_gateway_port_bounds():
    assert openclaw_notify._safe_gateway_port("18789") == 18789
    assert openclaw_notify._safe_gateway_port("0") == 18789
    assert openclaw_notify._safe_gateway_port("70000") == 18789


def test_get_gateway_url_rejects_port_injection(monkeypatch):
    monkeypatch.setattr(
        openclaw_notify,
        "_read_openclaw_config",
        lambda: {"gateway": {"port": "80@evil.com", "auth": {"token": "x"}}},
    )
    assert openclaw_notify._get_gateway_url() == "http://127.0.0.1:18789"
