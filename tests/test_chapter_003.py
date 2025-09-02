import pytest
from slip.slip_runtime import ScriptRunner

async def run_slip(src: str):
    runner = ScriptRunner(load_core=True)
    return await runner.handle_script(src)

def assert_ok(res, expected=None):
    assert res.status == 'success', f"expected success, got {res.status}: {res.error_message}"
    if expected is not None:
        assert res.value == expected


# 3.1 Assignment: return value semantics
@pytest.mark.asyncio
async def test_assignment_returns_assigned_value():
    res = await run_slip("x: 123")
    assert_ok(res, 123)


# 3.1.2 Generic Function Merging and Arity Overloading
@pytest.mark.asyncio
async def test_generic_function_merging_and_arity():
    src = """
    foo: fn {x} [ x ]
    foo: fn {x, y} [ x + y ]
    #[ foo 10, foo 2 3, eq (type-of foo) `function` ]
    """
    res = await run_slip(src)
    assert_ok(res, [10, 5, True])


# 3.1.3 Scope Registration (christening): meta.name and meta.type-id
@pytest.mark.asyncio
async def test_scope_registration_sets_meta_name_and_type_id():
    src = """
    TypeX: scope #{}
    #[ TypeX.meta.name, TypeX.meta.type-id > 0 ]
    """
    res = await run_slip(src)
    assert_ok(res, ["TypeX", True])


# 3.1.4 Destructuring Binding (multi-set)
@pytest.mark.asyncio
async def test_destructuring_assignment_binds_values():
    src = """
    [a, b]: #[10, 20]
    #[ a, b ]
    """
    res = await run_slip(src)
    assert_ok(res, [10, 20])


# 3.1.5 Slice Replacement on lists
@pytest.mark.asyncio
async def test_slice_replacement_assignment_mutates_list():
    src = """
    xs: #[1, 2, 3, 4, 5]
    xs[1:4]: #[20, 30, 40]
    #[ xs, xs[1:4] ]
    """
    res = await run_slip(src)
    assert_ok(res, [[1, 20, 30, 40, 5], [20, 30, 40]])


# 3.1.7 Parent Scope Binding from a function call
@pytest.mark.asyncio
async def test_parent_scope_binding_updates_outer_scope():
    src = """
    counter: 0
    inc: fn {} [ ../counter: + 1 ]
    #[ inc, counter ]
    """
    res = await run_slip(src)
    # inc returns the new value written to parent.counter; counter reflects the update
    assert_ok(res, [1, 1])


# 3.3 Functions: Typed dispatch by prototype (prefer most recent matching method)
@pytest.mark.asyncio
async def test_typed_dispatch_by_prototype():
    src = """
    A: scope #{}
    B: scope #{} |inherit A

    f: fn {x: A} [ 1 ]
    f: fn {x: B} [ 2 ]

    #[ f (create A), f (create B) ]
    """
    res = await run_slip(src)
    assert_ok(res, [1, 2])


# 3.3 Functions: return exits early with value
@pytest.mark.asyncio
async def test_return_exits_function_early():
    src = """
    early: fn {} [
        return 42
        x: 99  -- should not run
    ]
    early
    """
    res = await run_slip(src)
    assert_ok(res, 42)

@pytest.mark.asyncio
async def test_assignment_returns_assigned_value():
    res = await run_slip("a: 10")
    assert_ok(res, 10)

@pytest.mark.asyncio
async def test_update_infix_add_one():
    src = """
    x: 1
    x: + 1
    x
    """
    res = await run_slip(src)
    assert_ok(res, 2)

@pytest.mark.asyncio
async def test_unary_piped_update():
    src = """
    heal: fn {n} [ n + 10 ]
    hp: 40
    hp: |heal
    hp
    """
    res = await run_slip(src)
    assert_ok(res, 50)

@pytest.mark.asyncio
async def test_update_with_piped_binary_call():
    src = """
    x: 3
    x: |add 5
    x
    """
    res = await run_slip(src)
    assert_ok(res, 8)

def assert_ok(res, expected=None):
    assert res.status == 'success', f"expected success, got {res.status}: {res.error_message}"
    if expected is not None:
        assert res.value == expected

