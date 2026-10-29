import math

import pytest

from slip import ScriptRunner, slip_syntax as syntax
from slip.slip_core import Code, Scope, bind, execute
from slip.slip_library import SOURCE, library_scope


@pytest.mark.parametrize("source", [
    "none; true; false; -1; 1.25; 'a\\nb\\t\\\\c\\\'d'; '雪'",
    '"hello {{name}}!"; "a\\n{{1 + 2}}\\nend"',
    r'"hello {{\"world\"}}"',
    "[]; [x + 1]; [x: 1; x + 2]; (1 + 2); (x: 1; x)",
    "#[]; #{}; #[1, 'x', [y]]; #{'a.b': 1, nested: #[false, none]}",
    "fn {x: `number`, rest... |where x > 0} [x + 1]",
    "fn {this: Character, amount} [this.hp: - amount; this.hp]",
    "x: 1; /x; |map; ~obj.x; `obj.x:`; `~obj.x`; `|map`",
    "items[1]; items[(index + 1)].name; data(key); .hp",
    "items[.hp > 20].name; items[< 10]; xs[:]; xs[1:]; xs[:5]",
    "file://out.json#(content-type: 'application/json'): #{x: 1}",
    "https://example.test/data[0].name; https://example.test/put<- 1",
    "`file://source.slip`; `x#(flag: true)`; 'file://data': 7",
    SOURCE,
])
def test_symbolic_source_round_trip(source):
    code = syntax.parse(source)
    rendered = syntax.format_source(code)
    restored = syntax.parse(rendered)[0][0]
    assert isinstance(restored, Code)
    assert restored == code
    assert syntax.format_source(restored) == rendered
    assert code.stacks is None


def test_multiline_call_source_retains_statement_boundaries():
    source = """
        choose: fn {x} [
            if [x > 1] [y: x + 1; y * 2] [y: 0; y]
        ]
        #[choose 2, choose 0]
    """
    original = syntax.parse(source)
    rendered = syntax.format_source(original)
    assert "    " in rendered and "fn {x} [\n" in rendered
    restored = syntax.parse(rendered)[0][0]
    assert restored == original
    assert execute(restored, Scope(parent=library_scope())) == [6, 0]


def test_printing_bound_code_inspects_symbols_without_execution():
    scope = library_scope()

    def forbidden():
        raise AssertionError("printing executed a callable")

    scope["probe"] = forbidden
    bound = bind(syntax.parse("probe; 2 + 3"), scope)
    assert bound.stacks is not None
    assert syntax.parse(syntax.format_source(bound))[0][0] == bound


def test_symbolic_to_str_and_file_writing(tmp_path):
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        result = runner.handle_script("""
            code: [x: 40; x + 2]
            file://nested/code.slip: code
            #[to-str code, to-str `items[1:5]`, to-str {x: `number`}]
        """)
        assert result.status == "ok", result.error_message
        text, path, signature = result.value
        assert syntax.parse(text)[0][0] == runner.scope["code"]
        assert path == "`items[1:5]`"
        assert signature == "{x: `number`}"
        assert (tmp_path / "nested/code.slip").read_text() == text + "\n"
        loaded = runner.handle_script("file://nested/code.slip")
        assert loaded.status == "ok", loaded.error_message
        assert loaded.value.stacks is None
        assert loaded.value[0][0] == runner.scope["code"]
        assert "x" not in runner.scope
        evaluated = runner.handle_script(
            "run (run file://nested/code.slip)",
        )
        assert evaluated.status == "ok", evaluated.error_message
        assert evaluated.value == 42


def test_printed_data_is_valid_source_and_string_conversion_stays_text():
    with ScriptRunner() as runner:
        data = {"a.b": [True, None, "line\nquote'\\"], "file://x": 7}
        source = syntax.format_source(data)
        result = runner.handle_script(source)
        assert result.status == "ok", result.error_message
        assert result.value == data
        text = runner.handle_script("to-str 'hello'")
        assert text.status == "ok" and text.value == "hello"


def test_printer_rejects_runtime_objects_without_a_source_literal():
    with pytest.raises(TypeError, match="source"):
        syntax.format_source(object())


@pytest.mark.parametrize("number", [1e-20, 1e20, 0.0, 1.0, -0.0])
def test_float_source_preserves_values_without_exponent_syntax(number):
    with ScriptRunner() as runner:
        result = runner.handle_script(syntax.format_source(number))
        assert result.status == "ok", result.error_message
        assert type(result.value) is float and result.value == number
        assert math.copysign(1, result.value) == math.copysign(1, number)
