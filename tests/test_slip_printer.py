import pytest
from slip.slip_printer import Printer
from slip.slip_datatypes import (
    Code, List, IString, SlipFunction, Response,
    PathLiteral,
    GetPath, SetPath, DelPath, Name, Index, Slice, FilterQuery, Group,
    PipedPath, Root, Parent, Pwd, Scope, MultiSetPath
)
from slip.slip_runtime import SlipObject

@pytest.fixture
def printer():
    return Printer(indent_width=2)

# Test cases: (id, object, expected_string)
FORMAT_TEST_CASES = [
    ("str", "hello", "'hello'"),
    ("istr", IString("hello"), '"hello"'),
    ("int", 123, "123"),
    ("float", -1.5, "-1.5"),
    ("bool_true", True, "true"),
    ("bool_false", False, "false"),
    ("none", None, "none"),
    (
        "simple_get_path_literal",
        PathLiteral(GetPath([Name("a"), Name("b")])),
        "`a.b`"
    ),
    (
        "complex_get_path_literal",
        PathLiteral(GetPath([Parent, Name("data"), Index([1]), Group([[GetPath([Name('k')])]])])),
        "`../data[1](k)`"
    ),
    (
        "simple_set_path_literal",
        PathLiteral(SetPath([Name("a"), Name("b")])),
        "`a.b:`"
    ),
    (
        "simple_del_path_literal",
        PathLiteral(DelPath(GetPath([Name("a")]))),
        "`~a`"
    ),
    (
        "piped_path_lookup",
        PipedPath([Name("map")]),
        "|map"
    ),
    (
        "simple_lookup",
        GetPath([Name("a"), Name("b")]),
        "a.b"
    ),
    (
        "simple_set_path",
        SetPath([Name("a")]),
        "a:"
    ),
    (
        "simple_set_expr",
        [SetPath([Name("a")]), 1],
        "a: 1"
    ),
    (
        "simple_del_expr",
        [DelPath(GetPath([Name("a")]))],
        "~a"
    ),
    (
        "multi_set",
        [('multi-set', [SetPath([Name("a")]), SetPath([Name("b")])]), List([])],
        "[a,b]: #[]"
    ),
    (
        "simple_expr",
        [GetPath([Name('a')]), GetPath([Name('+')]), 1],
        "a + 1"
    ),
    (
        "empty_code",
        Code([]),
        "[]"
    ),
    (
        "nested_code",
        Code([
            [SetPath([Name('x')]), 1],
            [GetPath([Name('x')])]
        ]),
        "[\n  x: 1\n  x\n]"
    ),
    (
        "empty_list",
        List([]),
        "#[]"
    ),
    (
        "simple_list",
        List([1, True]),
        "#[\n  1\n  true\n]"
    ),
    (
        "empty_dict",
        SlipObject({}),
        "{}"
    ),
    (
        "simple_dict",
        SlipObject({'a': 1, 'b': 'foo'}),
        "{\n  a: 1\n  b: 'foo'\n}"
    ),
    (
        "response",
        Response(PathLiteral(GetPath([Name("ok")])), 42),
        "response `ok` 42"
    ),
    (
        "slip_function",
        SlipFunction(Code([[GetPath([Name('x')])]]), Code([]), Scope()),
        "fn [x] []"
    ),
    (
        "control_flow_if_assigned",
        [
            SetPath([Name('config')]),
            [
                GetPath([Name('if')]),
                Code([[GetPath([Name('a')])]]),
                Code([ [SetPath([Name('x')]), 1] ]),
                Code([ [SetPath([Name('x')]), 2] ])
            ]
        ],
        "config: if [a]\n"
        "  [\n"
        "    x: 1\n"
        "  ]\n"
        "  [\n"
        "    x: 2\n"
        "  ]"
    ),
    (
        "slice",
        PathLiteral(GetPath([Name("items"), Slice([1], [5])])),
        "`items[1:5]`"
    ),
    (
        "slice_open_end",
        PathLiteral(GetPath([Name("items"), Slice([1], None)])),
        "`items[1:]`"
    ),
    (
        "slice_open_start",
        PathLiteral(GetPath([Name("items"), Slice(None, [5])])),
        "`items[:5]`"
    ),
    (
        "slice_empty",
        PathLiteral(GetPath([Name("items"), Slice(None, None)])),
        "`items[:]`"
    ),
    (
        "filter_query_path_literal",
        PathLiteral(GetPath([Name("items"), FilterQuery('>', [20])])),
        "`items[> 20]`"
    )
]

@pytest.mark.parametrize(
    "test_id, obj, expected",
    FORMAT_TEST_CASES,
    ids=[t[0] for t in FORMAT_TEST_CASES]
)
def test_pformat(printer, test_id, obj, expected):
    assert printer.pformat(obj) == expected
