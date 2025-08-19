import pytest
from slip.slip_datatypes import (
    Scope, Code, List, IString, SlipFunction, Response,
    GetPathLiteral, SetPathLiteral, DelPathLiteral,
    GetPath, SetPath, DelPath, Name, Index, Slice, Group,
    Root, Parent, Pwd, PipedPath, MultiSetPath,
    PipedPathLiteral, MultiSetPathLiteral,
    SlipBlock, PathSegment
)

# --- Scope Tests ---

def test_scope_init():
    parent = Scope()
    child = Scope(parent=parent)
    assert child.parent is parent
    assert not child.bindings
    root = Scope()
    assert root.parent is None

def test_scope_setitem_getitem_str_key():
    scope = Scope()
    scope["a"] = 1
    assert scope["a"] == 1
    with pytest.raises(KeyError):
        _ = scope["b"]


def test_scope_prototype_chain_lookup():
    parent = Scope()
    parent["a"] = 100
    parent["b"] = 200

    child = Scope(parent=parent)
    child["b"] = 20  # shadow parent

    assert child["a"] == 100  # from parent
    assert child["b"] == 20   # from child
    assert parent["b"] == 200  # parent is unchanged

    with pytest.raises(KeyError):
        _ = child["c"]

def test_scope_delitem():
    scope = Scope()
    scope["a"] = 1
    del scope["a"]
    with pytest.raises(KeyError):
        _ = scope["a"]


def test_scope_delitem_does_not_affect_parent():
    parent = Scope()
    parent["a"] = 100
    child = Scope(parent=parent)
    child["a"] = 10  # shadow

    del child["a"]
    assert "a" not in child.bindings
    assert child["a"] == 100  # now gets from parent

    with pytest.raises(KeyError):
        del child["b"]  # not in child

def test_scope_contains():
    parent = Scope()
    parent["a"] = 1
    child = Scope(parent=parent)
    child["b"] = 2

    assert "a" in child
    assert "b" in child
    assert "c" not in child
    assert 123 not in child  # test non-key type

def test_scope_get_method():
    parent = Scope()
    parent["a"] = 1
    child = Scope(parent=parent)
    child["b"] = 2

    assert child.get("a") == 1
    assert child.get("b") == 2
    assert child.get("c") is None
    assert child.get("c", "default") == "default"
    assert child.get(123, "default") == "default" # non-string key

def test_scope_keys_method():
    parent = Scope()
    parent["a"] = 1
    child = Scope(parent=parent)
    child["b"] = 2

    assert set(child.keys()) == {"b"}
    assert set(parent.keys()) == {"a"}

def test_scope_find_owner():
    parent = Scope()
    parent["a"] = 1
    child = Scope(parent=parent)
    child["b"] = 2

    assert child.find_owner("a") is parent
    assert child.find_owner("b") is child
    assert child.find_owner("c") is None
    assert parent.find_owner("b") is None


# --- Other Type Tests ---

def test_code():
    c = Code([1, 2, 3])
    assert c.ast == [1, 2, 3]
    # repr is tested in test_slip_printer

def test_code_is_sequence():
    c = Code([1, 'a', True])
    assert isinstance(c, SlipBlock)
    assert len(c) == 3
    assert c[1] == 'a'

    c[1] = 'b'
    assert c[1] == 'b'
    assert c.ast[1] == 'b' # check underlying nodes

    sub = c[1:]
    assert isinstance(sub, list)
    assert sub == ['b', True]

    del c[0]
    assert len(c) == 2
    assert c[0] == 'b'

def test_list_is_sequence():
    ast_nodes = [{'tag': 'number', 'value': 1}, {'tag': 'string', 'text': 'a'}]
    l = List(ast_nodes)
    assert isinstance(l, SlipBlock)
    assert len(l) == 2
    assert l[0] == ast_nodes[0]
    sub = l[1:]
    assert sub == [{'tag': 'string', 'text': 'a'}]
    # repr is tested in test_slip_printer

