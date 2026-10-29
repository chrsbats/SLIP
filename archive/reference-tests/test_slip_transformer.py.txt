import pytest
from pathlib import Path
from koine import Parser

from slip.slip_transformer import SlipTransformer
from slip.slip_datatypes import (
    Code, List, IString,
    PathLiteral,
    GetPath, SetPath, DelPath, Name, Index, Slice, FilterQuery, Group,
    Root, Parent, Pwd, PipedPath, Sig, MultiSetPath
)

# --- Fixtures ---

@pytest.fixture(scope="module")
def parser():
    """Loads the SLIP grammar and returns a Parser instance."""
    grammar_path = Path(__file__).parent / ".." / "grammar" /  "slip_grammar.yaml"
    
    # Use Parser.from_file to correctly set the base path for subgrammars
    p = Parser.from_file(str(grammar_path))
    return p


@pytest.fixture(scope="module")
def transformer():
    """Returns a SlipTransformer instance."""
    return SlipTransformer()

# --- Comparison Helper ---

def compare_asts(actual, expected):
    """Recursively compares two transformed ASTs for structural equality."""
    assert type(actual) == type(expected), f"Type mismatch: {type(actual)} vs {type(expected)}"

    if isinstance(actual, (str, int, float, bool, type(None))):
        assert actual == expected
    elif actual in (Root, Parent, Pwd):
        assert actual is expected
    elif isinstance(actual, (list, tuple)):
        assert len(actual) == len(expected), "Sequence length mismatch"
        for a, e in zip(actual, expected):
            compare_asts(a, e)
    elif isinstance(actual, Code):
        compare_asts(actual.nodes, expected.nodes)
    elif isinstance(actual, List):
        compare_asts(actual.nodes, expected.nodes)
    elif isinstance(actual, Group):
        compare_asts(actual.nodes, expected.nodes)
    elif isinstance(actual, IString):
        assert str(actual) == str(expected)
    elif isinstance(actual, PathLiteral):
        assert actual == expected, "PathLiteral objects should be equal"
    elif isinstance(actual, PipedPath):
        assert actual == expected, "PipedPath objects should be equal"
    elif isinstance(actual, GetPath):
        assert actual == expected, "GetPath objects should be equal"
    elif isinstance(actual, SetPath):
        assert actual == expected, "SetPath objects should be equal"
    elif isinstance(actual, DelPath):
        assert actual == expected, "DelPath objects should be equal"
    elif isinstance(actual, Name):
        assert actual.text == expected.text
    elif isinstance(actual, Index):
        compare_asts(actual.expr_ast, expected.expr_ast)
    elif isinstance(actual, Slice):
        compare_asts(actual.start_ast, expected.start_ast)
        compare_asts(actual.end_ast, expected.end_ast)
    elif isinstance(actual, Sig):
        assert actual == expected
    else:
        pytest.fail(f"Cannot compare unknown type: {type(actual)}")

# --- Test Cases ---

