
def test_core_arithmetic_and_operators(runner):
    res = runner.handle_script("10 + 5 * 2")
    assert res.status == 'ok', res.error_message
    assert res.value == 30

    res = runner.handle_script("10 + (5 * 2)")
    assert res.status == 'ok', res.error_message
    assert res.value == 20


def test_core_print_alias_emits_stdout(runner):
    res = runner.handle_script('print "hello"')
    assert res.status == 'ok', res.error_message
    assert len(res.side_effects) == 1
    effect = res.side_effects[0]
    assert effect['topics'] == ['stdout']
    assert effect['message'] == 'hello'


def test_core_type_predicates(runner):

    for src, expected in [
        ("is-number 3", True),
        ("is-number -2.5", True),
        ("is-string 'raw'", True),
        ('is-string "interp"', True),
        ("is-boolean true", True),
        ("is-boolean false", True),
        ("is-none none", True),
        ("is-path `a.b`", True),
        ("is-list #[1,2,3]", True),
        ("is-dict #{a:1}", True),
        ("is-scope (scope #{})", True),
    ]:
        res = runner.handle_script(src)
        assert res.status == 'ok', f"{src}: {res.error_message}"
        assert res.value is expected, f"{src}: got {res.value!r}"


def test_core_list_utilities_reverse_map_filter_reduce_zip(runner):

    # reverse
    res = runner.handle_script("reverse #[1,2,3]")
    assert res.status == 'ok', res.error_message
    assert res.value == [3, 2, 1]

    # map (double each)
    script = "map (fn {x} [ x * 2 ]) #[1,2,3]"
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value == [2, 4, 6]

    # filter (> 1)
    script = "filter (fn {x} [ x > 1 ]) #[1,2,3]"
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value == [2, 3]

    # reduce (sum)
    script = "reduce (fn {acc, x} [ acc + x ]) 0 #[1,2,3]"
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value == 6

    # zip
    script = "zip #[1,2] #[3,4,5]"
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value == [[1, 3], [2, 4]]


def test_core_partial_and_compose(runner):

    # partial: inc x = add 1 x
    script = """
inc: partial add 1
inc 41
"""
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value == 42

    # compose: inc ∘ double (applies right-to-left)
    script = """
double: fn {x} [ x * 2 ]
inc: fn {y} [ y + 1 ]
f: compose inc double
f 10
"""
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value == 21


def test_core_object_model_create_and_is_a(runner):

    script = """
Character: scope #{ hp: 100 }
Player: create Character
is-a Player Character
"""
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value is True


def test_core_schema_and_is_schema(runner):

    script = """
SchemaObj: schema #{}
is-schema SchemaObj
"""
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value is True


def test_core_when_and_with_helpers(runner):

    # when
    script = """
x: 5
when [x > 3] [ print "bigger" ]
"""
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert any(e['topics'] == ['stdout'] and e['message'] == 'bigger'
               for e in res.side_effects)

    # with
    script = """
obj: scope #{}
obj |with [ name: "new" ]
obj.name
"""
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value == "new"
