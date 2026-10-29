import pytest

from slip import ScriptRunner
from slip.slip_core import Path as SlipPath, PathLiteral


@pytest.mark.parametrize(("source", "expected"), [
    ("User: schema #{name: `string`}; #[is-schema User, is-a User Schema, "
     "is-scope User]", [True, True, True]),
    ("User: schema #{name: `string`}; validate #{name: 'Ada', extra: 1} User",
     {"name": "Ada"}),
    ("Base: schema #{port: default 80, host: default 'localhost'}; "
     "Child: create Base [port: default 8080]; validate #{} Child",
     {"port": 8080, "host": "localhost"}),
    ("Address: schema #{zip: `int`, country: default 'GB'}; "
     "Profile: schema #{name: `string`, address: optional Address, "
     "nickname: optional `string`, active: default true}; "
     "validate #{name: 'Ada', address: #{zip: 123}} Profile",
     {"name": "Ada", "address": {"zip": 123, "country": "GB"},
      "active": True}),
    ("Profile: schema #{name: `string`, active: default true}; "
     "validate #{name: 'Ada', active: false} Profile",
     {"name": "Ada", "active": False}),
    ("T: schema #{amount: `number`}; validate #{amount: 1.5} T",
     {"amount": 1.5}),
    ("x: 1; r: ref `x`; first: r; x: 2; #[first, r]", [1, 2]),
    ("d: #{hp: 10}; r: ref `d.hp`; d: #{hp: 20}; r", 20),
    ("x: 1; rx: ref `x`; c: cell {x: rx} [x + 1]; "
     "first: c; x: 2; #[first, c]", [2, 3]),
    ("d: #{hp: 50}; c: cell {hp: `d.hp`} [hp < 60]; c", True),
    ("make: fn {x} [cell {x: `x`} [x + 1]]; c: make 7; c", 8),
    ("add: fn {x, y} [x + y] |example {x: 2, y: 3 -> 5}; test add", 1),
    ("x: 2; y: 3; add: fn {x, y} [x + y]; "
     "example add {x, y -> 5}; test add", 1),
    ("h: fn {x} [x + 1] |example {x: 1 -> 2} |example {x: 2 -> 3}; test h", 2),
    ("g: fn {x} [x] |example {x: 1 -> 1}; g: fn {x, y} [x + y]; "
     "example g {x: 2, y: 3 -> 5}; test g", 2),
    ("f: fn {x} ['guarded'] |where [x > 0] |where [x < 10]; "
     "f: fn {x} ['other']; #[f -1, f 5, f 11]", ["other", "guarded", "other"]),
])
def test_schemas_derived_reads_and_examples(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == "ok", result.error_message
        assert result.value == expected


def test_schema_collects_leaf_errors_in_field_order():
    with ScriptRunner() as runner:
        result = runner.handle_script("""
            Address: schema #{zip: `int`}
            Profile: schema #{name: `string`, address: Address, age: `int`}
            do [validate #{name: 7, address: #{zip: 'wrong'}} Profile]
        """)
        assert result.status == "ok", result.error_message
        error = result.value["error"]
        assert error["code"] == PathLiteral(SlipPath(["invalid"]))
        names = [item["field"] for item in error["data"]]
        assert names == ["name", "zip", "age"]
        assert "expected type" in error["data"][0]["error"]
        assert error["data"][2]["error"] == "field is required"


def test_example_failures_and_test_all_summaries():
    with ScriptRunner() as runner:
        result = runner.handle_script("""
            module: scope #{}
            run-with [
                f: fn {x} [x + 1] |example {x: 1 -> 2} |example {x: 1 -> 3}
                g: fn {x} [x] |example {x: 1 -> 1}
            ] module
            do [test-all module]
        """)
        assert result.status == "ok", result.error_message
        summary = result.value["error"]["data"]
        assert summary["with-examples"] == 2
        assert summary["passed"] == summary["failed"] == 1
        assert summary["details"][0]["name"] == "f"
        failed = runner.handle_script("test module.f")
        assert failed.status == "err"
        assert failed.error["data"] == [
            {"index": 1, "expected": 3, "actual": 2},
        ]


def test_ref_does_not_perform_io_until_read(tmp_path):
    path = tmp_path / "data.slip"
    with ScriptRunner() as runner:
        defined = runner.handle_script(f"r: ref `file://{path}`; 7")
        assert defined.status == "ok", defined.error_message
        path.write_text("40 + 2")
        read = runner.handle_script("#[is-code r, run r]")
        assert read.status == "ok" and read.value == [True, 42]
