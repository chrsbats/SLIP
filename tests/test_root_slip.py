import pytest
from slip.slip_runtime import ScriptRunner

@pytest.mark.asyncio
async def test_core_arithmetic_and_operators():
    runner = ScriptRunner()
    res = await runner.handle_script("10 + 5 * 2")
    assert res.status == 'success', res.error_message
    assert res.value == 30

    res = await runner.handle_script("10 + (5 * 2)")
    assert res.status == 'success', res.error_message
    assert res.value == 20

@pytest.mark.asyncio
async def test_core_print_alias_emits_stdout():
    runner = ScriptRunner()
    res = await runner.handle_script('print "hello"')
    assert res.status == 'success', res.error_message
    assert len(res.side_effects) == 1
    effect = res.side_effects[0]
    assert effect['topics'] == ['stdout']
    assert effect['message'] == 'hello'

@pytest.mark.asyncio
async def test_core_type_predicates():
    runner = ScriptRunner()

    for src, expected in [
        ("is-number? 3", True),
        ("is-number? -2.5", True),
        ("is-string? 'raw'", True),
        ('is-string? "interp"', True),
        ("is-boolean? true", True),
        ("is-boolean? false", True),
        ("is-none? none", True),
        ("is-path? `a.b`", True),
        ("is-list? #[1,2,3]", True),
        ("is-dict? #{a:1}", True),
        ("is-scope? (scope #{})", True),
    ]:
        res = await runner.handle_script(src)
        assert res.status == 'success', f"{src}: {res.error_message}"
        assert res.value is expected, f"{src}: got {res.value!r}"

@pytest.mark.asyncio
async def test_core_list_utilities_reverse_map_filter_reduce_zip():
    runner = ScriptRunner()

    # reverse
    res = await runner.handle_script("reverse #[1,2,3]")
    assert res.status == 'success', res.error_message
    assert res.value == [3, 2, 1]

    # map (double each)
    script = "map (fn {x} [ x * 2 ]) #[1,2,3]"
    res = await runner.handle_script(script)
    assert res.status == 'success', res.error_message
    assert res.value == [2, 4, 6]

    # filter (> 1)
    script = "filter (fn {x} [ x > 1 ]) #[1,2,3]"
    res = await runner.handle_script(script)
    assert res.status == 'success', res.error_message
    assert res.value == [2, 3]

    # reduce (sum)
    script = "reduce (fn {acc, x} [ acc + x ]) 0 #[1,2,3]"
    res = await runner.handle_script(script)
    assert res.status == 'success', res.error_message
    assert res.value == 6

    # zip
    script = "zip #[1,2] #[3,4,5]"
    res = await runner.handle_script(script)
    assert res.status == 'success', res.error_message
    assert res.value == [[1, 3], [2, 4]]

@pytest.mark.asyncio
async def test_core_partial_and_compose():
    runner = ScriptRunner()

    # partial: inc x = add 1 x
    script = """
inc: partial add 1
inc 41
"""
    res = await runner.handle_script(script)
    assert res.status == 'success', res.error_message
    assert res.value == 42

    # compose: inc ∘ double (applies right-to-left)
    script = """
double: fn {x} [ x * 2 ]
inc: fn {y} [ y + 1 ]
f: compose inc double
f 10
"""
    res = await runner.handle_script(script)
    assert res.status == 'success', res.error_message
    assert res.value == 21

@pytest.mark.asyncio
async def test_core_object_model_create_and_is_a():
    runner = ScriptRunner()

    script = """
Character: scope #{ hp: 100 }
Player: create Character
is-a? Player Character
"""
    res = await runner.handle_script(script)
    assert res.status == 'success', res.error_message
    assert res.value is True

@pytest.mark.asyncio
async def test_core_schema_and_is_schema():
    runner = ScriptRunner()

    script = """
SchemaObj: schema #{}
is-schema? SchemaObj
"""
    res = await runner.handle_script(script)
    assert res.status == 'success', res.error_message
    assert res.value is True

@pytest.mark.asyncio
async def test_core_when_and_with_helpers():
    runner = ScriptRunner()

    # when
    script = """
x: 5
when [x > 3] [ print "bigger" ]
"""
    res = await runner.handle_script(script)
    assert res.status == 'success', res.error_message
    assert any(e['topics'] == ['stdout'] and e['message'] == 'bigger' for e in res.side_effects)

    # with
    script = """
obj: scope #{}
obj |with [ name: "new" ]
obj.name
"""
    res = await runner.handle_script(script)
    assert res.status == 'success', res.error_message
    assert res.value == "new"

@pytest.mark.asyncio
async def test_to_int_and_to_float_return_none_on_invalid_input():
    runner = ScriptRunner()

    # to-int successes and failures
    res = await runner.handle_script("to-int '12'")
    assert res.status == 'success', res.error_message
    assert res.value == 12

    res = await runner.handle_script("to-int 'x'")
    assert res.status == 'success', res.error_message
    assert res.value is None

    # to-float successes and failures
    res = await runner.handle_script("to-float '1.5'")
    assert res.status == 'success', res.error_message
    assert res.value == 1.5

    res = await runner.handle_script("to-float 'x'")
    assert res.status == 'success', res.error_message
    assert res.value is None
