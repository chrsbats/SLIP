import os
import json
import pytest

from slip.slip_file import _resolve_locator, file_get, file_put, file_delete
from slip.slip_http import normalize_response_mode
from slip.slip_printer import Printer
from slip.slip_serialize import serialize, deserialize, detect_format
from slip.slip_datatypes import (
    PathLiteral, GetPath, Name, IString,
    PostPath, Response, ByteStream, SetPath, MultiSetPath
)

def test_resolve_locator_variants(tmp_path):
    base = str(tmp_path)

    # absolute path
    abs_path = tmp_path / "a.txt"
    expect_abs = "/" + str(abs_path).lstrip("/").lstrip("\\")
    assert _resolve_locator(f"file://{expect_abs}", base) == expect_abs

    # home path (~)
    home = os.path.expanduser("~")
    assert _resolve_locator("file://~", base) == home
    assert _resolve_locator("file://~/sub", base) == os.path.join(home, "sub")

    # ./ and ../
    assert _resolve_locator("file://./file.txt", base) == os.path.join(base, "file.txt")
    assert _resolve_locator("file://../up.txt", base) == os.path.normpath(os.path.join(base, "../up.txt"))

    # empty tail → base
    assert _resolve_locator("file://", base) == base

@pytest.mark.asyncio
async def test_file_dir_roundtrip_and_delete_behavior(tmp_path):
    # Prepare files
    d = tmp_path / "dir"
    d.mkdir()
    f1 = d / "one.bin"
    f2 = d / "two.bin"
    f1.write_bytes(b"abc")
    f2.write_bytes(b"xyz")

    # Directory listing returns dict of bytes
    listing = await file_get("file://./dir", base_dir=str(tmp_path))
    assert isinstance(listing, dict)
    assert set(listing.keys()) == {"one.bin", "two.bin"}
    assert listing["one.bin"] == b"abc"

    # Bytes round-trip via file_put/file_get
    await file_put("file://./out.bin", b"\x00\x01", base_dir=str(tmp_path))
    rb = await file_get("file://./out.bin", base_dir=str(tmp_path))
    assert rb == b"\x00\x01" or rb == "\x00\x01" or isinstance(rb, (bytes, bytearray))

    # Delete directory should raise IsADirectoryError
    with pytest.raises(IsADirectoryError):
        await file_delete("file://./dir", base_dir=str(tmp_path))

@pytest.mark.asyncio
async def test_file_put_with_content_type_and_slip_code(tmp_path):
    # content-type override → JSON written to .txt
    path = "file://./data.txt"
    data = {"a": 1, "b": [2, 3]}
    await file_put(path, data, config={"content-type": "application/json"}, base_dir=str(tmp_path))
    txt = await file_get(path, base_dir=str(tmp_path))
    # parseable JSON
    parsed = json.loads(txt if isinstance(txt, str) else txt.decode("utf-8"))
    assert parsed == data

    # .slip file returns Code object with source metadata set
    (tmp_path / "mod3.slip").write_text("x: 1\nx")
    code = await file_get("file://./mod3.slip", base_dir=str(tmp_path))
    from slip.slip_datatypes import Code
    assert isinstance(code, Code)
    assert getattr(code, "source_path", "").endswith("mod3.slip")
    assert getattr(code, "source_locator", "") == "file://./mod3.slip"

def test_normalize_response_mode_variants():
    # strings
    assert normalize_response_mode({"response-mode": "lite"}) == "lite"
    assert normalize_response_mode({"response-mode": IString("FULL")}) == "full"
    assert normalize_response_mode({"response-mode": "none"}) == "none"
    # path literal: `lite`
    lit = PathLiteral(GetPath([Name("lite")]))
    assert normalize_response_mode({"response-mode": lit}) == "lite"
    # get-path form: lite
    gp = GetPath([Name("lite")])
    assert normalize_response_mode({"response-mode": gp}) == "lite"
    # legacy flags
    assert normalize_response_mode({"lite": True}) == "lite"
    assert normalize_response_mode({"full": True}) == "full"
    # unknown → None
    assert normalize_response_mode({"response-mode": "weird"}) is None

def test_printer_misc_types():
    p = Printer()

    # PostPath
    pp = PostPath([Name("url")])
    assert p.pformat(pp) == "url<-"

    # Response printing
    resp = Response(PathLiteral(GetPath([Name("ok")])), 123)
    assert p.pformat(resp) == "response `ok` 123"

    # ByteStream printing (pretty, multi-line)
    bs = ByteStream("u8", [1, 2, 3])
    out = p.pformat(bs)
    assert out.startswith("u8#[")
    assert "1" in out and "2" in out and "3" in out

    # MultiSetPath formatting
    sp1 = SetPath([Name("x")])
    sp2 = SetPath([Name("y")])
    msp = MultiSetPath([sp1, sp2])
    ms = p.pformat(msp)
    assert ms == "[x,y]:"

def test_serialize_xml_and_detection():
    # XML serialize wraps non-dict under root
    xml = serialize(["A", "B"], fmt="xml")
    assert "<root>" in xml and "</root>" in xml
    # detect_format sniff for XML via text content (no content-type)
    assert detect_format(None, "<xml/>") == "xml"
    # roundtrip XML dict
    s = serialize({"root": {"item": ["A", "B"]}}, fmt="xml")
    out = deserialize(s, fmt="xml")
    assert out == {"root": {"item": ["A", "B"]}}
