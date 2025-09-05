import pytest
import asyncio
import collections.abc
from unittest.mock import Mock, MagicMock

from slip.slip_runtime import SlipObject, SLIPHost, StdLib
from slip.slip_datatypes import Scope, Code
from slip.slip_runtime import ExecutionResult, ScriptRunner
from slip.slip_interpreter import Evaluator
from slip.slip_datatypes import GetPath, Name, PathLiteral, SetPath
from slip.slip_datatypes import Sig, Group
from slip.slip_datatypes import PathLiteral as PLit, GetPath as GP, Name as Nm
from slip.slip_datatypes import SlipFunction, GenericFunction
from slip.slip_datatypes import PathNotFound, Response

# --- SlipObject Tests ---

def test_slip_object_is_dict():
    obj = SlipObject()
    assert isinstance(obj, collections.abc.MutableMapping)
    obj['a'] = 1
    assert obj['a'] == 1

def test_slip_object_hashing_and_equality():
    obj1 = SlipObject()
    obj2 = SlipObject()
    obj1_alias = obj1

    assert obj1 == obj1_alias
    print("1",obj1)
    print("2",obj2)
    assert obj1 != obj2
    assert hash(obj1) == hash(obj1_alias)


    assert hash(obj1) != hash(obj2)

    # Equality with regular dicts is still value-based
    obj1['a'] = 1
    assert obj1 == {'a': 1}



# --- SLIPHost Tests ---

class ConcreteHost(SLIPHost):
    def __getitem__(self, key): pass
    def __setitem__(self, key, value): pass
    def __delitem__(self, key): pass

@pytest.mark.asyncio
async def test_slip_host_task_management():
    host = ConcreteHost()
    
    async def dummy_coro():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(dummy_coro())
    host._register_task(task)
    assert task in host.active_slip_tasks

    count = host.cancel_tasks()
    assert count == 1
    assert not host.active_slip_tasks
    await asyncio.sleep(0)  # Allow event loop to process cancellation
    assert task.cancelled()

    # Test that done callback removes task
    task2 = asyncio.create_task(dummy_coro())
    host._register_task(task2)
    await task2
    assert task2 not in host.active_slip_tasks


# --- StdLib Tests ---

@pytest.fixture
def mock_evaluator():
    evaluator = Mock()
    evaluator.side_effects = []
    evaluator.run = MagicMock()
    return evaluator

@pytest.fixture
def stdlib(mock_evaluator):
    return StdLib(mock_evaluator)

def test_stdlib_math(stdlib):
    assert stdlib._add(1, 2) == 3
    assert stdlib._mul(3, 4) == 12
    assert stdlib._eq(5, 5) is True
    assert stdlib._gt(10, 5) is True

def test_stdlib_string(stdlib):
    assert stdlib._join(['a', 'b'], '-') == "a-b"
    assert stdlib._str_replace("hello", "l", "w") == "hewwo"

def test_stdlib_list(stdlib):
    assert stdlib._slice_range([1,2,3,4], 1, 3) == [2,3]
    assert stdlib._len("abc") == 3

def test_stdlib_dict_env(stdlib):
    d = {'a': 1}
    env = Scope()
    env['b'] = 2
    
    assert stdlib._keys(d) == ['a']
    assert stdlib._values(d) == [1]
    assert stdlib._keys(env) == ['b']
    assert stdlib._values(env) == [2]

def test_stdlib_inherit(stdlib):
    parent = Scope()
    child = Scope()
    result = stdlib._inherit(child, parent)
    assert result is child
    assert child.parent is parent
    assert child.meta["parent"] is parent

@pytest.mark.asyncio
async def test_stdlib_async(stdlib):
    # Just test that it's awaitable and doesn't crash
    await stdlib._sleep(0)

def test_stdlib_emit(stdlib):
    stdlib._emit("topic", "message", "parts")
    assert len(stdlib.evaluator.side_effects) == 1
    event = stdlib.evaluator.side_effects[0]
    assert event['topics'] == ["topic"]
    assert event['message'] == "message parts"

