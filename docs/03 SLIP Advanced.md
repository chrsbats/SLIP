# SLIP Advanced

Parts 1 and 2 teach the fast path for scripting and program design. This guide covers the features you reach for when:

- a script needs to keep running in the background
- SLIP is embedded inside a Python application
- host or database data needs to become a live SLIP object
- you want to build your own control-flow helpers
- you need to generate or run code dynamically

These features are powerful, but they are not the default path. Reach for them when the simpler tools stop being enough.

---

## How do I run background tasks?

The practical async story in SLIP is `task`.

Use it for:

- maintenance jobs
- polling loops
- periodic checks
- cooldowns and timers
- long-running watchers inside a host application

### Launch a task

```slip
task [
  sleep 0.01
  print "done"
]
```

### Use tasks for repeating work

```slip
task [
  loop [
    sleep 60
    print "tick"
  ]
]
```

### What happens inside loops?

Within task context, long `while` and `foreach` loops cooperate with the event loop so they do not monopolize execution.

That means task-based background work is safe enough for practical timers and watchers without introducing a second concurrency system into your scripts.

### Host-managed lifecycle

If your script is running inside a `SLIPHost`, tasks can be tracked and canceled by the host.

That makes `task` a good fit for embedded applications where background jobs belong to the host lifecycle.

### Takeaway

Use `task` when work should continue in the background without blocking the host.

- for periodic work, combine it with `sleep`
- keep tasks focused on one job
- let the host manage long-lived task lifecycle

---

## How do I integrate with Python?

SLIP is designed to be embedded in a Python application.

For many real uses, this is the main advanced feature: Python owns the engine, infrastructure, and persistence; SLIP owns game logic, rules, and moddable behavior.

### Expose host objects as data

If a Python object implements `__getitem__`, `__setitem__`, and `__delitem__`, SLIP can use path access against it.

```python
from slip.slip_runtime import SLIPHost


class CharacterHost(SLIPHost):
    def __init__(self):
        super().__init__()
        self._data = {"hp": 100}

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __delitem__(self, key):
        del self._data[key]
```

From SLIP, that object looks like ordinary path-accessible data:

```slip
obj.hp: 80
obj.hp
```

### Expose host methods deliberately

Python methods marked with `@slip_api_method` are safe to expose to SLIP.

```python
from slip.slip_runtime import slip_api_method


class CharacterHost(SLIPHost):
    ...

    @slip_api_method
    def take_damage(self, amount: int):
        self._data["hp"] -= amount
```

Expose them into the runner scope under `kebab-case` names:

```python
runner.root_scope["take-damage"] = host.take_damage
```

Then call them from SLIP like any other function:

```slip
take-damage 3
```

### Keep a long-lived runner

For embedded applications, a common pattern is to keep one `ScriptRunner` alive, preload functions into its environment, and then call into that environment repeatedly from Python.

```python
from slip import ScriptRunner


runner = ScriptRunner()

await runner.handle_script("""
attack: fn {attacker, target} [
    print "attack!"
    response ok none
]
""")

result = await runner.handle_script('attack (host-object "p1") (host-object "goblin-1")')
```

That is the right model when SLIP owns game logic and Python owns engine infrastructure.

### Use `ExecutionResult` from Python

Every script execution returns an `ExecutionResult`.

From Python, the main fields to care about are:

- `status`
- `value`
- `error_message`
- `side_effects`

Typical host-side pattern:

```python
result = await runner.handle_script('attack (host-object "p1") (host-object "goblin-1")')

if result.status == "ok":
    handle_success(result.value, result.side_effects)
else:
    log_error(result.error_message)
```

### Takeaway

The usual embedded split is:

- Python owns infrastructure
- SLIP owns rules and mechanics
- one long-lived `ScriptRunner` holds the loaded SLIP environment
- host objects and methods are exposed explicitly

---

## How do I work with host and persisted data?

The preferred host boundary has two entry points:

- `host-object id` returns a live SLIP object and auto-rehydrates marked persisted data
- `host-data id` returns the raw dict/list/value storage shape with no rehydration

Use `host-object` when you want normal SLIP behavior such as prototype dispatch. Use `host-data` when you want persistence-shaped data.

### Use `host-object` for live entities

```slip
person: host-object "player-1"
target: host-object "goblin-1"

attack person target
```

This is the right shape when game logic should see live typed objects.

### Use `host-data` for raw stored values

```slip
raw: host-data "player-1"
raw.location
```

This is the right shape when you want to inspect or manipulate persistence-shaped data directly.

### Use `as-slip` outside the host boundary

Sometimes data comes from somewhere other than `host-object`, but you still want it to become a real SLIP object that participates in prototype dispatch.

That is what `as-slip` is for.

```slip
obj: as-slip (host-data "player-1")
```

Current behavior:

