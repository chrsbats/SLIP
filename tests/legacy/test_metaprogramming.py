"""Chapter 010 behavior through the documented synchronous interfaces.

Path conversion uses to-path; call always invokes its target.
Dynamic invocation supplies an explicit list of argument values.
"""

import pytest

from slip import ScriptRunner


@pytest.mark.parametrize(("source", "expected"), [
    pytest.param("res: run [x: 1; x + 2]; probe: do [x]; "
                 "#[res, eq probe.status err]", [3, True], id="sandbox"),
    pytest.param('run []', None, id="empty_code"),
    pytest.param("s: scope #{}; out: run-with [a: 10; a * 2] s; #[out, s.a]",
                 [20, 10], id="target_scope"),
    pytest.param('xs: list [1; 1 + 1; 3]; xs', [1, 2, 3], id="list_values"),
    pytest.param('d: dict [a: 10; b: 5 + 1]; #[d.a, d.b]', [10, 6],
                 id="dict_assignments"),
    pytest.param("c: [y: 5; y + 7]; t1: is-code c; v: run c; "
                 "probe: do [y]; #[t1, v, eq probe.status err]",
                 [True, 12, True],
                 id="first_class_code"),
    pytest.param('make-adder: fn {n} [fn {x} [x + n]]; '
                 'add-10: make-adder 10; add-10 7', 17, id="lexical_closure"),
    pytest.param('my-var: 10; run [result: (add (inject my-var) 5); result]',
                 15, id="inject_value"),
    pytest.param('my-list: #[2, 3]; run [sum: (add (splice my-list)); sum]', 5,
                 id="splice_arguments"),
    pytest.param("p: to-path 'a.b'; eq p `a.b`", True,
                 id="construct_string_path"),
    pytest.param('p: to-path `a.b`; eq p `a.b`', True,
                 id="convert_literal_path"),
    pytest.param("p: to-path 'a.b'; eq p `a.b`", True,
                 id="convert_string_path"),
    pytest.param('is-scope (current-scope)', True, id="current_scope"),
    pytest.param("s: scope #{}; run-with [a: 1] s; "
                 "in-s: len (filter (fn {k} [eq k 'a']) (keys s)); "
                 "in-cur: len (filter (fn {k} [eq k 'a']) "
                 "(keys (current-scope))); "
                 "#[in-s, in-cur]", [1, 0], id="lexical_scope_not_target"),
    pytest.param("xs: #['x', 'y', 'z']; join xs ', '", 'x, y, z',
                 id="string_join"),
    pytest.param('eq (join `a.b` `c`) `a.b.c`', True, id="path_join"),
    pytest.param('eq (join `a` `b.c`) `a.b.c`', True, id="path_join_nested"),
    pytest.param("call 'x:' #[10]; ok1: x; call '~x' #[]; probe: do [x]; "
                 "(eq ok1 10) and (eq probe.status err)", True,
                 id="dynamic_set_delete"),
    pytest.param('op: `add`; v1: 2; v2: 3; '
                 'code: [call (inject op) #[(inject v1), (inject v2)]]; '
                 'run code',
                 5, id="inject_path"),
    pytest.param('v1: 4; v2: 6; '
                 'code: [(inject add) (inject v1) (inject v2)]; run code',
                 10, id="inject_function"),
    pytest.param('''name: 'Kael'; banner: "
      Hello, {{name}}!
    "; banner''', 'Hello, Kael!', id="lexical_interpolation"),
    pytest.param('my-var: 7; s: scope #{}; run-with [my-var: 1] s; '
                 'run-with [(inject my-var) + my-var] s', 8,
                 id="inject_reads_caller"),
])
def test_values(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == expected


def test_file_loaded_inject_statement_splice_and_argument_splice(tmp_path):
    (tmp_path / 'mod.slip').write_text(
        'x: (inject module-x)\n(splice extra-stmts)\n'
        'result: add (splice args)\nfinal: x + result + z\n',
    )
    with ScriptRunner() as runner:
        runner.source_dir = tmp_path
        result = runner.handle_script("""
            module-x: 5
            args: #[3, 4]
            extra-stmts: [y: 10; z: y * 2]
            code: file://./mod.slip
            run code
        """)
        assert result.status == 'ok', result.error_message
        assert result.value == 32


def test_file_loaded_inject_reads_caller_and_writes_target(tmp_path):
    (tmp_path / 'mod2.slip').write_text(
        'a: (inject seed)\nout: add (splice args)\na + out\n',
    )
    with ScriptRunner() as runner:
        runner.source_dir = tmp_path
        result = runner.handle_script("""
            seed: 2
            args: #[3, 4]
            code: file://./mod2.slip
            s: scope #{}
            res: run-with code s
            #[res, s.a]
        """)
        assert result.status == 'ok', result.error_message
        assert result.value == [9, 2]


@pytest.mark.parametrize('target', ["'zero'", '`zero`'])
def test_dynamic_zero_arity_call_uses_the_same_invocation_rule(target):
    with ScriptRunner() as runner:
        result = runner.handle_script(
            'zero: fn {} [42]; call ' + target + ' #[]',
        )
        assert result.status == 'ok', result.error_message
        assert result.value == 42
