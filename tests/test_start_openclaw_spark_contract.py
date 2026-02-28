import re
from pathlib import Path


_DEFAULT_RE = re.compile(r'^Set-DefaultEnv\s+"([A-Z0-9_]+)"\s+"([^"]+)"$', re.IGNORECASE)


def _extract_contract_defaults() -> dict[str, str]:
    path = Path("scripts/start_openclaw_spark.ps1")
    defaults: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        match = _DEFAULT_RE.match(line)
        if not match:
            continue
        key, value = match.groups()
        defaults[key] = value
    return defaults


def test_start_openclaw_defaults_are_alpha_contract_only():
    defaults = _extract_contract_defaults()
    assert defaults == {
        "SPARK_ADVISORY_ROUTE": "alpha",
        "SPARK_ADVISORY_ALPHA_ENABLED": "1",
        "SPARK_MEMORY_SPINE_CANONICAL": "1",
        "SPARK_VALIDATE_AND_STORE": "1",
        "SPARK_BRIDGE_LLM_ADVISORY_SIDECAR_ENABLED": "0",
        "SPARK_BRIDGE_LLM_EIDOS_SIDECAR_ENABLED": "0",
        "SPARK_EMBED_BACKEND": "auto",
    }
