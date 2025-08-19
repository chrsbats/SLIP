import pytest
import yaml
import json
from koine.parser import PlaceholderParser

# =================================================================
# Setup and Helper Functions
# =================================================================

@pytest.fixture(scope="module")
def parser():
    """Provides a parser instance for the path grammar."""
    with open("grammar/slip_path.yaml", "r") as f:
        grammar = yaml.safe_load(f)
    return PlaceholderParser(grammar)

def clean_ast(node):
    """
    Recursively simplifies a raw AST node from Koine for stable comparison.
    - Removes location info ('line', 'col', 'text' from non-leaf nodes).
    - Keeps 'tag' and 'children' for structural nodes.
    - Keeps 'tag' and 'value' for typed leaf nodes (number, bool, null).
    - Keeps 'tag' and 'text' for other leaf nodes (strings, paths).
    - For nodes without children/value/text, just returns the tag.
    """
    if isinstance(node, list):
        # Filter out nodes generated for unnamed literals by PlaceholderParser
        return [clean_ast(n) for n in node if '__' not in n.get('tag', '') and n.get('tag') != 'literal']

    if isinstance(node, dict) and 'tag' not in node: # It's a named children dict
        return {k: clean_ast(v) for k, v in node.items()}

    if not isinstance(node, dict):
        return node

    cleaned = {'tag': node['tag']}
    
    if 'children' in node:
        cleaned_children = clean_ast(node['children'])
        if cleaned_children:
            cleaned['children'] = cleaned_children
    elif 'value' in node:
        cleaned['value'] = node['value']
    elif 'text' in node and node['text']:
        cleaned['text'] = node['text']

    # Post-processing to match test expectations
    if cleaned.get('tag') in ('pipe', 'root', 'parent', 'pwd'):
        cleaned.pop('text', None)
            
    return cleaned

# =================================================================
# Test Cases for the Path Grammar
# =================================================================

GET_PATH_TEST_CASES = [
    # Tuple format: (test_id, path_string, expected_ast_dict)

    # --- Basic Name Paths ---
    ("simple_name", "a", {
        "tag": "get-path", "children": [{"tag": "name", "text": "a"}]
    }),
    ("dot_separated_names", "a.b-c.d", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "name", "text": "b-c"},
            {"tag": "name", "text": "d"}
        ]
    }),
    ("slash_separated_names", "a/b/c", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "name", "text": "b"},
            {"tag": "name", "text": "c"}
        ]
    }),
    ("mixed_separators", "a.b/c", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "name", "text": "b"},
            {"tag": "name", "text": "c"}
        ]
    }),
    ("variadic_name", "args...", {
        "tag": "get-path", "children": [{"tag": "name", "text": "args..."}]
    }),
    ("predicate_name", "is-a?", {
        "tag": "get-path", "children": [{"tag": "name", "text": "is-a?"}]
    }),

    # --- Special Prefixes ---
    ("root_path", "/config/path", {
        "tag": "get-path", "children": [{"tag": "root"}, {"tag": "name", "text": "config"}, {"tag": "name", "text": "path"}]
    }),
    ("root_only", "/", {
        "tag": "get-path", "children": [{"tag": "root"}]
    }),
    ("parent_path", "../a/b", {
        "tag": "get-path", "children": [{"tag": "parent"}, {"tag": "name", "text": "a"}, {"tag": "name", "text": "b"}]
    }),
    ("multiple_parents", "../../a", {
        "tag": "get-path", "children": [{"tag": "parent"}, {"tag": "parent"}, {"tag": "name", "text": "a"}]
    }),

    # --- Query Segments ---
    ("simple_query", "a[0]", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "query-segment", "children": [
                {"tag": "simple-query", "children": [{"tag": "expr", "text": "0"}]}
            ]}
        ]
    }),
    ("expr_query", "a[i+1]", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "query-segment", "children": [
                {"tag": "simple-query", "children": [{"tag": "expr", "text": "i+1"}]}
            ]}
        ]
    }),
    ("full_slice", "a[1:10]", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "query-segment", "children": [
                {"tag": "slice-query", "children": [
                    {"tag": "start-expr", "children": [{"tag": "expr", "text": "1"}]},
                    {"tag": "end-expr", "children": [{"tag": "expr", "text": "10"}]}
                ]}
            ]}
        ]
    }),
    ("slice_to", "a[:10]", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "query-segment", "children": [
                {"tag": "slice-query", "children": [
                    {"tag": "end-expr", "children": [{"tag": "expr", "text": "10"}]}
                ]}
            ]}
        ]
    }),
    ("slice_from", "a[1:]", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "query-segment", "children": [
                {"tag": "slice-query", "children": [
                    {"tag": "start-expr", "children": [{"tag": "expr", "text": "1"}]},
                    {"tag": "end-expr", "children": [{"tag": "expr"}]}
                ]}
            ]}
        ]
    }),
    ("slice_all", "a[:]", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "query-segment", "children": [
                {"tag": "slice-query", "children": [
                    {"tag": "end-expr", "children": [{"tag": "expr"}]}
                ]}
            ]}
        ]
    }),
    ("slice_with_expr", "a[x : y+1]", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "query-segment", "children": [
                {"tag": "slice-query", "children": [
                    {"tag": "start-expr", "children": [{"tag": "expr", "text": "x "}]},
                    {"tag": "end-expr", "children": [{"tag": "expr", "text": " y+1"}]}
                ]}
            ]}
        ]
    }),
    ("filter_query", "a[>10]", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "query-segment", "children": [
                {"tag": "filter-query", "children": [
                    {"tag": "operator", "text": ">"},
                    {"tag": "rhs-expr", "children": [{"tag": "expr", "text": "10"}]}
                ]}
            ]}
        ]
    }),
    ("filter_query_complex_op", "a[>= limit]", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "query-segment", "children": [
                {"tag": "filter-query", "children": [
                    {"tag": "operator", "text": ">="},
                    {"tag": "rhs-expr", "children": [{"tag": "expr", "text": "limit"}]}
                ]}
            ]}
        ]
    }),

    # --- Group (Dynamic) Segments ---
    ("simple_group", "a(key)", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "group", "children": [{"tag": "expr", "text": "key"}]}
        ]
    }),
    ("group_as_base", "(get-key).name", {
        "tag": "get-path", "children": [
            {"tag": "group", "children": [{"tag": "expr", "text": "get-key"}]},
            {"tag": "name", "text": "name"}
        ]
    }),
    ("parent_as_suffix", "a/../b", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "parent"},
            {"tag": "name", "text": "b"}
        ]
    }),

    # --- Metadata ---
    ("path_with_meta", "a.b#(meta:1)", {
        "tag": "get-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "name", "text": "b"},
            {"tag": "meta", "children": [{"tag": "expr", "text": "meta:1"}]}
        ]
    }),
    ("root_path_with_meta", "/#(m)", {
        "tag": "get-path", "children": [
            {"tag": "root"},
            {"tag": "meta", "children": [{"tag": "expr", "text": "m"}]}
        ]
    }),
]


