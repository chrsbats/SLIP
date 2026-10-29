"""Examples derived from the pseudocode and language guides, independently."""

import operator

import pytest

from slip.slip_core import (
    Code, Generic, Get, Group, Lambda, Parameter, Path, PathLiteral, Pipe,
    Query, Scope, Sig, convert, evaluate, execute, invoke, language_scope,
)


def test_source_order_and_grouping():
    scope = language_scope()
    expression = convert([10, Path(["+"]), 5, Path(["*"]), 2], scope)
    working = list(reversed(expression))
    assert evaluate(working, scope) == 30
    assert working == []
    assert len(expression) == 5
    grouped = Code([[10, Path(["+"]), Group([[5, Path(["*"]), 2]])]])
    assert execute(grouped, scope) == 20


def test_direct_function_identity_and_reusable_lists():
    scope = language_scope()
    function = Lambda(Sig(["x"]), Code([[Path(["x"]), Path(["+"]), 1]]), scope)
    saved = function.stacks[0]
    assert saved[1].target is operator.add
    assert scope["core-add"] is operator.add
    assert isinstance(saved[0], Get)
    assert function(10, scope=scope) == 11
    assert function(20, scope=scope) == 21
    assert function.stacks[0] is saved
    assert len(saved) == 3


def test_definition_order_and_pipe_capture():
    scope = language_scope()
    body = Code([[Path(["x"]), Path(["+"]), 1]])
    execute(Code([
        [Path(["f"], "set"), Path(["fn"]), Sig(["x"]), body],
    ]), scope)
    execute(Code([
        [Path(["+"], "set"), Path(["core-sub"], "pipe")],
    ]), scope)
    execute(Code([
        [Path(["g"], "set"), Path(["fn"]), Sig(["x"]), body],
    ]), scope)
    assert execute(Code([[Path(["f"]), 10]]), scope) == 11
    assert execute(Code([[Path(["g"]), 10]]), scope) == 9
    scope["target"] = operator.add
    execute(Code([
        [Path(["op"], "set"), Path(["target"], "pipe")],
    ]), scope)
    scope["target"] = operator.sub
    assert execute(Code([[10, Path(["op"]), 3]]), scope) == 13


def test_callable_parameters_and_local_shadowing():
    scope = language_scope()
    scope["operation"] = operator.mul
    function = Lambda(Sig(["operation", "value"]), Code([
        [Path(["operation"]), Path(["value"]), 2],
    ]), scope)
    assert function(operator.add, 10, scope=scope) == 12
    assert function(operator.sub, 10, scope=scope) == 8
    scope["local"] = operator.mul
    function = Lambda(Sig(["value"]), Code([
        [Path(["local"], "set"), Path(["value"])],
        [Path(["local"]), Path(["+"]), 1],
    ]), scope)
    assert function(10, scope=scope) == 11
    assert scope["local"] is operator.mul


def test_forward_names_and_closures():
    scope = language_scope()
    function = Lambda(Sig(["value"]), Code([
        [Path(["later"]), Path(["value"]), 2],
    ]), scope)
    scope["later"] = operator.add
    assert function(10, scope=scope) == 12
    scope["later"] = operator.sub
    assert function(10, scope=scope) == 8
    make_adder = Lambda(Sig(["n"]), Code([
        [Path(["fn"]), Sig(["x"]), Code([
            [Path(["x"]), Path(["+"]), Path(["n"])],
        ])],
    ]), scope)
    add_ten = make_adder(10, scope=scope)
    assert add_ten(7, scope=scope) == 17


def test_binding_does_not_read_host_members_and_live_replacement():
    scope = language_scope()
    reads = []

    class Host:
        def __getitem__(self, key):
            reads.append(key)
            return 10

    scope["obj"] = Host()
    function = Lambda(Sig(), Code([
        [Path(["obj", "hp"]), Path(["+"]), 1],
    ]), scope)
    assert reads == []
    assert function(scope=scope) == 11
    assert reads == ["hp"]
    scope["obj"] = {"hp": 20}
    assert function(scope=scope) == 21


def test_callable_arguments_are_non_greedy_and_nested_calls_are_explicit():
    scope = language_scope()
    calls = []

    def tick():
        calls.append(1)
        return 7

    def select(function, value):
        return function, value

    scope["tick"] = tick
    scope["select"] = select
    expression = convert([
        Path(["select"]), Path(["add"]), Group([[Path(["tick"])]]),
    ], scope)
    assert calls == []
    function, value = evaluate(list(reversed(expression)), scope)
    assert function is operator.add
    assert value == 7
    assert calls == [1]


def test_pipe_values_can_be_passed_as_required_arguments():
    scope = language_scope()

    def identity(value):
        return value

    scope["identity"] = identity
    result = execute(Code([
        [Path(["identity"]), Path(["add"], "pipe")],
    ]), scope)
    assert isinstance(result, Pipe)
    assert result.target is operator.add


def test_bare_return_exits_with_none():
    scope = language_scope()
    function = Lambda(Sig(), Code([[Path(["return"])], [99]]), scope)
    assert function(scope=scope) is None


def test_quoted_paths_are_late_bound_data():
    scope = language_scope()
    scope["target"] = operator.add
    quoted = PathLiteral(Path(["target"]))
    scope["args"] = [10, 3]
    function = Lambda(Sig(), Code([
        [Path(["call"]), quoted, Path(["args"])],
    ]), scope)
    assert function(scope=scope) == 13
    scope["target"] = operator.sub
    assert function(scope=scope) == 7


