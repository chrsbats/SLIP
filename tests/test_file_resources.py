import pytest
from safer_yaml import load

from slip import ScriptRunner
from slip.slip_core import Code, Path as SlipPath
from slip.slip_syntax import parse


def test_uri_paths_keep_write_suffix_queries_and_metadata_structural():
    write = parse("file://out.json: 7")[0][0]
    assert isinstance(write, SlipPath) and write.mode == "set"
    assert write.keys == ["file://out.json"]
    query = parse("file://players.json[0].name")
    assert len(query[0]) == 1
    assert query[0][0].keys[-1] == "name"
    configured = parse("file://out.txt#(content-type: 'application/json'): 7")
    assert configured[0][0].mode == "set"
    assert isinstance(configured[0][0].options, Code)
    separate = parse("file://data.slip [1]")
    assert len(separate[0]) == 2


def test_quoted_url_keys_remain_data(tmp_path):
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        result = runner.handle_script("""
            data: #{'file://not-a-write.json': 7}
            data['file://not-a-write.json']
        """)
        assert result.status == "ok", result.error_message
        assert result.value == 7
        assert not (tmp_path / "not-a-write.json").exists()


@pytest.mark.parametrize("extension", ["json", "yaml", "yml", "toml"])
def test_structured_file_round_trip(tmp_path, extension):
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        result = runner.handle_script(f"""
            data: #{{name: 'on', enabled: false, numbers: #[1, 2]}}
            file://nested/data.{extension}: data
            file://nested/data.{extension}
        """)
        assert result.status == "ok", result.error_message
        assert result.value == {"name": "on", "enabled": False,
                                "numbers": [1, 2]}
        if extension in ("yaml", "yml"):
            assert load(tmp_path / f"nested/data.{extension}") == result.value


def test_file_queries_handles_metadata_and_deletion(tmp_path):
    (tmp_path / "players.json").write_text(
        '[{"name": "A", "hp": 10}, {"name": "B", "hp": 90}]',
    )
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        result = runner.handle_script("""
            file://out.txt#(content-type: 'application/json'): #{answer: 42}
            handle: resource `file://copy.json`
            put handle #{answer: 7}
            #[file://players.json[0].name,
              file://players.json[.hp < 50].name,
              get handle, file://out.txt]
        """)
        assert result.status == "ok", result.error_message
        assert result.value[:3] == ["A", ["A"], {"answer": 7}]
        assert '"answer"' in result.value[3]
        deleted = runner.handle_script("del handle; ~file://out.txt")
        assert deleted.status == "ok", deleted.error_message
        assert not (tmp_path / "copy.json").exists()
        assert not (tmp_path / "out.txt").exists()


