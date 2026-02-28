import re
from pathlib import Path


_DEFAULT_RE = re.compile(
    r'^if "%([A-Z0-9_]+)%"=="" set ([A-Z0-9_]+)=(.+)$',
    re.IGNORECASE,
)


def _extract_contract_defaults() -> dict[str, str]:
    path = Path("start_spark.bat")
    defaults: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        match = _DEFAULT_RE.match(line)
        if not match:
            continue
        check_var, set_var, value = match.groups()
        assert check_var == set_var
        defaults[set_var] = value.strip()
    return defaults


def test_start_spark_defaults_are_alpha_contract_only():
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
