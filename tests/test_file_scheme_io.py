import os
import json
import pytest

from slip.slip_file import file_put, file_get, file_delete

@pytest.mark.asyncio
async def test_file_put_get_json_roundtrip(tmp_path):
    p = tmp_path / "data.json"
    locator = f"file://{p.as_posix()}"
    await file_put(locator, {"x": 1})
    got = await file_get(locator)
    assert got == {"x": 1}

@pytest.mark.asyncio
async def test_file_put_with_content_type_override_writes_json_string(tmp_path):
    p = tmp_path / "out.txt"
    locator = f"file://{p.as_posix()}"
    await file_put(locator, {"a": 2}, {"content-type": "application/json"})
    text = await file_get(locator)
    # It should be JSON text (not a dict)
    assert isinstance(text, str)
    assert json.loads(text) == {"a": 2}

@pytest.mark.asyncio
async def test_file_get_directory_returns_file_map(tmp_path):
    # create some files
    (tmp_path / "a.txt").write_text("A", encoding="utf-8")
    (tmp_path / "b.bin").write_bytes(b"\x00\x01")
    locator = f"file://{tmp_path.as_posix()}"
    out = await file_get(locator)
    # dict of filename -> bytes
    assert isinstance(out, dict)
    assert out["a.txt"] == b"A"
    assert out["b.bin"] == b"\x00\x01"

@pytest.mark.asyncio
async def test_file_delete_file_and_directory_behavior(tmp_path):
    # file deletion
    p = tmp_path / "t.txt"
    p.write_text("hi", encoding="utf-8")
    locator = f"file://{p.as_posix()}"
    await file_delete(locator)
    assert not p.exists()

    # directory deletion should raise IsADirectoryError
    d = tmp_path / "dir"
    d.mkdir()
    d_locator = f"file://{d.as_posix()}"
    with pytest.raises(IsADirectoryError):
        await file_delete(d_locator)
