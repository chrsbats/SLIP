import pytest

from slip.slip_interpreter import _tmpl_normalize_value, _scope_to_dict, Evaluator
from slip.slip_datatypes import (
    Scope, Code, IString, SlipFunction, GenericFunction, Sig,
    GetPath, Name, PathLiteral, SetPath, DelPath, PipedPath, MultiSetPath
)
from slip import ScriptRunner


def test_tmpl_normalize_value_and_scope_to_dict():
    # Build parent -> child scopes
    parent = Scope()
    parent["a"] = 1
    child = Scope(parent=parent)
    child["a"] = 2  # override parent
    child["b"] = IString("Hello")
    # Nested scope bound in child
    inner = Scope()
    inner["x"] = 3
    child["inner"] = inner

    # _scope_to_dict flattens parent chain with child overriding
    out = _scope_to_dict(child)
    assert out["a"] == 2
    assert out["b"] == "Hello"  # IString normalized to str by _tmpl_normalize_value
    assert isinstance(out["inner"], dict) and out["inner"]["x"] == 3

    # _tmpl_normalize_value on various inputs
    assert _tmpl_normalize_value(IString("X")) == "X"
    assert _tmpl_normalize_value([IString("Y"), 1]) == ["Y", 1]
    norm = _tmpl_normalize_value(child)  # scope -> plain dict
    assert norm["a"] == 2 and isinstance(norm["inner"], dict)


def _make_fn_with_sig(positional=None, keywords=None, rest=None, closure=None):
    # Helper to build a SlipFunction with a typed Sig in meta
    args_sig = Sig(positional or [], keywords or {}, rest, None)
    body = Code([])  # empty body; not executed in these unit tests
    fn = SlipFunction(args_sig, body, closure or Scope())
    fn.meta["type"] = args_sig
    return fn


def test_merge_methods_into_container_dedup_and_examples_merge():
    ev = Evaluator()

    # Existing GF with one typed method
    gf = GenericFunction("f")
    closure = Scope()
    m1 = _make_fn_with_sig(positional=[], keywords={"a": GetPath([Name("int")])}, closure=closure)
    gf.add_method(m1)

    # New method with the SAME signature, but with an example attached
    dup = _make_fn_with_sig(positional=[], keywords={"a": GetPath([Name("int")])}, closure=closure)
    dup.meta["examples"] = [Sig([], {"a": 1}, None, 1)]

    # New method with a different signature
    new = _make_fn_with_sig(positional=[], keywords={"a": GetPath([Name("string")])}, closure=closure)
    new.meta["examples"] = [Sig([], {"a": "s"}, None, "s")]

    merged = ev._merge_methods_into_container(gf, [dup, new])

    # Should still have 2 methods total: original int-method + new string-method
    assert isinstance(merged, GenericFunction)
    assert len(merged.methods) == 2

    # The example from dup should be merged into the existing int method
    int_method = None
    for m in merged.methods:
        kw = m.meta.get("type").keywords
        # detect int signature
        ann = kw.get("a")
        if isinstance(ann, GetPath) and len(ann.segments) == 1 and isinstance(ann.segments[0], Name) and ann.segments[0].text == "int":
            int_method = m
            break
    assert int_method is not None
    exs = int_method.meta.get("examples") or []
    assert any(isinstance(e, Sig) and e.keywords.get("a") == 1 for e in exs)


def test_infer_primitive_name_variants():
    ev = Evaluator()
    # primitives
    assert ev._infer_primitive_name(None) == "none"
    assert ev._infer_primitive_name(True) == "boolean"
    assert ev._infer_primitive_name(1) == "int"
    assert ev._infer_primitive_name(1.0) == "float"
    assert ev._infer_primitive_name(IString("s")) == "i-string"
    assert ev._infer_primitive_name("s") == "string"
    assert ev._infer_primitive_name([1, 2]) == "list"
    assert ev._infer_primitive_name({"a": 1}) == "dict"
    s = Scope()
    assert ev._infer_primitive_name(s) == "scope"
    # path-like
    assert ev._infer_primitive_name(GetPath([Name("x")])) == "path"
    assert ev._infer_primitive_name(PathLiteral(GetPath([Name("x")]))) == "path"
    assert ev._infer_primitive_name(SetPath([Name("x")])) == "path"
    assert ev._infer_primitive_name(DelPath(GetPath([Name("x")])) ) == "path"
    assert ev._infer_primitive_name(PipedPath([Name("x")])) == "path"
    assert ev._infer_primitive_name(MultiSetPath([SetPath([Name("x")])])) == "path"
    # callable
    fn = _make_fn_with_sig()
    gf = GenericFunction("g")
    assert ev._infer_primitive_name(fn) == "function"
    assert ev._infer_primitive_name(gf) == "function"
    # code
    assert ev._infer_primitive_name(Code([])) == "code"


@pytest.mark.asyncio
async def test_sig_types_match_primitives_and_scopes():
    ev = Evaluator()

    # Primitive annotation {a: `int`}
    sig_int = Sig([], {"a": GetPath([Name("int")])}, None, None)
    meth_int = _make_fn_with_sig(positional=[], keywords={"a": GetPath([Name("int")])})
    ok_prim = await ev._sig_types_match(sig_int, meth_int, [123], Scope())
    bad_prim = await ev._sig_types_match(sig_int, meth_int, ["x"], Scope())
    assert ok_prim is True and bad_prim is False

    # Scope annotation resolved via method.closure: {x: Player}
    Player = Scope()
    Player["kind"] = "proto"
    closure = Scope()
    closure["Player"] = Player

    sig_scope = Sig([], {"x": GetPath([Name("Player")])}, None, None)
    meth_scope = _make_fn_with_sig(positional=[], keywords={"x": GetPath([Name("Player")])}, closure=closure)

    # Instance that inherits from Player
    inst = Scope()
    inst.inherit(Player)

    ok_scope = await ev._sig_types_match(sig_scope, meth_scope, [inst], Scope())
    assert ok_scope is True

    # Mismatch: a dict won't match the Player scope annotation
    bad_scope = await ev._sig_types_match(sig_scope, meth_scope, [{"x": 1}], Scope())
    assert bad_scope is False


@pytest.mark.asyncio
async def test_unary_piped_operator_custom_and_error_cases():
    # Success case: define a unary function and use the unary pipe form
    src_ok = """
    double: fn {x} [ x * 2 ]
    5 |double
    """
    res_ok = await ScriptRunner().handle_script(src_ok)
    assert res_ok.status == "success" and res_ok.value == 10

    # Error case (existing coverage): unary pipe with a binary function like add
    res_err = await ScriptRunner().handle_script("5 |add")
    assert res_err.status == "error"
    assert "TypeError: invalid-args in (add)" in (res_err.error_message or "")
