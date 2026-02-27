from pathlib import Path
import builtins

import lib.service_control as service_control
import spark_pulse


def test_start_services_uses_pulse_repo_as_cwd(monkeypatch, tmp_path):
    pulse_dir = tmp_path / "vibeship-spark-pulse"
    pulse_dir.mkdir(parents=True, exist_ok=True)
    pulse_app = pulse_dir / "app.py"
    pulse_app.write_text("print('pulse')\n", encoding="utf-8")

    monkeypatch.setattr(service_control, "SPARK_PULSE_DIR", pulse_dir)
    monkeypatch.setattr(
        service_control,
        "service_status",
        lambda bridge_stale_s=90: {
            "mind": {"running": True},
            "sparkd": {"running": True},
            "bridge_worker": {"running": True},
            "pulse": {"running": False},
        },
    )
    monkeypatch.setattr(
        service_control,
        "_service_cmds",
        lambda **kwargs: {"pulse": ["python", str(pulse_app)]},
    )

    captured = {}

    def _fake_start_process(name, args, cwd=None):
        captured["name"] = name
        captured["args"] = args
        captured["cwd"] = cwd
        return 12345

    monkeypatch.setattr(service_control, "_start_process", _fake_start_process)
    monkeypatch.setattr(service_control, "_wait_for_service_ready", lambda *a, **k: True)

    result = service_control.start_services(
        include_watchdog=False,
    )

    assert result["pulse"] == "started:12345"
    assert captured["name"] == "pulse"
    assert captured["cwd"] == pulse_dir
    assert captured["args"] == ["python", str(pulse_app)]


def test_redirector_launches_external_pulse_with_repo_cwd(monkeypatch, tmp_path):
    pulse_dir = tmp_path / "vibeship-spark-pulse"
    pulse_dir.mkdir(parents=True, exist_ok=True)
    pulse_app = pulse_dir / "app.py"
    pulse_app.write_text("print('pulse')\n", encoding="utf-8")

    monkeypatch.setattr(service_control, "SPARK_PULSE_DIR", pulse_dir)

    called = {}

    def _fake_call(args, cwd=None):
        called["args"] = args
        called["cwd"] = cwd
        return 0

    monkeypatch.setattr(spark_pulse.subprocess, "call", _fake_call)

    try:
        spark_pulse.main()
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("Expected SystemExit from spark_pulse.main()")

    assert called["args"][0] == spark_pulse.sys.executable
    assert called["args"][1] == str(pulse_app)
    assert called["cwd"] == str(pulse_dir)


def test_pulse_health_requires_api_and_ui(monkeypatch):
    calls = []

    def _fake_http_ok(url, timeout=1.5):
        calls.append(url)
        # Simulate docs healthy but UI broken.
        return "docs" in url

    monkeypatch.setattr(service_control, "_http_ok", _fake_http_ok)

    assert service_control._pulse_ok() is False
    assert service_control.PULSE_DOCS_URL in calls
    assert service_control.PULSE_UI_URL in calls


def test_resolve_pulse_dir_prefers_sibling(monkeypatch, tmp_path):
    root = tmp_path / "vibeship-spark-intelligence"
    root.mkdir(parents=True, exist_ok=True)
    sibling_pulse = tmp_path / "vibeship-spark-pulse"
    sibling_pulse.mkdir(parents=True, exist_ok=True)
    (sibling_pulse / "app.py").write_text("print('pulse')\n", encoding="utf-8")

    monkeypatch.delenv("SPARK_PULSE_DIR", raising=False)
    monkeypatch.setattr(service_control, "ROOT_DIR", root)

    resolved = service_control._resolve_pulse_dir()
    assert resolved == sibling_pulse


def test_service_status_detects_pulse_using_absolute_app_path(monkeypatch, tmp_path):
    pulse_dir = tmp_path / "custom-pulse-dir"
    pulse_dir.mkdir(parents=True, exist_ok=True)
    pulse_app = pulse_dir / "app.py"
    pulse_app.write_text("print('pulse')\n", encoding="utf-8")

    monkeypatch.setattr(service_control, "SPARK_PULSE_DIR", pulse_dir)
    monkeypatch.setattr(service_control, "_pulse_ok", lambda: False)
    monkeypatch.setattr(service_control, "_bridge_heartbeat_age", lambda: None)
    monkeypatch.setattr(service_control, "_read_pid", lambda name: None)
    monkeypatch.setattr(
        service_control,
        "_process_snapshot",
        lambda: [(32123, f'python "{pulse_app}"')],
    )

    status = service_control.service_status()
    assert status["pulse"]["running"] is True
    assert status["pulse"]["healthy"] is False


