import pytest
from slip.slip_interpreter import Evaluator

def test_http_trailing_segment_str_helpers_roundtrip():
    ev = Evaluator()
    pr = ev.path_resolver
    s = "http://h/a.b#(cfg)"
    assert pr._http_has_trailing_segments_str(s) is True
    assert pr._canonicalize_http_token(s) == "http://h/a"
    assert pr._http_has_trailing_segments_str("http://h/a") is False
