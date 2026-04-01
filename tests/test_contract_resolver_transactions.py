import pytest
from slip import ScriptRunner


async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)


def assert_ok(res, expected=None):
    assert res.status == "ok", res.error_message
    if expected is not None:
        assert res.value == expected


@pytest.mark.asyncio
async def test_resolver_constructor_sets_meta_resolver_flag():
    src = """
    Combat: resolver #{}
    Combat.meta.resolver
    """
    res = await run_slip(src)
    assert_ok(res, True)


@pytest.mark.asyncio
async def test_type_of_resolver_scope_is_resolver():
    src = """
    Combat: resolver #{}
    type-of Combat
    """
    res = await run_slip(src)
    assert_ok(res, "`resolver`")


@pytest.mark.asyncio
async def test_write_rooted_at_this_requires_resolver_transaction():
    src = """
    this.hp["p1"]: 10
    """
    res = await run_slip(src)
    assert res.status == "err"
    assert "Committed writes require a resolver transaction" in (res.error_message or "")


@pytest.mark.asyncio
async def test_write_rooted_at_this_succeeds_inside_resolver_transaction():
    # NOTE: dict literals use ':' between key/value (as in docs).
    #
    # NOTE: This call style is supported but non-idiomatic SLIP:
    #   Combat |Combat.apply-damage ...
    # Preferred style is a free function that dispatches on Combat:
    #   Combat |apply-damage ...
    src = """
    Combat: resolver #{
        hp: #{ p1: 120 }
    }

    Combat.apply-damage: fn {this: Combat, target-id, amount} [
        next: this.hp[target-id] - amount
        this.hp[target-id]: next
        response ok next
    ]

    -- non-idiomatic (property access), but supported
    Combat |Combat.apply-damage "p1" 10
    """
    res = await run_slip(src)
    assert_ok(res, {"status": "ok", "value": 110})


@pytest.mark.asyncio
async def test_write_rooted_at_this_fails_if_this_receiver_is_not_a_resolver():
    # NOTE: dict literals use ':' between key/value (as in docs).
    #
    # NOTE: This is also non-idiomatic (method-style). Preferred is:
    #   Combat |apply-damage ...
    #
    # With the current contract, `this:` functions always require an explicit receiver.
    src = """
    Combat: scope #{
        hp: #{ p1: 120 }
    }

    Combat.apply-damage: fn {this: Combat, target-id, amount} [
        next: this.hp[target-id] - amount
        this.hp[target-id]: next
        response ok next
    ]

    Combat |Combat.apply-damage "p1" 10
    """
    res = await run_slip(src)
    assert res.status == "err"
    assert (
        "reserved for resolver transactions" in (res.error_message or "")
        or "missing receiver argument for `this:` transaction" in (res.error_message or "")
        or "No matching method" in (res.error_message or "")
    )


@pytest.mark.asyncio
async def test_write_with_identity_boundary_is_rejected_even_in_transaction():
    # NOTE: dict literals use ':' between key/value (as in docs).
    src = """
    Combat: resolver #{
        hp: #{ p1: 120 }
    }

    bad: fn {this: Combat} [
        this::hp["p1"]: 0
        response ok none
    ]

    Combat |bad
    """
    res = await run_slip(src)
    assert res.status == "err"
    assert "Cannot write across an identity boundary" in (res.error_message or "")
