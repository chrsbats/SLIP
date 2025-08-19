import pytest
from pathlib import Path
from koine import Parser

def clean_ast(node):
    # Unwrap Parser results that may be wrapped under 'ast'
    if isinstance(node, dict) and 'ast' in node:
        node = node['ast']

    if isinstance(node, list):
        # Filter out Nones and internal helper nodes (tags containing "__")
        cleaned_list = []
        for n in node:
            cleaned = clean_ast(n)
            if cleaned is None:
                continue
            if isinstance(cleaned, dict) and "__" in cleaned.get("tag", ""):
                continue
            cleaned_list.append(cleaned)
        return cleaned_list

    if isinstance(node, dict) and 'tag' not in node:
        # Named-children dict
        return {k: clean_ast(v) for k, v in node.items()}

    if not isinstance(node, dict) or 'tag' not in node:
        return node

    cleaned = {"tag": node["tag"]}

    if "children" in node:
        cleaned_children = clean_ast(node["children"])
        # Keep empty containers for structural nodes
        if cleaned_children or node.get("tag") in ("list", "dict", "sig", "code", "group"):
            cleaned["children"] = cleaned_children
    elif "value" in node:
        cleaned["value"] = node["value"]
    elif "text" in node:
        # Omit text for structural path segments for consistency with other tests
        if node.get("tag") not in ("pipe", "root", "parent", "pwd", "slice"):
            cleaned["text"] = node["text"]

    return cleaned

@pytest.fixture(scope="module")
def parser():
    grammar_path = Path(__file__).parent / ".." / "grammar" / "slip_grammar.yaml"
    return Parser.from_file(str(grammar_path))

def test_block_comment_then_sig_and_code(parser: Parser):
    source = """{--
SLIP Core Library v1.0

Header comment block should be ignored by the parser.
--}

reverse: fn {data-list} [
]
"""
    # This should parse successfully; currently it fails in root.slip integration.
    ast = parser.parse(source)

    cleaned = clean_ast(ast)
    assert cleaned.get("tag") == "code"
    assert isinstance(cleaned.get("children"), list)

    # Find our function definition expr
    exprs = [c for c in cleaned["children"] if isinstance(c, dict) and c.get("tag") == "expr"]
    assert exprs, "Expected at least one expression after the block comment"

    # Flatten children tags of the last expr to ensure pieces are present
    last_expr_children = exprs[-1]["children"]
    tags = [c.get("tag") for c in last_expr_children]

    # Expect sequence: set-path, get-path (fn), sig, code
    assert "set-path" in tags, "Missing set-path 'reverse:'"
    assert "get-path" in tags, "Missing 'fn' token as get-path"
    assert "sig" in tags, "Missing signature block {data-list}"
    assert "code" in tags, "Missing code block []"

    # Ensure the set-path is for 'reverse'
    set_path = next(c for c in last_expr_children if c.get("tag") == "set-path")
    set_names = [n.get("text") for n in set_path.get("children", []) if n.get("tag") == "name"]
    assert set_names == ["reverse"], f"Expected set-path 'reverse', got {set_names}"
