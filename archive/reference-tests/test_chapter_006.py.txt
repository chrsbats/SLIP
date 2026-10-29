import pytest

from slip import ScriptRunner


async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)


def assert_ok(res, expected=None):
    assert res.status == 'ok', res.error_message
    if expected is not None:
        assert res.value == expected


def assert_error(res, contains: str | None = None):
    assert res.status == 'err', f"expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or ""), f"error did not contain {contains!r}: {res.error_message!r}"


@pytest.mark.asyncio
async def test_arity_gating_typed_then_variadic_and_untyped_fallback():
    """
    New contract:
    - Too many args is an error unless a variadic (rest...) method matches.
    - Methods with a Sig are considered first; untyped methods are fallback-only.
    - Last-defined wins among matching methods (no ambiguity errors).
    """
    src = """
        add: fn {a: `int`, b: `int`} [ "exact" ]
        add: fn {a: `int`, b: `int`, rest...} [ "variadic" ]
        add: fn {a, b, rest...} [ "untyped-variadic" ]  -- fallback-only (no Sig)

        r1: add 1 2
        r2: add 1 2 3
        #[ r1, r2 ]
        """
    res = await run_slip(src)
    assert_ok(res, ["exact", "variadic"])

    # Type mismatch against the only Sig method => no match (untyped fallback is arity-mismatched here)
    src2 = """
        add: fn {a: `int`, b: `int`} [ "exact" ]
        add 'a' 2
        """
    res2 = await run_slip(src2)
    assert_error(res2, "No matching method")


@pytest.mark.asyncio
async def test_untyped_methods_last_defined_wins_no_ambiguity():
    src = """
        foo: fn [] [ 1 ]
        foo: fn [] [ 2 ]
        foo
        """
    res = await run_slip(src)
    assert_ok(res, 2)


@pytest.mark.asyncio
async def test_typed_dispatch_prefers_more_specific_over_parent():
    """
    Contract: for typed methods that both match via the prototype chain,
    the most specific (closest) match wins (Player beats Being for a Player).
    """
    src = """
        Being: scope #{}
        Character: scope #{} |inherit Being
        Player: scope #{} |inherit Character

        interact: fn {x: Player} [ "player" ]
        interact: fn {x: Being} [ "being" ]  -- less specific

        p: create Player
        interact p
        """
    res = await run_slip(src)
    assert_ok(res, "player")


@pytest.mark.asyncio
async def test_guards_filter_candidates_last_defined_wins():
    src = """
        choose: fn {x: `int`} [ "plain" ]
        choose: fn {x: `int`} [ "guarded-1" ] |where [x > 0]
        choose: fn {x: `int`} [ "guarded-2" ] |where [x > 0]
        #[ choose 5, choose -1 ]
        """
    res = await run_slip(src)
    assert_ok(res, ["guarded-2", "plain"])


@pytest.mark.asyncio
async def test_typed_beats_untyped_fallback():
    """
    New contract: untyped methods are fallback-only, even if they are last-defined.
    """
    src = """
        A: scope #{}

        f: fn {x: A} [ "typed" ]
        f: fn {x} [ "fallback" ]  -- last-defined but must not steal typed calls

        a: create A
        #[ f a, f 123 ]
        """
    res = await run_slip(src)
    assert_ok(res, ["typed", "fallback"])


@pytest.mark.asyncio
async def test_union_and_conjunction_not_supported_for_dispatch_typing_now():
    """
    The simplified dispatch contract does not use union/conjunction *scoring*.
    Conjunctions are still valid type constraints and must match.
    """
    src = """
        Character: scope #{}
        Player: scope #{} |inherit Character
        Buff: scope #{}
        OnFire: scope #{} |inherit Buff

        hit: fn {p: (Player and OnFire)} [ "onfire" ]

        p: create Player
        hit p
        """
    res = await run_slip(src)
    assert_error(res, "No matching method")


@pytest.mark.asyncio
async def test_union_sig_alias_is_supported_for_dispatch_typing():
    """
    Union typing is supported as a type constraint (no scoring beyond match/non-match).
    """
    src = """
        Character: scope #{}
        Player: scope #{} |inherit Character
        Monster: scope #{} |inherit Character

        treat: fn {x: {Player or Monster}} [ "entity" ]
        p: create Player
        treat p
        """
    res = await run_slip(src)
    assert_ok(res, "entity")


@pytest.mark.asyncio
async def test_variadic_accepts_unlimited_args():
    src = """
        f: fn {fmt: `string`, rest...} [ fmt ]
        f 's' 10 20 30
        """
    res = await run_slip(src)
    assert_ok(res, "s")


@pytest.mark.asyncio
async def test_too_many_args_non_variadic_is_error():
    src = """
        f: fn {x: `int`} [ x ]
        f 1 2
        """
    res = await run_slip(src)
    assert_error(res, "No matching method")
