"""Chapter 008 and non-authority where-sugar behavior.

Example-driven type synthesis is deferred by the user's explicit decision;
the typed-guard counterpart below uses a declared signature.
"""

import pytest

from slip.slip_core import Path, PathLiteral
from slip import ScriptRunner
from slip.slip_syntax import format_source


@pytest.mark.parametrize(("source", "expected"), [
    pytest.param("x: 42; x#(timeout: 2)", 42, id="008_get_metadata"),
    pytest.param("y: 0; y#(note: 'tmp'): 123; y", 123,
                 id="008_set_metadata"),
    pytest.param("f: fn {x} [x]; example f {x: 1 -> 1}; len f.meta.examples",
                 1, id="008_attach_example"),
    pytest.param("add: fn {a, b} [a + b] |example {a: 2, b: 3 -> 5} "
                 "|example {a: 2.5, b: 3.5 -> 6.0}; #[add 2 3, add 2.5 3.5]",
                 [5, 6.0], id="008_example_inputs_still_call_normally"),
    pytest.param("f: fn {x} ['global']; a: 1; "
                 "g: fn {} [f: fn {x} ['local']; a: 2; #[f 10, a]]; "
                 "#[f 1, a, g]", ['global', 1, ['local', 2]],
                 id="008_local_shadowing"),
    pytest.param("choose: fn {x} ['general']; "
                 "choose: fn {x} ['guarded'] |where [x > 10]; "
                 "#[choose 5, choose 15]", ['general', 'guarded'],
                 id="008_guard_priority"),
    pytest.param("choose: fn {x} ['ok'] |where [x > 0] |where [x < 10]; "
                 "choose: fn {x} ['fallback']; "
                 "#[choose -1, choose 5, choose 15]",
                 ['fallback', 'ok', 'fallback'], id="008_multiple_guards"),
    pytest.param("add: fn {a: `int`, b: `int`} ['guarded'] "
                 "|where [a > b] |example {a: 2, b: 1 -> 'guarded'}; "
                 "add: fn {a: `int`, b: `int`} ['plain']; #[add 2 1, add 1 2]",
                 ['guarded', 'plain'], id="008_explicit_typed_example_guard"),
    pytest.param("y: 10; f: fn {x} ['gt'] |where [x > y]; "
                 "f: fn {x} ['fallback']; #[f 20, f 5]", ['gt', 'fallback'],
                 id="008_lexical_guard"),
    pytest.param("choose: fn {x} ['parent']; runner: fn {} ["
                 "choose: fn {x} ['local']; "
                 "choose: fn {x} ['special'] |where [x = 42]; "
                 "#[choose 42, choose 1]]; #[choose 42, runner]",
                 ['parent', ['special', 'local']], id="008_generic_shadowing"),
    pytest.param("(true and false)", False, id="where_infix_and"),
    pytest.param("gt-10: fn {n |where n > 10} [true]; "
                 "gt-10: fn {n} [false]; #[gt-10 15, gt-10 5]", [True, False],
                 id="where_basic"),
    pytest.param("check: fn {n |where n > 10 and (n < 20)} [`in-range`]; "
                 "check: fn {n} [`out-of-range`]; "
                 "#[check 15, check 5, check 25]",
                 [PathLiteral(Path([name])) for name in (
                     'in-range', 'out-of-range', 'out-of-range',
                 )], id="where_multiple_conditions"),
    pytest.param("limit: 100; over-limit: fn {n |where n > limit} [true]; "
                 "over-limit: fn {n} [false]; "
                 "#[over-limit 150, over-limit 50]",
                 [True, False], id="where_lexical_scope"),
])
def test_values(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == expected


def test_delete_metadata_still_removes_the_binding():
    with ScriptRunner() as runner:
        result = runner.handle_script("z: 7; ~z#(soft-delete: true); z")
        assert result.status == 'err'
        assert "z" in result.error_message
        assert 'z' not in runner.scope.bindings


def test_literal_metadata_round_trips_with_native_values():
    with ScriptRunner() as runner:
        result = runner.handle_script('`a#(flag: true)`')
        assert result.status == 'ok', result.error_message
        assert isinstance(result.value, PathLiteral)
        assert format_source(result.value) == '`a#(flag: true)`'


def test_guard_keywords_rest_and_failed_dispatch():
    with ScriptRunner() as runner:
        result = runner.handle_script("""
            compute: fn {a, b, rest...} ['ok']
                |where [a = 1] |where [(len rest) > 0]
            compute: fn {a, b} ['fallback']
            #[compute 1 2, compute 1 2 3, compute 2 2 9]
        """)
        assert result.status == 'err'
        assert 'No matching method' in result.error_message


def test_repeated_where_clauses_inside_one_signature_are_invalid():
    with ScriptRunner() as runner:
        result = runner.handle_script(
            'f: fn {n |where n > 0 |where n < 10} [n]',
        )
        assert result.status == 'err'