def test_stdlib_list_constructor(stdlib, mock_evaluator):
    code = Code([1, 2])
    env = Scope()
    mock_evaluator.run.side_effect = [10, 20] # mock return values for each node
    
    result = stdlib._list(code, scope=env)
    
    assert result == [10, 20]
    assert mock_evaluator.run.call_count == 2
    mock_evaluator.run.assert_any_call(1, env)
    mock_evaluator.run.assert_any_call(2, env)

def test_stdlib_dict_constructor(stdlib, mock_evaluator):
    code = Code([('set', 'a', 1)])
    env = Scope()
    
    result = stdlib._dict(code, scope=env)
    
    assert isinstance(result, SlipObject)
    mock_evaluator.run.assert_called_once()
    # Check that it was called with a *new*, un-linked scope
    call_args = mock_evaluator.run.call_args
    assert call_args[0][0] == code.ast
    assert isinstance(call_args[0][1], Scope)
    assert call_args[0][1].parent is None

def test_stdlib_scope_constructor(stdlib):
    result = stdlib._scope({'a': 1})
    assert isinstance(result, Scope)
    assert result['a'] == 1
    with pytest.raises(ValueError):
        stdlib._scope({'meta': {}})

def test_execution_result_format_error_with_and_without_token():
    err = ExecutionResult(status='error', error_message="Boom")
    assert err.format_error() == "Boom"
    err_tok = ExecutionResult(status='error', error_message="Boom", error_token={'line': 3, 'col': 5})
    msg = err_tok.format_error()
    assert msg.startswith("Error on line 3, col 5:") and "Boom" in msg

@pytest.mark.asyncio
async def test_do_effects_view_sequence_and_slicing():
    ev = Evaluator()
    std = StdLib(ev)
    scope = Scope()
    scope['emit'] = std._emit
    code = Code([
        [GetPath([Name('emit')]), 'topic', 'one'],
        [GetPath([Name('emit')]), 'topic', 'two'],
        [42],
    ])
    out = await std._do(code, scope=scope)
    eff = out['effects']
    assert len(eff) == 2
    assert eff[0]['message'].endswith('one')
    assert list(eff[:1])[0]['message'].endswith('one')
    # iteration preserves order
    msgs = [e['message'] for e in eff]
    assert msgs == ["one", "two"]

def test_package_http_result_modes_and_header_lowercasing():
    ev = Evaluator()
    std = StdLib(ev)
    raw = (200, {'ok': True}, {'Content-Type': 'application/json', 'X-Test': 'yes'})
    # lite
    lite = std._package_http_result(raw, 'lite')
    assert lite == [200, {'ok': True}]
    # full
    full = std._package_http_result(raw, 'full')
    assert full['status'] == 200 and full['value'] == {'ok': True}
    assert full['meta']['headers'].get('content-type') == 'application/json'
    assert full['meta']['headers'].get('x-test') == 'yes'
    # default (None) returns raw tuple
    assert std._package_http_result(raw, None) == raw

def test_prepare_payload_json_and_bytes_and_headers():
    ev = Evaluator()
    std = StdLib(ev)
    # JSON content-type -> serialize and set header
    cfg = {'content-type': 'application/json'}
    payload = std._prepare_payload(cfg, {'a': 1})
    assert isinstance(payload, str) and '"a"' in payload
    assert cfg['headers']['Content-Type'] == 'application/json'
    # Bytes passthrough (no content-type)
    cfg2 = {}
    payload2 = std._prepare_payload(cfg2, b'abc')
    assert payload2 == b'abc'

