import pytest
import yaml
from pathlib import Path
from koine import Parser

# --- Test Setup and Fixtures ---

@pytest.fixture(scope="module")
def parser():
    """Loads the SLIP grammar and returns a Parser instance."""
    grammar_path = Path(__file__).parent / "slip_grammar.yaml"
    with grammar_path.open() as f:
        grammar_def = yaml.safe_load(f)

    # Create the parser
    p = Parser(grammar_def)

    return p

def clean_ast(node):
    """
    Recursively removes location info ('line', 'col') and verbose text from non-leaf
    nodes to make AST comparison in tests simpler and more focused on structure.
    """
    if 'ast' in node: 
        node = node['ast']
    if isinstance(node, list):
        return [clean_ast(n) for n in node]
    if not isinstance(node, dict):
        return node

    # It's a dict (an AST node)
    new_node = {}
    if 'tag' in node:
        new_node['tag'] = node['tag']

    # For leaf nodes, capture the essential value (typed or text)
    if 'children' not in node:
        if 'value' in node:
            new_node['value'] = node['value']
        elif 'tag' in node and node.get('tag') != 'pipe': # Leaf without a type, like a 'name'
            new_node['text'] = node['text']

    # For branch nodes, recurse on children
    if 'children' in node:
        new_node['children'] = clean_ast(node['children'])

    return new_node

# --- Test Cases ---

