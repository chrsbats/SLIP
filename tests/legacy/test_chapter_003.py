"""Synchronous behavioral port of tests/test_chapter_003.py."""

import pytest

from slip import ScriptRunner


@pytest.mark.parametrize(("source", "expected"), [
    pytest.param("x: 123", 123, id="assignment_value_first_definition"),
    pytest.param("a: 10", 10, id="assignment_value_second_definition"),
    pytest.param("foo: fn {x} [x]; foo: fn {x, y} [x + y]; "
                 "#[foo 10, foo 2 3, eq (type-of foo) `function`]",
                 [10, 5, True], id="generic_arity_merging"),
    pytest.param("TypeX: scope #{}; "
                 "#[TypeX.meta.name, TypeX.meta.type-id > 0]",
                 ["TypeX", True], id="scope_christening"),
    pytest.param("[a, b]: #[10, 20]; #[a, b]", [10, 20],
                 id="destructuring"),
    pytest.param("xs: #[1, 2, 3, 4, 5]; xs[1:4]: #[20, 30, 40]; "
                 "#[xs, xs[1:4]]", [[1, 20, 30, 40, 5], [20, 30, 40]],
                 id="slice_replacement"),
    pytest.param("counter: 0; inc: fn {} [../counter: + 1]; #[inc, counter]",
                 [1, 1], id="parent_scope_update"),
    pytest.param("A: scope #{}; B: scope #{} |inherit A; "
                 "f: fn {x: A} [1]; f: fn {x: B} [2]; "
                 "#[f (create A), f (create B)]", [1, 2],
                 id="prototype_dispatch"),
    pytest.param("early: fn {} [return 42; x: 99]; early", 42,
                 id="early_return"),
    pytest.param("x: 1; x: + 1; x", 2, id="infix_update"),
    pytest.param("heal: fn {n} [n + 10]; hp: 40; hp: |heal; hp", 50,
                 id="unary_piped_update"),
    pytest.param("x: 3; x: |add 5; x", 8, id="binary_piped_update"),
    pytest.param("players: #[#{name: 'A', hp: 75}, #{name: 'B', hp: 45}, "
                 "#{name: 'C', hp: 30}]; players.hp[< 50]: + 10",
                 [55, 40], id="vector_update_result"),
    pytest.param("players: #[#{name: 'A', hp: 75}, #{name: 'B', hp: 45}, "
                 "#{name: 'C', hp: 30}]; players.hp[< 50]: + 10; "
                 "#[players[0].hp, players[1].hp, players[2].hp]",
                 [75, 55, 40], id="vector_update_owners"),
    pytest.param("players: #[#{name: 'A', hp: 75}, #{name: 'B', hp: 45}, "
                 "#{name: 'C', hp: 30}]; players.hp[< 50]: 50; "
                 "#[players[0].hp, players[1].hp, players[2].hp]",
                 [75, 50, 50], id="vector_broadcast"),
    pytest.param("g: fn {x: `string`} ['s']; g: fn {x: `int`} ['i']; "
                 "#[g 'hello', g 42]", ['s', 'i'], id="primitive_dispatch"),
    pytest.param("h: fn {x: `path`} ['p']; #[h `a.b`, h `~a`, h `|map`]",
                 ['p', 'p', 'p'], id="path_dispatch"),
    pytest.param("""
        A: scope #{B: scope #{C: scope #{x: 1}}}
        ~A.B.C.x
        #[is-scope A, is-scope A.B, len A.B.C]
    """, [True, True, 0], id="delete_preserves_empty_scope_ancestors"),
    pytest.param("""
        A: scope #{B: scope #{C: scope #{x: 1}, k: 2}}
        ~A.B.C.x
        existsB: eq (do [A.B]).status ok
        kval: A.B.k
        #[existsB, kval, len A.B.C]
    """, [True, 2, 0], id="delete_preserves_empty_and_nonempty_ancestors"),
    pytest.param("A: scope #{B: scope #{k: 2}}; "
                 "res: eq (do [A.B]).status ok; res", True,
                 id="group_path_preserves_trailing_argument"),
    pytest.param("s: scope #{a: scope #{b: 1}}; ~s.a.b; has s 'a'", True,
                 id="interpreter_coverage_preserves_nested_scope"),
    pytest.param("s: scope #{a: scope #{b: 1}}; "
                 "~s.a.b#(note: 'exact-delete'); has s 'a'", True,
                 id="interpreter_extra_coverage_delete_metadata"),
    pytest.param("temp: scope #{x: 1}; ~temp.x; is-scope temp", True,
                 id="interpreter_preserves_lowercase_top_level_binding"),
])
def test_values(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == "ok", result.error_message
        assert result.value == expected


def test_vectorized_elementwise_assignment_requires_matching_lengths():
    with ScriptRunner() as runner:
        result = runner.handle_script("""
            players: #[#{hp: 75}, #{hp: 45}, #{hp: 30}]
            players.hp[< 50]: #[51, 52, 53]
        """)
        assert result.status == "err"
