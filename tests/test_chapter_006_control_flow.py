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
async def test_if_then_else_and_when():
    src = """
        x: 5
        a: if [x > 0] ["pos"] ["neg"]
        b: when [x > 10] ["big"]
        #[ a, b ]
    """
    res = await run_slip(src)
    assert_ok(res, ["pos", None])


@pytest.mark.asyncio
async def test_logical_short_circuit_and_or():
    src = """
        r1: false and (1 / 0)  -- must not evaluate RHS; no error
        r2: true or (1 / 0)    -- must not evaluate RHS; no error
        #[ r1, r2 ]
    """
    res = await run_slip(src)
    assert_ok(res, [False, True])


@pytest.mark.asyncio
async def test_while_returns_last_value():
    src = """
        i: 0
        last: while [i < 3] [
            i: i + 1
            i
        ]
        #[ i, last ]
    """
    res = await run_slip(src)
    assert_ok(res, [3, 3])


@pytest.mark.asyncio
async def test_foreach_over_list_mapping_and_scope():
    src = """
        -- list
        lst: #[1, 2, 3]
        sum1: 0
        foreach {x} lst [
            sum1: sum1 + x
        ]

        -- dict
        d: #{ a: 1, b: 2 }
        keys: #[]
        vals: #[]
        foreach {k, v} d [
            keys: add keys #[k]
            vals: add vals #[v]
        ]

        -- scope
        sc: scope #{ x: 10, y: 20 }
        skeys: #[]
        svals: #[]
        foreach {k, v} sc [
            skeys: add skeys #[k]
            svals: add svals #[v]
        ]

        #[ sum1, (sort keys), (sort vals), (sort skeys), (sort svals) ]
    """
    res = await run_slip(src)
    assert_ok(res, [6, ["a", "b"], [1, 2], ["x", "y"], [10, 20]])


@pytest.mark.asyncio
async def test_cond_selects_branch_and_none():
    src = """
        x: 5
        a: cond #[
            #[ [x < 5], "lt" ],
            #[ [x > 5], "gt" ],
            #[ [true], "eq" ]
        ]
        b: cond #[
            #[ [false], "never" ]
        ]
        #[ a, b ]
    """
    res = await run_slip(src)
    assert_ok(res, ["eq", None])


@pytest.mark.asyncio
async def test_for_counts_up_and_down_and_binds_var():
    src = """
        xs: #[]
        for {i} 1 4 [
            xs: add xs #[i]
        ]
        ys: #[]
        for {j} 3 0 [
            ys: add ys #[j]
        ]
        #[ xs, ys, i, j ]
    """
    res = await run_slip(src)
    assert_ok(res, [[1, 2, 3], [3, 2, 1], 3, 1])
