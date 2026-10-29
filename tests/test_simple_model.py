"""Architectural acceptance of direct paths and bound operations."""

from unittest.mock import patch

import pytest

from slip import slip_core as core
from slip.slip_library import library_scope
from slip.slip_syntax import parse


def test_ordinary_nested_paths_do_not_enter_selection():
    scope = core.language_scope()
    scope["obj"] = {"child": {"hp": 10}}
    with patch.object(core, "targets", side_effect=AssertionError("select")):
        assert core.execute(parse("obj.child.hp"), scope) == 10
        assert core.execute(parse("obj.child.hp: 20"), scope) == 20
        assert core.execute(parse("obj.child.hp: + 2"), scope) == 22
        assert core.execute(parse("~obj.child.hp"), scope) == 22
        scope["field"] = "hp"
        assert core.execute(parse("obj.child.(field): 10"), scope) == 10
        assert core.execute(parse("obj.child.(field)"), scope) == 10
        assert core.execute(parse("~obj.child.(field)"), scope) == 10
        scope["index"], scope["rows"] = 0, [{"hp": 10}]
        assert core.execute(parse("rows[index].hp"), scope) == 10
        assert core.execute(parse("rows[index].hp: 20"), scope) == 20
        assert core.execute(parse("~rows[index].hp"), scope) == 20
    assert scope["obj"]["child"] == {}


def test_query_extension_does_not_reread_its_host_prefix():
    scope = core.language_scope()
    reads = []
    players = [{"hp": 10}, {"hp": 90}]

    class Host:
        def __getitem__(self, key):
            reads.append(key)
            return players

    scope["obj"] = Host()
    assert core.execute(parse("obj.players[.hp < 50].hp"), scope) == [10]
    assert reads == ["players"]
    reads.clear()
    result = core.execute(parse("obj.players[.hp < 50].hp: + 5"), scope)
    assert result == [15]
    assert reads == ["players"]
    assert players == [{"hp": 15}, {"hp": 90}]


def test_scalar_filter_keeps_the_already_read_value():
    scope = core.language_scope()
    reads = []

    class Host:
        def __getitem__(self, key):
            reads.append(key)
            return 10

    scope["obj"] = Host()
    assert core.execute(parse("obj.hp[< 50]"), scope) == [10]
    assert reads == ["hp"]


def test_scalar_filter_after_a_computed_key_keeps_its_original_target():
    scope = core.language_scope()
    scope["rows"], scope["index"] = [10, 90], 0
    assert core.execute(parse("rows[index][< 50]"), scope) == [10]
    result = core.execute(parse("rows[index][< 50]: + 5"), scope)
    assert result == [15]
    assert scope["rows"] == [15, 90]


@pytest.mark.parametrize(("source", "expected"), [
    ("#[1, 2 + 3]", [1, 5]), ("#{answer: 2 + 3}", {"answer": 5}),
    ('"answer {{2 + 3}}"', "answer 5"), ("(2 + 3)", 5),
])
def test_syntax_descriptors_become_getters(source, expected):
    scope = core.language_scope()
    symbolic = parse(source)
    saved = core.convert(symbolic[0], scope)
    assert isinstance(saved[0], core.Get)
    assert saved[0] is not symbolic[0][0]
    assert core.evaluate(list(reversed(saved)), scope) == expected


def test_grouped_function_results_stay_values_when_used_as_arguments():
    scope = core.language_scope()

    def identity(value):
        return value

    scope["identity"] = identity
    function = core.execute(parse("identity (fn {} [7])"), scope)
    assert isinstance(function, core.Lambda)
    assert function(scope=scope) == 7


def test_native_calls_need_no_runtime_signature_interpretation():
    scope = core.Scope(parent=library_scope())
    calls = []

    def contextual(value, *, scope):
        calls.append((value, scope))
        return value + 1

    scope["contextual"] = contextual
    saved = core.convert(parse("contextual 10")[0], scope)
    assert saved[0] is contextual
    with patch.object(core.inspect, "signature",
                      side_effect=AssertionError("sig")):
        assert core.evaluate(list(reversed(saved)), scope) == 11
        assert core.evaluate(list(reversed(saved)), scope) == 11
    assert calls == [(10, scope), (10, scope)]


def test_dynamic_assignment_stores_evaluated_function_data():
    scope = core.language_scope()
    calls = []

    def value():
        calls.append("called")
        return 7

    scope["values"] = [value]
    result = core.execute(parse("call 'saved:' values"), scope)
    assert result is value
    assert scope["saved"] is value
    assert calls == []