def test_text_bytes_directory_and_missing_files(tmp_path):
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        runner.root_scope["payload"] = b"\x00\xff"
        result = runner.handle_script("""
            file://message.txt: 'hello'
            file://data.bin: payload
            #[file://message.txt, file://]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [
            "hello", {"message.txt": b"hello", "data.bin": b"\x00\xff"},
        ]
        missing = runner.handle_script("file://missing.txt")
        assert missing.status == "err"
        assert "missing.txt" in missing.error_message
        directory = runner.handle_script("~file://")
        assert directory.status == "err"


def test_home_and_parent_file_locators(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    (home / 'home.txt').write_text('from home')
    base = tmp_path / 'base'
    base.mkdir()
    child = base / 'child'
    child.mkdir()
    (base / 'parent.txt').write_text('from parent')
    monkeypatch.setenv('HOME', str(home))
    with ScriptRunner(background_io=False) as runner:
        runner.source_dir = str(child)
        result = runner.handle_script(
            '#[file://~/home.txt, file://../parent.txt, file://~]',
        )
        assert result.status == 'ok', result.error_message
        assert result.value == [
            'from home', 'from parent', {'home.txt': b'from home'},
        ]


def test_slip_read_is_unbound_code_and_code_import_is_isolated(tmp_path):
    (tmp_path / "module.slip").write_text("value: 7\n")
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        result = runner.handle_script("file://module.slip")
        assert result.status == "ok", result.error_message
        assert isinstance(result.value, Code) and result.value.stacks is None
        assert "value" not in runner.scope
        imported = runner.handle_script("""
            code: file://module.slip
            a: import code
            b: import code
            a.value: 100
            #[a.value, b.value, a = b]
        """)
        assert imported.status == "ok", imported.error_message
        assert imported.value == [100, 7, False]


def test_module_calls_and_definitions_follow_source_order(tmp_path):
    (tmp_path / "ordered.slip").write_text("""
        first: 1 + 2
        f: fn {x} [x + 1]
        /+: |core-sub
        second: 1 + 2
        g: fn {x} [x + 1]
    """)
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        result = runner.handle_script("""
            module: import `file://ordered.slip`
            #[module.first, module.second, module.f 10, module.g 10]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [3, -1, 11, 9]


def test_imported_functions_keep_their_source_directory(tmp_path):
    module_dir = tmp_path / "modules"
    module_dir.mkdir()
    (module_dir / "data.json").write_text('{"answer": 42}')
    (module_dir / "math.slip").write_text("add: fn {a, b} [a + b]\n")
    (module_dir / "world.slip").write_text("""
        math: import `file://math.slip`
        read: fn {} [file://data.json]
        sandbox: fn {} [run [file://data.json]]
        configured: fn {} [
            target: scope #{}
            run-with [answer: file://data.json] target
            target.answer
        ]
        add: core-function `math.add`
    """)
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        loaded = runner.handle_script(
            "world: import `file://modules/world.slip`",
        )
        assert loaded.status == "ok", loaded.error_message
        result = runner.handle_script("""
            #[world.add 2 3, world.read, world.sandbox, world.configured]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [
            5, {"answer": 42}, {"answer": 42}, {"answer": 42},
        ]


def test_diamond_imports_share_execution_and_isolate_modules(tmp_path):
    (tmp_path / "leaf.slip").write_text("count-load\nvalue: 7\n")
    for name in ("left", "right"):
        (tmp_path / f"{name}.slip").write_text(
            "leaf: import `file://leaf.slip`\nvalue: leaf.value\n",
        )
    (tmp_path / "private.slip").write_text("private-value: 42\n")
    (tmp_path / "probe.slip").write_text("value: private-value\n")
    calls = []
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        runner.root_scope["count-load"] = lambda: calls.append("load")
        result = runner.handle_script("""
            left: import `file://left.slip`
            right: import `file://right.slip`
            #[left.value, right.value]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [7, 7] and calls == ["load"]
        loaded = runner.handle_script("import `file://private.slip`")
        assert loaded.status == "ok", loaded.error_message
        failed = runner.handle_script("import `file://probe.slip`")
        assert failed.status == "err"
        assert "private-value" in failed.error_message


def test_completed_imports_share_exports_and_cycles_fail(tmp_path):
    (tmp_path / "shared.slip").write_text("count-load\nvalue: 7\n")
    (tmp_path / "a.slip").write_text("import `file://b.slip`\n")
    (tmp_path / "b.slip").write_text("import `file://a.slip`\n")
    calls = []

    def count_load():
        calls.append("load")

    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        runner.root_scope["count-load"] = count_load
        one = runner.handle_script("import `file://shared.slip`")
        two = runner.handle_script("import `file://shared.slip`")
        assert one.status == two.status == "ok", (
            one.error_message, two.error_message,
        )
        assert one.value is not two.value and calls == ["load"]
        assert one.value.parent is two.value.parent
        cached = runner.resources.modules[str(tmp_path / "shared.slip")][1]
        assert cached is one.value.parent
        failed = runner.handle_script("import `file://a.slip`")
        assert failed.status == "err"
        assert "circular import" in failed.error_message


def test_resource_metadata_values_and_read_prefix_execute_once(tmp_path):
    (tmp_path / "players.json").write_text('[{"name": "A", "hp": 10}]')
    calls = []
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)

        def content_type():
            calls.append("options")
            return "application/json"

        def payload():
            calls.append("value")
            return {"answer": 42}

        original_get = runner.root_scope["get"]

        def counted_get(target, options=None, *, scope):
            calls.append("read")
            return original_get(target, options, scope=scope)

        runner.root_scope["content-type"] = content_type
        runner.root_scope["payload"] = payload
        runner.root_scope["get"] = counted_get
        loaded = runner.handle_script("""
            query: fn {} [file://players.json[.hp < 50].name]
        """)
        assert loaded.status == "ok", loaded.error_message
        assert calls == []
        result = runner.handle_script("""
            file://out.txt#(content-type: (content-type)): (payload)
            query
        """)
        assert result.status == "ok", result.error_message
        assert result.value == ["A"]
        assert calls == ["options", "value", "read"]


def test_modules_share_runner_random_state_effects_and_not_other_runners(
    tmp_path,
):
    (tmp_path / "random.slip").write_text("""
        emit 'audit' 'loaded'
        draw: fn {} [random]
    """)
    with ScriptRunner() as first, ScriptRunner() as second:
        first.source_dir = second.source_dir = str(tmp_path)
        loaded = first.handle_script(
            "module: import `file://random.slip`",
        )
        assert loaded.status == "ok", loaded.error_message
        assert loaded.side_effects == [
            {"topics": ["audit"], "message": "loaded"},
        ]
        other = second.handle_script("""
            seed-random 99
            module: import `file://random.slip`
            module.draw
        """)
        assert other.status == "ok", other.error_message
        result = first.handle_script("""
            again: import `file://random.slip`
            seed-random 7
            expected: random
            seed-random 7
            module.draw = expected
        """)
        assert result.status == "ok", result.error_message
        assert result.value is True and result.side_effects == []


def test_failed_import_does_not_leave_a_failed_cache_entry(
    tmp_path,
):
    path = tmp_path / "module.slip"
    path.write_text("explode")
    failures = []

    def explode():
        failures.append("failed")
        raise ValueError("load failed")

    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        runner.root_scope["explode"] = explode
        failed = runner.handle_script("import `file://module.slip`")
        assert failed.status == "err" and "load failed" in failed.error_message
        assert failures == ["failed"] and runner.resources.modules == {}
        path.write_text("value: 7")
        retried = runner.handle_script("""
            module: import `file://./module.slip`
            module.value
        """)
        assert retried.status == "ok", retried.error_message
        assert retried.value == 7


def test_deferred_async_module_body_is_not_executed_or_cached(tmp_path):
    path = tmp_path / "module.slip"
    path.write_text("task [emit 'audit' 'must not run']; value: 7")

    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        failed = runner.handle_script("import `file://module.slip`")
        assert failed.status == "err" and "unsupported" in failed.error_message
        assert failed.side_effects == [
            {"topics": ["stderr"], "message": failed.error_message},
        ]
        assert runner.resources.modules == {}
        path.write_text("value: 7")
        retried = runner.handle_script(
            "module: import `file://module.slip`; module.value",
        )
        assert retried.status == "ok" and retried.value == 7
    with pytest.raises(RuntimeError, match="closed"):
        runner.resources.import_module(
            "file://module.slip", scope=runner.scope,
        )
