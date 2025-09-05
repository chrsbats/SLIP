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
async def test_operator_alias_cycle_errors_nicely():
    # Make the operator name resolve to itself to trigger cycle detection in _resolve_operator_to_func_path
    src = """
    op: `op`
    1 op 2
    """
    res = await run_slip(src)
    assert_error(res, "cycle detected")


@pytest.mark.asyncio
async def test_division_operator_normalization_from_root_token():
    # Ensure '/' parsed as Root is normalized to the division operator and evaluates correctly
    res = await run_slip("10 / 2")
    assert_ok(res, 5)


@pytest.mark.asyncio
async def test_del_path_meta_prune_false_preserves_parent_scope():
    # Default pruning is on; explicitly disable via #(prune: false) to keep empty parent scopes
    src = """
    s: scope #{}
    s.a: scope #{}
    s.a.b: 1
    ~s.a.b#(prune: false)
    has-a: (has-key? s 'a')
    has-a
    """
    res = await run_slip(src)
    # Parent key 'a' should still exist (now empty), so has-a is True
    assert_ok(res, True)


@pytest.mark.asyncio
async def test_unary_piped_operator_missing_rhs_invokes_function_and_errors():
    # Unary pipe should attempt a single-arg call; add requires 2 args -> invalid-args in (add)
    res = await run_slip("5 |add")
    assert_error(res, "TypeError: invalid-args in (add)")


@pytest.mark.asyncio
async def test_http_get_with_trailing_segments_is_rejected_client_side():
    # Trailing segments after an http URL should error before any network call
    src = """
    probe: do [ http://example.com/data.name ]
    eq probe.outcome.status err
    """
    res = await run_slip(src)
    assert_ok(res, True)


@pytest.mark.asyncio
async def test_file_get_with_trailing_segments_is_rejected_client_side():
    # Bracketed trailing segments after a file:// URL should error without touching filesystem
    src = """
    probe: do [ file://./[0] ]
    eq probe.outcome.status err
    """
    res = await run_slip(src)
    assert_ok(res, True)