def test_assignment_keeps_data_identity_and_paths_use_native_protocols():
    scope = language_scope()
    original = {"hp": 10}
    scope["original"] = original
    result = execute(Code([
        [Path(["alias"], "set"), Path(["original"])],
    ]), scope)
    assert result is original and scope["alias"] is original
    result = execute(Code([[Path(["alias", "hp"], "set"), 20]]), scope)
    assert result == 20
    assert original["hp"] == 20
    execute(Code([[Path(["alias", "hp"], "del")]]), scope)
    assert original == {}


def test_pluck_filter_update_retains_original_targets():
    scope = language_scope()
    players = [{"hp": 120}, {"hp": 45}]
    scope["players"] = players
    query = Query(Code([[Path([".hp"]), Path(["<"]), 50]]), predicate=True)
    assert execute(Code([[Path(["players", "hp"])]]), scope) == [120, 45]
    update = Path(["players", query, "hp"], "set")
    assert execute(Code([[update, Path(["*"]), 2]]), scope) == [90]
    assert players == [{"hp": 120}, {"hp": 90}]


def test_query_bare_names_are_lexical_and_reads_are_once():
    scope = language_scope()
    scope["limit"] = 50
    scope["players"] = [{"hp": 45, "limit": 0}, {"hp": 120, "limit": 200}]
    query = Query(Code([
        [Path([".hp"]), Path(["<"]), Path(["limit"])],
    ]), predicate=True)
    result = execute(Code([[Path(["players", query])]]), scope)
    assert result == [scope["players"][0]]


def test_dispatch_specificity_guards_and_generic_capture():
    scope = language_scope()
    character = Scope()
    player = Scope(parent=character)
    instance = Scope(parent=player)
    fallback = Lambda(Sig(["x"]), Code([["other"]]), scope)
    typed = Lambda(
        Sig([Parameter("x", character)]), Code([["character"]]), scope,
    )
    most_specific = Lambda(
        Sig([Parameter("x", player)]), Code([["player"]]), scope,
    )
    generic = Generic([most_specific, typed, fallback])
    assert generic(instance, scope=scope) == "player"
    assert generic(123, scope=scope) == "other"
    scope["describe"] = generic
    captured = Lambda(Sig(["x"]), Code([
        [Path(["describe"]), Path(["x"])],
    ]), scope)
    guard = Code([[Path(["x", "special"])]])
    method = Lambda(
        Sig([Parameter("x", player)], where=guard), Code([["special"]]), scope,
    )
    generic.methods.append(method)
    instance["special"] = True
    assert captured(instance, scope=scope) == "special"
    instance["special"] = False
    assert captured(instance, scope=scope) == "player"


def test_dispatch_exact_arity_and_id_refinement():
    scope = language_scope()
    exact = Lambda(Sig([Parameter("x", "string")]), Code([["exact"]]), scope)
    variadic = Lambda(
        Sig([Parameter("x", "string")], rest="rest"), Code([["rest"]]), scope,
    )
    refined = Lambda(Sig([Parameter("x", "id")]), Code([["id"]]), scope)
    generic = Generic([exact, variadic, refined])
    assert generic("hello", scope=scope) == "exact"
    assert generic("hello", 1, 2, scope=scope) == "rest"
    assert generic("id:player", scope=scope) == "id"
    with pytest.raises(TypeError, match="No matching method"):
        generic(10, scope=scope)


def test_native_scopes_keep_definition_and_caller_links():
    definition = language_scope()
    caller = Scope({"value": 20}, definition)
    function = Lambda(Sig(), Code([[Path(["current-scope"])]]), definition)
    frame = function(scope=caller)
    assert frame["meta"]["parent"] is definition
    assert frame["meta"]["caller"] is caller


def test_lazy_controls_early_return_and_outcomes():
    scope = language_scope()
    function = Lambda(Sig(), Code([
        [Path(["do"]), Code([
            [Path(["if"]), Code([[True]]), Code([[Path(["return"]), 7]]),
             Code([[Path(["missing"])]])],
        ])],
        [99],
    ]), scope)
    assert function(scope=scope) == 7
    outcome = execute(Code([[Path(["do"]), Code([
        [Path(["emit"]), "audit", {"n": 1}],
        [10, Path(["/"]), 0],
    ])]]), scope)
    assert outcome["status"] == PathLiteral(Path(["err"]))
    assert outcome["error"]["kind"] == PathLiteral(Path(["runtime"]))
    assert outcome["effects"] == [{"topics": ["audit"], "message": {"n": 1}}]


def test_short_circuit_skips_grouped_rhs():
    scope = language_scope()
    missing = Group([[Path(["missing"])]])
    result = execute(Code([[False, Path(["and"]), missing]]), scope)
    assert result is False
    assert execute(Code([[True, Path(["or"]), missing]]), scope) is True
    assert execute(Code([[True, Path(["and"]), 7]]), scope) == 7


def test_code_stays_symbolic_and_run_is_sandboxed():
    scope = language_scope()
    code = Code([[Path(["x"], "set"), 10], [Path(["x"]), Path(["+"]), 2]])
    assert execute(Code([[Path(["run"]), code]]), scope) == 12
    assert "x" not in scope
    assert isinstance(code[0][0], Path)
    target = Scope(parent=scope)
    result = execute(Code([[Path(["run-with"]), code, target]]), scope)
    assert result == 12
    assert target["x"] == 10
    code[-1][-1] = 3
    assert execute(Code([[Path(["run"]), code]]), scope) == 13


def test_async_functions_rejected_but_stored_coroutines_remain_data():
    scope = language_scope()

    async def native():
        return 7

    stored = native()
    scope["stored"] = stored
    try:
        assert execute(Code([[Path(["stored"])]]), scope) is stored
        with pytest.raises(TypeError, match="Async functions.*unsupported"):
            invoke(native, [], scope)
        assert stored.cr_frame is not None
    finally:
        stored.close()