PIPED_PATH_TEST_CASES = [
    ("pipe_path", "|map", {
        "tag": "piped-path", "children": [{"tag": "name", "text": "map"}]
    }),
    ("kitchen_sink", "|../a.b[i1:i2](key1)/c[>i3]#(m)", {
        "tag": "piped-path", "children": [
            {"tag": "parent"},
            {"tag": "name", "text": "a"},
            {"tag": "name", "text": "b"},
            {"tag": "query-segment", "children": [
                {"tag": "slice-query", "children": [
                    {"tag": "start-expr", "children": [{"tag": "expr", "text": "i1"}]},
                    {"tag": "end-expr", "children": [{"tag": "expr", "text": "i2"}]}
                ]}
            ]},
            {"tag": "group", "children": [{"tag": "expr", "text": "key1"}]},
            {"tag": "name", "text": "c"},
            {"tag": "query-segment", "children": [
                {"tag": "filter-query", "children": [
                    {"tag": "operator", "text": ">"},
                    {"tag": "rhs-expr", "children": [{"tag": "expr", "text": "i3"}]}
                ]}
            ]},
            {"tag": "meta", "children": [{"tag": "expr", "text": "m"}]}
        ]
    })
]


def run_path_test(parser, test_id: str, path_string: str, expected_ast: dict, *, rule: str = None):
    """
    Helper to run a single path parsing test.
    If `rule` is provided, it's used as the start rule.
    Otherwise, the grammar's default start rule is used.
    """
    rule_info = f"(rule: {rule})" if rule else "(default start rule)"
    try:
        parse_result = parser.parse(path_string, start_rule=rule)
        if parse_result.get("status") != "success":
            error_info = parse_result.get("error_message", str(parse_result))
            pytest.fail(f"Parsing failed for '{test_id}' {rule_info}:\n{error_info}", pytrace=False)
        result_ast = parse_result["ast"]
    except Exception as e:
        pytest.fail(f"Parsing failed unexpectedly for '{test_id}' {rule_info}:\n{e}", pytrace=False)

    # The parser may return a single-item list for promoted sequences.
    # We unwrap it for consistent comparison.
    if isinstance(result_ast, list) and len(result_ast) == 1:
        result_ast = result_ast[0]

    cleaned_result_ast = clean_ast(result_ast)

    if cleaned_result_ast != expected_ast:
        print("\n" + "="*20 + " AST Diff " + "="*20)
        print(f"Test ID: {test_id} {rule_info}")
        print("----- Path String -----")
        print(path_string)
        print("----- Actual (Cleaned) -----")
        print(json.dumps(cleaned_result_ast, indent=2))
        print("----- Expected -----")
        print(json.dumps(expected_ast, indent=2))
        print("="*50)

    assert cleaned_result_ast == expected_ast

