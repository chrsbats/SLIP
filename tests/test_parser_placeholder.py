import pytest
import yaml
import json
from koine.parser import PlaceholderParser

# =================================================================
# Setup and Helper Functions
# =================================================================

@pytest.fixture(scope="module")
def parser():
    """Provides a parser instance for the new structural grammar."""
    with open("grammar/slip_grammar.yaml", "r") as f:
        grammar = yaml.safe_load(f)
    return PlaceholderParser(grammar)

def clean_ast(node):
    """
    Recursively simplifies a raw AST node from Koine for stable comparison.
    - Removes location info ('line', 'col', 'text' from non-leaf nodes).
    - Keeps 'tag' and 'children' for structural nodes.
    - Keeps 'tag' and 'value' for typed leaf nodes (number, bool, null).
    - Keeps 'tag' and 'text' for other leaf nodes (strings, paths).
    """
    if isinstance(node, list):
        return [clean_ast(n) for n in node]

    if not isinstance(node, dict):
        return node

    cleaned = {'tag': node['tag']}
    
    if 'children' in node:
        cleaned['children'] = clean_ast(node['children'])
    elif 'value' in node:
        cleaned['value'] = node['value']
    elif 'text' in node:
        cleaned['text'] = node['text']
        
    return cleaned

def _run_structural_test(parser, test_id, source_and_expected_yaml):
    """Helper to run a single structural parsing test."""
    try:
        source_code, expected_yaml = source_and_expected_yaml.strip().split('---', 1)
        source_code = source_code.strip()
        expected_ast = yaml.safe_load(expected_yaml)
    except (ValueError, yaml.YAMLError) as e:
        pytest.fail(f"Invalid test case format for '{test_id}': {e}", pytrace=False)

    try:
        parse_result = parser.parse(source_code)
        if parse_result.get("status") != "success":
            error_info = parse_result.get("error_message", str(parse_result))
            pytest.fail(f"Parsing failed for '{test_id}':\n{error_info}", pytrace=False)
        result_ast = parse_result["ast"]
    except Exception as e:
        pytest.fail(f"Parsing failed unexpectedly for '{test_id}':\n{e}", pytrace=False)

    cleaned_result_ast = clean_ast(result_ast)

    if cleaned_result_ast != expected_ast:
        print("\n" + "="*20 + " AST Diff " + "="*20)
        print(f"Test ID: {test_id}")
        print("----- Source Code -----")
        print(source_code)
        print("----- Actual (Cleaned) -----")
        print(json.dumps(cleaned_result_ast, indent=2))
        print("----- Expected -----")
        print(json.dumps(expected_ast, indent=2))
        print("="*50)

    assert cleaned_result_ast == expected_ast

# =================================================================
# Test Cases for the Structural Grammar
# =================================================================

def test_empty_program(parser):
    case = """

---
tag: code
children: []
"""
    _run_structural_test(parser, "empty_program", case)

def test_program_with_only_comments(parser):
    case = """
-- line comment
{-- block comment --}
---
tag: code
children: []
"""
    _run_structural_test(parser, "program_with_only_comments", case)

def test_simple_get_path_expression(parser):
    case = """
a b c
---
tag: code
children:
  - tag: expr
    children:
      - tag: get-path
        text: a
      - tag: get-path
        text: b
      - tag: get-path
        text: c
"""
    _run_structural_test(parser, "simple_get_path_expression", case)

def test_multi_line_expressions(parser):
    case = """
a:1; b |c
~d
---
tag: code
children:
  - tag: expr
    children:
      - tag: set-path
        text: 'a:'
      - tag: number
        value: 1
  - tag: expr
    children:
      - tag: get-path
        text: b
      - tag: piped-path
        text: "|c"
  - tag: expr
    children:
      - tag: del-path
        text: "~d"
"""
    _run_structural_test(parser, "multi_line_expressions", case)

