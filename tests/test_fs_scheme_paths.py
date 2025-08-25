import os
import pytest
import json
import yaml
from slip import ScriptRunner
from slip.slip_datatypes import Code

async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)

def assert_ok(res, expected=None):
    assert res.status == 'success', res.error_message
    if expected is not None:
        assert res.value == expected

def assert_error(res, contains: str | None = None):
    assert res.status == 'error', f"expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or ""), f"error did not contain {contains!r}: {res.error_message!r}"

@pytest.mark.asyncio
async def test_file_get_directory_keys_and_file_read(tmp_path):
    # Create files
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.bin"
    f1.write_text("hello", encoding="utf-8")
    f2.write_bytes(b"\x01\x02\x03")

    # Read directory and list keys
    url_dir = f"file:///{str(tmp_path).lstrip('/')}"
    src = f"""
    dir: {url_dir}
    sort (keys dir)
    """
    res = await run_slip(src)
    assert_ok(res)
    names = res.value
    assert "a.txt" in names
    assert "b.bin" in names

    # Read a file (text)
    url_file = f"file:///{str(f1).lstrip('/')}"
    res2 = await run_slip(url_file)
    assert_ok(res2, "hello")

@pytest.mark.asyncio
async def test_file_put_then_get_roundtrip(tmp_path):
    target = tmp_path / "out.txt"
    url_file = f"file:///{str(target).lstrip('/')}"
    src = f'''
    {url_file}: "world"
    {url_file}
    '''
    res = await run_slip(src)
    assert_ok(res, "world")
    # Also verify on disk
    assert target.read_text(encoding="utf-8") == "world"

@pytest.mark.asyncio
async def test_file_read_by_extension_text_and_structured(tmp_path):
    f_md = tmp_path / "readme.md"
    f_md.write_text("# Title", encoding="utf-8")
    f_json = tmp_path / "data.json"
    f_yaml = tmp_path / "data.yaml"
    f_yml  = tmp_path / "data.yml"
    f_toml = tmp_path / "data.toml"
    f_json.write_text('{"a": 1, "b": "x"}', encoding="utf-8")
    f_yaml.write_text("a: 1\nb: x\n", encoding="utf-8")
    f_yml.write_text("a: 2\nb: y\n", encoding="utf-8")
    f_toml.write_text('a = 3\nb = "z"\n', encoding="utf-8")
    url_md   = f"file:///{str(f_md).lstrip('/')}"
    url_json = f"file:///{str(f_json).lstrip('/')}"
    url_yaml = f"file:///{str(f_yaml).lstrip('/')}"
    url_yml  = f"file:///{str(f_yml).lstrip('/')}"
    url_toml = f"file:///{str(f_toml).lstrip('/')}"
    res_md = await run_slip(url_md)
    assert_ok(res_md, "# Title")
    res_json = await run_slip(url_json)
    assert_ok(res_json); assert res_json.value == {"a": 1, "b": "x"}
    res_yaml = await run_slip(url_yaml)
    assert_ok(res_yaml); assert res_yaml.value == {"a": 1, "b": "x"}
    res_yml = await run_slip(url_yml)
    assert_ok(res_yml); assert res_yml.value == {"a": 2, "b": "y"}
    res_toml = await run_slip(url_toml)
    assert_ok(res_toml); assert res_toml.value == {"a": 3, "b": "z"}

