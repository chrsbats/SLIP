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
