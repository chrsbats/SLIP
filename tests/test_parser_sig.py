from koine.parser import PlaceholderParser
import pytest
import yaml

@pytest.fixture(scope="module")
def parser():
    with open("grammar/slip_sig.yaml", "r") as f:
        grammar = yaml.safe_load(f)
    return PlaceholderParser(grammar)

def parse_sig(parser: PlaceholderParser, text: str):
    result = parser.parse(text)
    assert result.get("status") == "success", f"Parsing failed: {result.get('error_message')}"
    ast = result["ast"]
    # PlaceholderParser may wrap the sig node in a single-item list; unwrap
    if isinstance(ast, list) and len(ast) == 1:
        ast = ast[0]
    return ast

def find_children_by_tag(children, tag):
    return [c for c in (children or []) if isinstance(c, dict) and c.get("tag") == tag]

def assert_parse_error(parser: PlaceholderParser, text: str):
    result = parser.parse(text)
    assert result.get("status") != "success", f"Expected parse error but succeeded: {text}"

def test_empty_sig(parser):
    ast = parse_sig(parser, "")
    assert ast.get("tag") == "sig"
    assert isinstance(ast.get("children"), list)
    assert len(ast["children"]) == 0

def test_positional_and_rest(parser):
    ast = parse_sig(parser, "a, b, rest...")
    assert ast["tag"] == "sig"
    children = ast["children"]
    args = find_children_by_tag(children, "sig-arg")
    rests = find_children_by_tag(children, "sig-rest-arg")
    assert [n.get("text") or (n.get("children") or [{}])[0].get("text") for n in args] == ["a", "b"]
    assert len(rests) == 1
    rest = rests[0]
    rest_name = rest.get("text") or (rest.get("children") or [{}])[0].get("text")
    assert rest_name == "rest"

def test_keywords_and_return(parser):
    # With PlaceholderParser, kwarg values and return are placeholder expr leafs
    ast = parse_sig(parser, "x: 10, y: 'raw' -> int")
    children = ast["children"]

    kwargs = find_children_by_tag(children, "sig-kwarg")
    assert len(kwargs) == 2

    def extract_kw(kw_node):
        ch = kw_node["children"]
        key = ch["sig-key"]["text"]
        # Find the expr placeholder among unnamed children
        expr_val = None
        for v in ch.values():
            if isinstance(v, dict) and v.get("tag") == "expr":
                expr_val = v["text"].strip()
                break
        assert expr_val is not None
        return key, expr_val

    kv = dict(extract_kw(k) for k in kwargs)
    assert kv["x"] == "10"
    assert kv["y"] == "'raw'"

    returns = find_children_by_tag(children, "sig-return")
    assert len(returns) == 1
    ret_expr = returns[0]["children"][0]
    assert ret_expr["tag"] == "expr"
    assert ret_expr["text"].strip() == "int"

def test_complex_value_placeholder(parser):
    ast = parse_sig(parser, "a: a + b * 2")
    kw = find_children_by_tag(ast["children"], "sig-kwarg")[0]
    ch = kw["children"]
    assert ch["sig-key"]["text"] == "a"
    expr_val = None
    for v in ch.values():
        if isinstance(v, dict) and v.get("tag") == "expr":
            expr_val = v["text"].strip()
            break
    assert expr_val == "a + b * 2"

def test_predicate_and_variadic_name(parser):
    ast = parse_sig(parser, "is-a?, args...")
    children = ast["children"]
    first = children[0]
    first_name = first.get("text") or (first.get("children") or [{}])[0].get("text")
    assert first_name == "is-a?"
    rest = children[1]
    assert rest["tag"] == "sig-rest-arg"
    rest_name = rest.get("text") or (rest.get("children") or [{}])[0].get("text")
    assert rest_name == "args"

def test_kwarg_union_value(parser):
    ast = parse_sig(parser, "x: {A or B or C}")
    children = ast["children"]
    kwargs = find_children_by_tag(children, "sig-kwarg")
    assert len(kwargs) == 1
    kw = kwargs[0]
    # Value is named "value" in the sig_kwarg rule
    value_node = kw["children"]["value"]
    assert value_node["tag"] == "sig-union"
    # Expect union children to be get-path nodes (from placeholder)
    union_items = value_node.get("children") or []
    assert len(union_items) == 3
    for item in union_items:
        assert item["tag"] == "get-path"

def test_kwarg_union_value_with_spaces(parser):
    ast = parse_sig(parser, "kind: { Player or Monster }")
    kwargs = find_children_by_tag(ast["children"], "sig-kwarg")
    assert len(kwargs) == 1
    value_node = kwargs[0]["children"]["value"]
    assert value_node["tag"] == "sig-union"
    union_items = value_node.get("children") or []
    assert [c["tag"] for c in union_items] == ["get-path", "get-path"]


def test_kwarg_and_chain_value(parser):
    ast = parse_sig(parser, "x: Player and OnFire and Poisoned")
    kwargs = find_children_by_tag(ast["children"], "sig-kwarg")
    assert len(kwargs) == 1
    value_node = kwargs[0]["children"]["value"]
    assert value_node["tag"] == "sig-and"
    items = value_node.get("children") or []
    assert [c.get("tag") for c in items] == ["get-path", "get-path", "get-path"]


def test_kwarg_or_chain_value(parser):
    ast = parse_sig(parser, "x: A or B or C")
    kwargs = find_children_by_tag(ast["children"], "sig-kwarg")
    assert len(kwargs) == 1
    value_node = kwargs[0]["children"]["value"]
    assert value_node["tag"] == "sig-union"
    items = value_node.get("children") or []
    assert [c.get("tag") for c in items] == ["get-path", "get-path", "get-path"]


def test_mixed_and_or_without_parens_is_error(parser):
    # Mixed at same nesting level must be a syntax error
    assert_parse_error(parser, "x: Player and OnFire or Poisoned")
    assert_parse_error(parser, "x: A or B and C")


def test_mixed_with_parens_ok_union_of_and(parser):
    # (A and B) or C → sig-union with first child sig-and
    ast = parse_sig(parser, "x: (Player and OnFire) or Poisoned")
    kwargs = find_children_by_tag(ast["children"], "sig-kwarg")
    assert len(kwargs) == 1
    value_node = kwargs[0]["children"]["value"]
    assert value_node["tag"] == "sig-union"
    children = value_node.get("children") or []
    assert len(children) == 2
    assert children[0]["tag"] == "sig-and"
    assert [c.get("tag") for c in (children[0].get("children") or [])] == ["get-path", "get-path"]
    assert children[1]["tag"] == "get-path"


def test_mixed_with_parens_ok_and_with_union(parser):
    # A and (B or C) → sig-and with second child sig-union
    ast = parse_sig(parser, "x: Player and (OnFire or Poisoned)")
    kwargs = find_children_by_tag(ast["children"], "sig-kwarg")
    assert len(kwargs) == 1
    value_node = kwargs[0]["children"]["value"]
    assert value_node["tag"] == "sig-and"
    children = value_node.get("children") or []
    assert len(children) == 2
    assert children[0]["tag"] == "get-path"
    assert children[1]["tag"] == "sig-union"
    assert [c.get("tag") for c in (children[1].get("children") or [])] == ["get-path", "get-path"]
