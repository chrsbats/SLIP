"""Binding and execution remain separate across the documented Code forms."""

import copy
import operator
from unittest.mock import patch

from slip import slip_core as core
from slip.slip_library import SOURCE, library_scope
from slip.slip_syntax import parse


def test_nested_control_lists_are_reused_with_live_call_frames():
    scope = core.Scope(parent=library_scope())
    core.execute(parse("""
        work: fn {n, amount} [
            i: 0; total: 0
            while [i < n] [
                if [true] [total: + amount]
                i: + 1
            ]
            total
        ]
    """), scope)
    with patch.object(core, "convert", side_effect=AssertionError("rebind")):
        assert core.invoke(scope["work"], [3, 2], scope) == 6
        assert core.invoke(scope["work"], [4, 5], scope) == 20


def test_slip_control_helper_reuses_the_callers_bound_block():
    scope = core.Scope(parent=library_scope())
    core.execute(parse(SOURCE), scope.root)
    core.execute(parse("""
        sum: fn {n} [total: 0; for {i} 0 n [total: + i]; total]
    """), scope)
    with patch.object(core, "convert", side_effect=AssertionError("rebind")):
        assert core.invoke(scope["sum"], [3], scope) == 3
        assert core.invoke(scope["sum"], [5], scope) == 10


def test_slip_control_helper_binds_raw_code_once_at_entry():
    scope = core.Scope(parent=library_scope())
    core.execute(parse(SOURCE), scope.root)
    program = parse("total: 0; for {i} 0 limit [total: + i]; total")
    counts = []
    for limit in (3, 30):
        scope["limit"] = limit
        with patch.object(core, "convert", wraps=core.convert) as convert:
            result = core.execute(program, scope)
            assert result == sum(range(limit))
            counts.append(convert.call_count)
    assert counts[0] == counts[1]
    assert program[1][-1].stacks is None


def test_nested_blocks_and_inner_functions_have_definition_boundaries():
    scope = core.language_scope()
    result = core.execute(parse("""
        f: fn {x} [if [true] [x + 1]]
        make: fn {n} [fn {x} [x + n]]
        /+: |core-sub
        g: fn {x} [if [true] [x + 1]]
        inner: make 3
        #[f 10, g 10, inner 10]
    """), scope)
    assert result == [11, 9, 7]


def test_constructors_queries_and_interpolation_reuse_bound_lists():
    scope = core.Scope(parent=library_scope())
    core.execute(parse("""
        report: fn {players, limit} [
            #[players[.hp < limit].hp, "{{limit + 1}}", #{count: len players}]
        ]
    """), scope)
    players = [{"hp": 5}, {"hp": 15}]
    with patch.object(core, "convert", side_effect=AssertionError("rebind")):
        result = core.invoke(scope["report"], [players, 10], scope)
        assert result == [[5], "11", {"count": 2}]
        players[0] = {"hp": 25}
        result = core.invoke(scope["report"], [players, 20], scope)
        assert result == [[15], "21", {"count": 2}]


def test_source_stays_symbolic_and_new_function_observes_source_edits():
    scope = core.language_scope()
    source = parse("if [true] [x + 1]")
    original = copy.deepcopy(source)
    first = core.Lambda(core.Sig(["x"]), source, scope)
    assert source == original
    assert isinstance(source[0][2][0][1], core.Path)
    source[0][2][0][-1] = 2
    second = core.Lambda(core.Sig(["x"]), source, scope)
    assert first(10, scope=scope) == 11
    assert second(10, scope=scope) == 12


def test_code_arguments_keep_their_identity_and_remain_unbound_data():
    scope = core.language_scope()
    source = parse("x + 1")
    identity = core.Lambda(
        core.Sig(["value"]), core.Code([[core.Path(["value"])]]), scope,
    )
    assert identity(source, scope=scope) is source
    assert source.stacks is None


def test_shared_symbolic_source_has_runtime_local_bindings():
    source = parse("if [true] [x + 1]")
    first_scope, second_scope = core.language_scope(), core.language_scope()
    second_scope["+"] = core.Pipe(operator.sub)
    first = core.Lambda(core.Sig(["x"]), source, first_scope)
    second = core.Lambda(core.Sig(["x"]), source, second_scope)
    assert first(10, scope=first_scope) == 11
    assert second(10, scope=second_scope) == 9
    assert source.stacks is None
    assert source[0][2].stacks is None


