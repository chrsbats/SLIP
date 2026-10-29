"""Behavioral ports of chapters 004–007 and 006_control_flow.

Use the documented Sig constructor for the old empty Code parameter pattern.
Outcome enums are compared as native values instead of legacy display strings.
"""

import pytest

from slip.slip_core import Path, PathLiteral
from slip import ScriptRunner


@pytest.mark.parametrize(("source", "expected"), [
    pytest.param("10 + 5", 15, id="004_infix"),
    pytest.param("10 + 5 * 2", 30, id="004_left_to_right"),
    pytest.param("10 + (5 * 2)", 20, id="004_parentheses"),
    pytest.param("10 |add 5", 15, id="004_binary_pipe"),
    pytest.param("2 |exp", pytest.approx(7.38905609893, rel=1e-9),
                 id="004_unary_pipe"),
    pytest.param("10 |add 5 |mul 2", 30, id="004_chained_pipes"),
    pytest.param("add 10 5 |mul 3", 45, id="004_prefix_then_pipe"),
    pytest.param("/+: |sub; 10 + 2", 8, id="004_rebind_alias"),
    pytest.param("2 |exp |to-int", 7, id="004_unary_chain"),
    pytest.param("Character: scope #{hp: 100, stamina: 100}; "
                 "Player: scope #{} |inherit Character; "
                 "#[Player.stamina, is-a Player Character, "
                 "is-a Character Player]", [100, True, False],
                 id="005_inheritance"),
    pytest.param("Character: scope #{}; obj1: create; obj2: create Character; "
                 "obj3: create Character [name: 'Kael']; "
                 "#[is-scope obj1, is-a obj2 Character, obj3.name, "
                 "is-a obj3 Character]", [True, True, "Kael", True],
                 id="005_creation_configuration"),
    pytest.param("UserSchema: schema #{}; #[is-schema UserSchema, "
                 "is-a UserSchema Schema, is-scope UserSchema]", [True] * 3,
                 id="005_schema_prototype"),
    pytest.param("obj: scope #{a: 1}; res: obj |with [b: 2]; "
                 "#[eq obj res, res.b]", [True, 2], id="005_with_identity"),
    pytest.param("is-a 5 Schema", False, id="005_non_scope_is_a"),
    pytest.param("""
        add: fn {a: `int`, b: `int`} ['exact']
        add: fn {a: `int`, b: `int`, rest...} ['variadic']
        add: fn {a, b, rest...} ['untyped-variadic']
        r1: add 1 2
        r2: add 1 2 3
        #[r1, r2]
    """, ['exact', 'variadic'], id="006_typed_exact_variadic_fallback"),
    pytest.param("foo: fn {} [1]; foo: fn {} [2]; foo", 2,
                 id="006_last_defined_untyped"),
    pytest.param("Being: scope #{}; Character: scope #{} |inherit Being; "
                 "Player: scope #{} |inherit Character; "
                 "interact: fn {x: Player} ['player']; "
                 "interact: fn {x: Being} ['being']; "
                 "p: create Player; interact p", 'player',
                 id="006_prototype_specificity"),
    pytest.param("choose: fn {x: `int`} ['plain']; "
                 "choose: fn {x: `int`} ['guarded-1'] |where [x > 0]; "
                 "choose: fn {x: `int`} ['guarded-2'] |where [x > 0]; "
                 "#[choose 5, choose -1]", ['guarded-2', 'plain'],
                 id="006_guards_and_definition_order"),
    pytest.param("A: scope #{}; f: fn {x: A} ['typed']; "
                 "f: fn {x} ['fallback']; a: create A; #[f a, f 123]",
                 ['typed', 'fallback'], id="006_typed_precedes_fallback"),
    pytest.param("Character: scope #{}; Player: scope #{} |inherit Character; "
                 "Monster: scope #{} |inherit Character; "
                 "treat: fn {x: {Player or Monster}} ['entity']; "
                 "p: create Player; treat p", 'entity', id="006_union"),
    pytest.param("A: scope #{}; B: scope #{} |inherit A; "
                 "f: fn {x: (A and B)} ['both']; f (create B)", 'both',
                 id="006_grouped_conjunction_match"),
    pytest.param("f: fn {fmt: `string`, rest...} [fmt]; f 's' 10 20 30", 's',
                 id="006_variadic"),
    pytest.param("x: 5; a: if [x > 0] ['pos'] ['neg']; "
                 "b: when [x > 10] ['big']; #[a, b]", ['pos', None],
                 id="control_if_when"),
    pytest.param("r1: false and (1 / 0); r2: true or (1 / 0); #[r1, r2]",
                 [False, True], id="control_short_circuit"),
    pytest.param("i: 0; last: while [i < 3] [i: i + 1; i]; #[i, last]",
                 [3, 3], id="control_while_last_value"),
    pytest.param("""
        lst: #[1, 2, 3]
        sum1: 0
        foreach {x} lst [sum1: sum1 + x]
        d: #{a: 1, b: 2}
        keys: #[]
        vals: #[]
        foreach {k, v} d [keys: add keys #[k]; vals: add vals #[v]]
        sc: scope #{x: 10, y: 20}
        skeys: #[]
        svals: #[]
        foreach {k, v} sc [skeys: add skeys #[k]; svals: add svals #[v]]
        #[sum1, sort keys, sort vals, sort skeys, sort svals]
    """, [6, ['a', 'b'], [1, 2], ['x', 'y'], [10, 20]],
                 id="control_foreach_list_dict_scope"),
    pytest.param("x: 5; a: cond #[#[[x < 5], 'lt'], #[[x > 5], 'gt'], "
                 "#[[true], 'eq']]; b: cond #[#[[false], 'never']]; #[a, b]",
                 ['eq', None], id="control_cond"),
    pytest.param("xs: #[]; for {i} 1 4 [xs: add xs #[i]]; "
                 "ys: #[]; for {j} 3 0 [ys: add ys #[j]]; #[xs, ys, i, j]",
                 [[1, 2, 3], [3, 2, 1], 3, 1], id="control_count_up_down"),
    pytest.param("f: fn {} [123]; f", 123, id="007_ordinary_return"),
    pytest.param("f: fn {} [return 7; 999]; f", 7, id="007_early_return"),
    pytest.param("return 42", 42, id="007_top_level_return"),
    pytest.param("g: fn {} [x: 1; return 99; x: 2]; g", 99,
                 id="007_no_execution_after_return"),
    pytest.param("#[eq ok `ok`, eq err `err`, eq not-found `not-found`, "
                 "eq invalid `invalid`]", [True] * 4,
                 id="007_status_and_failure_code_aliases"),
])
def test_values(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == expected


@pytest.mark.parametrize(("source", "message"), [
    pytest.param("true |and false", "already piped", id="004_double_pipe"),
    pytest.param("Proto1: scope #{}; Proto2: scope #{}; o: create Proto1; "
                 "inherit o Proto2", "once", id="005_second_inheritance"),
    pytest.param("add: fn {a: `int`, b: `int`} ['exact']; add 'a' 2",
                 "No matching method", id="006_type_mismatch"),
    pytest.param("Character: scope #{}; "
                 "Player: scope #{} |inherit Character; Buff: scope #{}; "
                 "OnFire: scope #{} |inherit Buff; "
                 "hit: fn {p: (Player and OnFire)} ['onfire']; "
                 "p: create Player; hit p", "No matching method",
                 id="006_conjunction_mismatch"),
    pytest.param("f: fn {x: `int`} [x]; f 1 2", "Expected a piped function",
                 id="006_extra_value_after_fixed_arity_prefix_call"),
    pytest.param("f: fn {x: `int`} [x]; call f #[1, 2]", "No matching method",
                 id="006_too_many_explicit_call_arguments"),
    pytest.param("f: fn {} [fail 'oops'; 'unreachable']; f", "oops",
                 id="007_failure"),
])
def test_errors(source, message):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == 'err'
        assert message in result.error_message


@pytest.mark.parametrize(("body", "expected"), [
    ("when [local-value > 0] [local-value]", 7),
    ("cond #[#[[local-value > 0], [local-value]]]", 7),
    ("seen: #[]; for {i} 0 3 [seen: add seen #[local-value + i]]; seen",
     [7, 8, 9]),
    ("seen: #[]; do [loop [seen: add seen #[local-value]; "
     "if [(len seen) = 2] [fail 'done']]]; seen", [7, 7]),
])
def test_control_helpers_use_function_local_bindings(body, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(
            f"probe: fn {{local-value}} [{body}]; probe 7",
        )
        assert result.status == 'ok', result.error_message
        assert result.value == expected


def test_nested_helpers_share_the_callers_loop_binding():
    with ScriptRunner() as runner:
        result = runner.handle_script("""
            collect: fn {offset} [
                seen: #[]
                for {i} 0 3 [
                    when [i > 0] [seen: add seen #[offset + i]]
                ]
                #[seen, i]
            ]
            result: collect 10
            i-probe: do [i]
            offset-probe: do [offset]
            #[result, i-probe.status, offset-probe.status]
        """)
        assert result.status == 'ok', result.error_message
        err = PathLiteral(Path(['err']))
        assert result.value == [[[11, 12], 2], err, err]


def test_emit_records_ordered_effects_and_returns_last_expression():
    with ScriptRunner() as runner:
        result = runner.handle_script('emit "stdout" "Hello, world!"; 1 + 1')
        assert result.status == 'ok', result.error_message
        assert result.value == 2
        assert result.side_effects == [
            {'topics': ['stdout'], 'message': 'Hello, world!'},
        ]
