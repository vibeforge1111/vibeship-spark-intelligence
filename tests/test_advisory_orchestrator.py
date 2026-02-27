import lib.advisory_engine_alpha as alpha_engine


def test_alpha_runtime_entrypoints_exist():
    assert callable(alpha_engine.on_pre_tool)
    assert callable(alpha_engine.on_post_tool)
    assert callable(alpha_engine.on_user_prompt)


def test_alpha_runtime_exports_expected_hooks():
    assert hasattr(alpha_engine, "on_pre_tool")
    assert hasattr(alpha_engine, "on_post_tool")
    assert hasattr(alpha_engine, "on_user_prompt")
