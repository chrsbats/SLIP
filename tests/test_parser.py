import pytest
import yaml
from pathlib import Path
from koine import Parser

# --- Test Setup and Fixtures ---

@pytest.fixture(scope="module")
def parser():
    """Loads the SLIP grammar and returns a Parser instance."""
    grammar_path = Path(__file__).parent / ".." / "grammar" /  "slip_grammar.yaml"
    
    # Use Parser.from_file to correctly set the base path for subgrammars
    p = Parser.from_file(str(grammar_path))
    # with open("grammar/slip_grammar.yaml", "r") as f:
    #     grammar = yaml.safe_load(f)
    # # Create the parser
    # p = Parser(fro)
    return p

def clean_ast(node):
    """
    Recursively simplifies a raw AST node from Koine for stable comparison.
    - Unwraps the 'ast' key from Lark transformer results.
    - Removes location info ('line', 'col') and verbose text from non-leaf nodes.
    - Keeps 'tag' and 'children' for structural nodes.
    - Keeps 'tag' and 'value' for typed leaf nodes (number, bool, null).
    - Keeps 'tag' and 'text' for other leaf nodes (strings, paths).
    """
    if 'ast' in node:
        node = node['ast']

    if isinstance(node, list):
        # Filter out any None results from optional, discarded rules, and internal parser nodes
        return [cleaned for n in node if (cleaned := clean_ast(n)) is not None and not (isinstance(cleaned, dict) and "__" in cleaned.get("tag", ""))]

    if isinstance(node, dict) and 'tag' not in node: # It's a named children dict
        return {k: clean_ast(v) for k, v in node.items()}

    if not isinstance(node, dict) or 'tag' not in node:
        return node

    cleaned = {'tag': node['tag']}

    if 'children' in node:
        cleaned_children = clean_ast(node['children'])
        # Keep empty containers, but discard empty children from other nodes
        if cleaned_children or node.get('tag') in ('list', 'dict', 'sig', 'code', 'group'):
            cleaned['children'] = cleaned_children
    elif 'value' in node:
        cleaned['value'] = node['value']
    elif 'text' in node:
        if node.get('tag') not in ('pipe', 'root', 'parent', 'pwd', 'slice'):
            cleaned['text'] = node['text']

    return cleaned


# --- Test Cases ---