TRANSFORMER_TEST_CASES = [
    (
        "literals_and_get_path_literal",
        "1 'raw' \"interp\" true none `a.b`",
        Code([[
            1,
            "raw",
            IString("interp"),
            True,
            None,
            PathLiteral(GetPath([Name('a'), Name('b')]))
        ]])
    ),
    (
        "set_path_literal",
        "`a.b:`",
        Code([[PathLiteral(SetPath([Name('a'), Name('b')]))]])
    ),
    (
        "del_path_literal",
        "`~a.b`",
        Code([[PathLiteral(DelPath(GetPath([Name('a'), Name('b')])))]])
    ),
    (
        "get_path_literal_with_meta",
        "`a#(m:1)`",
        Code([[PathLiteral(
            GetPath([Name('a')], meta=Group([[SetPath([Name('m')]), 1]])))
        ]])
    ),
    (
        "simple_lookup",
        "a.b",
        Code([[GetPath([Name('a'), Name('b')])]])
    ),
    (
        "set_path",
        "a.b: 1",
        Code([[SetPath([Name('a'), Name('b')]), 1]])
    ),
    (
        "del_path",
        "~a.b",
        Code([[DelPath(GetPath([Name('a'), Name('b')]))]])
    ),
    (
        "multi_set",
        "[a, b]: 1",
        Code([[('multi-set', [SetPath([Name('a')]), SetPath([Name('b')])]), 1]])
    ),
    (
        "containers",
        "[a] #[b] (c)",
        Code([[
            Code([[GetPath([Name('a')])]]),
            List([[GetPath([Name('b')])]]),
            Group([[GetPath([Name('c')])]])
        ]])
    ),
    (
        "sig_literal_keywords",
        "{a:1}",
        Code([[Sig([], {'a': 1}, None, None)]])
    ),
    (
        "sig_literal_positional_and_rest",
        "{x, y...}",
        Code([[Sig(['x'], {}, 'y', None)]])
    ),
    (
        "desugared_dict_hash",
        "#{a:1}",
        Code([[('dict', [[SetPath([Name('a')]), 1]])]])
    ),
    (
        "complex_path_lookup",
        "../data[i+1].(get-key)",
        Code([[
            GetPath([
                Parent,
                Name('data'),
                Index([GetPath([Name('i')]), GetPath([Name('+')]), 1]),
                Group([[GetPath([Name('get-key')])]])
            ])
        ]])
    ),
    (
        "path_with_singleton_segments",
        "/a |b ./c",
        Code([[
            GetPath([Root, Name('a')]),
            PipedPath([Name('b')]),
            GetPath([Pwd, Name('c')]),
        ]])
    ),
    (
        "slice_variants",
        "items[1:2] items[:3] items[4:]",
        Code([[
            GetPath([Name('items'), Slice([1], [2])]),
            GetPath([Name('items'), Slice(None, [3])]),
            GetPath([Name('items'), Slice([4], None)])
        ]])
    ),
    (
        "empty_slice",
        "items[:]",
        Code([[GetPath([Name('items'), Slice(None, None)])]])
    ),
    (
        "filter_query_transformer",
        "items[> 20]",
        Code([[GetPath([Name('items'), FilterQuery('>', [20])])]])
    ),
    (
        "path_literals_piped_and_multiset",
        "`|map` `[a,b]:`",
        Code([[PathLiteral(PipedPath([Name('map')]))], [PathLiteral(MultiSetPath([SetPath([Name('a')]), SetPath([Name('b')])]))]])
    ),
    (
        "sig_kwarg_union_value_literal",
        "{x: {A or B}}",
        Code([[Sig([], {'x': ('union', [GetPath([Name('A')]), GetPath([Name('B')])])}, None, None)]])
    ),
    (
        "sig_kwarg_conjunction_group",
        "{p: (Player and OnFire)}",
        Code([[Sig([], {'p': ('and', [GetPath([Name('Player')]), GetPath([Name('OnFire')])])}, None, None)]])
    ),
    (
        "fn_with_sig_union_annotation",
        "f: fn {x: {A or B}} []",
        Code([[
            SetPath([Name('f')]),
            GetPath([Name('fn')]),
            Sig([], {'x': ('union', [GetPath([Name('A')]), GetPath([Name('B')])])}, None, None),
            Code([])
        ]])
    ),
    (
        "sig_kwarg_mixed_union_of_and",
        "{x: (Player and OnFire) or Poisoned}",
        Code([[Sig([], {
            'x': ('union', [
                ('and', [GetPath([Name('Player')]), GetPath([Name('OnFire')])]),
                GetPath([Name('Poisoned')])
            ])
        }, None, None)]])
    ),
    (
        "sig_kwarg_mixed_and_with_union",
        "{x: Player and (OnFire or Poisoned)}",
        Code([[Sig([], {
            'x': ('and', [
                GetPath([Name('Player')]),
                ('union', [GetPath([Name('OnFire')]), GetPath([Name('Poisoned')])])
            ])
        }, None, None)]])
    )
]

# --- Test Function ---

@pytest.mark.parametrize(
    "test_id, source_code, expected_ast",
    TRANSFORMER_TEST_CASES,
    ids=[t[0] for t in TRANSFORMER_TEST_CASES]
)
def test_transformation(parser, transformer, test_id, source_code, expected_ast):
    """
    Tests that the transformer correctly converts a raw AST from the parser
    into a semantic AST composed of slip_datatypes objects.
    """
    try:
        raw_ast = parser.parse(source_code)
        transformed_ast = transformer.transform(raw_ast['ast'])
    except Exception as e:
        pytest.fail(f"Parsing or transformation failed unexpectedly for '{test_id}':\n{e}", pytrace=False)

    compare_asts(transformed_ast, expected_ast)