@pytest.mark.asyncio
async def test_normalize_resource_variants_and_response_mode(monkeypatch):
    ev = Evaluator()
    std = StdLib(ev)
    scope = Scope()
    gp = GetPath([Name('http://example/api')])
    # meta -> lite via legacy flag
    async def fake_meta(meta, scope):
        return {'lite': True}
    ev.path_resolver._meta_to_dict = fake_meta
    gp_norm, url, cfg = await std._normalize_resource(gp, scope=scope)
    assert url == 'http://example/api'
    assert cfg.get('response-mode') == 'lite'
    # Resource wrapper + explicit string mode (case-insensitive)
    resource_scope = await std._resource(gp, scope=scope)
    async def fake_meta2(meta, scope):
        return {'response-mode': 'FULL'}
    ev.path_resolver._meta_to_dict = fake_meta2
    gp2, url2, cfg2 = await std._normalize_resource(resource_scope, scope=scope)
    assert url2 == 'http://example/api'
    assert cfg2.get('response-mode') == 'full'

def test_format_stacktrace_friendly_names():
    runner = ScriptRunner()
    ev = runner.evaluator
    # Push a frame with a StdLib function (friendly name)
    ev._push_frame('add', runner.root_scope['add'], [1, 2], GetPath([Name('add')]))
    ev._push_frame('return', None, [], None)
    s = runner._format_stacktrace()
    assert "SLIP stacktrace:" in s
    assert "(add 1 2)" in s
    assert "(return)" in s

def test_to_getpath_with_pathliteral_setpath_raises():
    ev = Evaluator()
    std = StdLib(ev)
    bad = PathLiteral(SetPath([Name('x')]))
    with pytest.raises(TypeError):
        std._to_getpath(bad)

@pytest.mark.asyncio
async def test_call_string_dynamic_set_and_delete():
    ev = Evaluator()
    std = StdLib(ev)
    scope = Scope()
    # Dynamic set-path from string
    out = await std._call("x:", [10], scope=scope)
    assert out == 10 and scope['x'] == 10
    # Dynamic del-path from string
    out2 = await std._call("~x", [], scope=scope)
    assert out2 is None
    assert 'x' not in scope.bindings

def test_to_getpath_string_variants_roundtrip():
    ev = Evaluator()
    std = StdLib(ev)
    # Dotted/slashed name splits into segments
    gp = std._to_getpath("a.b/c")
    assert isinstance(gp, GP) and [s.text for s in gp.segments] == ["a", "b", "c"]
    # Absolute/special and URLs remain a single name segment
    for s in ("/root", "../up", "./here", "http://x/y", "https://x/y", "|map", "~del"):
        gp2 = std._to_getpath(s)
        assert isinstance(gp2, GP) and len(gp2.segments) == 1 and gp2.segments[0].text == s
    # Empty is invalid
    with pytest.raises(ValueError):
        std._to_getpath("")

@pytest.mark.asyncio
async def test_resource_invalid_non_http_and_normalize_cfg(monkeypatch):
    ev = Evaluator()
    std = StdLib(ev)
    # Non-http path raises
    with pytest.raises(TypeError):
        await std._resource("file://x", scope=Scope())
    # Normalize resource on direct GP and legacy flags via meta-to-dict
    gp = GP([Nm("http://example/api")])
    async def fake_meta(meta, scope): return {"lite": True}
    ev.path_resolver._meta_to_dict = fake_meta
    gp2, url2, cfg2 = await std._normalize_resource(gp, scope=Scope())
    assert url2 == "http://example/api" and cfg2.get("response-mode") == "lite"

@pytest.mark.asyncio
async def test_import_reject_invalid_targets(monkeypatch):
    ev = Evaluator()
    std = StdLib(ev)
    scope = Scope()
    # PathLiteral(GetPath(...)) without loc should be rejected
    with pytest.raises(PathNotFound):
        await std._import(PLit(GP([Nm("http://example/mod.slip")])), scope=scope)
    # String that is not a scheme path should be rejected
    with pytest.raises(PathNotFound):
        await std._import("not-a-scheme", scope=scope)

