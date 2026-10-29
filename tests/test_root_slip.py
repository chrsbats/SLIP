
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


def test_core_update_helper_for_dict_and_scope(runner):

    script = """
target: #{ hp: 100 }
update target #{ hp: 80, mana: 20 }
#[ target.hp, target.mana ]
"""
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value == [80, 20]

    script = """
obj: scope #{ hp: 100 }
update obj #{ hp: 75, mana: 30 }
#[ obj.hp, obj.mana ]
"""
    res = runner.handle_script(script)
    assert res.status == 'ok', res.error_message
    assert res.value == [75, 30]


def test_to_int_and_to_float_return_none_on_invalid_input(runner):

    # to-int successes and failures
    res = runner.handle_script("to-int '12'")
    assert res.status == 'ok', res.error_message
    assert res.value == 12

    res = runner.handle_script("to-int 'x'")
    assert res.status == 'ok', res.error_message
    assert res.value is None

    # to-float successes and failures
    res = runner.handle_script("to-float '1.5'")
    assert res.status == 'ok', res.error_message
    assert res.value == 1.5

    res = runner.handle_script("to-float 'x'")
    assert res.status == 'ok', res.error_message
    assert res.value is None


def test_partial_reuses_bound_arguments_without_accumulating_calls(runner):
    res = runner.handle_script("""
inc: partial add 1
#[inc 2, inc 3, inc 4]
""")
    assert res.status == 'ok', res.error_message
    assert res.value == [3, 4, 5]


def test_partial_preserves_reference_identity_of_bound_values(runner):
    res = runner.handle_script("""
state: scope #{value: 0}
set-value: fn {target, value} [target.value: value]
set-state: partial set-value state
set-state 1
set-state 2
state.value
""")
    assert res.status == 'ok', res.error_message
    assert res.value == 2


def test_collection_overloads_preserve_prefix_and_pipe_forms(runner):
    res = runner.handle_script("""
xs: #[1, 2, 3]
double: fn {x} [x * 2]
is-positive: fn {x} [x > 1]
#[
    map double xs,
    xs |map double,
    filter is-positive xs,
    xs |filter is-positive,
    xs,
    zip xs #[4, 5],
    replace xs #[2] #[9]
]
""")
    assert res.status == 'ok', res.error_message
    assert res.value == [
        [2, 4, 6], [2, 4, 6], [2, 3], [2, 3], [1, 2, 3],
        [[1, 4], [2, 5]], [1, 9, 3],
    ]


def test_constructor_overloads_and_configuration_preserve_shadowing(runner):
    res = runner.handle_script("""
Player: scope #{hp: 100}
empty: create
plain: create Player
configured: create Player [hp: 80]
mapped: create Player #{hp: 60}
mapped |with #{mana: 20}
#[is-scope empty, Player.hp, plain.hp, configured.hp, mapped.hp, mapped.mana]
""")
    assert res.status == 'ok', res.error_message
    assert res.value == [True, 100, 100, 80, 60, 20]
