# SLIP Power Guide: Advanced Features

Parts 1 and 2 teach the fast path for scripting and program design. This guide covers the features you reach for when you need to:

- treat code as data
- control where code runs
- build code dynamically
- run background work
- integrate with Python host objects
- rehydrate typed SLIP objects from plain data

These features are powerful, but they are not the default path. Reach for them when the simpler tools stop being enough.

---

## 1. Code as data

In SLIP, `[...]` creates a first-class `code` value.

That means you can:

- store code in variables
- pass code to functions
- build code now and run it later

```slip
c: [
  y: 5
  y + 7
]

#[ is-code? c, run c ]
-- => #[true, 12]
```

Important: a code value is unevaluated until something runs it.

## 2. `run` and `run-with`

### `run`

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

### `run-with`

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

### `current-scope`

`current-scope` returns the current lexical scope, not the `run-with` target.

That distinction matters when you mix caller values with target-scope writes.

---

## 3. Constructor functions: `list` and `dict`

You already saw the literal forms `#[...]` and `#{...}` in Part 1. The advanced forms are the constructor functions:

- `list [ ... ]`
- `dict [ ... ]`

These are useful when you want to construct values from generated code.

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

---

## 4. `call` for dynamic invocation

`call` is the escape hatch for dynamic function and path use.

It can:

- call a function with a list of args
- evaluate a runtime path value
- build a path from a string
- perform dynamic assignment or deletion

### Call with assembled args

```slip
call add #[1, 2]
```

### Turn a string into a path-like value

```slip
p: call 'a.b'
eq p `a.b`
```

### Dynamic set and delete

```slip
call 'x:' #[10]
call '~x' #[]
```

Use `call` when the target is only known at runtime. If the target is already static, ordinary SLIP syntax is clearer.

---

## 5. Building code with `inject` and `splice`

`inject` and `splice` let you build code from surrounding runtime values.

### `inject`

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

### `splice`

`splice` inserts multiple values or statements.

```slip
args: #[2, 3]

run [
  add (splice args)
]
-- => 5
```

`splice` is also useful for statement-level expansion when you load code from a file and want to fill in pieces from the caller.

### A good rule

Use these only when you truly need dynamic code generation. If a normal function call works, prefer the normal function call.

---

## 6. Closures still matter

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

---

## 7. Background work with `task`

The practical async story in SLIP is `task`.

Use it for:

- background maintenance work
- polling loops
- periodic checks
- long-running watchers
- cron-like behavior inside a host application

### Launch a task

```slip
task [
  sleep 0.01
  print "done"
]
```

### Tasks and loops

Within task context, long `while` and `foreach` loops cooperate with the event loop so they do not monopolize execution.

That means a background task like this is reasonable:

```slip
task [
  loop [
    sleep 60
    print "tick"
  ]
]
```

### Host-managed lifecycle

If your script is running inside a `SLIPHost`, tasks can be tracked and canceled by the host.

That makes `task` a good fit for embedded applications where background jobs belong to the host lifecycle.

---

## 8. Host integration

SLIP can work directly with Python objects exposed by the host.

There are two main patterns.

### Mapping-style host objects

If a Python object implements `__getitem__`, `__setitem__`, and `__delitem__`, SLIP can use path access against it.

```slip
obj.hp: 80
obj.hp
```

### Exposed Python methods

Host methods marked with `@slip_api_method` can be safely exposed to SLIP.

The usual binding style is `kebab-case`.

```slip
take-damage 3
```

### Gateway functions

The preferred host boundary has two entry points:

- `host-object id` returns a live SLIP object and auto-rehydrates marked persisted data
- `host-data id` returns the raw dict/list/value storage shape with no rehydration

Use `host-object` when you want normal SLIP behavior such as prototype dispatch. Use `host-data` when you want persistence-shaped data.

```slip
obj: host-object "player-1"
obj.hp
```

```slip
raw: host-data "player-1"
raw.location
```

This is the cleanest way to cross the host boundary without making the whole host object graph globally visible.

---

## 9. Rehydrating typed values with `as-slip`

Sometimes host or database data is plain dict/list/value data, but you want it to become a real SLIP object that participates in prototype dispatch.

That is what `as-slip` is for.

### Why `as-slip` exists

- storage systems often handle JSON-like data well
- plain dicts do not participate in scope/prototype dispatch
- explicit rehydration is safer than automatic magic at every boundary

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

### Rehydrate it explicitly

```slip
obj: as-slip (host-data "player-1")
```

Current behavior:

- plain dicts and lists stay plain
- `__slip__`-marked values are rehydrated recursively
- `type: "scope"` creates a real `scope`
- if `prototype` is present, it is resolved by name
- unknown prototypes raise an error

### Dispatch example

```slip
Character: scope #{}

describe: fn {x: Character} [ "typed" ]
describe: fn {x} [ "fallback" ]

obj: host-object "player-1"
describe obj
```

This is the intended pattern when host/db data needs real SLIP type behavior. Use `as-slip` directly when the data comes from some other boundary, such as raw file, HTTP, or manually assembled dict/list values.

---

## 10. Loading code from files and filling it in

One of the most powerful advanced workflows is:

1. load a `.slip` file as code
2. provide caller values
3. expand it with `inject` and `splice`
4. run it with `run` or `run-with`

That gives you configurable code templates without inventing a separate macro system.

Typical pattern:

```slip
module-x: 5
args: #[3, 4]
extra-stmts: [ y: 10; z: y * 2 ]

code: file://./mod.slip
run code
```

Use this when code must be assembled from reusable pieces at runtime. For static composition, normal modules are easier.

---

## 11. When to use these features

Reach for advanced features when:

- the code to run is only known at runtime
- you need a controlled target scope
- you are embedding SLIP in a host application
- you want persisted data to come back as typed SLIP objects
- you need background work that should not block the host

Avoid them when:

- a normal function call is enough
- a closure is enough
- ordinary modules and scopes already express the design clearly

Advanced features are for leverage, not for everyday ceremony.