def test_service_status_detects_watchdog_wrapper_command(monkeypatch):
    monkeypatch.setattr(service_control, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr(service_control, "_pulse_ok", lambda: False)
    monkeypatch.setattr(service_control, "_bridge_heartbeat_age", lambda: None)
    monkeypatch.setattr(service_control, "_scheduler_heartbeat_age", lambda: None)
    monkeypatch.setattr(service_control, "_read_pid", lambda name: None)
    monkeypatch.setattr(
        service_control,
        "_process_snapshot",
        lambda: [(45678, "python scripts/watchdog.py --interval 60")],
    )

    status = service_control.service_status()
    assert status["watchdog"]["running"] is True


def test_service_status_detects_codex_bridge_process(monkeypatch):
    monkeypatch.setattr(service_control, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr(service_control, "_pulse_ok", lambda: False)
    monkeypatch.setattr(service_control, "_bridge_heartbeat_age", lambda: None)
    monkeypatch.setattr(service_control, "_scheduler_heartbeat_age", lambda: None)
    monkeypatch.setattr(service_control, "_codex_bridge_telemetry_age", lambda: 5.0)
    monkeypatch.setattr(service_control, "_read_pid", lambda name: None)
    monkeypatch.setattr(
        service_control,
        "_process_snapshot",
        lambda: [(56789, "python adapters/codex_hook_bridge.py --mode observe --poll 2 --max-per-tick 200")],
    )

    status = service_control.service_status()
    assert status["codex_bridge"]["running"] is True
    assert status["codex_bridge"]["process_running"] is True
    assert status["codex_bridge"]["telemetry_fresh"] is True


def test_service_cmds_includes_codex_bridge_by_default(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    bridge_script = repo_root / "adapters" / "codex_hook_bridge.py"
    bridge_script.parent.mkdir(parents=True, exist_ok=True)
    bridge_script.write_text("print('bridge')\n", encoding="utf-8")

    monkeypatch.setattr(service_control, "ROOT_DIR", repo_root)
    monkeypatch.delenv("SPARK_CODEX_BRIDGE_MODE", raising=False)
    monkeypatch.delenv("SPARK_CODEX_BRIDGE_POLL", raising=False)
    monkeypatch.delenv("SPARK_CODEX_BRIDGE_MAX_PER_TICK", raising=False)

    cmds = service_control._service_cmds(include_mind=False, include_pulse=False)
    codex = cmds.get("codex_bridge")
    assert codex is not None
    assert "--mode" in codex
    assert codex[codex.index("--mode") + 1] == "observe"
    assert codex[codex.index("--poll") + 1] == "2"
    assert codex[codex.index("--max-per-tick") + 1] == "200"


def test_load_repo_env_parses_basic_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "MINIMAX_API_KEY=abc123",
                "SPARK_MINIMAX_MODEL=MiniMax-M2.5",
                "export SPARK_OPPORTUNITY_LLM_PROVIDER=minimax",
                "QUOTED='hello world'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    out = service_control._load_repo_env(env_file)
    assert out["MINIMAX_API_KEY"] == "abc123"
    assert out["SPARK_MINIMAX_MODEL"] == "MiniMax-M2.5"
    assert out["SPARK_OPPORTUNITY_LLM_PROVIDER"] == "minimax"
    assert out["QUOTED"] == "hello world"


def test_env_for_child_includes_repo_env_without_overriding(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MINIMAX_API_KEY=from_file\nSPARK_MINIMAX_MODEL=MiniMax-M2.5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(service_control, "REPO_ENV_FILE", env_file)
    monkeypatch.setenv("MINIMAX_API_KEY", "from_env")

    env = service_control._env_for_child(tmp_path)
    assert env["MINIMAX_API_KEY"] == "from_env"
    assert env["SPARK_MINIMAX_MODEL"] == "MiniMax-M2.5"


def test_scheduler_heartbeat_age_falls_back_to_root_file(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "spark_scheduler.py").write_text(
        "def scheduler_heartbeat_age_s():\n    return 42.5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(service_control, "ROOT_DIR", root)

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "spark_scheduler":
            raise ModuleNotFoundError("forced missing module")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert service_control._scheduler_heartbeat_age() == 42.5


def test_scheduler_heartbeat_age_returns_none_when_unavailable(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(service_control, "ROOT_DIR", root)

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "spark_scheduler":
            raise ModuleNotFoundError("forced missing module")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert service_control._scheduler_heartbeat_age() is None