@pytest.mark.asyncio
async def test_vectorized_update_returns_new_values():
    src = """
    players: #[
      #{ name: "A", hp: 75 },
      #{ name: "B", hp: 45 },
      #{ name: "C", hp: 30 }
    ]
    players.hp[< 50]: + 10
    """
    res = await run_slip(src)
    # Assignment returns the list of new values written for matched targets (B and C)
    assert_ok(res, [55, 40])

@pytest.mark.asyncio
async def test_vectorized_update_writes_back_to_owners():
    src = """
    players: #[
      #{ name: "A", hp: 75 },
      #{ name: "B", hp: 45 },
      #{ name: "C", hp: 30 }
    ]
    players.hp[< 50]: + 10
    #[ players[0].hp, players[1].hp, players[2].hp ]
    """
    res = await run_slip(src)
    # After update: A unchanged; B and C increased by 10
    assert_ok(res, [75, 55, 40])

@pytest.mark.asyncio
async def test_vectorized_broadcast_assignment():
    src = """
    players: #[
      #{ name: "A", hp: 75 },
      #{ name: "B", hp: 45 },
      #{ name: "C", hp: 30 }
    ]
    players.hp[< 50]: 50
    #[ players[0].hp, players[1].hp, players[2].hp ]
    """
    res = await run_slip(src)
    assert_ok(res, [75, 50, 50])

@pytest.mark.asyncio
async def test_vectorized_elementwise_assignment_requires_matching_lengths():
    src = """
    players: #[
      #{ name: "A", hp: 75 },
      #{ name: "B", hp: 45 },
      #{ name: "C", hp: 30 }
    ]
    -- Two matches (< 50) but three RHS values -> should error
    players.hp[< 50]: #[51, 52, 53]
    """
    res = await run_slip(src)
    # Any error is acceptable; message wording is standardized by the runtime
    assert res.status == 'error'

# 3.x Primitive type annotations in dispatch
@pytest.mark.asyncio
async def test_primitive_typed_dispatch_string_vs_int():
    src = """
    g: fn {x: `string`} [ 's' ]
    g: fn {x: `int`} [ 'i' ]
    #[ g 'hello', g 42 ]
    """
    res = await run_slip(src)
    assert_ok(res, ['s', 'i'])

@pytest.mark.asyncio
async def test_primitive_typed_dispatch_matches_path_literal():
    src = """
    h: fn {x: `path`} [ 'p' ]
    #[ h `a.b`, h `~a`, h `|map` ]
    """
    res = await run_slip(src)
    assert_ok(res, ['p', 'p', 'p'])


@pytest.mark.asyncio
async def test_del_path_prunes_empty_scopes_cascading():
    src = """
    -- Build three nested scopes A.B.C with a single leaf x
    A: scope #{
      B: scope #{
        C: scope #{
          x: 1
        }
      }
    }
    -- Delete the leaf; C becomes empty -> prune C from B, B becomes empty -> prune from A, A becomes empty -> prune from root
    ~A.B.C.x
    -- Probing A should now error since it was pruned
    probeA: do [ A ]
    eq probeA.outcome.status err
    """
    res = await run_slip(src)
    assert_ok(res, True)


@pytest.mark.asyncio
async def test_del_pruning_stops_when_parent_not_empty():
    src = """
    -- A.B has two keys: C (which will be emptied) and k (to keep B non-empty)
    A: scope #{
      B: scope #{
        C: scope #{
          x: 1
        },
        k: 2
      }
    }
    -- Delete the only field in C; C should be pruned but B remains due to 'k'
    ~A.B.C.x
    -- B should still exist and keep key 'k'
    existsB: eq (do [ A.B ]).outcome.status ok
    kval: A.B.k
    #[ existsB, kval ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, 2])

@pytest.mark.asyncio
async def test_group_then_multiname_chain_preserves_trailing_ok_argument():
    src = """
    -- Build nested scopes without any delete operation
    A: scope #{
      B: scope #{
        k: 2
      }
    }
    -- This is the minimal reproduction of the folding bug:
    -- (do [ A.B ]) produces a response ok/value; we then chain
    -- .outcome.status via folding from a Group base, and must NOT
    -- skip the trailing 'ok' argument to 'eq'.
    res: eq (do [ A.B ]).outcome.status ok
    res
    """
    res = await run_slip(src)
    assert_ok(res, True)

