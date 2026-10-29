import sys

from slip import ScriptRunner, cli


def test_repl_exit_immediately(monkeypatch, capsys):
    runner = ScriptRunner()
    monkeypatch.setattr(cli, 'ScriptRunner', lambda: runner)
    monkeypatch.setattr('builtins.input', lambda prompt: 'exit')
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert 'SLIP REPL' in out
    assert "Type 'exit' or press Ctrl+D to quit." in out
    assert runner.closed and not runner.resources.worker.thread.is_alive()


def test_repl_prints_side_effects_and_values(monkeypatch, capsys):
    lines = iter(['emit "stdout" "hello from slip"', 'x: 1', 'x + 2', 'exit'])
    monkeypatch.setattr('builtins.input', lambda prompt: next(lines))
    assert cli.main([]) == 0
    out, err = capsys.readouterr()
    assert 'SLIP REPL' in out and 'hello from slip' in out
    assert '\n3\n' in out
    assert err == ''


def test_repl_errors_print_to_stderr_once_and_allow_next_input(
    monkeypatch, capsys,
):
    lines = iter(['add 1 "a"', '1 + 2', 'exit'])
    monkeypatch.setattr('builtins.input', lambda prompt: next(lines))
    assert cli.main([]) == 0
    out, err = capsys.readouterr()
    assert 'SLIP REPL' in out and '\n3\n' in out
    assert err.count('TypeError:') == 1
    assert 'SLIP stacktrace:' in err


def test_repl_eof_quits_and_closes_owned_resources(monkeypatch, capsys):
    def end(prompt):
        raise EOFError

    runner = ScriptRunner()
    monkeypatch.setattr(cli, 'ScriptRunner', lambda: runner)
    monkeypatch.setattr('builtins.input', end)
    assert cli.main([]) == 0
    assert 'Exiting.' in capsys.readouterr().out
    assert runner.closed and runner.resources.http_client.is_closed


def test_repl_interrupt_closes_owned_resources(monkeypatch, capsys):
    def interrupt(prompt):
        raise KeyboardInterrupt

    runner = ScriptRunner()
    monkeypatch.setattr(cli, 'ScriptRunner', lambda: runner)
    monkeypatch.setattr('builtins.input', interrupt)
    assert cli.main([]) == 130
    assert 'Exiting.' in capsys.readouterr().out
    assert runner.closed and not runner.resources.worker.thread.is_alive()


def test_script_file_uses_its_directory_and_reports_stderr(tmp_path, capsys):
    (tmp_path / 'data.json').write_text('{"answer": 42}')
    path = tmp_path / 'script.slip'
    path.write_text("stderr 'note'; data: file://data.json; data.answer")
    assert cli.main([str(path)]) == 0
    out, err = capsys.readouterr()
    assert out == '42\n' and err == 'note\n'
    assert 'slip.slip_runtime' not in sys.modules


def test_script_error_retains_file_location_and_prior_effects(
    tmp_path, capsys,
):
    path = tmp_path / 'broken.slip'
    path.write_text("print 'before'; stderr 'note'; 1 / 0")
    assert cli.main([str(path)]) == 1
    out, err = capsys.readouterr()
    assert out == 'before\n'
    assert err.startswith('note\n')
    assert err.count('ZeroDivisionError:') == 1
    assert str(path) in err and '^' in err


def test_missing_script_does_not_construct_a_runner(
    tmp_path, monkeypatch, capsys,
):
    def forbidden():
        raise AssertionError('a missing file created owned resources')

    monkeypatch.setattr(cli, 'ScriptRunner', forbidden)
    assert cli.main([str(tmp_path / 'missing.slip')]) == 1
    out, err = capsys.readouterr()
    assert out == '' and 'missing.slip' in err


def test_function_results_are_displayed_without_calling(tmp_path, capsys):
    path = tmp_path / 'function.slip'
    path.write_text('make: fn {} [fn {} [7]]; (make)')
    assert cli.main([str(path)]) == 0
    out, err = capsys.readouterr()
    assert out == '<function>\n' and err == ''
