import pytest
from slip.slip_datatypes import (
    Scope, Code, List, IString, SlipFunction, Response,
    PathLiteral,
    GetPath, SetPath, DelPath, Name, Index, Slice, Group,
    Root, Parent, Pwd, PipedPath, MultiSetPath,
    SlipBlock, PathSegment, Sig
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
    p = PathLiteral(GetPath([Name("ok")]))
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

def test_path_literal_structure_and_equality():
    pl1 = PathLiteral(GetPath([Name("user"), Name("name")]))
    pl2 = PathLiteral(GetPath([Name("user"), Name("name")]))
    pl3 = PathLiteral(GetPath([Name("user"), Name("email")]))
    # Inner is a GetPath with two Name segments
    assert isinstance(pl1.inner, GetPath)
    assert len(pl1.inner.segments) == 2
    assert isinstance(pl1.inner.segments[0], Name) and pl1.inner.segments[0].text == "user"
    assert isinstance(pl1.inner.segments[1], Name) and pl1.inner.segments[1].text == "name"
    # Equality/hash by canonical string
    assert pl1 == pl2
    assert hash(pl1) == hash(pl2)
    assert pl1 != pl3
    assert hash(pl1) != hash(pl3)

def test_path_literal_with_set_and_del_and_multiset():
    pls = PathLiteral(SetPath([Name("user"), Name("name")]))
    pld = PathLiteral(DelPath(GetPath([Name("user")])))
    plm = PathLiteral(MultiSetPath([SetPath([Name("a")]), SetPath([Name("b")])]))
    # String forms
    from slip.slip_printer import Printer
    pf = Printer().pformat
    assert pf(pls) == "`user.name:`"
    assert pf(pld) == "`~user`"
    assert pf(plm) == "`[a,b]:`"


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

def test_path_literal_piped_path_structure():
    pl = PathLiteral(PipedPath([Name("map")]))
    assert isinstance(pl.inner, PipedPath)
    assert len(pl.inner.segments) == 1
    assert isinstance(pl.inner[0], Name)
    assert pl.inner[0].text == "map"

def test_path_literal_piped_path_equality_and_hash():
    p1 = PathLiteral(PipedPath([Name("map")]))
    p2 = PathLiteral(PipedPath([Name("map")]))
    p3 = PathLiteral(PipedPath([Name("filter")]))
    assert p1 == p2
    assert hash(p1) == hash(p2)
    assert p1 != p3
    assert p1 != "not a path"

def test_path_literal_multiset_structure():
    pl = PathLiteral(MultiSetPath([SetPath([Name("a")]), SetPath([Name("b")])]))
    assert isinstance(pl.inner, MultiSetPath)
    assert len(list(pl.inner)) == 2

def test_path_literal_multiset_equality_and_hash():
    m1 = PathLiteral(MultiSetPath([SetPath([Name("a")]), SetPath([Name("b")])]))
    m2 = PathLiteral(MultiSetPath([SetPath([Name("a")]), SetPath([Name("b")])]))
    m3 = PathLiteral(MultiSetPath([SetPath([Name("x")])]))
    assert m1 == m2
    assert hash(m1) == hash(m2)
    assert m1 != m3
    assert m1 != "not a path"


def test_path_literal_set_path_structure():
    meta = Group([])
    pl = PathLiteral(SetPath([Name("user"), Name("name")], meta=meta))
    assert isinstance(pl.inner, SetPath)
    assert len(pl.inner.segments) == 2
    assert pl.inner.meta is meta
    assert isinstance(pl.inner[0], Name)

def test_path_literal_set_path_equality_and_hash():
    p1 = PathLiteral(SetPath([Name("user")]))
    p2 = PathLiteral(SetPath([Name("user")]))
    p3 = PathLiteral(SetPath([Name("email")]))
    p4_meta = PathLiteral(SetPath([Name("user")], meta=Group([])))

    assert p1 == p2
    assert hash(p1) == hash(p2)
    assert p1 != p3
    assert p1 != p4_meta

def test_path_literal_del_path_structure():
    gp = GetPath([Name("user")])
    pl = PathLiteral(DelPath(gp))
    assert isinstance(pl.inner, DelPath)
    assert pl.inner.path is gp

def test_path_literal_del_path_equality_and_hash():
    d1 = PathLiteral(DelPath(GetPath([Name("user")])))
    d2 = PathLiteral(DelPath(GetPath([Name("user")])))
    d3 = PathLiteral(DelPath(GetPath([Name("email")])))
    assert d1 == d2
    assert hash(d1) == hash(d2)
    assert d1 != d3

# --- New tests for Sig with union/conjunction annotations ---

def test_sig_with_union_keyword_value():
    a = GetPath([Name("A")])
    b = GetPath([Name("B")])
    s1 = Sig([], {"x": ("union", [a, b])}, None, None)
    s2 = Sig([], {"x": ("union", [GetPath([Name("A")]), GetPath([Name("B")])])}, None, None)
    assert s1 == s2
    # Basic repr smoke check (should include 'Sig(' and 'union')
    r = repr(s1)
    assert "Sig(" in r
    assert "union" in r

def test_sig_with_conjunction_keyword_value():
    p = GetPath([Name("Player")])
    onf = GetPath([Name("OnFire")])
    s1 = Sig([], {"p": ("and", [p, onf])}, None, None)
    s2 = Sig([], {"p": ("and", [GetPath([Name("Player")]), GetPath([Name("OnFire")])])}, None, None)
    assert s1 == s2
    r = repr(s1)
    assert "and" in r