@pytest.mark.asyncio
async def test_if_then_else_code_and_errors():
    ev = Evaluator()
    std = StdLib(ev)
    scope = Scope()
    # cond true -> then runs
    out = await std._if([Code([[True]]), Code([[1]]), Code([[2]])], scope=scope)
    assert out == 1
    # cond false -> else runs
    out2 = await std._if([Code([[False]]), Code([[1]]), Code([[2]])], scope=scope)
    assert out2 == 2
    # else omitted and cond false -> None
    out3 = await std._if([Code([[False]]), Code([[1]])], scope=scope)
    assert out3 is None
    # Non-code branch raises
    with pytest.raises(TypeError):
        await std._if([Code([[True]]), 1, 2], scope=scope)

@pytest.mark.asyncio
async def test_while_errors_and_returns_last():
    runner = ScriptRunner()
    await runner._initialize()
    std = StdLib(runner.evaluator)
    scope = Scope(parent=runner.root_scope)
    # Wrong arity
    with pytest.raises(TypeError):
        await std._while([Code([[True]])], scope=scope)
    # Non-code body error
    with pytest.raises(TypeError):
        await std._while([Code([[True]]), 1], scope=scope)
    # Returns last body value
    # i: 0; while [i < 3] [ i: i + 1; i ]
    scope["i"] = 0
    cond = Code([[GP([Nm("i")]), GP([Nm("<")]), 3]])
    body = Code([[SetPath([Nm("i")]), GP([Nm("i")]), GP([Nm("+")]), 1], [GP([Nm("i")])]])
    res = await std._while([cond, body], scope=scope)
    assert res == 3 and scope["i"] == 3

@pytest.mark.asyncio
async def test_foreach_over_mapping_and_sequence_and_errors():
    runner = ScriptRunner()
    await runner._initialize()
    std = StdLib(runner.evaluator)
    scope = Scope(parent=runner.root_scope)
    # Mapping {k}
    d = {"a": 1, "b": 2}
    seen = []
    scope["seen"] = seen
    body_keys = Code([[GP([Nm("seen")]), GP([Nm("+")]), [GP([Nm("k")])]]])
    await std._foreach([Sig(["k"], {}, None, None), d, body_keys], scope=scope)
    assert set(scope["seen"]) == {"a", "b"}
    # Mapping {k, v}
    scope["pairs"] = []
    body_pairs = Code([[GP([Nm("pairs")]), GP([Nm("+")]), [[GP([Nm("k")]), GP([Nm("v")])]]]])
    await std._foreach([Sig(["k", "v"], {}, None, None), d, body_pairs], scope=scope)
    assert sorted(scope["pairs"]) == [["a", 1], ["b", 2]]
    # Sequence {x}
    scope["sum"] = 0
    body_sum = Code([[GP([Nm("sum")]), GP([Nm("+")]), GP([Nm("x")])]])
    await std._foreach([Sig(["x"], {}, None, None), [1, 2, 3], body_sum], scope=scope)
    assert scope["sum"] == 6
    # Destructuring mismatch for pairs -> error
    with pytest.raises(TypeError):
        await std._foreach([Sig(["a", "b"], {}, None, None), [[1], [2, 3, 4]], Code([[0]])], scope=scope)

@pytest.mark.asyncio
async def test_run_is_hermetic_and_run_with_writes_and_cleans_wrappers():
    ev = Evaluator()
    std = StdLib(ev)
    scope = Scope()
    tgt = Scope()
    # run does not leak writes into caller
    code = Code([[SetPath([Nm("x")]), 1]])
    r = await std._run(code, scope=scope)
    assert r == 1 and "x" not in scope.bindings
    # run-with writes into target scope and removes temporary wrappers
    code2 = Code([[SetPath([Nm("z")]), 2]])
    out = await std._run_with(code2, tgt, scope=scope)
    assert out == 2 and tgt["z"] == 2
    assert "mixin" not in tgt.bindings  # wrapper was removed

@pytest.mark.asyncio
async def test_task_registers_with_host_and_executes():
    class Host(SLIPHost):
        def __getitem__(self, k): raise KeyError
        def __setitem__(self, k, v): pass
        def __delitem__(self, k): pass
    host = Host()
    runner = ScriptRunner(host_object=host)
    std = StdLib(runner.evaluator)
    # Simple no-op code block
    t = std._task(Code([[None]]), scope=Scope())
    assert isinstance(t, asyncio.Task)
    await t
    assert t not in host.active_slip_tasks

