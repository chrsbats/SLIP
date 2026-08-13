import os
import subprocess
import sys

import pytest
from slip.slip_file import file_get
from slip.slip_datatypes import Code, GetPath, Name, Parent, Scope, Sig
from slip.slip_runtime import ScriptRunner, SLIPHost, slip_api_method


class CountingHost(SLIPHost):
    def __init__(self):
        super().__init__()
        self.count = 0

    def __getitem__(self, key):
        raise KeyError(key)

    def __setitem__(self, key, value):
        raise KeyError(key)

    def __delitem__(self, key):
        raise KeyError(key)

    @slip_api_method
    def count_load(self):
        self.count += 1


@pytest.mark.asyncio
async def test_import_file_module_caches(tmp_path):
    # Create a simple module
    mod_path = tmp_path / "math.slip"
    mod_path.write_text(
        "value: 7\n"
        "add: fn {a, b} [ a + b ]\n",
        encoding="utf-8",
    )

    src = f"""
    math1: import `file://{mod_path.as_posix()}`
    math2: import `file://{mod_path.as_posix()}`
    
    -- Shadowing check: modify math1, math2 should remain unchanged
    math1.value: 100
    
    diff: math1.value != math2.value
    same-identity: math1 = math2
    
    result: math2.add 2 3
    result
    """
    print("SOURCE")
    print(src)
    runner = ScriptRunner()
    runner.source_dir = tmp_path.as_posix()
    res = await runner.handle_script(src)
    if res.status != 'ok':
        print("\nDEBUG:", res.format_error())
        print("SIDE_EFFECTS:", res.side_effects)
    assert res.status == 'ok', f"\n{res.format_error()}\nside_effects={res.side_effects!r}"
    # Last expression returns 5 (2 + 3) from math2, which was not modified
    assert res.value == 5
    # Shadowing: math1.value was changed to 100, math2.value remains 7
    assert runner.root_scope['diff'] is True
    # Identity should be false because each import returns a new shadow scope
    assert runner.root_scope['same-identity'] is False

@pytest.mark.asyncio
async def test_file_slip_returns_code_block_not_executed(tmp_path):
    # Write a module that would assign a binding if it were executed
    mod_path = tmp_path / "mod.slip"
    mod_path.write_text(
        "ran: 1\n",
        encoding="utf-8",
    )

    src = f"""
    c: file://{mod_path.as_posix()}
    is-code: is-code? c
    is-code
    """

    runner = ScriptRunner()
    runner.source_dir = tmp_path.as_posix()
    res = await runner.handle_script(src)
    assert res.status == 'ok'
    # The file:// read of a .slip file should return a Code block (not execute it)
    assert res.value is True
    # And the module code must not have executed implicitly
    assert 'ran' not in runner.root_scope.bindings


