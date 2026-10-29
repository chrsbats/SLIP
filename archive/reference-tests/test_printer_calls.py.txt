from slip.slip_printer import Printer
from slip.slip_datatypes import GetPath, Name, Code

def test_pformat_lisp_style_call_private():
    pr = Printer()
    # Build a faux call node: head + args; strings are fine for args
    call = [GetPath([Name("foo")]), "a", "b", "c"]
    s = pr._pformat_lisp_style_call(call, 0)
    lines = s.splitlines()
    assert lines[0] == "foo 'a'"
    # subsequent args each on their own line
    assert "'b'" in lines[1]
    assert "'c'" in lines[2]

def test_pformat_expr_line_aware_split_on_multiline_arg():
    pr = Printer()
    # This Code value with two expressions will render as a multi-line block
    multi = Code([[GetPath([Name("a")])], [GetPath([Name("b")])]])
    call = [GetPath([Name("do-something")]), multi, "x"]
    out = pr.pformat(call)
    lines = out.splitlines()
    # First line is head only because the first arg is multi-line
    assert lines[0] == "do-something"
    # Next lines include rendered Code block then the remaining arg
    assert lines[1].startswith("[")
    assert lines[-1] == "'x'"