def test_istring():
    s = IString("hello {{name}}")
    assert isinstance(s, str)
    assert s == "hello {{name}}"
    assert "hello" in s
    assert repr(s) == 'i"hello {{name}}"'

def test_slip_function():
    args = Code([])
    body = Code([])
    closure = Scope()
    f = SlipFunction(args, body, closure)
    assert f.args is args
    assert f.body is body
    assert f.closure is closure
    assert repr(f) == "fn [] []"

def test_response():
    p = GetPathLiteral([Name("ok")])
    r = Response(p, 123)
    assert r.status is p
    assert r.value == 123
    assert repr(r) == "response `ok` 123"


# --- Path and Segment Tests ---

def test_get_path_structure():
    meta = Group([])
    p = GetPath([Name("user"), Name("name")], meta=meta)
    assert len(p.segments) == 2
    assert p.meta is meta
    assert isinstance(p[0], Name)
    assert p[0].text == "user"

def test_get_path_equality_and_hash():
    p1 = GetPath([Name("user")])
    p2 = GetPath([Name("user")])
    p3 = GetPath([Name("email")])
    p4_meta = GetPath([Name("user")], meta=Group([]))

    assert p1 == p2
    assert hash(p1) == hash(p2)
    assert p1 != p3
    assert p1 != "not a path"
    assert p1 != p4_meta # metadata makes it different

def test_path_segments_repr():
    assert repr(Name("user")) == "Name<'user'>"
    assert repr(Index([1])) == "Index([1])"
    assert repr(Slice([1], [2])) == "Slice(start=[1], end=[2])"
    assert repr(Group([])) == "Group([])"
    assert repr(Root) == "Root<>"
    assert repr(Parent) == "Parent<>"
    assert repr(Pwd) == "Pwd<>"

def test_group_is_sequence():
    g = Group(['x', '*', 2])
    assert isinstance(g, SlipBlock)
    assert isinstance(g, PathSegment)
    assert len(g) == 3
    assert g[0] == 'x'
    g[1] = '+'
    assert g[:] == ['x', '+', 2]
    g.append(3)
    assert g.ast == ['x', '+', 2, 3]

def test_get_path_literal_structure():
    p = GetPathLiteral([Name("user"), Name("name")])
    assert len(p.segments) == 2
    assert isinstance(p[0], Name)
    assert p[0].text == "user"
    assert isinstance(p[1], Name)
    assert p[1].text == "name"

def test_get_path_literal_getitem():
    segments = [Name("a"), Index([]), Name("b")]
    p = GetPathLiteral(segments)
    assert p[0] is segments[0]
    assert p[1:] == segments[1:]

def test_path_literal_empty_error():
    with pytest.raises(ValueError):
        GetPathLiteral([])

def test_get_path_literal_equality_and_hash():
    p1 = GetPathLiteral([Name("user"), Name("name")])
    p2 = GetPathLiteral([Name("user"), Name("name")])
    p3 = GetPathLiteral([Name("user"), Name("email")])

    assert p1 == p2
    assert hash(p1) == hash(p2)
    assert p1 != p3
    assert hash(p1) != hash(p3)
    assert p1 != "not a path"


def test_set_path_structure():
    meta = Group([])
    p = SetPath([Name("user"), Name("name")], meta=meta)
    assert len(p.segments) == 2
    assert p.meta is meta
    assert isinstance(p[0], Name)
    assert p[0].text == "user"

def test_set_path_equality_and_hash():
    p1 = SetPath([Name("user")])
    p2 = SetPath([Name("user")])
    p3 = SetPath([Name("email")])
    p4_meta = SetPath([Name("user")], meta=Group([]))

    assert p1 == p2
    assert hash(p1) == hash(p2)
    assert p1 != p3
    assert p1 != GetPath([Name("user")]) # Different types
    assert p1 != p4_meta # Different meta

def test_del_path_structure():
    p = GetPath([Name("user")])
    d = DelPath(p)
    assert d.path is p