def test_raw_native_loop_binds_once_per_execution_boundary():
    scope = core.language_scope()
    scope["i"], scope["limit"] = 0, 3
    condition, body = parse("i < limit"), parse("i: + 1")
    with patch.object(core, "convert", wraps=core.convert) as convert:
        assert core.while_loop(condition, body, scope=scope) == 3
        assert convert.call_count == 2
    scope["i"], scope["limit"] = 0, 30
    body[0][-1] = 2
    with patch.object(core, "convert", wraps=core.convert) as convert:
        assert core.while_loop(condition, body, scope=scope) == 30
        assert convert.call_count == 2
    assert condition.stacks is None and body.stacks is None


def test_explicit_code_execution_binds_in_the_receiving_scope():
    scope = core.Scope(parent=library_scope())
    result = core.execute(parse("""
        operation: core-function `core-add`
        target: scope #{operation: core-function `core-sub`}
        run-with [operation 10 3] target
    """), scope)
    assert result == 7


def test_one_native_call_boundary_per_operation():
    scope = core.language_scope()
    saved = core.convert([
        core.Path(["core-add"]), 1, 2, core.Path(["core-mul"], "pipe"), 3,
    ], scope)
    assert saved[0] is operator.add
    with patch.object(
        core, "bind_signature", side_effect=AssertionError("sig"),
    ):
        assert core.evaluate(list(reversed(saved)), scope) == 9


def test_generic_arity_updates_when_the_same_object_gains_a_method():
    scope = core.language_scope()
    one = core.Lambda(core.Sig(["x"]), core.Code([[1]]), scope)
    two = core.Lambda(core.Sig(["x", "y"]), core.Code([[2]]), scope)
    generic = core.Generic([one])
    scope["choose"] = generic
    assert core.execute(parse("choose 10"), scope) == 1
    generic.methods.append(two)
    assert core.execute(parse("choose 10 20"), scope) == 2


def test_fresh_code_literals_reuse_preparation_and_retain_inserted_data():
    scope = core.language_scope()
    original = core.Scope({'value': 7})
    data = [original, operator.add]
    literal = core.Code([[original, operator.add, data]])
    make = core.Lambda(core.Sig(), core.Code([[literal]]), scope)
    with patch.object(core, 'convert', side_effect=AssertionError('rebind')):
        first = make(scope=scope)
        second = make(scope=scope)
    assert first is not second and first[0] is not second[0]
    assert first.stacks is second.stacks
    assert first[0][0] is second[0][0] is original
    assert first[0][1] is second[0][1] is operator.add
    assert first[0][2] is second[0][2] is data


def test_slip_conditionals_reuse_captured_blocks_with_caller_effects():
    scope = core.Scope(parent=library_scope())
    core.execute(parse(SOURCE), scope.root)
    core.execute(parse('''
        operation: core-function `core-add`
        probe: fn {x} [
            result: 0
            when [true] [result: operation x 3; emit 'when' result]
            cond #[#[[true], [result: operation result 1; emit 'cond' result]]]
            result
        ]
        operation: core-function `core-sub`
    '''), scope)
    with patch.object(core, 'convert', side_effect=AssertionError('rebind')):
        assert core.invoke(scope['probe'], [10], scope) == 14
        assert core.invoke(scope['probe'], [20], scope) == 24
    assert scope.effects == [
        {'topics': ['when'], 'message': 13},
        {'topics': ['cond'], 'message': 14},
        {'topics': ['when'], 'message': 23},
        {'topics': ['cond'], 'message': 24},
    ]


def test_nested_run_with_retains_the_original_lexical_scope():
    scope = core.Scope(parent=library_scope())
    result = core.execute(parse('''
        here: current-scope
        first: scope #{}
        second: scope #{}
        observed: run-with [
            a: 1
            run-with [b: 2; emit 'nested' b; current-scope] second
        ] first
        observed.c: 3
        #[observed = here, first.a, second.b, c]
    '''), scope)
    assert result == [True, 1, 2, 3]
    assert 'b' not in scope['first'] and 'a' not in scope['second']
    assert scope.effects == [{'topics': ['nested'], 'message': 2}]


def test_derived_binder_preserves_captures_and_observes_local_names():
    scope = core.Scope(parent=library_scope())
    core.execute(parse('''
        target: core-function `core-add`
        each: cell {} [emit 'read' 'each'; core-function `foreach`]
        probe: fn {} [
            before: target 10 3
            each {target} #[core-function `core-sub`] [none]
            #[before, target 10 3]
        ]
        target: core-function `core-mul`
    '''), scope)
    assert scope.effects == []
    with patch.object(core, 'convert', side_effect=AssertionError('rebind')):
        assert core.invoke(scope['probe'], [], scope) == [13, 7]
        assert core.invoke(scope['probe'], [], scope) == [13, 7]
    assert scope.effects == [
        {'topics': ['read'], 'message': 'each'},
        {'topics': ['read'], 'message': 'each'},
    ]