# Each entry is a tuple: (test_id, source_code, expected_cleaned_ast)
# The expected AST is what `clean_ast` should produce.
TEST_CASES = [
    # ----------------------------------------------------------------
    # Basic Structure & Comments
    # ----------------------------------------------------------------
    ("empty_program", "", {'tag': 'code', 'children': []}),
    ("program_with_only_comments", """
     // line comment
     /* block comment */
     """, {'tag': 'code', 'children': []}),
    ("program_with_semicolon_and_newline", "a:1; b:2\n c:3", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'a'}]}, {'tag': 'number', 'value': 1}]},
            {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'b'}]}, {'tag': 'number', 'value': 2}]},
            {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'c'}]}, {'tag': 'number', 'value': 3}]},
        ]
    }),
    ("program_with_trailing_separator", "a:1; \n", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'a'}]},
                {'tag': 'number', 'value': 1}
            ]}
        ]
    }),
    ("comments_inline", "x: 1 /* block */ + 2 // line", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'x'}]},
                {'tag': 'number', 'value': 1},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': '+'}]},
                {'tag': 'number', 'value': 2},
            ]}
        ]
    }),

    # ----------------------------------------------------------------
    # Expressions (Flat & Grouped)
    # ----------------------------------------------------------------
    ("flat_infix_expression", "10 + 5 * 2", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'number', 'value': 10},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': '+'}]},
                {'tag': 'number', 'value': 5},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': '*'}]},
                {'tag': 'number', 'value': 2},
            ]}
        ]
    }),
    ("grouped_expression", "10 + (5 * 2)", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'number', 'value': 10},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': '+'}]},
                {'tag': 'expr', 'children': [
                    {'tag': 'number', 'value': 5},
                    {'tag': 'path', 'children': [{'tag': 'name', 'text': '*'}]},
                    {'tag': 'number', 'value': 2},
                ]}
            ]}
        ]
    }),
    ("chained_prefix_is_flat", "add 1 add 2", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'add'}]},
                {'tag': 'number', 'value': 1},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'add'}]},
                {'tag': 'number', 'value': 2},
            ]}
        ]
    }),
    ("piped_expression", "data |map [x*2]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'data'}]},
                {'tag': 'path', 'children': [
                    {'tag': 'pipe'},
                    {'tag': 'name', 'text': 'map'}
                ]},
                {'tag': 'code', 'children': [
                    {'tag': 'expr', 'children': [
                        {'tag': 'path', 'children': [{'tag': 'name', 'text': 'x'}]},
                        {'tag': 'path', 'children': [{'tag': 'name', 'text': '*'}]},
                        {'tag': 'number', 'value': 2},
                    ]}
                ]}
            ]}
        ]
    }),

    # ----------------------------------------------------------------
    # Literals
    # ----------------------------------------------------------------
    ("all_literals", "1 -2.5 'raw' \"interp\" `a.b` true false none", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'number', 'value': 1},
                {'tag': 'number', 'value': -2.5},
                {'tag': 'string', 'text': 'raw'},
                {'tag': 'i-string', 'text': 'interp'},
                {'tag': 'path-literal', 'children': [
                    {'tag': 'name', 'text': 'a'},
                    {'tag': 'name', 'text': 'b'},
                ]},
                {'tag': 'boolean', 'value': True},
                {'tag': 'boolean', 'value': False},
                {'tag': 'null', 'value': None},
            ]}
        ]
    }),

    # ----------------------------------------------------------------
    # Containers
    # ----------------------------------------------------------------
    ("container_literals", "#[1,2] {a:1} #{b:2} [c:3]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'list', 'children': [{'tag': 'number', 'value': 1}, {'tag': 'number', 'value': 2}]},
                {'tag': 'dict', 'children': [
                    {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'a'}]}, {'tag': 'number', 'value': 1}]}
                ]},
                {'tag': 'env', 'children': [
                    {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'b'}]}, {'tag': 'number', 'value': 2}]}
                ]},
                {'tag': 'code', 'children': [
                    {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'c'}]}, {'tag': 'number', 'value': 3}]}
                ]},
            ]}
        ]
    }),
    ("empty_containers", "#[] {} #{} [] ()", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'list', 'children': []},
                {'tag': 'dict', 'children': []},
                {'tag': 'env', 'children': []},
                {'tag': 'code', 'children': []},
                {'tag': 'expr', 'children': []},
            ]}
        ]
    }),

    # ----------------------------------------------------------------
    # Assignment
    # ----------------------------------------------------------------
    ("simple_assignment", "user.name: \"John\"", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [
                    {'tag': 'name', 'text': 'user'},
                    {'tag': 'name', 'text': 'name'}
                ]},
                {'tag': 'i-string', 'text': 'John'}
            ]}
        ]
    }),
    ("multiset_assignment", "[x, y]: #[1, 2]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'multi-set', 'children': [
                    {'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'x'}]},
                    {'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'y'}]}
                ]},
                {'tag': 'list', 'children': [{'tag': 'number', 'value': 1}, {'tag': 'number', 'value': 2}]}
            ]}
        ]
    }),
    ("dynamic_assignment", "(get-path): 1", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'expr', 'children': [
                    {'tag': 'path', 'children': [{'tag': 'name', 'text': 'get-path'}]}
                ]},
                {'tag': 'number', 'value': 1}
            ]}
        ]
    }),

    # ----------------------------------------------------------------
    # Paths
    # ----------------------------------------------------------------
    ("complex_path", "../data[i+1].(get-key)", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [
                    {'tag': 'parent', 'text': '../'},
                    {'tag': 'name', 'text': 'data'},
                    {'tag': 'index', 'children': [
                        {'tag': 'expr', 'children': [
                            {'tag': 'path', 'children': [{'tag': 'name', 'text': 'i'}]},
                            {'tag': 'path', 'children': [{'tag': 'name', 'text': '+'}]},
                            {'tag': 'number', 'value': 1}
                        ]}
                    ]},
                    {'tag': 'expr', 'children': [
                        {'tag': 'path', 'children': [{'tag': 'name', 'text': 'get-key'}]}
                    ]}
                ]}
            ]}
        ]
    }),
    ("path_slicing", "items[1:4] items[:3] items[5:] items[:]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [
                    {'tag': 'name', 'text': 'items'},
                    {'tag': 'slice', 'children': [
                        {'tag': 'expr', 'children': [{'tag': 'number', 'value': 1}]},
                        {'tag': 'expr', 'children': [{'tag': 'number', 'value': 4}]}
                    ]}
                ]},
                {'tag': 'path', 'children': [
                    {'tag': 'name', 'text': 'items'},
                    {'tag': 'slice', 'children': [
                        {'tag': 'expr', 'children': [{'tag': 'number', 'value': 3}]}
                    ]}
                ]},
                {'tag': 'path', 'children': [
                    {'tag': 'name', 'text': 'items'},
                    {'tag': 'slice', 'children': [
                        {'tag': 'expr', 'children': [{'tag': 'number', 'value': 5}]}
                    ]}
                ]},
                {'tag': 'path', 'children': [
                    {'tag': 'name', 'text': 'items'},
                    {'tag': 'slice', 'children': []}
                ]}
            ]}
        ]
    }),
    ("variadic_parameter", "fn [tags...] []", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'fn'}]},
                {'tag': 'code', 'children': [
                    {'tag': 'expr', 'children': [
                        {'tag': 'path', 'children': [{'tag': 'name', 'text': 'tags...'}]}
                    ]}
                ]},
                {'tag': 'code', 'children': []},
            ]}
        ]
    }),
    ("operator_path", "a + b / c", { # note / must be spaced
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'a'}]},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': '+'}]},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'b'}]},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': '/'}]},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'c'}]},
            ]}
        ]
    }),

    # ----------------------------------------------------------------
    # Assignment (Advanced)
    # ----------------------------------------------------------------
    ("assignment_to_slice", "items[1:3]: #[99]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [
                    {'tag': 'name', 'text': 'items'},
                    {'tag': 'slice', 'children': [
                        {'tag': 'expr', 'children': [{'tag': 'number', 'value': 1}]},
                        {'tag': 'expr', 'children': [{'tag': 'number', 'value': 3}]}
                    ]}
                ]},
                {'tag': 'list', 'children': [{'tag': 'number', 'value': 99}]}
            ]}
        ]
    }),
    ("vectorized_assignment", "users[:10].is-active: false", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [
                    {'tag': 'name', 'text': 'users'},
                    {'tag': 'slice', 'children': [
                        {'tag': 'expr', 'children': [{'tag': 'number', 'value': 10}]}
                    ]},
                    {'tag': 'name', 'text': 'is-active'}
                ]},
                {'tag': 'boolean', 'value': False}
            ]}
        ]
    }),
    ("parent_scope_assignment", "../counter: 1", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [
                    {'tag': 'parent', 'text': '../'},
                    {'tag': 'name', 'text': 'counter'}
                ]},
                {'tag': 'number', 'value': 1}
            ]}
        ]
    }),
    ("operator_definition", "/+: |add", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [
                    {'tag': 'root', 'text': '/'},
                    {'tag': 'name', 'text': '+'}
                ]},
                {'tag': 'path', 'children': [
                    {'tag': 'pipe'},
                    {'tag': 'name', 'text': 'add'}
                ]}
            ]}
        ]
    }),
    ("empty_multiset_assignment", "[]: #[]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'multi-set', 'children': []},
                {'tag': 'list', 'children': []}
            ]}
        ]
    }),

    # ----------------------------------------------------------------
    # Paths (Advanced)
    # ----------------------------------------------------------------
    ("root_path_read", "/config.path", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [
                    {'tag': 'root', 'text': '/'},
                    {'tag': 'name', 'text': 'config'},
                    {'tag': 'name', 'text': 'path'}
                ]}
            ]}
        ]
    }),
    ("pwd_path_read", "./file", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [
                    {'tag': 'pwd', 'text': './'},
                    {'tag': 'name', 'text': 'file'}
                ]}
            ]}
        ]
    }),
    ("nestable_block_comments", "a: /* outer /* inner */ outer */ 1", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'a'}]},
                {'tag': 'number', 'value': 1}
            ]}
        ]
    }),

    # ----------------------------------------------------------------
    # Integration Tests (common constructs)
    # ----------------------------------------------------------------
    ("full_function_definition", "double: fn [x] [ x * 2 ]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'double'}]},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'fn'}]},
                {'tag': 'code', 'children': [
                    {'tag': 'expr', 'children': [
                        {'tag': 'path', 'children': [{'tag': 'name', 'text': 'x'}]}
                    ]}
                ]},
                {'tag': 'code', 'children': [
                    {'tag': 'expr', 'children': [
                        {'tag': 'path', 'children': [{'tag': 'name', 'text': 'x'}]},
                        {'tag': 'path', 'children': [{'tag': 'name', 'text': '*'}]},
                        {'tag': 'number', 'value': 2}
                    ]}
                ]}
            ]}
        ]
    }),
    ("if_statement", "if condition [then] [else]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'if'}]},
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'condition'}]},
                {'tag': 'code', 'children': [
                    {'tag': 'expr', 'children': [
                        {'tag': 'path', 'children': [{'tag': 'name', 'text': 'then'}]}
                    ]}
                ]},
                {'tag': 'code', 'children': [
                    {'tag': 'expr', 'children': [
                        {'tag': 'path', 'children': [{'tag': 'name', 'text': 'else'}]}
                    ]}
                ]}
            ]}
        ]
    }),

    # ----------------------------------------------------------------
    # Core Primitives
    # ----------------------------------------------------------------
    ("del_statement", "del user.profile", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'del'}]},
                {'tag': 'path', 'children': [
                    {'tag': 'name', 'text': 'user'},
                    {'tag': 'name', 'text': 'profile'}
                ]}
            ]}
        ]
    }),
    ("return_statement", "return 42", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'return'}]},
                {'tag': 'number', 'value': 42}
            ]}
        ]
    }),
    ("return_statement_no_value", "return", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'path', 'children': [{'tag': 'name', 'text': 'return'}]}
            ]}
        ]
    }),
]

