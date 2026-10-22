import asyncio

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
        next
    ]

    -- non-idiomatic (property access), but supported
    Combat |Combat.apply-damage "p1" 10
    """
    res = await run_slip(src)
    assert_ok(res, 110)


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
        next
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
        none
    ]

    Combat |bad
    """
    res = await run_slip(src)
    assert res.status == "err"
    assert "Cannot write across an identity boundary" in (res.error_message or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [
    "Combat.hp.p1: 0",
    "hp: Combat.hp; hp.p1: 0",
    "hp: Combat.hp; ~hp.p1",
    "hp: Combat.hp; call `hp.p1:` #[0]",
    "rows: Combat.players; rows.hp[< 50]: 0",
    "rows: Combat.players[.hp < 50]; rows[0].hp: 0",
    "rows: Combat.players[.hp < 50]; rows.hp[< 50]: 0",
    "snapshot: copy Combat; snapshot.hp: #{}",
    "Combat.hp: fn {} [0]",
    "add Combat.values #[2]",
    "bad: fn {this: Combat} [hp: this.hp; hp.p1: 0]; Combat |bad",
])
async def test_resolver_owned_values_cannot_be_mutated_through_aliases(operation):
    runner = ScriptRunner()
    res = await runner.handle_script("""
Combat: resolver #{hp: #{p1: 100}, players: #[#{hp: 40}], values: #[1]}
""" + operation)
    assert res.status == "err", res.value
    assert 'resolver' in res.error_message.lower()
    combat = runner.root_scope['Combat']
    assert combat['hp']['p1'] == 100
    assert combat['players'][0]['hp'] == 40
    assert combat['values'] == [1]


@pytest.mark.asyncio
async def test_resolver_owner_transaction_updates_nested_and_selected_values():
    res = await run_slip("""
Combat: resolver #{hp: #{p1: 100}, players: #[#{hp: 40}, #{hp: 80}], values: #[1]}
heal: fn {this: Combat} [
    this.hp.p1: + 5
    this.players.hp[< 50]: + 10
    this.values: + #[2]
]
Combat |heal
#[Combat.hp.p1, Combat.players.hp, Combat.values]
""")
    assert_ok(res, [105, [50, 80], [1, 2]])


@pytest.mark.asyncio
async def test_resolver_methods_dispatch_on_the_declared_owner():
    res = await run_slip("""
A: resolver #{hp: 10}
B: resolver #{hp: 20}
change: fn {this: A} [this.hp: + 1]
change: fn {this: B} [this.hp: + 2]
A |change
B |change
#[A.hp, B.hp]
""")
    assert_ok(res, [11, 22])


@pytest.mark.asyncio
@pytest.mark.parametrize('invocation', [
    'B |change', 'call change.methods[0] #[B]',
])
async def test_resolver_method_rejects_an_unrelated_receiver(invocation):
    res = await run_slip("""
A: resolver #{hp: 10}
B: resolver #{hp: 20}
change: fn {this: A} [this.hp: 0]
""" + invocation)
    assert res.status == 'err'
    assert 'No matching method' in res.error_message


@pytest.mark.asyncio
async def test_nested_transaction_failure_restores_the_outer_owner():
    res = await run_slip("""
A: resolver #{hp: 10}
B: resolver #{hp: 20}
reject: fn {this: B} [fail 'rejected']
change: fn {this: A} [
    do [B |reject]
    this.hp: + 1
]
A |change
#[A.hp, B.hp]
""")
    assert_ok(res, [11, 20])


@pytest.mark.asyncio
async def test_control_helpers_preserve_the_enclosing_transaction():
    res = await run_slip("""
Combat: resolver #{hp: 0}
advance: fn {this: Combat} [
    for {i} 0 3 [
        when [i > 0] [this.hp: + i]
    ]
    cond #[#[[true], [this.hp: + 10]]]
    do [loop [this.hp: + 1; fail 'done']]
]
Combat |advance
Combat.hp
""")
    assert_ok(res, 14)


