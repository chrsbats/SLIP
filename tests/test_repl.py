import asyncio
import importlib.util
import sys
from pathlib import Path
import uuid
import pytest

def _load_repl_module():
    """Dynamically load the top-level slip.py (REPL) as a module with a unique name."""
    repl_path = Path(__file__).resolve().parents[1] / "slip.py"
    mod_name = f"slip_repl_for_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(mod_name, str(repl_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod

@pytest.mark.asyncio
async def test_repl_exit_immediately(monkeypatch, capsys):
    repl = _load_repl_module()

    async def fake_ainput(prompt: str) -> str:
        return "exit"
    monkeypatch.setattr(repl, "ainput", fake_ainput)

    await repl.main()
    out = capsys.readouterr().out
    assert "SLIP REPL v0.1" in out
    assert "Type 'exit' or press Ctrl+D to quit." in out

@pytest.mark.asyncio
async def test_repl_prints_side_effects_and_values(monkeypatch, capsys):
    repl = _load_repl_module()
    lines = iter([
        'emit "stdout" "hello from slip"',
        "1 + 2",
        "exit",
    ])

    async def fake_ainput(prompt: str) -> str:
        return next(lines)
    monkeypatch.setattr(repl, "ainput", fake_ainput)

    await repl.main()
    out, err = capsys.readouterr()
    # Header
    assert "SLIP REPL v0.1" in out
    # Side effect printed to stdout
    assert "hello from slip" in out
    # Expression result printed
    assert "\n3\n" in out or out.rstrip().endswith("3")
    # No error for this run
    assert "TypeError" not in err

@pytest.mark.asyncio
async def test_repl_errors_print_to_stderr(monkeypatch, capsys):
    repl = _load_repl_module()
    lines = iter([
        'add 1 "a"',  # will cause a TypeError in add
        "exit",
    ])

    async def fake_ainput(prompt: str) -> str:
        return next(lines)
    monkeypatch.setattr(repl, "ainput", fake_ainput)

    await repl.main()
    out, err = capsys.readouterr()
    # Header still printed
    assert "SLIP REPL v0.1" in out
    # Error message should be nicely formatted to stderr
    assert "TypeError: invalid-args" in err

@pytest.mark.asyncio
async def test_repl_eof_quits(monkeypatch, capsys):
    repl = _load_repl_module()

    async def fake_ainput(prompt: str) -> str:
        raise EOFError
    monkeypatch.setattr(repl, "ainput", fake_ainput)

    await repl.main()
    out = capsys.readouterr().out
    assert "SLIP REPL v0.1" in out
    assert "Exiting." in out
