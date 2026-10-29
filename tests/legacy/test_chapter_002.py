"""Synchronous behavioral port of tests/test_chapter_002.py."""

import pytest

from slip import ScriptRunner


@pytest.mark.parametrize(("source", "expected"), [
    pytest.param("""
        -- single line is ignored
        a: 1
        {-- block comment {-- nested --} --}
        a
    """, 1, id="comments_ignored_single_and_block_nested"),
    pytest.param("#[123, -5, true, false, none, 'raw', \"interp\"]",
                 [123, -5, True, False, None, 'raw', 'interp'],
                 id="numbers_booleans_none_and_strings"),
    pytest.param("eq none ()", True, id="empty_group"),
    pytest.param("xs: #[1, 1 + 1, 3]; d: #{a: 10, b: 5 + 1}; "
                 "#[xs, d.a + d.b]", [[1, 2, 3], 16],
                 id="list_and_dict_contents"),
    pytest.param("s: scope #{a: 1}; #[is-scope s, s.a]", [True, 1],
                 id="scope_constructor_and_predicate"),
    pytest.param("#[is-path `a`, is-path `a:`, is-path `~a`, "
                 "is-path `|map`, is-path `[a,b]:`]", [True] * 5,
                 id="all_path_literal_modes"),
    pytest.param("#[eq `a.b` `a.b`, eq `a.b` `a/b`, "
                 "eq `a.b.c` `a/b.c`, eq `a.b` `a.c`]",
                 [True, True, True, False], id="path_canonical_equality"),
    pytest.param("#[eq `|map` `|map`, eq `~a.b` `~a.b`, "
                 "eq `[x,y]:` `[x,y]:`, eq `~a` `~b`]",
                 [True, True, True, False], id="path_modes_equality"),
    pytest.param("d: #{a: 1}; e: d; e.a: 42; d.a", 42,
                 id="mutable_dict_reference"),
    pytest.param("arr: #[10, 20, 30, 40, 50]; arr[1]", 20,
                 id="query_index"),
    pytest.param("arr: #[10, 20, 30, 40, 50]; arr[1:4]", [20, 30, 40],
                 id="query_slice"),
    pytest.param("arr: #[10, 20, 30, 40, 50]; arr[> 20]", [30, 40, 50],
                 id="query_filter"),
    pytest.param('d: #{name: "Kael", hp: 100}; d["name"]', "Kael",
                 id="query_string_key"),
    pytest.param("players: #[#{name: 'Kael', hp: 75}, "
                 "#{name: 'Jaina', hp: 120}, #{name: 'Thrall', hp: 90}]; "
                 "players.hp[> 100]", [120], id="vectorized_pluck"),
    pytest.param("dist: fn {p} [p.x + p.y]; points: #[#{x: 3, y: 4}, "
                 "#{x: 6, y: 8}, #{x: 1, y: 1}]; points[|dist < 10]",
                 [{'x': 3, 'y': 4}, {'x': 1, 'y': 1}],
                 id="filter_pipeline_transform"),
    pytest.param("xs: #[5, 10, 30]; xs[* 10 - 20 / 2 > 20]", [10, 30],
                 id="filter_chained_infix"),
    pytest.param('name: "Kael"; "Hello, {{name}}!"', "Hello, Kael!",
                 id="istring_variable"),
    pytest.param('user: #{name: "Kael", hp: 100}; '
                 '"User: {{user.name}} (HP {{user.hp}})"',
                 "User: Kael (HP 100)", id="istring_nested_lookup"),
    pytest.param("display-name: fn {obj} [obj.name]; "
                 'obj: #{name: \'brass key\'}; '
                 '"You take {{display-name obj}}."',
                 "You take brass key.", id="istring_call"),
    pytest.param('x: 2; "total {{(x + 3)}}"', "total 5",
                 id="istring_group"),
    pytest.param('''
    name: "Kael"
    banner: "
      Welcome, {{name}}!
      Ready."
    banner
    ''', "Welcome, Kael!\nReady.", id="istring_auto_dedent"),
    pytest.param("name: \"World\"; s: '{{name}}\\n'; s", "{{name}}\n",
                 id="noninterpolated_string_decodes_escapes"),
])
def test_values(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == "ok", result.error_message
        assert result.value == expected


def test_i_string_missing_interpolation_name_errors():
    with ScriptRunner() as runner:
        result = runner.handle_script('"Hello, {{missing-name}}!"')
        assert result.status == "err"
        assert "missing-name" in (result.error_message or "")