def test_all_literals(parser):
    case = """
1 -2.5 'raw' "interp" true false none `a.path`
---
tag: code
children:
  - tag: expr
    children:
      - tag: number
        value: 1
      - tag: number
        value: -2.5
      - tag: string
        text: raw
      - tag: i-string
        text: interp
      - tag: boolean
        value: true
      - tag: boolean
        value: false
      - tag: 'null'
        value: null
      - tag: path-literal
        children:
          - tag: path-placeholder
            text: a.path
"""
    _run_structural_test(parser, "all_literals", case)

def test_path_types_as_tokens(parser):
    case = """
user.name: 1; ~user.profile |map
---
tag: code
children:
  - tag: expr
    children:
      - tag: set-path
        text: 'user.name:'
      - tag: number
        value: 1
  - tag: expr
    children:
      - tag: del-path
        text: ~user.profile
      - tag: piped-path
        text: "|map"
"""
    _run_structural_test(parser, "path_types_as_tokens", case)

def test_path_with_metadata_as_token(parser):
    case = """
api/call#meta: 1
---
tag: code
children:
  - tag: expr
    children:
      - tag: set-path
        text: 'api/call#meta:'
      - tag: number
        value: 1
"""
    _run_structural_test(parser, "path_with_metadata_as_token", case)

def test_get_path_with_parens(parser):
    case = """
user[(x+1)]
---
tag: code
children:
  - tag: expr
    children:
      - tag: get-path
        text: user
      - tag: code
        children:
          - tag: expr
            children:
              - tag: group
                children:
                  - tag: expr
                    children:
                      - tag: get-path
                        text: x+1
"""
    _run_structural_test(parser, "get_path_with_parens", case)

def test_del_path_with_metadata_as_token(parser):
    case = """
~user.profile#soft
---
tag: code
children:
  - tag: expr
    children:
      - tag: del-path
        text: '~user.profile#soft'
"""
    _run_structural_test(parser, "del_path_with_metadata_as_token", case)

def test_empty_containers(parser):
    case = """
() [] #[] #{} {}
---
tag: code
children:
  - tag: expr
    children:
      - tag: group
        children: []
      - tag: code
        children: []
      - tag: list
        children: []
      - tag: dict
        children: []
      - tag: sig
        children: []
"""
    _run_structural_test(parser, "empty_containers", case)

def test_nested_containers(parser):
    case = """
#{ a: [ b: { 1 } ] }
---
tag: code
children:
  - tag: expr
    children:
      - tag: dict
        children:
          - tag: expr
            children:
              - tag: set-path
                text: 'a:'
              - tag: code
                children:
                  - tag: expr
                    children:
                      - tag: set-path
                        text: 'b:'
                      - tag: sig
                        children:
                          - tag: expr
                            children:
                              - tag: number
                                value: 1
"""
    _run_structural_test(parser, "nested_containers", case)

def test_function_definition(parser):
    case = """
my-func: fn [x] [x*2]
---
tag: code
children:
  - tag: expr
    children:
      - tag: set-path
        text: 'my-func:'
      - tag: get-path
        text: fn
      - tag: code
        children:
          - tag: expr
            children:
              - tag: get-path
                text: x
      - tag: code
        children:
          - tag: expr
            children:
              - tag: get-path
                text: x*2
"""
    _run_structural_test(parser, "function_definition", case)

def test_infix_expression(parser):
    case = """
10 + 5 * 2
---
tag: code
children:
  - tag: expr
    children:
      - tag: number
        value: 10
      - tag: get-path
        text: +
      - tag: number
        value: 5
      - tag: get-path
        text: "*"
      - tag: number
        value: 2
"""
    _run_structural_test(parser, "infix_expression", case)

def test_grouped_expression(parser):
    case = """
10 + (5 * 2)
---
tag: code
children:
  - tag: expr
    children:
      - tag: number
        value: 10
      - tag: get-path
        text: +
      - tag: group
        children:
          - tag: expr
            children:
              - tag: number
                value: 5
              - tag: get-path
                text: "*"
              - tag: number
                value: 2
"""
    _run_structural_test(parser, "grouped_expression", case)