def test_type_conversions_and_type_of():
    ev = Evaluator()
    std = StdLib(ev)
    assert std._to_str(b"abc") == "abc"
    assert std._to_int("12") == 12 and std._to_int("x") is None
    assert std._to_float("1.5") == 1.5 and std._to_float("x") is None
    assert std._to_bool(0) is False and std._to_bool(1) is True
    # type-of mapping
    lit = std._type_of(1)
    assert isinstance(lit, PLit) and isinstance(lit.inner, GP) and lit.inner.segments[-1].text == "int"
    assert std._type_of("s").inner.segments[-1].text == "string"

@pytest.mark.asyncio
async def test_respond_and_response_emit_stderr():
    ev = Evaluator()
    std = StdLib(ev)
    out = std._respond(PLit(GP([Nm("err")])), "bad")
    # _respond returns Response(return <Response(err, 'bad')>)
    assert isinstance(out, Response) and isinstance(out.status, PLit)
    assert any("bad" in e["message"] for e in ev.side_effects if "stderr" in e["topics"])

@pytest.mark.asyncio
async def test_call_pathliteral_invocation_and_value_and_errors():
    ev = Evaluator()
    std = StdLib(ev)
    scope = Scope()
    # Build a simple function: add: fn {a, b} [ a + b ]
    add_fn = std._fn([Sig(["a", "b"], {}, None, None), Code([[GP([Nm("a")]), GP([Nm("+")]), GP([Nm("b")])]])], scope=scope)
    scope["adder"] = add_fn
    # call `adder` #[1,2] -> 3
    res = await std._call(PLit(GP([Nm("adder")])), [1, 2], scope=scope)
    assert res == 3
    # call `val` with no args returns value; with args raises
    scope["val"] = 123
    assert await std._call(PLit(GP([Nm("val")])), [], scope=scope) == 123
    with pytest.raises(TypeError):
        await std._call(PLit(GP([Nm("val")])), [1], scope=scope)

@pytest.mark.asyncio
async def test_get_body_for_slip_and_generic_and_missing():
    ev = Evaluator()
    std = StdLib(ev)
    # SlipFunction -> returns its body
    fn = std._fn([Sig([], {}, None, None), Code([[42]])], scope=Scope())
    body = std._get_body(fn, Sig([], {}, None, None), scope=Scope())
    assert isinstance(body, Code)
    # GenericFunction with typed method
    gf = GenericFunction("g")
    m = SlipFunction(Sig(["x"], {}, None, None), Code([[GP([Nm("x")])]]), Scope())
    typed_sig = Sig([], {"x": GP([Nm("int")])}, None, None)
    m.meta["type"] = typed_sig
    gf.add_method(m)
    out_body = std._get_body(gf, typed_sig, scope=Scope())
    assert out_body is m.body
    # No matching method -> PathNotFound
    with pytest.raises(PathNotFound):
        std._get_body(gf, Sig([], {"x": GP([Nm("string")])}, None, None), scope=Scope())

@pytest.mark.asyncio
async def test_del_promotes_content_type_header(monkeypatch):
    ev = Evaluator()
    std = StdLib(ev)
    # Monkeypatch meta to include content-type and response-mode full
    async def fake_meta(meta, scope): return {"content-type": "application/json", "response-mode": "full"}
    ev.path_resolver._meta_to_dict = fake_meta
    captured = {}
    async def fake_http_delete(url, config=None):
        captured["cfg"] = dict(config or {})
        return (204, None, {"X": "y"})
    import slip.slip_http as http_mod
    monkeypatch.setattr(http_mod, "http_delete", fake_http_delete)
    out = await std._del(GP([Nm("http://example/api")]), scope=Scope())
    assert out["status"] == 204
    assert captured["cfg"]["headers"]["Content-Type"] == "application/json"