@pytest.mark.asyncio
async def test_file_put_serializes_json_and_yaml_then_roundtrip(tmp_path):
    f_json = tmp_path / "out.json"
    url_json = f"file:///{str(f_json).lstrip('/')}"
    src_json = f"""
    {url_json}: #{{ a: 10, b: 'hi' }}
    {url_json}
    """
    res_json = await run_slip(src_json)
    assert_ok(res_json); assert res_json.value == {"a": 10, "b": "hi"}
    with open(f_json, "r", encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert on_disk == {"a": 10, "b": "hi"}
    f_yaml = tmp_path / "out.yaml"
    url_yaml = f"file:///{str(f_yaml).lstrip('/')}"
    src_yaml = f"""
    {url_yaml}: #{{ a: 20, b: 'yo' }}
    {url_yaml}
    """
    res_yaml = await run_slip(src_yaml)
    assert_ok(res_yaml); assert res_yaml.value == {"a": 20, "b": "yo"}
    with open(f_yaml, "r", encoding="utf-8") as fh:
        on_disk_yaml = yaml.safe_load(fh)
    assert on_disk_yaml == {"a": 20, "b": "yo"}

@pytest.mark.asyncio
async def test_file_put_plain_text_and_read(tmp_path):
    f_txt = tmp_path / "note.txt"
    url_txt = f"file:///{str(f_txt).lstrip('/')}"
    src = f"""
    {url_txt}: 'hello world'
    {url_txt}
    """
    res = await run_slip(src)
    assert_ok(res, "hello world")
    assert f_txt.read_text(encoding="utf-8") == "hello world"
    f_md = tmp_path / "note.md"
    url_md = f"file:///{str(f_md).lstrip('/')}"
    src2 = f"""
    {url_md}: 'markdown text'
    {url_md}
    """
    res2 = await run_slip(src2)
    assert_ok(res2, "markdown text")
    assert f_md.read_text(encoding="utf-8") == "markdown text"

@pytest.mark.asyncio
async def test_file_delete_then_read_raises(tmp_path):
    f_txt = tmp_path / "temp.txt"
    url = f"file:///{str(f_txt).lstrip('/')}"
    src = f"""
    {url}: 'to be removed'
    ~{url}
    {url}
    """
    res = await run_slip(src)
    assert_error(res, "PathNotFound")

@pytest.mark.asyncio
async def test_file_resolution_bare_dot_and_parent(tmp_path, monkeypatch):
    a = tmp_path / "a.txt"
    a.write_text("ok", encoding="utf-8")
    (tmp_path / "sub").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path)
    url_bare = "file://"
    url_dot  = "file://./"
    url_parent = "file://../"
    src1 = f"""
    d1: {url_bare}
    sort (keys d1)
    """
    res1 = await run_slip(src1)
    assert_ok(res1); assert "a.txt" in res1.value
    src2 = f"""
    d2: {url_dot}
    sort (keys d2)
    """
    res2 = await run_slip(src2)
    assert_ok(res2); assert "a.txt" in res2.value
    res3 = await run_slip(url_parent)
    assert_ok(res3); assert isinstance(res3.value, dict)

@pytest.mark.asyncio
async def test_file_put_with_content_type_overrides_serialization(tmp_path):
    target = tmp_path / "payload.txt"
    url = f"file:///{str(target).lstrip('/')}"
    src = f"""
    {url}#(content-type: "application/json"): #{{ a: 42, b: "ok" }}
    """
    res = await run_slip(src)
    assert_ok(res)
    # Verify on disk content is valid JSON with expected structure
    import json
    with open(target, "r", encoding="utf-8") as fh:
        body = fh.read()
    assert json.loads(body) == {"a": 42, "b": "ok"}


@pytest.mark.asyncio
async def test_file_slip_locator_returns_code_and_runs(tmp_path):
    # Create a SLIP source file without an explicit surrounding code block.
    mod = tmp_path / "module.slip"
    mod.write_text("val: 41\nval + 1\n", encoding="utf-8")
    url = f"file:///{str(mod).lstrip('/')}"

    # Directly evaluating the locator should return a Code block (not execute it).
    res = await run_slip(url)
    assert_ok(res)
    assert isinstance(res.value, Code)

    # When bound and passed to 'run', it should execute and return the last value.
    src = f"""
    c: {url}
    run c
    """
    res2 = await run_slip(src)
    assert_ok(res2, 42)
