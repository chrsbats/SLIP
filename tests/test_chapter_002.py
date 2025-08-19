import pytest
from slip.slip_runtime import ScriptRunner

async def run_slip(src: str):
    runner = ScriptRunner(load_core=True)
    return await runner.handle_script(src)

def assert_ok(res, expected=None):
    assert res.status == 'success', f"expected success, got {res.status}: {res.error_message}"
    if expected is not None:
        assert res.value == expected

# 2.1 Comments

@pytest.mark.asyncio
async def test_comments_ignored_single_and_block_nested():
    src = """
    -- single line is ignored
    a: 1
    {--
      block comment
      {-- nested --}
    --}
    a
    """
    res = await run_slip(src)
    assert_ok(res, 1)

# 2.2 Literals and Core Data Types

@pytest.mark.asyncio
async def test_numbers_booleans_none_and_strings():
    src = """
    #[ 123, -5, true, false, none, 'raw', "interp" ]
    """
    res = await run_slip(src)
    assert_ok(res, [123, -5, True, False, None, 'raw', 'interp'])

@pytest.mark.asyncio
async def test_empty_group_evaluates_to_none_and_equals_none():
    src = """
    eq none ()
    """
    res = await run_slip(src)
    assert_ok(res, True)

@pytest.mark.asyncio
async def test_list_and_dict_literals_evaluate_contents():
    src = """
    xs: #[ 1, 1 + 1, 3 ]
    d: #{ a: 10, b: 5 + 1 }
    #[ xs, d.a + d.b ]
    """
    res = await run_slip(src)
    assert res.status == 'success'
    xs, summed = res.value
    assert xs == [1, 2, 3]
    assert summed == 16

# 2.3 The scope Data Type

@pytest.mark.asyncio
async def test_scope_constructor_and_is_scope_predicate():
    src = """
    s: scope #{ a: 1 }
    #[ is-scope? s, s.a ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, 1])

# 2.4 Data Type Semantics: Paths and equality

@pytest.mark.asyncio
async def test_is_path_predicate_for_path_literals():
    src = """
    #[ is-path? `a`,
       is-path? `a:`,
       is-path? `~a`,
       is-path? `|map`,
       is-path? `[a,b]:`
     ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, True, True, True, True])

@pytest.mark.asyncio
async def test_path_literal_equality_and_canonicalization():
    # Same path equals same path; dots and slashes canonicalize to the same structure
    src = """
    #[ eq `a.b` `a.b`,
       eq `a.b` `a/b`,
       eq `a.b.c` `a/b.c`,
       eq `a.b` `a.c`
     ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, True, True, False])

@pytest.mark.asyncio
async def test_piped_and_multi_set_and_del_path_literal_equality():
    src = """
    #[ eq `|map` `|map`,
       eq `~a.b` `~a.b`,
       eq `[x,y]:` `[x,y]:`,
       eq `~a` `~b`
     ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, True, True, False])

@pytest.mark.asyncio
async def test_mutable_container_reference_behavior_for_dict():
    # dict is a mutable reference type; two names bound to the same dict see changes
    src = """
    d: #{ a: 1 }
    e: d
    e.a: 42
    d.a
    """
    res = await run_slip(src)
    assert_ok(res, 42)

# 2.5 Querying Collections with [...]

@pytest.mark.asyncio
async def test_query_index_slice_and_filter_on_list():
    # index
    res = await run_slip("""
    arr: #[10, 20, 30, 40, 50]
    arr[1]
    """)
    assert_ok(res, 20)

    # slice
    res = await run_slip("""
    arr: #[10, 20, 30, 40, 50]
    arr[1:4]
    """)
    assert_ok(res, [20, 30, 40])

    # filter
    res = await run_slip("""
    arr: #[10, 20, 30, 40, 50]
    arr[> 20]
    """)
    assert_ok(res, [30, 40, 50])

@pytest.mark.asyncio
async def test_query_index_string_key_on_dict():
    src = """
    d: #{ name: "Kael", hp: 100 }
    d["name"]
    """
    res = await run_slip(src)
    assert_ok(res, "Kael")

@pytest.mark.asyncio
async def test_vectorized_pluck_operation():
    src = """
    players: #[
      #{ name: "Kael", hp: 75 },
      #{ name: "Jaina", hp: 120 },
      #{ name: "Thrall", hp: 90 }
    ]
    players.hp[> 100]
    """
    res = await run_slip(src)
    # Vectorized pluck: players.hp → #[75, 120, 90], then filter > 100 → #[120]
    assert res.status == 'success' and res.value == [120]

@pytest.mark.asyncio
async def test_filter_with_lhs_pipeline_transform():
    src = """
    dist: fn {p} [ p.x + p.y ]

    points: #[
      #{ x: 3, y: 4 },
      #{ x: 6, y: 8 },
      #{ x: 1, y: 1 }
    ]

    points[|dist < 10]
    """
    res = await run_slip(src)
    assert_ok(res, [{'x': 3, 'y': 4}, {'x': 1, 'y': 1}])

@pytest.mark.asyncio
async def test_filter_with_chained_infix_transform():
    src = """
    xs: #[ 5, 10, 30 ]
    xs[* 10 - 20 / 2 > 20]
    """
    res = await run_slip(src)
    assert_ok(res, [10, 30])

@pytest.mark.asyncio
async def test_i_string_interpolates_variables():
    src = """
    name: "Kael"
    "Hello, {{name}}!"
    """
    res = await run_slip(src)
    assert_ok(res, "Hello, Kael!")

@pytest.mark.asyncio
async def test_i_string_nested_lookup_into_dict():
    src = """
    user: #{ name: "Kael", hp: 100 }
    "User: {{user.name}} (HP {{user.hp}})"
    """
    res = await run_slip(src)
    assert_ok(res, "User: Kael (HP 100)")

@pytest.mark.asyncio
async def test_i_string_auto_dedent_multiline():
    src = """
    name: "Kael"
    banner: "
      Welcome, {{name}}!
      Ready."
    banner
    """
    res = await run_slip(src)
    assert_ok(res, "Welcome, Kael!\nReady.")

@pytest.mark.asyncio
async def test_raw_string_is_verbatim_no_interpolation_or_escapes():
    src = """
    name: "World"
    s: '{{name}}\\n'
    s
    """
    res = await run_slip(src)
    assert_ok(res, "{{name}}\\n")
