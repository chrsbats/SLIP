"""Remaining ordinary helpers and symbolic path/signature contracts."""

import pytest

from slip import ScriptRunner
from slip.slip_core import Scope, bind, execute, language_scope
from slip.slip_syntax import format_source, parse


@pytest.mark.parametrize(("source", "expected"), [
    ("cond #[#[[false], 'no'], #[[true], 'yes'], #[[missing], 'bad']]", "yes"),
    ("cond #[]", None),
    ("f: fn {x} [cond #[#[[x > 0], [x + 1]]]]; f 3", 4),
    ("x: 0; cond #[#[[true], [x: 7]]]; x", 7),
    ("join `a` `b.c` = `a.b.c`", True),
    ("join #[1, 2, 3] ':'", "1:2:3"),
    ("replace #[1, 2, 1] #[1] #[7]", [7, 2, 7]),
    ("original: #[#{n: 1}, 2]; out: replace original #[2] #[3]; "
     "out[0].n: 7; #[original[0].n, out[1]]", [1, 3]),
    ("find 'hello' 'missing'", None),
    ("[a, b]: #[3, 4]; #[a, b]", [3, 4]),
    ("[a, a]: #[1, 2]; a", 2),
    ("d: #{x: 0}; [d.x, y]: #[7, 9]; #[d.x, y]", [7, 9]),
    ("f: fn {} [[a, b]: #[3, 4]; a + b]; f", 7),
    ("obj: scope #{n: 7}; obj::n", 7),
    ("x: 9; f: fn {} [../x]; f", 9),
    ("f: fn {x} [./x]; f 7", 7),
    ("obj: scope #{}; obj['..']: 7; obj['..']", 7),
    ("kind: fn {x: {int or string}} ['typed']; kind: fn {x} ['other']; "
     "#[kind 1, kind 'a', kind true]", ["typed", "typed", "other"]),
    ("number: {int or float}; f: fn {x: number} [x]; #[f 1, f 1.5]", [1, 1.5]),
    ("Base: scope #{}; Child: create Base; obj: create Child; "
     "f: fn {x: Base and Child} [7]; f obj", 7),
    ("f: fn {x -> `int`} [x]; description: get-sig f; "
     "description.return-annotation = `int`", True),
    ("f: fn {x, y: `string`} [x]; s: get-sig f; "
     "#[s.positional, keys s.keywords]", [["x"], ["y"]]),
    ("f: fn {x: none} ['none']; f: fn {x} ['other']; "
     "#[f none, f 7]", ["none", "other"]),
    ("#[floor 1.7, ceil 1.2, trunc -1.7, round 1.234 2, sqrt 9, abs -4]",
     [1, 2, -1, 1.23, 3.0, 4]),
    ("2 |exp |to-int", 7),
    ("add: fn {a: int, b: int} [a + b]; "
     "is-code (get-body add {a: int, b: int})", True),
    ("xs: #[1, 2, 3, 4, 5]; xs[1:4]: #[20, 30]; xs", [1, 20, 30, 5]),
    ("xs: #[#{hp: 1}, #{hp: 2}]; xs.hp: #[7, 9]; xs.hp", [7, 9]),
    ("obj: scope #{n: 1}; eq (do [obj]).status ok", True),
    ("(#[#{n: 3}, #{n: 7}])[1].n", 7),
    ("(#[#{n: 3}, #{n: 7}])[.n > 4].n", [7]),
    ("obj: #{n: 3}; (obj).n: 7; obj.n", 7),
    ("inspect: fn {value, body} [#[value, is-code body]]; "
     "inspect (7) [8]", [7, True]),
    ("dist: fn {p} [p.x + p.y]; points: #[#{x: 3, y: 4}, #{x: 6, y: 8}]; "
     "points[|dist < 10]", [{"x": 3, "y": 4}]),
    ("xs: #[5, 10, 30]; xs[* 10 - 20 / 2 > 20]", [10, 30]),
    ("TypeX: scope #{}; #[TypeX.meta.name, TypeX.meta.type-id > 0]",
     ["TypeX", True]),
])
def test_remaining_documented_values(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == "ok", result.error_message
        assert result.value == expected


@pytest.mark.parametrize("source", [
    "../x; ./x; a::b; ../../x", "[a, b.x]: #[1, 2]",
    "{x: {int or string}, rest... -> `int`}",
    "{x: Base and (Child or Other)}", "{int or float}",
    "{x: (Base and Child)}", "{x: (int or string)}",
    "(do [1]).status; (#[1, 2])[0]; (#[#{n: 3}])[.n > 2].n",
])
def test_remaining_symbolic_source_round_trip(source):
    code = parse(source)
    assert parse(format_source(code))[0][0] == code
    assert code.stacks is None


def test_destructuring_reads_rhs_once_and_keeps_value_identity():
    scope = language_scope()
    child = {"n": 1}
    calls = []

    def values():
        calls.append("read")
        return [child, 7]

    scope["values"] = values
    assert execute(parse("[a, b]: values; b"), scope) == 7
    assert scope["a"] is child and calls == ["read"]


def test_grouped_path_base_is_live_bound_once_and_read_once(monkeypatch):
    from slip import slip_core

    scope = language_scope()
    calls = []
    current = {"value": {"n": 3}}

    def current_value():
        calls.append("read")
        return current["value"]

    scope["current-value"] = current_value
    code = bind(parse("(current-value).n"), scope)
    assert calls == []

    def forbidden(*args):
        raise AssertionError("warm grouped path rebound its source")

    monkeypatch.setattr(slip_core, "convert", forbidden)
    assert execute(code, scope) == 3
    current["value"] = {"n": 7}
    assert execute(code, scope) == 7
    assert calls == ["read", "read"]


@pytest.mark.parametrize("source", ["obj::n: 7", "~obj::n"])
def test_identity_paths_are_read_only(source):
    scope = Scope({"obj": {"n": 1}}, parent=language_scope())
    with pytest.raises(PermissionError, match="read-only"):
        execute(parse(source), scope)
    assert scope["obj"]["n"] == 1
