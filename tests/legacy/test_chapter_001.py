"""Synchronous behavioral port of tests/test_chapter_001.py."""

from slip import ScriptRunner


def run_slip(src):
    with ScriptRunner() as runner:
        return runner.handle_script(src)


def assert_ok(res, expected):
    assert res.status == 'ok', res.error_message
    assert res.value == expected


def test_script_returns_last_expression_value():
    assert_ok(run_slip("1\n2\n3"), 3)


def test_prefix_call_and_infix_call_equivalence():
    assert_ok(run_slip("add 10 5"), 15)
    assert_ok(run_slip("10 + 5"), 15)


def test_left_to_right_and_parentheses_control_order():
    assert_ok(run_slip("result: 10 + 5 * 2; result"), 30)
    assert_ok(run_slip("result: 10 + (5 * 2); result"), 20)


def test_group_evaluates_nested_expression_and_returns_value():
    assert_ok(run_slip("x: (add 2 3); x"), 5)


def test_group_with_multiple_expressions_returns_last_value():
    assert_ok(run_slip("x: (a: 1; a + 2); x"), 3)


def test_semicolon_separators_between_expressions():
    assert_ok(run_slip("a: 1; b: 2\nb"), 2)


def test_code_block_is_unevaluated_until_run():
    assert_ok(run_slip("x: 1; block: [x: 2]; x"), 1)
    assert_ok(run_slip("x: 1; block: [x: 2]; run block; x"), 1)


def test_code_block_type_is_code():
    assert_ok(run_slip("block: [1]; eq (type-of block) `code`"), True)


def test_list_and_dict_literals_construct_values():
    assert_ok(run_slip("xs: #[1, 2, 3]; xs"), [1, 2, 3])
    assert_ok(run_slip("d: #{a: 1, b: 2}; d.a + d.b"), 3)


def test_explicit_pipe_operator_triggers_implicit_pipe_call():
    assert_ok(run_slip("10 |add 5"), 15)


def test_del_path_cannot_participate_in_larger_expression():
    result = run_slip("a: 1; ~a + 1")
    assert result.status == 'err'
    assert "del-path cannot be part of a larger expression" in (
        result.error_message or ""
    )


def test_piped_path_cannot_be_first_term_of_expression():
    assert run_slip("|add 1 2").status == 'err'


def test_set_path_cannot_appear_mid_expression():
    assert run_slip("10 + a: 20").status == 'err'


def test_operator_alias_assignment_is_not_update():
    assert_ok(run_slip("plus-op: |add; 10 plus-op 5"), 15)