def test_del_path_equality_and_hash():
    d1 = DelPath(GetPath([Name("user")]))
    d2 = DelPath(GetPath([Name("user")]))
    d3 = DelPath(GetPath([Name("email")]))
    assert d1 == d2
    assert hash(d1) == hash(d2)
    assert d1 != d3


# --- New Datatype Tests -------------------------------------------------------

def test_piped_path_structure():
    p = PipedPath([Name("map")])
    assert len(p.segments) == 1
    assert isinstance(p[0], Name)
    assert p[0].text == "map"

def test_piped_path_equality_and_hash():
    p1 = PipedPath([Name("map")])
    p2 = PipedPath([Name("map")])
    p3 = PipedPath([Name("filter")])
    assert p1 == p2
    assert hash(p1) == hash(p2)
    assert p1 != p3
    assert p1 != "not a path"

def test_multi_set_path_structure():
    p = MultiSetPath([SetPath([Name("a")]), SetPath([Name("b")])])
    assert len(list(p)) == 2
    first, second = list(p)
    assert isinstance(first, SetPath)
    assert isinstance(second, SetPath)

def test_multi_set_path_equality_and_hash():
    m1 = MultiSetPath([SetPath([Name("a")]), SetPath([Name("b")])])
    m2 = MultiSetPath([SetPath([Name("a")]), SetPath([Name("b")])])
    m3 = MultiSetPath([SetPath([Name("x")])])
    assert m1 == m2
    assert hash(m1) == hash(m2)
    assert m1 != m3
    assert m1 != "not a path"
    assert m1 != SetPath([Name("user")])


# --- Literal Datatype Tests ---------------------------------------------------

def test_piped_path_literal_structure():
    p = PipedPathLiteral([Name("map")])
    assert len(p.segments) == 1
    assert isinstance(p[0], Name)
    assert p[0].text == "map"

def test_piped_path_literal_equality_and_hash():
    p1 = PipedPathLiteral([Name("map")])
    p2 = PipedPathLiteral([Name("map")])
    p3 = PipedPathLiteral([Name("filter")])
    assert p1 == p2
    assert hash(p1) == hash(p2)
    assert p1 != p3
    assert p1 != "not a path"

def test_multi_set_path_literal_structure():
    p = MultiSetPathLiteral([SetPath([Name("a")]), SetPath([Name("b")])])
    assert len(list(p)) == 2

def test_multi_set_path_literal_equality_and_hash():
    m1 = MultiSetPathLiteral([SetPath([Name("a")]), SetPath([Name("b")])])
    m2 = MultiSetPathLiteral([SetPath([Name("a")]), SetPath([Name("b")])])
    m3 = MultiSetPathLiteral([SetPath([Name("x")])])
    assert m1 == m2
    assert hash(m1) == hash(m2)
    assert m1 != m3
    assert m1 != "not a path"


def test_set_path_literal_structure():
    meta = Group([])
    p = SetPathLiteral([Name("user"), Name("name")], meta=meta)
    assert len(p.segments) == 2
    assert p.meta is meta
    assert isinstance(p[0], Name)

def test_set_path_literal_equality_and_hash():
    p1 = SetPathLiteral([Name("user")])
    p2 = SetPathLiteral([Name("user")])
    p3 = SetPathLiteral([Name("email")])
    p4_meta = SetPathLiteral([Name("user")], meta=Group([]))

    assert p1 == p2
    assert hash(p1) == hash(p2)
    assert p1 != p3
    assert p1 != p4_meta

def test_del_path_literal_structure():
    p = GetPathLiteral([Name("user")])
    d = DelPathLiteral(p)
    assert d.path is p

def test_del_path_literal_equality_and_hash():
    d1 = DelPathLiteral(GetPathLiteral([Name("user")]))
    d2 = DelPathLiteral(GetPathLiteral([Name("user")]))
    d3 = DelPathLiteral(GetPathLiteral([Name("email")]))
    assert d1 == d2
    assert hash(d1) == hash(d2)
    assert d1 != d3