@pytest.mark.asyncio
async def test_task_does_not_inherit_its_creators_transaction_authority():
    runner = ScriptRunner()
    res = await runner.handle_script("""
Combat: resolver #{hp: 100}
launch: fn {this: Combat} [task [this.hp: 0]]
Combat |launch
""")
    assert_ok(res)
    with pytest.raises(PermissionError, match='resolver transaction'):
        await res.slip_result
    assert runner.root_scope['Combat']['hp'] == 100


@pytest.mark.asyncio
async def test_cancelled_transaction_does_not_leak_authority():
    entered = asyncio.Event()

    async def checkpoint():
        entered.set()
        await asyncio.Event().wait()

    runner = ScriptRunner()
    runner.root_scope['checkpoint'] = checkpoint
    res = await runner.handle_script("""
Combat: resolver #{hp: 100}
wait: fn {this: Combat} [checkpoint; this.hp: 0]
task [Combat |wait]
""")
    assert_ok(res)
    task = res.slip_result
    try:
        await asyncio.wait_for(entered.wait(), 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    denied = await runner.handle_script('this.hp: 0')
    assert denied.status == 'err'
    assert 'resolver transaction' in denied.error_message
    changed = await runner.handle_script("""
change: fn {this: Combat} [this.hp: + 1]
Combat |change
""")
    assert_ok(changed, 101)


@pytest.mark.asyncio
async def test_local_aliases_remain_shared_and_detached_values_are_local():
    res = await run_slip("""
state: #{hp: 1}
alias: state
alias.hp: 2
Combat: resolver #{hp: state}
replace-hp: fn {this: Combat} [this.hp: #{hp: 10}]
Combat |replace-hp
alias.hp: 3
#[state.hp, Combat.hp.hp]
""")
    assert_ok(res, [3, 10])


@pytest.mark.asyncio
async def test_imported_resolver_keeps_authority_for_exported_aliases(tmp_path):
    (tmp_path / 'combat.slip').write_text("""
Combat: resolver #{hp: #{p1: 100}, values: #[1]}
hp: Combat.hp
advance: fn {this: Combat} [
    this.hp.p1: + 1
    this.values: + #[2]
]
""", encoding='utf-8')
    runner = ScriptRunner()
    runner.source_dir = str(tmp_path)
    changed = await runner.handle_script("""
combat: import `file://combat.slip`
combat.Combat |combat.advance
#[combat.hp.p1, combat.Combat.values]
""")
    assert_ok(changed, [101, [1, 2]])
    denied = await runner.handle_script('combat.hp.p1: 0')
    assert denied.status == 'err'
    assert 'resolver' in denied.error_message.lower()


@pytest.mark.asyncio
async def test_overlapping_task_transactions_keep_their_own_authority():
    entered = {label: asyncio.Event() for label in ('a', 'b')}
    release = {label: asyncio.Event() for label in ('a', 'b')}

    async def checkpoint(label):
        entered[label].set()
        await release[label].wait()

    runner = ScriptRunner()
    runner.root_scope['checkpoint'] = checkpoint
    res = await runner.handle_script("""
A: resolver #{hp: 0}
B: resolver #{hp: 0}
write-a: fn {this: A} [checkpoint 'a'; this.hp: 11]
write-b: fn {this: B} [checkpoint 'b'; this.hp: 22]
#[task [A |write-a], task [B |write-b]]
""")
    assert_ok(res)
    first, second = res.slip_result
    try:
        await asyncio.wait_for(entered['a'].wait(), 2)
        await asyncio.wait_for(entered['b'].wait(), 2)
        release['a'].set()
        await asyncio.wait_for(first, 2)
        release['b'].set()
        await asyncio.wait_for(second, 2)
        assert runner.root_scope['A']['hp'] == 11
        assert runner.root_scope['B']['hp'] == 22
    finally:
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)