# --- Pytest Test Function ---

@pytest.mark.parametrize("test_id, source_code, expected_ast", TEST_CASES, ids=[t[0] for t in TEST_CASES])
def test_parsing(parser: Parser, test_id: str, source_code: str, expected_ast: dict):
    """
    Parses a given source code string and compares the cleaned AST
    against the expected AST structure.
    """
    try:
        # On success, parser.parse() returns the AST dictionary directly.
        result_ast = parser.parse(source_code)
    except Exception as e:
        # On failure, it should raise an exception.
        # We use pytest.fail to provide a rich error message for unexpected failures.
        pytest.fail(f"Parsing failed unexpectedly for '{test_id}':\n{e}", pytrace=False)

    # Clean the resulting AST to remove location info for stable comparison
    cleaned_result_ast = clean_ast(result_ast)
    if cleaned_result_ast != expected_ast:
        # When an assertion fails, print the cleaned AST for easier debugging.
        import json
        print("\n" + "="*20 + " AST Diff " + "="*20)
        print(f"Test ID: {test_id}")
        print("----- Actual (Cleaned) -----")
        print(json.dumps(cleaned_result_ast, indent=2))
        print("----- Expected -----")
        print(json.dumps(expected_ast, indent=2))
        print("="*50)

    assert cleaned_result_ast == expected_ast
