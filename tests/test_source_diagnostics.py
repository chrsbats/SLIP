from slip import ScriptRunner


def test_runtime_error_reports_source_call_chain_and_one_stderr():
    with ScriptRunner() as runner:
        source = "boom: fn {x} [x |div 0]\nouter: fn {x} [boom x]\nouter 7"
        result = runner.handle_script(source)
        assert result.status == "err"
        assert "ZeroDivisionError" in result.error_message
        assert "in line 1" in result.error_message
        assert "boom: fn {x} [x |div 0]" in result.error_message
        assert "^" in result.error_message
        assert "SLIP stacktrace:" in result.error_message
        assert [entry["text"] for entry in result.error["trace"]] == [
            "x", "boom", "outer",
        ]
        assert result.side_effects == [
            {"topics": ["stderr"], "message": result.error_message},
        ]


def test_captured_native_error_token_is_body_location():
    with ScriptRunner() as runner:
        result = runner.handle_script("f: fn {} [\ncore-div 1 0\n]\nf")
        assert result.status == "err"
        assert result.error_token["line"] == 2
        assert result.error_token["text"] == "core-div"


def test_imported_function_reports_module_source(tmp_path):
    path = tmp_path / "boom.slip"
    path.write_text("boom: fn {} [\ncore-div 1 0\n]")
    with ScriptRunner() as runner:
        result = runner.handle_script(
            f"module: import `file://{path}`; module.boom",
        )
        assert result.status == "err"
        assert str(path) in result.error_message
        assert result.error_token["line"] == 2


def test_parse_error_has_diagnostic_stderr_and_captured_errors_do_not():
    with ScriptRunner() as runner:
        result = runner.handle_script("x : 1")
        assert result.status == "err" and "ParseError:" in result.error_message
        assert result.side_effects == [
            {"topics": ["stderr"], "message": result.error_message},
        ]
        captured = runner.handle_script("do [core-div 1 0]")
        assert captured.status == "ok"
        assert captured.side_effects == captured.value["effects"] == []


def test_file_loaded_run_with_keeps_nested_function_source(tmp_path):
    path = tmp_path / "body.slip"
    path.write_text("boom: fn {} [\ncore-div 1 0\n]")
    with ScriptRunner() as runner:
        result = runner.handle_script(
            f"code: file://{path}; run-with code (current-scope); boom",
        )
        assert result.status == "err"
        assert str(path) in result.error_message
        assert result.error_token["line"] == 2


def test_return_reports_extra_values_and_dispatch_reports_candidates():
    with ScriptRunner() as runner:
        result = runner.handle_script("f: fn {} [return 1 = 1]; f")
        assert result.status == "err"
        assert "return takes at most one value" in result.error_message
        assert "wrap complex return expressions in parentheses" \
            in result.error_message
        dispatch = runner.handle_script("f: fn {x: int} [x]; f 'wrong'")
        assert dispatch.status == "err"
        assert "args: (string)" in dispatch.error_message
        assert "candidates:" in dispatch.error_message
