from slip.slip_interpreter import Evaluator
from slip.slip_datatypes import GetPath, SetPath, Name

def test_http_token_canonicalization_and_trailing_detection():
    ev = Evaluator()
    pr = ev.path_resolver

    assert pr._canonicalize_http_token("http://h/a.b#(cfg)") == "http://h/a"
    assert pr._canonicalize_http_token("http://h/a[b]") == "http://h/a"
    assert pr._http_has_trailing_segments_str("http://h/a.b#(cfg)") is True
    assert pr._http_has_trailing_segments_str("http://h/a#(cfg)") is False

def test_file_token_canonicalization_and_trailing_detection():
    ev = Evaluator()
    pr = ev.path_resolver

    assert pr._canonicalize_file_token("file:///tmp/x.json#(cfg)") == "file:///tmp/x.json"
    assert pr._canonicalize_file_token("file:///tmp/x.json[0]") == "file:///tmp/x.json"
    assert pr._file_has_trailing_segments_str("file:///tmp/x.json") is False
    assert pr._file_has_trailing_segments_str("file:///tmp/x.json[0]") is True

def test_extract_http_url_from_loc_and_segments_and_has_trailing():
    ev = Evaluator()
    pr = ev.path_resolver

    # From segment text
    p = GetPath([Name("http://h/a.b#(cfg)")])
    assert pr._extract_http_url(p).startswith("http://h/a")

    # From loc text, and SetPath should strip trailing colon
    p2 = SetPath([Name("http://h/a.b:")])
    # simulate tokenizer text via loc
    try:
        p2.loc = {"text": "http://h/a.b:#(cfg)"}
    except Exception:
        pass
    assert pr._extract_http_url(p2) == "http://h/a"

    # Trailing segments present when more than one segment
    p3 = GetPath([Name("http://h/a"), Name("b")])
    assert pr._has_http_trailing_segments(p3) is True

def test_extract_file_locator_variants_and_trailing():
    ev = Evaluator()
    pr = ev.path_resolver

    p = GetPath([Name("file:///tmp/x.json[0]")])
    assert pr._extract_file_locator(p) == "file:///tmp/x.json"

    p2 = GetPath([Name("file://./")])
    assert pr._extract_file_locator(p2) == "file://./"

    # If path has extra segments, has trailing segments is True
    p3 = GetPath([Name("file:///tmp/x.json"), Name("more")])
    assert pr._has_file_trailing_segments(p3) is True
