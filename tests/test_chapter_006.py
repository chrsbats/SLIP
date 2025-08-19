import pytest

from slip import ScriptRunner


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
async def test_if_then_else_truthy_and_falsey():
    src = """
    #[
      (if [true]  [ 1 ] [ 2 ]),
      (if [false] [ 1 ] [ 2 ])
    ]
    """
    res = await run_slip(src)
    assert_ok(res, [1, 2])


@pytest.mark.asyncio
async def test_when_runs_then_or_returns_none():
    src = """
    #[
      (when [true]  [ 123 ]),
      (when [false] [ 456 ])
    ]
    """
    res = await run_slip(src)
    assert_ok(res, [123, None])


@pytest.mark.asyncio
async def test_while_loop_returns_last_value_and_none_if_never_runs():
    src = """
    i: 0
    a: while [i < 3] [
      i: i + 1
      i                -- body value each iteration; last should be 3
    ]
    j: 0
    b: while [j < 0] [
      j: j + 1
    ]
    #[ a, b ]
    """
    res = await run_slip(src)
    assert_ok(res, [3, None])


@pytest.mark.asyncio
async def test_foreach_over_list_and_dict_accumulates():
    src = """
    xs: #[1, 2, 3]
    total: 0
    foreach x xs [
      total: total + x
    ]

    scores: #{
      kael: 100,
      jaina: 150
    }
    sum-scores: 0
    foreach s scores [
      sum-scores: sum-scores + s
    ]

    #[ total, sum-scores ]
    """
    res = await run_slip(src)
    assert_ok(res, [6, 250])


@pytest.mark.asyncio
async def test_loop_with_return_exits_early():
    src = """
    i: 0
    loop [
      i: i + 1
      if [i >= 3] [
        return i
      ] []
    ]
    """
    res = await run_slip(src)
    assert_ok(res, 3)


@pytest.mark.asyncio
async def test_cond_multi_branch_selects_first_match():
    src = """
    x: 5
    cond #[
      #[ [x < 5],    "less"    ],
      #[ [x > 5],    "greater" ],
      #[ [true],     "equal"   ]
    ]
    """
    res = await run_slip(src)
    assert_ok(res, "equal")


@pytest.mark.asyncio
async def test_logical_and_or_short_circuiting():
    src = """
    counter: 0
    bump: fn {} [ counter: counter + 1 ]

    r1: logical-and false (bump)  -- right should not evaluate
    r2: logical-or  true (bump)   -- right should not evaluate
    r3: logical-and true (bump)   -- right should evaluate once

    #[ r1, r2, r3, counter ]
    """
    res = await run_slip(src)
    assert_ok(res, [False, True, 1, 1])