# --- GET PATHS (rule: 'path') ---

@pytest.mark.parametrize(
    "test_id, path_string, expected_ast",
    GET_PATH_TEST_CASES,
    ids=[t[0] for t in GET_PATH_TEST_CASES]
)
def test_get_path_parsing(parser: PlaceholderParser, test_id: str, path_string: str, expected_ast: dict):
    """Tests parsing using the 'get_path' rule."""
    run_path_test(parser, test_id, path_string, expected_ast, rule="get_path")


# --- PIPED PATHS (rule: 'piped_path') ---

@pytest.mark.parametrize(
    "test_id, path_string, expected_ast",
    PIPED_PATH_TEST_CASES,
    ids=[t[0] for t in PIPED_PATH_TEST_CASES]
)
def test_piped_path_parsing(parser: PlaceholderParser, test_id: str, path_string: str, expected_ast: dict):
    """Tests parsing using the 'piped_path' rule."""
    run_path_test(parser, test_id, path_string, expected_ast, rule="piped_path")


# --- SET PATHS (rule: 'set_path') ---

SET_PATH_TEST_CASES = [
    ("simple_set_path", "a:", {
        "tag": "set-path", "children": [{"tag": "name", "text": "a"}]
    }),
    ("complex_set_path", "a.b[0]:", {
        "tag": "set-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "name", "text": "b"},
            {"tag": "query-segment", "children": [
                {"tag": "simple-query", "children": [{"tag": "expr", "text": "0"}]}
            ]}
        ]
    }),
    ("set_path_with_meta", "a#(m):", {
        "tag": "set-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "meta", "children": [{"tag": "expr", "text": "m"}]}
        ]
    }),
    ("multi_set_path", "[a, b.c]:", {
        "tag": "multi-set-path", "children": [
            {"tag": "set-path", "children": [{"tag": "name", "text": "a"}]},
            {"tag": "set-path", "children": [
                {"tag": "name", "text": "b"},
                {"tag": "name", "text": "c"}
            ]}
        ]
    }),
    ("dynamic_set_path", "(a+b):", {
        "tag": "set-path", "children": [
            {"tag": "group", "children": [{"tag": "expr", "text": "a+b"}]}
        ]
    }),
]

@pytest.mark.parametrize(
    "test_id, path_string, expected_ast",
    SET_PATH_TEST_CASES,
    ids=[t[0] for t in SET_PATH_TEST_CASES]
)
def test_set_path_parsing(parser: PlaceholderParser, test_id: str, path_string: str, expected_ast: dict):
    """Tests parsing using the 'set_path' rule."""
    run_path_test(parser, test_id, path_string, expected_ast, rule="set_path")


# --- DEL PATHS (rule: 'del_path') ---

DEL_PATH_TEST_CASES = [
    ("simple_del_path", "~a", {
        "tag": "del-path", "children": [{"tag": "name", "text": "a"}]
    }),
    ("complex_del_path", "~a.b[0]", {
        "tag": "del-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "name", "text": "b"},
            {"tag": "query-segment", "children": [
                {"tag": "simple-query", "children": [{"tag": "expr", "text": "0"}]}
            ]}
        ]
    }),
    ("del_path_with_meta", "~a#(m)", {
        "tag": "del-path", "children": [
            {"tag": "name", "text": "a"},
            {"tag": "meta", "children": [{"tag": "expr", "text": "m"}]}
        ]
    }),
    ("dynamic_del_path", "~(a+b)", {
        "tag": "del-path", "children": [
            {"tag": "group", "children": [{"tag": "expr", "text": "a+b"}]}
        ]
    }),
]

@pytest.mark.parametrize(
    "test_id, path_string, expected_ast",
    DEL_PATH_TEST_CASES,
    ids=[t[0] for t in DEL_PATH_TEST_CASES]
)
def test_del_path_parsing(parser: PlaceholderParser, test_id: str, path_string: str, expected_ast: dict):
    """Tests parsing using the 'del_path' rule."""
    run_path_test(parser, test_id, path_string, expected_ast, rule="del_path")


# --- Test Default Start Rule ---

ALL_PATH_TEST_CASES = GET_PATH_TEST_CASES + PIPED_PATH_TEST_CASES + SET_PATH_TEST_CASES + DEL_PATH_TEST_CASES

@pytest.mark.parametrize(
    "test_id, path_string, expected_ast",
    ALL_PATH_TEST_CASES,
    ids=[t[0] for t in ALL_PATH_TEST_CASES]
)
def test_start_rule_parsing(parser: PlaceholderParser, test_id: str, path_string: str, expected_ast: dict):
    """
    Tests that the default start rule ('any_path') can correctly parse all
    path variants by dispatching to the correct specific rule.
    """
    run_path_test(parser, test_id, path_string, expected_ast) # Uses default start rule
