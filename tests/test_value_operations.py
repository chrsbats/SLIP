import json
import struct

import pytest

from slip import ScriptRunner, slip_core as core
from slip.slip_library import library_scope
from slip.slip_resources import read_file
from slip.slip_syntax import format_source, parse


@pytest.mark.parametrize(("source", "expected"), [
    ("u8#[65, 66, 67]", b"ABC"),
    ("u8#[-1, 256, 257]", b"\xff\0\1"),
    ("i8#[-1, 127, -128, 256]", b"\xff\x7f\x80\0"),
    ("u16#[65535, 65536, -1]", b"\xff\xff\0\0\xff\xff"),
    ("i16#[-1, 1000, -32768]", b"\xff\xff\xe8\3\0\x80"),
    ("u32#[4294967295, 1]", b"\xff\xff\xff\xff\1\0\0\0"),
    ("i32#[-2147483648]", b"\0\0\0\x80"),
    ("u64#[18446744073709551615]", b"\xff" * 8),
    ("i64#[-9223372036854775808]", b"\0" * 7 + b"\x80"),
    ("f32#[3.14, -0.0]", struct.pack("<ff", 3.14, -0.0)),
    ("f64#[3.14, -0.0]", struct.pack("<dd", 3.14, -0.0)),
    ("b1#[1, 0, 1, 1, 0, 0, 1, 0]", b"\xb2"),
    ("b1#[true, false, true, none, 0, 1, 1, 0, true]", b"\xa6\x80"),
    ("u8#[65 + 1]", b"B"),
])
def test_typed_stream_bytes(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == "ok", result.error_message
        assert result.value == expected and isinstance(result.value, bytes)


@pytest.mark.parametrize("kind", [
    "u8", "u16", "u32", "u64", "i8", "i16", "i32", "i64", "f32", "f64", "b1",
])
def test_empty_streams_and_symbolic_source_round_trip(kind):
    code = parse(f"{kind}#[]")
    assert parse(format_source(code))[0][0] == code
    assert code.stacks is None
    assert core.execute(code, library_scope()) == b""


@pytest.mark.parametrize("source", [
    "i16#[32768]", "i32#[2147483648]", "i64#[9223372036854775808]",
    "u8#['not an integer']", "f32#['not a number']",
])
def test_invalid_stream_values_are_runtime_errors(source):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == "err"
        assert "byte stream" in result.error_message


def test_stream_elements_are_live_ordered_and_bound_once(monkeypatch):
    calls = []
    with ScriptRunner() as runner:
        def sample(value):
            calls.append(value)
            return value

        runner.root_scope["sample"] = sample
        defined = runner.handle_script(
            "encode: fn {x} [u8#[sample x, sample (x + 1)]]",
        )
        assert defined.status == "ok", defined.error_message
        assert calls == []
        method = runner.scope["encode"].methods[0]
        saved = method.stacks
        assert isinstance(saved[0][0], core.Get)

        def forbidden(*args, **kwargs):
            raise AssertionError("warm binary constructor rebound source")

        monkeypatch.setattr(core, "convert", forbidden)
        assert core.invoke(runner.scope["encode"], [65], runner.scope) \
            == b"AB"
        assert core.invoke(runner.scope["encode"], [67], runner.scope) \
            == b"CD"
        assert calls == [65, 66, 67, 68] and method.stacks is saved


def test_streams_file_io_printing_and_unbound_cache(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("SLIP_CACHE_DIR", str(tmp_path / "cache"))
    path = tmp_path / "module.slip"
    path.write_text("encode: fn {x} [u16#[x, x + 1]]\n")
    first, second = read_file(path, {}), read_file(path, {})
    assert first == second and first is not second
    assert first[0][3][0][0].code.stacks is None
    assert parse(format_source(first))[0][0] == first
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        result = runner.handle_script("""
            module: import `file://module.slip`
            file://payload.bin: module.encode 256
            #[to-str u8#[65, 66, 67], to-str u8#[255]]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == ["ABC", "\ufffd"]
        assert (tmp_path / "payload.bin").read_bytes() == b"\0\1\1\1"
        bytes_source = format_source(b"\0\xff")
        assert core.execute(parse(bytes_source), library_scope()) \
            == b"\0\xff"


@pytest.mark.parametrize(("source", "expected"), [
    ("#[is-number 1, is-number 1.5, is-number true]", [True, True, False]),
    ("#[is-string 'x', is-string \"x\", is-string none]", [True, True, False]),
    ("#[is-list #[], is-list [1], is-code [1]]", [True, False, True]),
    ("#[is-dict #{}, is-dict (scope #{}), is-scope (scope #{})]",
     [True, False, True]),
    ("#[is-path `a.b`, is-path 'a.b', is-fn (fn {x} [x])]",
     [True, False, True]),
    ("#[is-boolean false, is-boolean 0, is-none none, is-none false]",
     [True, False, True, False]),
    ("#[is-number u8#[1], is-string u8#[65]]", [False, True]),
])
def test_standard_predicates(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == "ok", result.error_message
        assert result.value == expected


@pytest.mark.parametrize("format", ["json", "yaml", "toml"])
@pytest.mark.parametrize("quoted", [False, True])
def test_serialization_round_trip(format, quoted):
    name = f"'{format}'" if quoted else f"`{format}`"
    with ScriptRunner() as runner:
        result = runner.handle_script(f"""
            data: #{{name: "雪", enabled: false, values: #[1, 2]}}
            text: to {name} data
            #[type-of text = `string`, from {name} text]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [True, {
            "name": "雪", "enabled": False, "values": [1, 2],
        }]


def test_yaml_12_and_reference_decode_fallbacks():
    with ScriptRunner() as runner:
        result = runner.handle_script("""
            #[from `yaml` 'flag: on\\nother: off\\nenabled: true',
              from `json` 'a: 1', from `toml` '[broken',
              from `yaml` '[broken', from `json` '[broken']
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [
            {"flag": "on", "other": "off", "enabled": True},
            {"a": 1}, "[broken", "[broken", "[broken",
        ]


def test_formatted_emit_preserves_structured_and_unformatted_messages():
    with ScriptRunner() as runner:
        result = runner.handle_script("""
            data: #{hp: 120, names: #["雪"]}
            emit #['self', 'others'] data
            emit 'stdout' `json` data
            emit 'audit' 'yaml' data
            emit 'debug' 'hello' 42
            data.hp
        """)
        assert result.status == "ok", result.error_message
        assert result.value == 120
        effects = result.side_effects
        assert effects[0] == {"topics": ["self", "others"],
                              "message": {"hp": 120, "names": ["雪"]}}
        assert json.loads(effects[1]["message"]) == effects[0]["message"]
        assert "hp: 120" in effects[2]["message"]
        assert effects[3] == {"topics": ["debug"], "message": "hello 42"}


@pytest.mark.parametrize(("source", "message"), [
    ("to `unsupported` #{}", "format"),
    ("from `unsupported` 'text'", "format"),
    ("to `json` (fn {x} [x])", "serializable"),
])
def test_serialization_errors_remain_errors(source, message):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == "err"
        assert message in result.error_message
