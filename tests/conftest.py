from pathlib import Path

import pytest


@pytest.fixture
def spark_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an isolated HOME/USERPROFILE with a writable ~/.spark directory."""
    home = tmp_path / "home"
    spark_dir = home / ".spark"
    spark_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


@pytest.fixture
def spark_dir(spark_home: Path) -> Path:
    return spark_home / ".spark"
