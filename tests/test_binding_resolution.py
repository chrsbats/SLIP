import copy
import gc
import pickle
import weakref

import pytest

from slip import ScriptRunner
from slip.slip_datatypes import (
    Code, GetPath, Group, HostScopePath, Name, PathLiteral, PathNotFound,
    PipedPath, Scope,
)
from slip.slip_interpreter import Evaluator


@pytest.mark.asyncio
async def test_name_reads_bypass_general_path_resolution(monkeypatch):
    evaluator = Evaluator()
    parent = Scope()
    parent["value"] = 1
    scope = Scope(parent=parent)
    path = GetPath([Name("value")])

    def unexpected(*args):
        raise AssertionError("ordinary names must not enter general traversal")

    for method in (
        "_extract_http_url", "_extract_file_locator", "_resolve_value",
        "_get_segment_key",
    ):
        monkeypatch.setattr(evaluator.path_resolver, method, unexpected)

    assert await evaluator.path_resolver.get(path, scope) == 1
    parent["value"] = 2
    assert await evaluator.path_resolver.get(path, scope) == 2
    scope["value"] = 3
    assert await evaluator.path_resolver.get(path, scope) == 3
    del scope["value"]
    assert await evaluator.path_resolver.get(path, scope) == 2
    del parent["value"]
    with pytest.raises(PathNotFound):
        await evaluator.path_resolver.get(path, scope)


@pytest.mark.asyncio
async def test_operator_aliases_observe_binding_and_parent_changes():
    evaluator = Evaluator()
    parent = Scope()
    parent["add"] = lambda a, b: a + b
    parent["sub"] = lambda a, b: a - b
    parent["alias"] = PipedPath([Name("add")])
    parent["op"] = GetPath([Name("alias")])
    scope = Scope(parent=parent)
    expression = [10, GetPath([Name("op")]), 2]

    assert await evaluator.eval(expression, scope) == 12
    cached = scope._operator_lookups["op"]
    for i in range(3):
        scope["i"] = i
        assert await evaluator.eval(expression, scope) == 12
        assert scope._operator_lookups["op"] is cached

    parent["alias"] = PipedPath([Name("sub")])
    assert await evaluator.eval(expression, scope) == 8
    scope["alias"] = PipedPath([Name("add")])
    assert await evaluator.eval(expression, scope) == 12
    del scope["alias"]
    assert await evaluator.eval(expression, scope) == 8
    parent.bindings.update(sub=lambda a, b: a * b)
    assert await evaluator.eval(expression, scope) == 20

    other = Scope()
    other["op"] = PipedPath([Name("other")])
    other["other"] = lambda a, b: a / b
    scope.meta["parent"] = other
    assert await evaluator.eval(expression, scope) == 5
    other.bindings = {
        "op": PipedPath([Name("other")]), "other": lambda a, b: 7,
    }
    assert await evaluator.eval(expression, scope) == 7


@pytest.mark.parametrize("remove", [
    lambda bindings: bindings.pop("value"),
    lambda bindings: bindings.popitem(),
    lambda bindings: bindings.clear(),
    lambda bindings: bindings.__delitem__("value"),
])
def test_binding_map_removals_invalidate_inherited_lookup(remove):
    root = Scope()
    root["value"] = 1
    parent = Scope(parent=root)
    parent["value"] = 2
    child = Scope(parent=parent)
    assert child["value"] == 2
    remove(parent.bindings)
    assert child["value"] == 1
    parent.bindings.setdefault("value", 3)
    assert child["value"] == 3
    parent.bindings |= {"value": 4}
    assert child["value"] == 4


@pytest.mark.asyncio
async def test_cached_operators_keep_mutable_syntax_live():
    evaluator = Evaluator()
    scope = Scope()
    scope["add"] = lambda a, b: a + b
    scope["sub"] = lambda a, b: a - b
    scope["first"] = PipedPath([Name("add")])
    scope["second"] = PipedPath([Name("sub")])
    alias = GetPath([Name("first")])
    scope["op"] = alias
    expression = [10, GetPath([Name("op")]), 2]

    assert await evaluator.eval(expression, scope) == 12
    alias.segments[0].text = "second"
    assert await evaluator.eval(expression, scope) == 8
    scope["second"].segments[0].text = "add"
    assert await evaluator.eval(expression, scope) == 12

    literal = PathLiteral(GetPath([Name("first")]))
    scope["op"] = literal
    assert await evaluator.eval(expression, scope) == 12
    literal.inner = GetPath([Name("sub")])
    # A quoted alias to a plain callable is not an infix operator.
    with pytest.raises(TypeError, match="piped-path"):
        await evaluator.eval(expression, scope)


@pytest.mark.asyncio
async def test_operator_paths_are_reused_without_allocations(monkeypatch):
    evaluator = Evaluator()
    scope = Scope()
    scope["add"] = lambda a, b: a + b
    scope["op"] = PipedPath([Name("add")])
    expression = [10, GetPath([Name("op")]), 2]
    allocations = []
    original = GetPath.__init__

    def record(self, *args, **kwargs):
        allocations.append(args)
        original(self, *args, **kwargs)

    monkeypatch.setattr(GetPath, "__init__", record)
    for _ in range(3):
        assert await evaluator.eval(expression, scope) == 12
    assert allocations == []


