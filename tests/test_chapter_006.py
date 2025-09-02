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
async def test_arity_gating_exact_then_variadic_and_no_match():
    src = """
        add: fn {a: `int`, b: `int`} [ "exact" ]
        add: fn {a, b, rest...} [ "variadic" ]
        add: fn [] [ "untyped" ]  -- will never be considered if exact/variadic tiers have candidates

        r1: add 1 2
        r2: add 1 2 3
        #[ r1, r2 ]
        """
    res = await run_slip(src)
    assert_ok(res, ["exact", "variadic"])

    # No matching method (exact tier chosen; typed fails)
    src2 = """
        add: fn {a: `int`, b: `int`} [ "exact" ]
        add 'a' 2
        """
    res2 = await run_slip(src2)
    assert_error(res2, "No matching method")


@pytest.mark.asyncio
async def test_untyped_tier_ambiguity_raises():
    src = """
        foo: fn [] [ 1 ]   -- untyped (args is a Code literal)
        foo: fn [] [ 2 ]   -- untyped
        foo
        """
    res = await run_slip(src)
    assert_error(res, "Ambiguous method call")


@pytest.mark.asyncio
async def test_lexicographic_tie_break_on_second_argument():
    src = """
        Being: scope #{}
        Character: scope #{} |inherit Being
        Player: scope #{} |inherit Character
        Item: scope #{}
        Weapon: scope #{} |inherit Item

        -- First arg tie-break: Player vs Being
        interact: fn {p: Player, i: Item} [ "A" ]
        interact: fn {b: Being, w: Weapon} [ "B" ]

        p: create Player
        w: create Weapon
        interact p w
        """
    res = await run_slip(src)
    assert_ok(res, "A")


@pytest.mark.asyncio
async def test_guards_filter_and_tie_break_guarded_over_plain():
    src = """
        choose: fn {x: `int`} [ "plain" ]
        choose: fn {x: `int`} [ "guarded" ] |guard [x > 0]
        #[ choose 5, choose -1 ]
        """
    res = await run_slip(src)
    assert_ok(res, ["guarded", "plain"])


@pytest.mark.asyncio
async def test_specificity_scoring_conjunction_and_families():
    src = """
        Character: scope #{}
        Player: scope #{} |inherit Character
        Item: scope #{}
        Weapon: scope #{} |inherit Item
        Buff: scope #{}
        OnFire: scope #{} |inherit Buff
        Poisoned: scope #{} |inherit Buff
        Frozen: scope #{} |inherit Buff

        apply-effect: fn {p: (Player and OnFire and Poisoned), w: (Weapon and Frozen)} [ "A" ]
        apply-effect: fn {p: (Character and OnFire), w: (Weapon and Frozen)} [ "B" ]
        apply-effect: fn {p: (Player and OnFire and Poisoned), i: Item} [ "C" ]

        p: create Player |with [
          mixin OnFire
          mixin Poisoned
        ]
        w: create Weapon

        -- Initially weapon has no Frozen -> only C applies
        r1: apply-effect p w

        -- Add Frozen later (family cache must reflect new mixin)
        mixin w Frozen
        r2: apply-effect p w

        #[ r1, r2 ]
        """
    res = await run_slip(src)
    assert_ok(res, ["C", "A"])


@pytest.mark.asyncio
async def test_union_with_scopes_picks_best_branch():
    src = """
        Character: scope #{}
        Player: scope #{} |inherit Character
        Monster: scope #{} |inherit Character

        treat: fn {x: {Player or Monster}} [ "entity" ]
        treat: fn {x: Character} [ "generic" ]

        p: create Player
        m: create Monster
        c: create Character
        #[ treat p, treat m, treat c ]
        """
    res = await run_slip(src)
    assert_ok(res, ["entity", "entity", "generic"])


