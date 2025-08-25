import struct
import pytest
from slip import ScriptRunner

async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)

def assert_ok(res, expected=None):
    assert res.status == 'success', res.error_message
    if expected is not None:
        assert res.value == expected

@pytest.mark.asyncio
async def test_u8_literal_to_bytes_and_to_str():
    # u8#[65, 66, 67] -> b'ABC'
    src = "u8#[65, 66, 67]"
    res = await run_slip(src)
    assert_ok(res, b"ABC")
    # to-str decodes bytes as UTF-8
    src2 = """
    x: u8#[65,66,67]
    to-str x
    """
    res2 = await run_slip(src2)
    assert_ok(res2, "ABC")

@pytest.mark.asyncio
async def test_i8_wrap_and_sign():
    # i8 negative wraps modulo 256
    src = "i8#[-1, 0, 127, -128]"
    res = await run_slip(src)
    assert_ok(res, bytes([255, 0, 127, 128]))

@pytest.mark.asyncio
async def test_i16_and_endianness():
    # i16 is little-endian: [-1, 1000, 42] -> 0xFFFF, 0x03E8, 0x002A
    src = "i16#[-1, 1000, 42]"
    res = await run_slip(src)
    expected = b"\xff\xff" + b"\xe8\x03" + b"\x2a\x00"
    assert_ok(res, expected)
    # Order preservation
    src2 = "i16#[1000, -1]"
    res2 = await run_slip(src2)
    assert_ok(res2, b"\xe8\x03\xff\xff")

@pytest.mark.asyncio
async def test_u16_u32_u64_unsigned():
    src = "u16#[65535, 1]"
    res = await run_slip(src)
    assert_ok(res, b"\xff\xff\x01\x00")
    src2 = "u32#[4294967295, 1]"
    res2 = await run_slip(src2)
    assert_ok(res2, b"\xff\xff\xff\xff\x01\x00\x00\x00")
    src3 = "u64#[18446744073709551615, 1]"
    res3 = await run_slip(src3)
    assert_ok(res3, b"\xff\xff\xff\xff\xff\xff\xff\xff\x01\x00\x00\x00\x00\x00\x00\x00")

@pytest.mark.asyncio
async def test_f32_and_f64_literals():
    src = "f32#[3.14, 2.71]"
    res = await run_slip(src)
    expected = struct.pack("<f", 3.14) + struct.pack("<f", 2.71)
    assert_ok(res, expected)
    src2 = "f64#[3.14, 2.71]"
    res2 = await run_slip(src2)
    expected2 = struct.pack("<d", 3.14) + struct.pack("<d", 2.71)
    assert_ok(res2, expected2)

@pytest.mark.asyncio
async def test_b1_bit_packing_full_and_partial():
    # Full byte: 1 0 1 1 0 0 1 0 -> 0b10110010 = 0xB2
    src = "b1#[1,0,1,1,0,0,1,0]"
    res = await run_slip(src)
    assert_ok(res, bytes([0xB2]))
    # Partial byte pads remaining bits to the left (MSB side): 1 0 1 -> 10100000 = 0xA0
    src2 = "b1#[1,0,1]"
    res2 = await run_slip(src2)
    assert_ok(res2, bytes([0xA0]))

@pytest.mark.asyncio
async def test_file_put_with_bytestream(tmp_path):
    # Write bytes produced by a typed stream to disk
    target = tmp_path / "payload.bin"
    url = f"file:///{str(target).lstrip('/')}"
    src = f"""
    {url}: u8#[65, 66, 67]
    """
    res = await run_slip(src)
    assert_ok(res)
    assert target.read_bytes() == b"ABC"