- plain dicts and lists stay plain
- `__slip__`-marked values are rehydrated recursively
- `type: "scope"` creates a real `scope`
- if `prototype` is present, it is resolved by name
- unknown prototypes raise an error

### Serialized shape

Version 1 uses a reserved metadata envelope:

```json
{
  "__slip__": {
    "type": "scope",
    "prototype": "Character"
  },
  "hp": 77
}
```

### Dispatch example

```slip
Character: scope #{}

describe: fn {x: Character} [ "typed" ]
describe: fn {x} [ "fallback" ]

obj: host-object "player-1"
describe obj
```

Use `as-slip` directly when the data comes from some other boundary, such as raw file, HTTP, or manually assembled dict/list values.

### Takeaway

Use the host boundary deliberately:

- `host-object` for live runtime objects
- `host-data` for raw storage data
- `as-slip` for explicit rehydration outside that boundary

---

## How do I write my own control flow?

One of SLIP's unusual features is that many control-flow patterns can be built as ordinary functions because code blocks are already first-class values.

That means advanced users can build abstractions that would require macros or special forms in many other languages.

### Start with code as data

In SLIP, `[...]` creates a first-class `code` value.

```slip
c: [
  y: 5
  y + 7
]

#[ is-code? c, run c ]
-- => #[true, 12]
```

Important: a code value is unevaluated until something runs it.

### Use `run`

`run` executes a code value and returns the last value it produced.

```slip
res: run [
  x: 1
  x + 2
]
```

Current behavior:

- `run` returns the final value
- writes inside `run` do not leak into the caller's scope

```slip
res: run [
  x: 1
  x + 2
]

probe: do [ x ]
#[ res, probe.outcome.status = err ]
-- => #[3, true]
```

### Use `run-with`

`run-with` executes code in a specific target scope.

```slip
s: scope #{}

out: run-with [
  a: 10
  a * 2
] s

#[ out, s.a ]
-- => #[20, 10]
```

Use `run-with` when you want controlled writes into an object, module scope, or temporary working scope.

### Watch `current-scope`

`current-scope` returns the current lexical scope, not the `run-with` target.

That distinction matters when you mix caller values with target-scope writes.

### Constructor functions help here too

The advanced forms `list [ ... ]` and `dict [ ... ]` are useful when you want to construct values from generated code.

```slip
xs: list [
  1
  1 + 1
  3
]

d: dict [
  a: 10
  b: 5 + 1
]
```

### Keep closures in mind

Before reaching for metaprogramming, remember that plain closures solve many dynamic problems.

```slip
make-adder: fn {n} [
  fn {x} [ x + n ]
]

add-10: make-adder 10
add-10 7
-- => 17
```

If a closure is enough, it is usually the better tool.

### Takeaway

Write your own control flow when a normal function over a code block will make the language fit your domain better.

- start with `[...]` as code data
- use `run` and `run-with` deliberately
- prefer closures first when they are enough

---

## How do I build and run code dynamically?

This is the most advanced layer: build code at runtime, select targets dynamically, and then execute the result.

### Use `call` for dynamic invocation

`call` is the escape hatch for dynamic function and path use.

It can:

- call a function with a list of args
- evaluate a runtime path value
- build a path from a string
- perform dynamic assignment or deletion

```slip
call add #[1, 2]
```

```slip
p: call 'a.b'
eq p `a.b`
```

```slip
call 'x:' #[10]
call '~x' #[]
```

Use `call` when the target is only known at runtime. If the target is already static, ordinary SLIP syntax is clearer.

### Use `inject` and `splice`

`inject` and `splice` let you build code from surrounding runtime values.

#### `inject`

`inject` inserts one value into a code block.

```slip
my-var: 10

run [
  result: (add (inject my-var) 5)
  result
]
-- => 15
```

You can inject:

- plain values
- path literals
- function objects

```slip
op: `add`
v1: 2
v2: 3

code: [ call (inject op) #[(inject v1), (inject v2)] ]
run code
```

#### `splice`

`splice` inserts multiple values or statements.

```slip
args: #[2, 3]

run [
  add (splice args)
]
-- => 5
```

`splice` is also useful for statement-level expansion when you load code from a file and want to fill in pieces from the caller.

### Load code from files and fill it in

One of the most powerful advanced workflows is:

1. load a `.slip` file as code
2. provide caller values
3. expand it with `inject` and `splice`
4. run it with `run` or `run-with`

That gives you configurable code templates without inventing a separate macro system.

```slip
module-x: 5
args: #[3, 4]
extra-stmts: [ y: 10; z: y * 2 ]

code: file://./mod.slip
run code
```

Use this when code must be assembled from reusable pieces at runtime. For static composition, normal modules are easier.

### Takeaway

This layer is for the cases where static code is not enough.

- use `call` when the target is dynamic
- use `inject` and `splice` when code must be assembled
- prefer static composition whenever it is still clear enough

---

Advanced features are for leverage, not for everyday ceremony.