@pytest.mark.asyncio
async def test_variadic_scoring_ignores_rest_and_prefers_typed_base():
    src = """
        f: fn {fmt: `string`, parts...} [ "fmt-only" ]
        f: fn {fmt: `string`, x: `int`, rest...} [ "fmt-int" ]
        #[ f 's' 10, f 's' 'x' ]
        """
    res = await run_slip(src)
    assert_ok(res, ["fmt-int", "fmt-only"])


@pytest.mark.asyncio
async def test_conjunction_more_specific_than_single_type():
    src = """
        Character: scope #{}
        Player: scope #{} |inherit Character
        Buff: scope #{}
        OnFire: scope #{} |inherit Buff

        hit: fn {p: Player} [ "player" ]
        hit: fn {p: (Player and OnFire)} [ "onfire" ]

        a: create Player
        b: create Player |with [ mixin OnFire ]

        #[ hit a, hit b ]
        """
    res = await run_slip(src)
    assert_ok(res, ["player", "onfire"])


@pytest.mark.asyncio
async def test_mixed_kind_conjunction_inapplicable_no_match():
    src = """
        Character: scope #{}
        Player: scope #{} |inherit Character

        only: fn {x: (Player and `string`)} [ "impossible" ]
        obj: create Player
        only obj
        """
    res = await run_slip(src)
    assert_error(res, "No matching method")


@pytest.mark.asyncio
async def test_exact_tier_ambiguity_raises():
    src = """
        g: fn {x: `int`} [ "one" ]
        g: fn {x: `int`} [ "two" ]
        g 1
        """
    res = await run_slip(src)
    assert_error(res, "Ambiguous method call")


@pytest.mark.asyncio
async def test_multidispatch_and_with_union_one_arg():
    src = """
        Character: scope #{}
        Player: scope #{} |inherit Character
        Buff: scope #{}
        OnFire: scope #{} |inherit Buff
        Poisoned: scope #{} |inherit Buff

        treat: fn {p: Player and (OnFire or Poisoned)} [ "player-buffed" ]
        treat: fn {p: (Character and OnFire)} [ "onfire-generic" ]
        treat: fn {p: Player} [ "player-generic" ]

        p1: create Player |with [ mixin OnFire ]
        p2: create Player |with [ mixin Poisoned ]
        p3: create Character |with [ mixin OnFire ]
        p4: create Player

        #[ treat p1, treat p2, treat p3, treat p4 ]
    """
    res = await run_slip(src)
    assert_ok(res, ["player-buffed", "player-buffed", "onfire-generic", "player-generic"])


@pytest.mark.asyncio
async def test_multidispatch_mixed_and_or_two_args():
    src = """
        Character: scope #{}
        Player: scope #{} |inherit Character
        Item: scope #{}
        Weapon: scope #{} |inherit Item
        Buff: scope #{}
        OnFire: scope #{} |inherit Buff
        Poisoned: scope #{} |inherit Buff
        Frozen: scope #{} |inherit Buff

        apply: fn {p: Player and (OnFire or Poisoned), w: (Weapon and Frozen)} [ "both-specific" ]
        apply: fn {p: (Character and OnFire), w: Weapon} [ "onfire-player" ]
        apply: fn {p: Player, w: Weapon} [ "plain" ]

        p_onfire: create Player |with [ mixin OnFire ]
        p_poison: create Player |with [ mixin Poisoned ]
        p_plain:  create Player

        w_frozen: create Weapon |with [ mixin Frozen ]
        w_plain:  create Weapon

        r1: apply p_onfire w_frozen     -- matches both-specific
        r2: apply p_onfire w_plain      -- matches onfire-player
        r3: apply p_poison w_frozen     -- matches both-specific (via Poisoned branch)
        r4: apply p_plain  w_plain      -- matches plain

        #[ r1, r2, r3, r4 ]
    """
    res = await run_slip(src)
    assert_ok(res, ["both-specific", "onfire-player", "both-specific", "plain"])
