from pathlib import Path

import pytest

import slip
from slip import ScriptRunner
from slip.grammar import GRAMMAR_PATH
from slip.slip_datatypes import GetPath, IString, Name
from slip.slip_interpreter import Evaluator
from slip.slip_runtime import StdLib


def test_runtime_resources_are_available():
    assert Path(slip.__file__).with_name("root.slip").is_file()
    for name in ("slip_grammar.yaml", "slip_path.yaml", "slip_sig.yaml"):
        assert GRAMMAR_PATH.with_name(name).is_file()


@pytest.mark.asyncio
async def test_runner_loads_root_and_subgrammars():
    runner = ScriptRunner()
    result = await runner.handle_script(
        "add-one: fn {n: `int`} [n + 1]\n"
        "data: #{values: #[40, 41]}\n"
        "add-one data.values[1]"
    )
    assert result.status == "ok", result.error_message
    assert result.value == 42


@pytest.mark.asyncio
async def test_bare_evaluator_loads_root_and_interpolation(monkeypatch):
    monkeypatch.setattr(Evaluator, "_core_parser", None)
    monkeypatch.setattr(Evaluator, "_core_ast_cache", None)
    monkeypatch.setattr(Evaluator, "_core_parse_error", None)
    evaluator = Evaluator()
    evaluator.stdlib = StdLib(evaluator)
    scope = evaluator.core_scope

    result = await evaluator.eval([40, GetPath([Name("+")]), 2], scope)
    assert result == 42
    assert scope.meta["_root_loaded"] is True

    # Interpolation also constructs its parser independently of core loading.
    monkeypatch.setattr(Evaluator, "_core_parser", None)
    result = await evaluator.eval(IString("answer {{40 + 2}}"), scope)
    assert result == "answer 42"


@pytest.mark.asyncio
async def test_public_import_uses_persistent_code_cache(tmp_path, monkeypatch):
    from slip import slip_file

    monkeypatch.setenv("SLIP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(slip_file, "_pipeline_fingerprint", None)
    monkeypatch.setattr(slip_file, "_compiled_slip_cache", {})
    module = tmp_path / "commands.slip"
    module.write_text("answer: fn {n: `int`} [n + 1] |public\n")
    locator = f"file://{module.as_posix()}"

    for attempt in range(2):
        before = slip_file.cache_stats()
        commands = await ScriptRunner().import_public_module(locator)
        result = await commands.run_json_command(
            {"function": "answer", "arguments": {"n": 41}}
        )
        assert result.status == "ok", result.error_message
        assert result.value == 42
        after = slip_file.cache_stats()
        if attempt == 0:
            assert after["writes"] == before["writes"] + 1
        else:
            assert after["persistent_hits"] == before["persistent_hits"] + 1
        slip_file._compiled_slip_cache.clear()
