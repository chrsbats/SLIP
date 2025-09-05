import pytest
from slip.slip_serialize import serialize, deserialize, detect_format

def test_json_roundtrip():
    value = {"a": 1, "b": [1, 2, "x"], "c": {"d": True}}
    s = serialize(value, fmt="json")
    out = deserialize(s)  # JSON is sniffed from leading "{"
    assert out == value

def test_yaml_roundtrip_content_type():
    value = {"a": 1, "b": ["x", "y"], "c": {"d": 2}}
    s = serialize(value, fmt="yaml")
    out = deserialize(s, content_type="application/x-yaml")
    assert out == value

def test_yaml_with_json_content_type_fallback():
    # YAML payload mislabeled as JSON should still load via fallback to YAML
    yaml_text = "a: 1\nb: [x, y]\n"
    out = deserialize(yaml_text, content_type="application/json")
    assert out == {"a": 1, "b": ["x", "y"]}

def test_toml_roundtrip_with_fmt():
    value = {"title": "TOML Example", "owner": {"name": "Tom"}}
    s = serialize(value, fmt="toml")
    out = deserialize(s, fmt="toml")  # TOML requires explicit fmt or content type
    assert out == value

def test_xml_roundtrip_with_fmt():
    # Use string values to avoid XML numeric typing ambiguity
    value = {"root": {"item": ["A", "B"], "note": "x"}}
    s = serialize(value, fmt="xml")
    out = deserialize(s, fmt="xml")
    assert out == value

def test_html_deserialize_via_content_type():
    html = "<html><head><title>t</title></head><body><p>Hello</p></body></html>"
    out = deserialize(html, content_type="text/html")
    assert out["html"]["head"]["title"] == "t"
    assert out["html"]["body"]["p"] == "Hello"

@pytest.mark.parametrize(
    "ct,expected",
    [
        ("application/json", "json"),
        ("application/x-yaml", "yaml"),
        ("application/yaml", "yaml"),
        ("application/toml", "toml"),
        ("application/xml", "xml"),
        ("text/html", "xml"),  # detect_format treats HTML as XML-family
    ],
)
def test_detect_format_from_content_type(ct, expected):
    assert detect_format(ct) == expected

def test_deserialize_bytes_with_charset_yaml():
    data = "a: 1\n".encode("utf-8")
    out = deserialize(data, content_type="application/x-yaml; charset=utf-8")
    assert out == {"a": 1}

def test_deserialize_unknown_returns_text():
    txt = "plain text"
    out = deserialize(txt, content_type="text/plain")
    assert out == "plain text"