@pytest.mark.asyncio
async def test_callable_rebinding_in_operand_is_seen_before_invocation():
    evaluator = Evaluator()
    scope = Scope()
    scope["op"] = PipedPath([Name("add")])
    scope["add"] = lambda a, b: a + b

    def rhs():
        scope["add"] = lambda a, b: a - b
        return 3

    scope["rhs"] = rhs
    expression = [10, GetPath([Name("op")]), Group([[GetPath([Name("rhs")])]])]
    assert await evaluator.eval(expression, scope) == 7


@pytest.mark.asyncio
async def test_reused_loop_observes_operator_rebinding():
    result = await ScriptRunner().handle_script("""
results: #[]
i: 0
while [i < 4] [
    if [i = 2] [/+: |core-sub]
    results: add results (10 + i)
    i: i |core-add 1
]
results
""")
    assert result.status == "ok", result.error_message
    assert result.value == [10, 11, 8, 7]


@pytest.mark.asyncio
async def test_shared_function_syntax_uses_current_frames_and_runners():
    source = "calculate: fn {value} [value + 1]"
    first = ScriptRunner()
    second = ScriptRunner()
    for runner in (first, second):
        result = await runner.handle_script(source)
        assert result.status == "ok", result.error_message
    changed = await first.handle_script("/+: |core-sub")
    assert changed.status == "ok", changed.error_message
    for value in (3, 8, 20):
        for runner, expected in ((first, value - 1), (second, value + 1)):
            result = await runner.evaluator.call(
                runner.root_scope["calculate"], [value], runner.root_scope,
            )
            assert result == expected


def test_lookahead_never_reads_live_parent_scope():
    class LiveDict(dict):
        def __getitem__(self, key):
            if key == "operand":
                raise AssertionError("lookahead read a live host value")
            return super().__getitem__(key)

    live = HostScopePath(LiveDict(operand=7), [], lambda _: None)
    scope = Scope(parent=live)
    path = GetPath([Name("operand")])
    assert Evaluator()._peek_piped_path(path, scope) is None


@pytest.mark.parametrize("wrapper", [Code, Group])
def test_lookahead_preserves_wrapped_operator_aliases(wrapper):
    scope = Scope()
    target = PipedPath([Name("add")])
    scope["target"] = target
    scope["op"] = wrapper([[GetPath([Name("target")])]])
    path = GetPath([Name("op")])
    assert Evaluator()._peek_piped_path(path, scope) is target


def test_quoted_get_alias_remains_a_lookahead_operand():
    scope = Scope()
    scope["target"] = PipedPath([Name("add")])
    scope["op"] = PathLiteral(GetPath([Name("target")]))
    assert Evaluator()._peek_piped_path(GetPath([Name("op")]), scope) is None


@pytest.mark.parametrize("clone", [
    copy.deepcopy, lambda value: pickle.loads(pickle.dumps(value)),
])
def test_scope_copies_do_not_retain_lookup_cache_dependencies(clone):
    parent = Scope()
    parent["value"] = 1
    child = Scope(parent=parent)
    assert child["value"] == 1
    copied = clone(child)
    parent["value"] = 2
    assert child["value"] == 2
    assert copied["value"] == 1
    copied.parent["value"] = 3
    assert copied["value"] == 3


@pytest.mark.asyncio
async def test_custom_binding_map_operator_is_read_once():
    class LiveBindings(dict):
        reads = 0

        def __getitem__(self, key):
            if key == "op":
                self.reads += 1
                return PipedPath([Name("add" if self.reads == 1 else "sub")])
            return super().__getitem__(key)

    scope = Scope()
    scope.bindings = LiveBindings(
        op=None, add=lambda a, b: a + b, sub=lambda a, b: a - b,
    )
    evaluator = Evaluator()
    expression = [10, GetPath([Name("op")]), 2]
    assert await evaluator.eval(expression, scope) == 12
    assert scope.bindings.reads == 1


def test_binding_cache_does_not_retain_detached_parent():
    parent = Scope()
    parent["value"] = 1
    parent["self"] = parent
    child = Scope(parent=parent)
    assert child["value"] == 1
    old_parent = weakref.ref(parent)
    child.meta["parent"] = Scope()
    del parent
    gc.collect()
    assert old_parent() is None


@pytest.mark.asyncio
async def test_operator_cache_does_not_retain_detached_parent():
    parent = Scope()
    parent["op"] = PipedPath([Name("add")], Group([[parent]]))
    parent["add"] = lambda a, b: a + b
    child = Scope(parent=parent)
    expression = [10, GetPath([Name("op")]), 2]
    evaluator = Evaluator()
    assert await evaluator.eval(expression, child) == 12
    old_parent = weakref.ref(parent)
    child.meta["parent"] = Scope()
    del parent
    gc.collect()
    assert old_parent() is None


@pytest.mark.parametrize("indirect", [False, True])
def test_cyclic_parent_lookup_raises_without_unbounded_traversal(indirect):
    scope = Scope()
    scope.inherit(Scope(parent=scope) if indirect else scope)
    scope["local"] = 1
    assert scope["local"] == 1
    with pytest.raises(RecursionError):
        scope["missing"]