def test_mixed_separators(parser):
    case = """
a:1; b:2, c:3
d:4
---
tag: code
children:
  - tag: expr
    children:
      - tag: set-path
        text: 'a:'
      - tag: number
        value: 1
  - tag: expr
    children:
      - tag: set-path
        text: 'b:'
      - tag: number
        value: 2
  - tag: expr
    children:
      - tag: set-path
        text: 'c:'
      - tag: number
        value: 3
  - tag: expr
    children:
      - tag: set-path
        text: 'd:'
      - tag: number
        value: 4
"""
    _run_structural_test(parser, "mixed_separators", case)

def test_path_variants(parser):
    case = r"""
/a ../b ./c d.e f/g |h i...
---
tag: code
children:
  - tag: expr
    children:
      - tag: get-path
        text: /a
      - tag: get-path
        text: ../b
      - tag: get-path
        text: ./c
      - tag: get-path
        text: d.e
      - tag: get-path
        text: f/g
      - tag: piped-path
        text: "|h"
      - tag: get-path
        text: i...
"""
    _run_structural_test(parser, "path_variants", case)

def test_variadic_function_definition(parser):
    case = """
my-func: fn [a, b...] []
---
tag: code
children:
  - tag: expr
    children:
      - tag: set-path
        text: 'my-func:'
      - tag: get-path
        text: fn
      - tag: code
        children:
          - tag: expr
            children:
              - tag: get-path
                text: a
          - tag: expr
            children:
              - tag: get-path
                text: b...
      - tag: code
        children: []
"""
    _run_structural_test(parser, "variadic_function_definition", case)

def test_dynamic_access_as_terms(parser):
    case = """
items[idx]
---
tag: code
children:
  - tag: expr
    children:
      - tag: get-path
        text: items
      - tag: code
        children:
          - tag: expr
            children:
              - tag: get-path
                text: idx
"""
    _run_structural_test(parser, "dynamic_access_as_terms", case)


def test_multi_set_path_placeholder(parser):
    case = """
[a, b.c]: 1
---
tag: code
children:
  - tag: expr
    children:
      - tag: set-path
        text: "[a, b.c]:"
      - tag: number
        value: 1
"""
    _run_structural_test(parser, "multi_set_path_placeholder", case)


def test_spec_coverage_additions(parser):
    # Path literal with complex content, motivated by ` `x[a + b]` `
    case1 = """
`a[b+c]`
---
tag: code
children:
  - tag: expr
    children:
      - tag: path-literal
        children:
          - tag: path-placeholder
            text: a[b+c]
"""
    _run_structural_test(parser, "complex_path_literal", case1)

    # Path with // that is not a comment, which is allowed.
    case2 = """
http://example.com
---
tag: code
children:
  - tag: expr
    children:
      - tag: get-path
        text: http://example.com
"""
    _run_structural_test(parser, "path_with_double_slash", case2)

    # Path followed by a valid comment.
    case3 = """
a -- comment
---
tag: code
children:
  - tag: expr
    children:
      - tag: get-path
        text: a
"""
    _run_structural_test(parser, "path_with_comment", case3)

    # Nested block comments.
    case4 = """
a {-- outer {-- inner --} outer --} b
---
tag: code
children:
  - tag: expr
    children:
      - tag: get-path
        text: a
      - tag: get-path
        text: b
"""
    _run_structural_test(parser, "nested_block_comments", case4)

    # Test for `strings_with_escaped_quotes` is now in a separate function
    # `test_strings_with_escaped_quotes` to avoid YAML parsing ambiguity.


def test_strings_with_escaped_quotes(parser):
    """
    Tests strings with escaped quotes directly, avoiding YAML's complexities
    with escape sequences in the expected output.
    """
    source_code = r"""'it\'s' "\"that\"" """
    parse_result = parser.parse(source_code)

    assert parse_result.get("status") == "success", f"Parsing failed: {parse_result.get('error_message')}"

    result_ast = clean_ast(parse_result["ast"])

    raw_string_node = result_ast['children'][0]['children'][0]
    i_string_node = result_ast['children'][0]['children'][1]

    assert raw_string_node['tag'] == 'string'
    assert raw_string_node['text'] == "it\\'s"

    assert i_string_node['tag'] == 'i-string'
    assert i_string_node['text'] == '\\"that\\"'