@pytest.mark.asyncio
async def test_repeated_slip_file_reads_compile_once_and_return_isolated_code(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SLIP_CACHE_DIR", str(tmp_path / "cache"))
    path = tmp_path / "repeated.slip"
    path.write_text("value: 1\nvalue\n", encoding="utf-8")
    parser = ScriptRunner().parser
    original_parse = parser.parse
    calls = 0

    def counting_parse(source, *args, **kwargs):
        nonlocal calls
        if source == "value: 1\nvalue\n":
            calls += 1
        return original_parse(source, *args, **kwargs)

    monkeypatch.setattr(parser, "parse", counting_parse)
    first = await file_get("file://./repeated.slip", base_dir=str(tmp_path))
    second = await file_get("file://./repeated.slip", base_dir=str(tmp_path))

    assert calls == 1
    assert first is not second
    first.nodes.clear()
    assert second.nodes


@pytest.mark.asyncio
async def test_cached_slip_code_recursively_isolates_syntax_and_singletons(tmp_path):
    path = tmp_path / "syntax.slip"
    path.write_text("f: fn {x} [../x]\n", encoding="utf-8")

    first = await file_get("file://./syntax.slip", base_dir=str(tmp_path))
    second = await file_get("file://./syntax.slip", base_dir=str(tmp_path))

    first_sig = next(
        term for expression in first.nodes for term in expression
        if isinstance(term, Sig)
    )
    second_sig = next(
        term for expression in second.nodes for term in expression
        if isinstance(term, Sig)
    )
    first_path = next(
        term for expression in first.nodes for term in expression
        if isinstance(term, Code)
        for body_expression in term.nodes
        for term in body_expression
        if isinstance(term, GetPath)
    )
    second_path = next(
        term for expression in second.nodes for term in expression
        if isinstance(term, Code)
        for body_expression in term.nodes
        for term in body_expression
        if isinstance(term, GetPath)
    )

    assert first_sig.parameters[0].is_typed is False
    assert second_sig.parameters[0].is_typed is False
    assert first_path.segments[0] is Parent
    assert second_path.segments[0] is Parent
    first_sig.parameters[0].annotation = GetPath([Name("string")])
    first_path.segments[1].text = "changed"
    assert second_sig.parameters[0].is_typed is False
    assert second_path.segments[1].text == "x"


@pytest.mark.asyncio
async def test_slip_file_cache_invalidates_when_file_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("SLIP_CACHE_DIR", str(tmp_path / "cache"))
    path = tmp_path / "changing.slip"
    path.write_text("value: 1\n", encoding="utf-8")
    parser = ScriptRunner().parser
    original_parse = parser.parse
    calls = 0

    def counting_parse(source, *args, **kwargs):
        nonlocal calls
        if source.startswith("value:"):
            calls += 1
        return original_parse(source, *args, **kwargs)

    monkeypatch.setattr(parser, "parse", counting_parse)
    await file_get("file://./changing.slip", base_dir=str(tmp_path))
    path.write_text("value: 200\n", encoding="utf-8")
    updated = await file_get("file://./changing.slip", base_dir=str(tmp_path))

    assert calls == 2
    result = await ScriptRunner().evaluator._eval(updated.nodes, Scope())
    assert result == 200


@pytest.mark.asyncio
async def test_diamond_import_parses_and_executes_shared_module_once(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SLIP_CACHE_DIR", str(tmp_path / "cache"))
    leaf_source = "count-load\nvalue: 7\n"
    (tmp_path / "leaf.slip").write_text(leaf_source, encoding="utf-8")
    (tmp_path / "left.slip").write_text(
        "leaf: import `file://./leaf.slip`\nvalue: leaf.value\n",
        encoding="utf-8",
    )
    (tmp_path / "right.slip").write_text(
        "leaf: import `file://./leaf.slip`\nvalue: leaf.value\n",
        encoding="utf-8",
    )
    parser = ScriptRunner().parser
    original_parse = parser.parse
    leaf_parses = 0

    def counting_parse(source, *args, **kwargs):
        nonlocal leaf_parses
        if source == leaf_source:
            leaf_parses += 1
        return original_parse(source, *args, **kwargs)

    monkeypatch.setattr(parser, "parse", counting_parse)
    host = CountingHost()
    runner = ScriptRunner(host_object=host)
    runner.source_dir = str(tmp_path)
    result = await runner.handle_script("""
    left: import `file://./left.slip`
    right: import `file://./right.slip`
    #[left.value, right.value]
    """)

    assert result.status == "ok", result.error_message
    assert result.value == [7, 7]
    assert leaf_parses == 1
    assert host.count == 1


@pytest.mark.asyncio
async def test_direct_import_reuses_compiled_code_across_runners(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SLIP_CACHE_DIR", str(tmp_path / "cache"))
    source = "count-load\nvalue: 7\n"
    module_path = tmp_path / "shared.slip"
    module_path.write_text(source, encoding="utf-8")
    parser = ScriptRunner().parser
    original_parse = parser.parse
    parses = 0

    def counting_parse(text, *args, **kwargs):
        nonlocal parses
        if text == source:
            parses += 1
        return original_parse(text, *args, **kwargs)

    monkeypatch.setattr(parser, "parse", counting_parse)
    host = CountingHost()
    locator = f"file://{module_path.as_posix()}"

    first = ScriptRunner(host_object=host)
    first_result = await first.handle_script(f"module: import `{locator}`\nmodule.value")
    second = ScriptRunner(host_object=host)
    second_result = await second.handle_script(f"module: import `{locator}`\nmodule.value")

    assert first_result.status == "ok", first_result.error_message
    assert second_result.status == "ok", second_result.error_message
    assert first_result.value == 7
    assert second_result.value == 7
    assert parses == 1
    assert host.count == 2


@pytest.mark.asyncio
async def test_imported_modules_do_not_leak_bindings(tmp_path):
    (tmp_path / "first.slip").write_text(
        "private-value: 41\n"
        "plus-one: fn {value} [value + 1]\n",
        encoding="utf-8",
    )
    (tmp_path / "second.slip").write_text(
        "can-see-first: private-value\n"
        "value: 7\n",
        encoding="utf-8",
    )
    runner = ScriptRunner()
    runner.source_dir = str(tmp_path)

    first = await runner.handle_script("""
first: import `file://./first.slip`
first.plus-one first.private-value
""")
    second = await runner.handle_script("import `file://./second.slip`")

    assert first.status == "ok", first.error_message
    assert first.value == 42
    assert second.status == "err"
    assert "private-value" in second.error_message


@pytest.mark.asyncio
async def test_imported_overload_does_not_mutate_root_generic(tmp_path):
    (tmp_path / "overload.slip").write_text(
        "join: fn {left: `int`, right: `int`} [left + right]\n",
        encoding="utf-8",
    )
    runner = ScriptRunner()
    runner.source_dir = str(tmp_path)

    result = await runner.handle_script("""
module: import `file://./overload.slip`
#[module.join 2 3, join #['a', 'b'] ',']
""")

    assert result.status == "ok", result.error_message
    assert result.value == [5, "a,b"]


def test_persistent_compiled_cache_bypasses_parser_in_new_process(tmp_path):
    module_path = tmp_path / "persistent.slip"
    module_path.write_text("value: 7\n", encoding="utf-8")
    cache_dir = tmp_path / "cache"
    environment = {
        **os.environ,
        "SLIP_CACHE_DIR": str(cache_dir),
    }
    populate = (
        "import asyncio; "
        "from slip.slip_file import file_get; "
        f"asyncio.run(file_get('file://{module_path.as_posix()}'))"
    )
    use_without_parser = (
        "import asyncio; "
        "from koine import Parser; "
        "Parser.from_file = classmethod(lambda cls, path: "
        "(_ for _ in ()).throw(AssertionError('parser constructed'))); "
        "from slip.slip_file import file_get; "
        f"code = asyncio.run(file_get('file://{module_path.as_posix()}')); "
        "assert code.nodes"
    )

    subprocess.run(
        [sys.executable, "-c", populate],
        check=True,
        cwd=tmp_path,
        env=environment,
    )
    subprocess.run(
        [sys.executable, "-c", use_without_parser],
        check=True,
        cwd=tmp_path,
        env=environment,
    )


def test_corrupt_persistent_cache_falls_back_to_parser(tmp_path):
    module_path = tmp_path / "corrupt.slip"
    module_path.write_text("value: 7\n", encoding="utf-8")
    cache_dir = tmp_path / "cache"
    environment = {
        **os.environ,
        "SLIP_CACHE_DIR": str(cache_dir),
    }
    populate = (
        "import asyncio; "
        "from slip.slip_file import file_get; "
        f"asyncio.run(file_get('file://{module_path.as_posix()}'))"
    )
    subprocess.run(
        [sys.executable, "-c", populate],
        check=True,
        cwd=tmp_path,
        env=environment,
    )
    artifact = next(cache_dir.rglob("*.pickle"))
    artifact.write_bytes(b"not a pickle")

    subprocess.run(
        [sys.executable, "-c", populate],
        check=True,
        cwd=tmp_path,
        env=environment,
    )
    assert artifact.read_bytes() != b"not a pickle"


def test_persistent_cache_reuses_content_across_paths_and_cleans_old_artifact(
    tmp_path,
):
    first_path = tmp_path / "first" / "module.slip"
    second_path = tmp_path / "second" / "module.slip"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    first_path.write_text("value: 1\n", encoding="utf-8")
    second_path.write_text("value: 1\n", encoding="utf-8")
    cache_dir = tmp_path / "cache"
    environment = {
        **os.environ,
        "SLIP_CACHE_DIR": str(cache_dir),
    }

    def load_module(module_path, *, disable_parser=False):
        parser_guard = (
            "from koine import Parser; "
            "Parser.from_file = classmethod(lambda cls, path: "
            "(_ for _ in ()).throw(AssertionError('parser constructed'))); "
            if disable_parser else ""
        )
        source = (
            "import asyncio; " + parser_guard +
            "from slip.slip_file import file_get; "
            f"asyncio.run(file_get('file://{module_path.as_posix()}'))"
        )
        subprocess.run(
            [sys.executable, "-c", source],
            check=True,
            cwd=tmp_path,
            env=environment,
        )

    load_module(first_path)
    load_module(second_path, disable_parser=True)
    artifacts = list((cache_dir / "transformed" / "artifacts").glob("*.pickle"))
    assert len(artifacts) == 1
    shared_artifact = artifacts[0]
    indexes = list((cache_dir / "transformed" / "paths").glob("*.index"))
    assert len(indexes) == 2
    assert {index.read_text() for index in indexes} == {shared_artifact.stem}

    first_path.write_text("value: 200\n", encoding="utf-8")
    load_module(first_path)
    artifacts = list((cache_dir / "transformed" / "artifacts").glob("*.pickle"))
    assert len(artifacts) == 2
    assert shared_artifact.exists()

    second_path.write_text("value: 200\n", encoding="utf-8")
    load_module(second_path, disable_parser=True)
    artifacts = list((cache_dir / "transformed" / "artifacts").glob("*.pickle"))
    assert len(artifacts) == 1
    assert not shared_artifact.exists()


def test_cross_path_cache_reattaches_current_source_path(tmp_path):
    first_path = tmp_path / "first.slip"
    second_path = tmp_path / "second.slip"
    source = "value: 1\n"
    first_path.write_text(source, encoding="utf-8")
    second_path.write_text(source, encoding="utf-8")
    cache_dir = tmp_path / "cache"
    environment = {**os.environ, "SLIP_CACHE_DIR": str(cache_dir)}
    populate = (
        "import asyncio; from slip.slip_file import file_get; "
        f"asyncio.run(file_get('file://{first_path.as_posix()}'))"
    )
    verify = (
        "import asyncio; from koine import Parser; "
        "Parser.from_file = classmethod(lambda cls, path: "
        "(_ for _ in ()).throw(AssertionError('parser constructed'))); "
        "from slip.slip_file import file_get; "
        f"code = asyncio.run(file_get('file://{second_path.as_posix()}')); "
        f"assert code.source_path == {str(second_path.resolve())!r}"
    )

    subprocess.run(
        [sys.executable, "-c", populate], check=True, cwd=tmp_path, env=environment
    )
    subprocess.run(
        [sys.executable, "-c", verify], check=True, cwd=tmp_path, env=environment
    )


def test_cache_removes_legacy_versioned_directories(tmp_path):
    cache_dir = tmp_path / "cache"
    legacy = cache_dir / "transformed-v2"
    legacy.mkdir(parents=True)
    (legacy / "old.pickle").write_bytes(b"old")
    module_path = tmp_path / "module.slip"
    module_path.write_text("value: 1\n", encoding="utf-8")
    environment = {**os.environ, "SLIP_CACHE_DIR": str(cache_dir)}
    source = (
        "import asyncio; from slip.slip_file import file_get; "
        f"asyncio.run(file_get('file://{module_path.as_posix()}'))"
    )

    subprocess.run(
        [sys.executable, "-c", source], check=True, cwd=tmp_path, env=environment
    )

    assert not legacy.exists()
    assert (cache_dir / "transformed").is_dir()


def test_concurrent_processes_compile_shared_content_once(tmp_path):
    first_path = tmp_path / "first.slip"
    second_path = tmp_path / "second.slip"
    source = "\n".join(f"value-{index}: {index}" for index in range(500))
    first_path.write_text(source, encoding="utf-8")
    second_path.write_text(source, encoding="utf-8")
    cache_dir = tmp_path / "cache"
    environment = {
        **os.environ,
        "SLIP_CACHE_DIR": str(cache_dir),
    }

    def command(path):
        return [
            sys.executable,
            "-c",
            (
                "import asyncio; from slip.slip_file import file_get, cache_stats; "
                f"asyncio.run(file_get('file://{path.as_posix()}')); "
                "print(cache_stats()['parses'])"
            ),
        ]

    first = subprocess.Popen(
        command(first_path),
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        text=True,
    )
    second = subprocess.Popen(
        command(second_path),
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        text=True,
    )
    first_output, _ = first.communicate(timeout=30)
    second_output, _ = second.communicate(timeout=30)

    assert first.returncode == 0
    assert second.returncode == 0
    assert sorted([int(first_output), int(second_output)]) == [0, 1]


@pytest.mark.asyncio
async def test_circular_import_fails_explicitly(tmp_path):
    (tmp_path / "a.slip").write_text(
        "b: import `file://./b.slip`\n",
        encoding="utf-8",
    )
    (tmp_path / "b.slip").write_text(
        "a: import `file://./a.slip`\n",
        encoding="utf-8",
    )
    runner = ScriptRunner()
    runner.source_dir = str(tmp_path)

    result = await runner.handle_script("import `file://./a.slip`")

    assert result.status == "err"
    assert "circular import" in result.error_message

@pytest.mark.asyncio
async def test_call_allows_assignment_from_path_literal():
    src = """
    x: `y:`
    (call x) 2
    y
    """
    runner = ScriptRunner()
    res = await runner.handle_script(src)
    assert res.status == 'ok'
    assert res.value == 2
