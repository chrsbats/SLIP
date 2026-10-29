import sys
from importlib.resources import files

from slip import ScriptRunner
from slip.grammar import GRAMMAR_PATH
from slip.slip_core import Code, Scope
from slip.slip_syntax import parse


def test_runtime_resources_are_available():
    assert files('slip').joinpath('root.slip').is_file()
    for name in ('slip_grammar.yaml', 'slip_path.yaml', 'slip_sig.yaml'):
        assert GRAMMAR_PATH.with_name(name).is_file()


def test_runner_loads_root_and_subgrammars():
    with ScriptRunner() as runner:
        result = runner.handle_script(
            'add-one: fn {n: `int`} [n + 1]\n'
            'data: #{values: #[40, 41]}\n'
            'add-one data.values[1]'
        )
        assert result.status == 'ok', result.error_message
        assert result.value == 42


def test_public_package_has_one_runtime_identity_and_parses_interpolation():
    from slip.slip_embedding import ScriptRunner as NativeRunner

    assert ScriptRunner is NativeRunner
    assert ScriptRunner.__module__ == 'slip.slip_embedding'
    assert type(parse('42')) is Code
    with ScriptRunner() as runner:
        assert isinstance(runner.root_scope, Scope)
        result = runner.handle_script('"answer {{40 + 2}}"')
        assert result.status == 'ok', result.error_message
        assert result.value == 'answer 42'
    assert 'slip.slip_runtime' not in sys.modules
    assert 'slip.slip_interpreter' not in sys.modules
    assert 'slip_core' not in sys.modules


def test_public_import_uses_persistent_code_cache(tmp_path, monkeypatch):
    from slip import slip_cache, slip_syntax

    monkeypatch.setenv('SLIP_CACHE_DIR', str(tmp_path / 'cache'))
    module = tmp_path / 'commands.slip'
    module.write_text('answer: fn {n: `int`} [n + 1] |public\n')
    locator = 'file://' + str(module)
    with ScriptRunner() as first:
        commands = first.import_public_module(locator)
        result = commands.run_json_command(
            {'function': 'answer', 'arguments': {'n': 41}},
        )
        assert result.status == 'ok', result.error_message
        assert result.value == 42
    assert len(list((tmp_path / 'cache').rglob('*.pickle'))) == 1
    slip_cache.compiled.cache_clear()
    with ScriptRunner() as second:
        def forbidden(source):
            raise AssertionError('persistent module source was parsed again')

        monkeypatch.setattr(slip_syntax, 'parse', forbidden)
        commands = second.import_public_module(locator)
        result = commands.run_json_command(
            {'function': 'answer', 'arguments': {'n': 41}},
        )
        assert result.status == 'ok', result.error_message
        assert result.value == 42
