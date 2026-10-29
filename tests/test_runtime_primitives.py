from slip import ScriptRunner
from slip.slip_core import Path, PathLiteral


def test_if_with_code_variables_and_missing_else(runner):
    result = runner.handle_script("""
        then-block: ['t']
        else-block: ['e']
        if [false] then-block else-block
    """)
    assert result.status == 'ok', result.error_message
    assert result.value == 'e'
    result = runner.handle_script('if [false] [1]')
    assert result.status == 'ok', result.error_message
    assert result.value is None


def test_foreach_over_mapping_keys_and_items(runner):
    result = runner.handle_script("""
        d: #{a: 1, b: 2}
        out: #[]
        foreach {k} d [out: add out #[k]]
        sort out
    """)
    assert result.status == 'ok', result.error_message
    assert result.value == ['a', 'b']
    result = runner.handle_script("""
        d: #{a: 1, b: 2}
        sum: 0
        foreach {k, v} d [if [eq k 'a'] [sum: v] [none]]
        sum
    """)
    assert result.status == 'ok', result.error_message
    assert result.value == 1


def test_small_math_family_is_available(runner):
    result = runner.handle_script("""
        #[floor 1.7, ceil 1.2, trunc -1.7, round 1.6,
          round 1.234 2, sqrt 9, abs -4]
    """)
    assert result.status == 'ok', result.error_message
    assert result.value == [1, 2, -1, 2, 1.23, 3.0, 4]


def test_runner_local_randomness_is_repeatable_and_isolated(runner):
    source = 'seed-random 42; #[random, random, random-int 1 6]'
    with ScriptRunner() as second:
        one = runner.handle_script(source)
        two = second.handle_script(source)
        replay = runner.handle_script(source)
        for result in (one, two, replay):
            assert result.status == 'ok', result.error_message
        assert one.value == two.value == replay.value
        runner.handle_script('random')
        following = second.handle_script('random')
        replay = runner.handle_script(
            'seed-random 42; #[random, random, random-int 1 6, random]',
        )
        assert following.status == replay.status == 'ok'
        assert following.value == replay.value[-1]


def test_random_ranges_and_seed_return_value(runner):
    result = runner.handle_script("""
        seeded: seed-random 7
        values: #[random-int 1 1, random-int -2 2, random]
        #[seeded, values]
    """)
    assert result.status == 'ok', result.error_message
    assert result.value[0] is None
    assert result.value[1][0] == 1
    assert -2 <= result.value[1][1] <= 2
    assert 0 <= result.value[1][2] < 1


def test_imported_module_shares_runner_random_stream(tmp_path, runner):
    (tmp_path / 'random-value.slip').write_text('value: random')
    runner.source_dir = str(tmp_path)
    imported = runner.handle_script("""
        seed-random 91
        module: import `file://random-value.slip`
        #[module.value, random]
    """)
    direct = runner.handle_script('seed-random 91; #[random, random]')
    assert imported.status == 'ok', imported.error_message
    assert direct.status == 'ok', direct.error_message
    assert imported.value == direct.value


def test_return_multiple_values_explains_parentheses(runner):
    result = runner.handle_script('f: fn {} [return 1 = 1]; f')
    assert result.status == 'err'
    assert 'return takes at most one value' in result.error_message
    assert 'wrap complex return expressions in parentheses' \
        in result.error_message


def test_get_body_returns_code_for_typed_method(runner):
    result = runner.handle_script("""
        add: fn {a: int, b: int} [a + b]
        body: get-body add {a: int, b: int}
        is-code body
    """)
    assert result.status == 'ok', result.error_message
    assert result.value is True


def test_test_and_test_all_helpers(runner):
    result = runner.handle_script("""
        good: fn {a, b} [a + b] |example {a: 2, b: 3 -> 5}
        bad: fn {x} [x + 1] |example {x: 2 -> 4}
        passed: test good
        failed: do [test bad]
        #[passed, failed.status, failed.error.code]
    """)
    assert result.status == 'ok', result.error_message
    assert result.value == [1, PathLiteral(Path(['err'])),
                            PathLiteral(Path(['test-failed']))]
    result = runner.handle_script("""
        out: do [test-all]
        (out.error.data.passed >= 1) and (
            out.error.data.passed + out.error.data.failed >= 1
        )
    """)
    assert result.status == 'ok', result.error_message
    assert result.value is True


def test_run_with_accepts_grouped_current_scope(runner):
    result = runner.handle_script('run-with [a: 123] (current-scope); a')
    assert result.status == 'ok', result.error_message
    assert result.value == 123


def test_get_body_missing_sig_errors_cleanly(runner):
    result = runner.handle_script("""
        add: fn {a: int, b: int} [a + b]
        probe: do [get-body add {a: string, b: string}]
        probe.status
    """)
    assert result.status == 'ok', result.error_message
    assert result.value == PathLiteral(Path(['err']))


def test_friendly_callable_name_prints_kebab_for_stdlib_method(runner):
    result = runner.handle_script('add 1 str-join')
    assert result.status == 'err'
    assert 'SLIP stacktrace:' in result.error_message
    assert 'str-join' in result.error_message