# Each entry is a tuple: (test_id, source_code, expected_cleaned_ast)
# The expected AST is what `clean_ast` should produce for the full, integrated parser.
TEST_CASES = [
    ("empty_program", "", {'tag': 'code', 'children': []}),
    ("program_with_only_comments", """
     -- line comment
     {-- block comment --}
     """, {'tag': 'code', 'children': []}),
    ("program_starts_with_multiline_comment", """{--
     first thing in file
     --}
     a: 1
     """, {'tag': 'code', 'children': [
        {'tag': 'expr', 'children': [
            {'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'a'}]},
            {'tag': 'number', 'value': 1}
        ]}
     ]}),
    ("multiline_and_nested_comments", """
     a {-- outer {-- inner --}
     still outer --} b
     """, {'tag': 'code', 'children': [
        {'tag': 'expr', 'children': [
            {'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'a'}]},
            {'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'b'}]}
        ]}
     ]}),
    ("program_with_semicolon_and_newline", "a:1; b:2\n c:3", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'a'}]}, {'tag': 'number', 'value': 1}]},
            {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'b'}]}, {'tag': 'number', 'value': 2}]},
            {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'c'}]}, {'tag': 'number', 'value': 3}]},
        ]
    }),
    ("flat_infix_expression", "10 + 5 * 2", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'number', 'value': 10},
                {'tag': 'get-path', 'children': [{'tag': 'name', 'text': '+'}]},
                {'tag': 'number', 'value': 5},
                {'tag': 'get-path', 'children': [{'tag': 'name', 'text': '*'}]},
                {'tag': 'number', 'value': 2},
            ]}
        ]
    }),
    ("grouped_expression", "10 + (5 * 2)", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'number', 'value': 10},
                {'tag': 'get-path', 'children': [{'tag': 'name', 'text': '+'}]},
                {'tag': 'group', 'children': [
                    {'tag': 'expr', 'children': [
                        {'tag': 'number', 'value': 5},
                        {'tag': 'get-path', 'children': [{'tag': 'name', 'text': '*'}]},
                        {'tag': 'number', 'value': 2},
                    ]}
                ]}
            ]}
        ]
    }),
    ("piped_expression", "data [x*2]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'data'}]},
                {'tag': 'code', 'children': [
                    {'tag': 'expr', 'children': [
                        {'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'x'}]},
                        {'tag': 'get-path', 'children': [{'tag': 'name', 'text': '*'}]},
                        {'tag': 'number', 'value': 2},
                    ]}
                ]}
            ]}
        ]
    }),
    ("all_literals", "1 -2.5 'raw' \"interp\" `a.b` true false none", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'number', 'value': 1},
                {'tag': 'number', 'value': -2.5},
                {'tag': 'string', 'text': 'raw'},
                {'tag': 'i-string', 'text': 'interp'},
                {'tag': 'path-literal', 'children': [
                    {'tag': 'SlipPath_any_embedded_path', 'children': [
                        {'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'a'}, {'tag': 'name', 'text': 'b'}]}
                    ]}
                ]},
                {'tag': 'boolean', 'value': True},
                {'tag': 'boolean', 'value': False},
                {'tag': 'null', 'value': None},
            ]}
        ]
    }),
    ("container_literals", "#[1,2] {a:1} #{b:2} [c:3]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'list', 'children': [
                    {'tag': 'expr', 'children': [{'tag': 'number', 'value': 1}]},
                    {'tag': 'expr', 'children': [{'tag': 'number', 'value': 2}]}
                ]},
                {
                  'tag': 'sig',
                  'children': [
                    {
                      'tag': 'sig-kwarg',
                      'children': {
                        'sig-key': {'tag': 'name', 'text': 'a'},
                        'value': {'tag': 'expr', 'text': '1'}
                      }
                    }
                  ]
                },
                {'tag': 'dict', 'children': [
                    {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'b'}]}, {'tag': 'number', 'value': 2}]}
                ]},
                {'tag': 'code', 'children': [
                    {'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'c'}]}, {'tag': 'number', 'value': 3}]}
                ]},
            ]}
        ]
    }),
    ("simple_assignment", "user.name: \"John\"", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'user'}, {'tag': 'name', 'text': 'name'}]},
                {'tag': 'i-string', 'text': 'John'}
            ]}
        ]
    }),
    ("destructuring_assignment", "[x, y.z]: #[1, 2]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'multi-set-path', 'children': [
                    {'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'x'}]},
                    {'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'y'}, {'tag': 'name', 'text': 'z'}]}
                ]},
                {'tag': 'list', 'children': [
                    {'tag': 'expr', 'children': [{'tag': 'number', 'value': 1}]},
                    {'tag': 'expr', 'children': [{'tag': 'number', 'value': 2}]}
                ]}
            ]}
        ]
    }),
    ("dynamic_assignment", "(get-path): 1", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [
                    {'tag': 'group', 'children': [
                        {'tag': 'expr', 'children': [
                            {'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'get-path'}]}
                        ]}
                    ]}
                ]},
                {'tag': 'number', 'value': 1}
            ]}
        ]
    }),
    ("complex_path", "../data[i+1].(get-key)", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'get-path', 'children': [
                    {'tag': 'parent'},
                    {'tag': 'name', 'text': 'data'},
                    {'tag': 'query-segment', 'children': [
                        {'tag': 'simple-query', 'children': [
                            {'tag': 'expr', 'children': [
                                {'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'i'}]},
                                {'tag': 'get-path', 'children': [{'tag': 'name', 'text': '+'}]},
                                {'tag': 'number', 'value': 1}
                            ]}
                        ]}
                    ]},
                    {'tag': 'group', 'children': [{'tag': 'expr', 'children': [{'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'get-key'}]}]}]}
                ]}
            ]}
        ]
    }),
    ("path_slicing", "items[1:4] items[:3] items[5:] items[:]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'get-path', 'children': [
                    {'tag': 'name', 'text': 'items'},
                    {'tag': 'query-segment', 'children': [
                        {'tag': 'slice-query', 'children': [
                            {'tag': 'start-expr', 'children': [{'tag': 'expr', 'children': [{'tag': 'number', 'value': 1}]}]},
                            {'tag': 'end-expr', 'children': [{'tag': 'expr', 'children': [{'tag': 'number', 'value': 4}]}]}
                        ]}
                    ]}
                ]},
                {'tag': 'get-path', 'children': [
                    {'tag': 'name', 'text': 'items'},
                    {'tag': 'query-segment', 'children': [
                        {'tag': 'slice-query', 'children': [
                            {'tag': 'start-expr'},
                            {'tag': 'end-expr', 'children': [{'tag': 'expr', 'children': [{'tag': 'number', 'value': 3}]}]}
                        ]}
                    ]}
                ]},
                {'tag': 'get-path', 'children': [
                    {'tag': 'name', 'text': 'items'},
                    {'tag': 'query-segment', 'children': [
                        {'tag': 'slice-query', 'children': [
                            {'tag': 'start-expr', 'children': [{'tag': 'expr', 'children': [{'tag': 'number', 'value': 5}]}]},
                            {'tag': 'end-expr'}
                        ]}
                    ]}
                ]},
                {'tag': 'get-path', 'children': [
                    {'tag': 'name', 'text': 'items'},
                    {'tag': 'query-segment', 'children': [
                        {'tag': 'slice-query', 'children': [
                            {'tag': 'start-expr'},
                            {'tag': 'end-expr'}
                        ]}
                    ]}
                ]},
            ]}
        ]
    }),
    ("del_statement", "~user.profile", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'del-path', 'children': [{'tag': 'name', 'text': 'user'}, {'tag': 'name', 'text': 'profile'}]}
            ]}
        ]
    }),
    ("dynamic_del_statement", "~(get-path)", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'del-path', 'children': [
                    {'tag': 'group', 'children': [
                        {'tag': 'expr', 'children': [
                            {'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'get-path'}]}
                        ]}
                    ]}
                ]}
            ]}
        ]
    }),
    ("get_path_with_metadata", "api/call#(timeout: 5)", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'get-path', 'children': [
                    {'tag': 'name', 'text': 'api'},
                    {'tag': 'name', 'text': 'call'},
                    {'tag': 'meta', 'children': [{'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'timeout'}]}, {'tag': 'number', 'value': 5}]}]}
                ]}
            ]}
        ]
    }),
    ("set_path_with_metadata", "user.name#(private: true): \"John\"", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'set-path', 'children': [
                    {'tag': 'name', 'text': 'user'},
                    {'tag': 'name', 'text': 'name'},
                    {'tag': 'meta', 'children': [{'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'private'}]}, {'tag': 'boolean', 'value': True}]}]}
                ]},
                {'tag': 'i-string', 'text': 'John'}
            ]}
        ]
    }),
    ("del_path_with_metadata", "~user.profile#(soft: true)", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'del-path', 'children': [
                    {'tag': 'name', 'text': 'user'},
                    {'tag': 'name', 'text': 'profile'},
                    {'tag': 'meta', 'children': [{'tag': 'expr', 'children': [{'tag': 'set-path', 'children': [{'tag': 'name', 'text': 'soft'}]}, {'tag': 'boolean', 'value': True}]}]}
                ]}
            ]}
        ]
    }),
    ("path_literals_all_forms", "`a.b` `c.d:` `~e.f`", {
        "tag": "code", "children": [
            {"tag": "expr", "children": [
                {"tag": "path-literal", "children": [
                    {"tag": "SlipPath_any_embedded_path", "children": [
                        {"tag": "get-path", "children": [{"tag": "name", "text": "a"}, {"tag": "name", "text": "b"}]}
                    ]}
                ]},
                {"tag": "path-literal", "children": [
                    {"tag": "SlipPath_any_embedded_path", "children": [
                        {"tag": "set-path", "children": [{"tag": "name", "text": "c"}, {"tag": "name", "text": "d"}]}
                    ]}
                ]},
                {"tag": "path-literal", "children": [
                    {"tag": "SlipPath_any_embedded_path", "children": [
                        {"tag": "del-path", "children": [{"tag": "name", "text": "e"}, {"tag": "name", "text": "f"}]}
                    ]}
                ]},
            ]}
        ]
    }),
    ("filter_query_integrated", "items[> 10]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'get-path', 'children': [
                    {'tag': 'name', 'text': 'items'},
                    {'tag': 'query-segment', 'children': [
                        {'tag': 'filter-query', 'children': [
                            {'tag': 'operator', 'text': '>'},
                            {'tag': 'rhs-expr', 'children': [
                                {'tag': 'expr', 'children': [
                                    {'tag': 'number', 'value': 10}
                                ]}
                            ]}
                        ]}
                    ]}
                ]}
            ]}
        ]
    }),
    ("path_literals_piped_and_multiset", "`|map` `[a,b]:`", {
        "tag": "code", "children": [
            {"tag": "expr", "children": [
                {"tag": "path-literal", "children": [
                    {"tag": "SlipPath_any_embedded_path", "children": [
                        {"tag": "piped-path", "children": [{"tag": "name", "text": "map"}]}
                    ]}
                ]},
                {"tag": "path-literal", "children": [
                    {"tag": "SlipPath_any_embedded_path", "children": [
                        {"tag": "multi-set-path", "children": [
                            {"tag": "set-path", "children": [{"tag": "name", "text": "a"}]},
                            {"tag": "set-path", "children": [{"tag": "name", "text": "b"}]}
                        ]}
                    ]}
                ]}
            ]}
        ]
    }),
    ("piped_expression_with_pipe", "data |map [x*2]", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'data'}]},
                {'tag': 'piped-path', 'children': [{'tag': 'name', 'text': 'map'}]},
                {'tag': 'code', 'children': [
                    {'tag': 'expr', 'children': [
                        {'tag': 'get-path', 'children': [{'tag': 'name', 'text': 'x'}]},
                        {'tag': 'get-path', 'children': [{'tag': 'name', 'text': '*'}]},
                        {'tag': 'number', 'value': 2},
                    ]}
                ]}
            ]}
        ]
    }),
    ("root_path_integrated", "/a/b", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'get-path', 'children': [
                    {'tag': 'root'},
                    {'tag': 'name', 'text': 'a'},
                    {'tag': 'name', 'text': 'b'}
                ]}
            ]}
        ]
    }),
    ("parent_path_chain_integrated", "../../x", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'get-path', 'children': [
                    {'tag': 'parent'},
                    {'tag': 'parent'},
                    {'tag': 'name', 'text': 'x'}
                ]}
            ]}
        ]
    }),
    ("predicate_name_integrated", "is-a?", {
        'tag': 'code', 'children': [
            {'tag': 'expr', 'children': [
                {'tag': 'get-path', 'children': [
                    {'tag': 'name', 'text': 'is-a?'}
                ]}
            ]}
        ]
    }),
    ("path_literal_with_metadata_simple", "`a#(m)`", {
        "tag": "code", "children": [
            {"tag": "expr", "children": [
                {"tag": "path-literal", "children": [
                    {"tag": "SlipPath_any_embedded_path", "children": [
                        {"tag": "get-path", "children": [
                            {"tag": "name", "text": "a"},
                            {"tag": "meta", "children": [
                                {"tag": "expr", "children": [
                                    {"tag": "get-path", "children": [{"tag": "name", "text": "m"}]}
                                ]}
                            ]}
                        ]}
                    ]}
                ]}
            ]}
        ]
    }),
    ("import_with_file_path_literal", "math1: import `file:///tmp/pytest-of-bats/pytest-66/test_import_file_module_caches0/math.slip`", {
        "tag": "code", "children": [
            {"tag": "expr", "children": [
                {"tag": "set-path", "children": [{"tag": "name", "text": "math1"}]},
                {"tag": "get-path", "children": [{"tag": "name", "text": "import"}]},
                {"tag": "path-literal", "children": [
                    {"tag": "SlipPath_get_path", "children": [
                        {"tag": "get-path", "children": [
                            {"tag": "name", "text": "file:///tmp/pytest-of-bats/pytest-66/test_import_file_module_caches0/math.slip"}
                        ]}
                    ]}
                ]}
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
