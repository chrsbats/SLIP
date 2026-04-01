import pytest
from slip.slip_runtime import ScriptRunner


async def run(src: str):
    runner = ScriptRunner()
    res = await runner.handle_script(src)
    return res


async def run_with_tmp(src: str, tmp_path):
    runner = ScriptRunner()
    runner.source_dir = str(tmp_path)
    await runner._initialize()
    return await runner.handle_script(src)


@pytest.mark.asyncio
async def test_dispatch_last_defined_wins_untyped():
    """
    Untyped methods (no Sig) dispatch by last-defined wins (when only untyped methods exist).
    """
    src = """
    greet: fn {name} [ "Hello {{name}}" ]
    greet: fn {name} [ "Hi {{name}}" ]

    greet "Karl"
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == "Hi Karl"


@pytest.mark.asyncio
async def test_dispatch_guards_filter_candidates_and_last_defined_wins():
    """
    Guards filter; among passing guarded candidates, last-defined wins.
    """
    src = """
    -- Both match fire, last-defined should win
    apply-effect: fn {kind} [ "burn-1" ] |where [kind = `fire`]
    apply-effect: fn {kind} [ "burn-2" ] |where [kind = `fire`]

    -- Only this matches ice
    apply-effect: fn {kind} [ "frozen" ] |where [kind = `ice`]

    #[
      apply-effect `fire`,
      apply-effect `ice`
    ]
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == ["burn-2", "frozen"]


@pytest.mark.asyncio
async def test_dispatch_guarded_methods_prioritized_over_unguarded():
    """
    Guards refine ties within a tier:
      - try guarded candidates first (last-defined among guarded)
      - else fallback to unguarded (last-defined among unguarded)
    """
    src = """
    choose: fn {x} [ "general-1" ]
    choose: fn {x} [ "guarded" ] |where [x > 10]
    choose: fn {x} [ "general-2" ]  -- last-defined unguarded

    #[ choose 5, choose 15 ]
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == ["general-2", "guarded"]


@pytest.mark.asyncio
async def test_dispatch_arity_tier_beats_guard_priority():
    """
    Arity is chosen before guards.
    Exact-arity should beat a guarded variadic when the call is exact-arity.
    """
    src = """
    f: fn {x: `int`} [ "exact" ]
    f: fn {x: `int`, rest...} [ "variadic" ] |where [true]

    -- With 1 arg, exact-arity tier is selected; variadic must not steal via guard.
    f 1
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == "exact"


@pytest.mark.asyncio
async def test_dispatch_type_tier_beats_guard_priority():
    """
    Type constraints are applied before guards.
    A typed method should be selected over an untyped guarded fallback when types match.
    """
    src = """
    A: scope #{}

    f: fn {x: A} [ "typed" ]
    f: fn {x} [ "fallback" ] |where [true]   -- guarded but untyped; must not steal typed match

    a: create A
    f a
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == "typed"


@pytest.mark.asyncio
async def test_dispatch_typed_beats_untyped_fallback():
    """
    Contract: methods with a Sig are considered first; untyped methods are fallback-only.
    """
    src = """
    A: scope #{}

    f: fn {x} [ "fallback" ]
    f: fn {x: A} [ "typed" ]

    a: create A

    #[
      f a,      -- should pick typed
      f 123     -- should fall back
    ]
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == ["typed", "fallback"]


@pytest.mark.asyncio
async def test_dispatch_typed_last_defined_wins_same_type():
    """
    When multiple typed methods match, last-defined wins.
    """
    src = """
    A: scope #{}

    f: fn {x: A} [ "t1" ]
    f: fn {x: A} [ "t2" ]

    a: create A
    f a
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == "t2"


@pytest.mark.asyncio
async def test_dispatch_typed_matches_on_single_inheritance_parent_chain():
    """
    Typed dispatch matches on prototype chain via `.parent` (single inheritance).
    """
    src = """
    A: scope #{}
    B: scope #{} |inherit A

    f: fn {x: A} [ "as-A" ]

    b: create B
    f b
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == "as-A"


@pytest.mark.asyncio
async def test_dispatch_typed_sig_supports_dotted_paths_for_imported_prototypes(tmp_path):
    mod = tmp_path / "agents.slip"
    mod.write_text("Player: scope #{}\n", encoding="utf-8")
    url = f"file:///{str(mod).lstrip('/')}"

    src = f"""
    agents: import `{url}`

    greet: fn {{x: agents.Player}} [ "ok" ]

    p: create agents.Player
    p |greet
    """
    res = await run_with_tmp(src, tmp_path)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == "ok"


@pytest.mark.asyncio
async def test_dispatch_typed_prefers_more_specific_over_parent():
    """
    Typed dispatch prefers the most specific prototype match:
      - B beats A when the argument is a B (even if A was defined later).
    """
    src = """
    A: scope #{}
    B: scope #{} |inherit A

    f: fn {x: B} [ "B" ]
    f: fn {x: A} [ "A" ]   -- less specific

    b: create B
    f b
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == "B"

@pytest.mark.asyncio
async def test_dispatch_type_specificity_is_lexicographic_by_param_order():
    """
    When multiple args have type constraints, specificity is compared in parameter order.
    """
    src = """
    A: scope #{}
    B: scope #{} |inherit A

    g: fn {x: B, y: A} [ "BA" ]
    g: fn {x: A, y: B} [ "AB" ]

    x: create B
    y: create B

    g x y
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == "BA"


@pytest.mark.asyncio
async def test_dispatch_strict_arity_errors_when_too_many_args_non_variadic():
    """
    Contract: too many args is an error unless the method is variadic (rest...).
    """
    src = """
    g: fn {x: `int`} [ x ]
    g 1 2
    """
    res = await run(src)
    assert res.status == "err"
    assert "No matching method" in (res.error_message or "")


@pytest.mark.asyncio
async def test_dispatch_variadic_accepts_unlimited_args():
    """
    Variadic Sig methods (rest...) accept unlimited args.
    """
    src = """
    take: fn {x: `int`, rest...} [ x ]
    take 7 8 9
    """
    res = await run(src)
    assert res.status == "ok", f"ERROR: {res.error_message}\nEFFECTS: {res.side_effects}"
    assert res.value == 7


@pytest.mark.asyncio
async def test_dispatch_guard_exception_raises():
    """
    Contract: guard errors propagate (do not count as false).
    """
    src = """
    f: fn {x} [ "ok" ] |where [missing-name > 0]
    f 1
    """
    res = await run(src)
    assert res.status == "err"
    # Guard should raise a normal runtime error (PathNotFound for missing-name)
    assert ("PathNotFound" in (res.error_message or "")) or ("missing-name" in (res.error_message or ""))


@pytest.mark.asyncio
async def test_dispatch_no_match_raises_error():
    """Verify that a TypeError is raised when no methods match."""
    src = """
    only-fire: fn {kind} [ "ok" ] |where [kind = `fire`]
    only-fire `ice`
    """
    res = await run(src)
    assert res.status == "err"
    assert "No matching method" in (res.error_message or "")


