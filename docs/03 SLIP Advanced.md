# SLIP Advanced

The public Python API uses synchronous, run-to-completion evaluation. A Runner
owns a separate async I/O worker; explicit submissions return pollable jobs. Use
ordinary `with`, `handle_script(...)` and `close()`. Local `task`/`sleep` suspension
and resolver transaction authority remain deferred.

## Background I/O jobs

`from slip import ScriptRunner` provides `submit` alongside synchronous script
execution. No separate runner or event-loop setup is needed.

Submit an HTTP locator or a native async host function and receive a standard
`concurrent.futures.Future`. Submission returns immediately; poll with `done()`
and collect with `result()` after completion. Errors are raised on collection.

<!-- slip-test: fragment -->
```python
job = runner.submit("https://example.test/data")

# On a later host tick:
if job.done():
    value = job.result()
```

For native async operations, pass the function and an argument sequence:

<!-- slip-test: fragment -->
```python
job = runner.submit(host.fetch, ["id:item-1"])
```

SLIP uses the same explicit submission boundary. Quote paths so submitting does
not first perform an ordinary resource read or call the host function:

<!-- slip-test: fragment -->
```slip
first: submit `https://example.test/first`
second: submit `https://example.test/second`
loaded: submit `fetch` #['id:item-1']

if [job-done first] [data: job-result first]
```

`job-result` fails immediately when pending; it never blocks a host tick. Python's
Future also provides `cancel()`. Assigning/passing job handles retains their identity.
For PUT/POST, use the corresponding path suffix and supply one payload argument;
for example, `submit 'https://example.test/items<-' #[data]`. GET/DELETE take none.
Attached path metadata is evaluated in the submitting caller's scope, once; request
encoding and metadata normalization happen before queueing. Submit locator paths
without queries and apply collection queries after collecting the response.

By default, each Runner starts one worker/event loop/client and reuses it, with at
most 32 active operations. Ordinary HTTP reads still return decoded values and wait at the
resource boundary; they share the owned session with background HTTP. File I/O and
all local SLIP evaluation remain synchronous. Use the runner's ordinary context
manager or call `close()` at host shutdown; it cancels pending jobs, waits for their
cleanup, closes the owned client and joins the thread. Borrowed synchronous
`http_client` instances retain their foreground behavior and caller ownership;
background HTTP with that injection fails explicitly rather than using a different
session. Native async functions are submitted explicitly, not called by evaluation.

### Disable background I/O

Background I/O is enabled by default. Use `background_io=False` for a Runner
without a background worker, thread or event loop:

```python
from slip import ScriptRunner


with ScriptRunner(background_io=False) as runner:
    result = runner.handle_script("10 + 20")
    assert result.status == "ok", result.error_message
    assert result.value == 30
```

Foreground HTTP uses an owned synchronous client in this mode; files, modules,
host calls and script execution work normally. Python and SLIP `submit` calls
report that background I/O is disabled. Closing the Runner closes its owned
client. An injected `http_client` remains caller-owned in either mode.

Worker jobs perform external I/O and must return data to the host for local state
changes. Calling back into the Runner's evaluator or blocking HTTP API from its
I/O worker fails clearly. Local SLIP Code jobs, `task` and `sleep` are deferred.
Future `slip://` calls to other processes can use this boundary; RPC is not yet
implemented. Executable API examples are in `tests/test_io_jobs.py`.

---

Parts 1 and 2 teach the fast path for scripting and program design. This guide covers the features you reach for when:

- an application needs overlapping external I/O
- SLIP is embedded inside a Python application
- host or database data needs to become a live SLIP object
- you want to build your own control-flow helpers
- you need to generate or run code dynamically

These features are powerful, but they are not the default path. Reach for them when the simpler tools stop being enough.

---

## Who schedules local work?

Python owns timers, maintenance scheduling and local state changes. SLIP loops run
to completion on the calling thread and do not yield. Use `submit` for native
external I/O, then apply the completed data during a later host call. Local SLIP
`task` and `sleep` currently raise unsupported-operation errors without executing
a task body; they do not start background mechanics.

---

## How do I integrate with Python?

SLIP is designed to be embedded in a Python application.

For many real uses, this is the main advanced feature: Python owns the engine, infrastructure, and persistence; SLIP owns game logic, rules, and moddable behavior.

The Python examples use the synchronous public package. The context manager owns
cleanup; long-lived applications can instead call `runner.close()` at shutdown.

### Run one script

Start with a `ScriptRunner` and inspect its result:

```python
from slip import ScriptRunner


with ScriptRunner() as runner:
    result = runner.handle_script("10 + 20")

if result.status == "ok":
    print(result.value)
else:
    print(result.error_message)
```

Every execution returns an `ExecutionResult`. Its main fields are `status`, `value`, `error`, `error_message`, and `side_effects`.

### Expose host objects as data

If a Python object implements `__getitem__`, `__setitem__`, and `__delitem__`, SLIP can use path access against it.

```python
from slip import ScriptRunner, SLIPHost, slip_api_method


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

    @slip_api_method
    def take_damage(self, amount: int):
        self._data["hp"] -= amount


host = CharacterHost()
with ScriptRunner(host_object=host) as runner:
    runner.root_scope["obj"] = host
    result = runner.handle_script("obj.hp: 80; take-damage 3; obj.hp")
```

From SLIP, that object looks like ordinary path-accessible data:

```slip
obj.hp: 80
obj.hp
```

### Expose host methods deliberately

Python methods marked with `@slip_api_method` are safe to expose to SLIP. The `take_damage` method in the complete class above is one example.

Methods decorated with `@slip_api_method` are exposed automatically under `kebab-case` names when the runner uses that host:

<!-- slip-test: fragment -->
```python
runner = ScriptRunner(host_object=host)
```

Then call them from SLIP like any other function:

```slip
take-damage 3
```

### Keep a long-lived runner

For embedded applications, a common pattern is to keep one `ScriptRunner` alive, preload functions into its environment, and then call into that environment repeatedly from Python.

```python
from slip import ScriptRunner


registry = {
    "id:p1": {"name": "Player"},
    "id:goblin-1": {"name": "Goblin"},
}
with ScriptRunner(host_data=registry.__getitem__) as runner:
    runner.handle_script("""
attack: fn {attacker, target} [
    print "attack!"
    return none
]
    """)

    result = runner.handle_script(
        "attack (host-object 'id:p1') (host-object 'id:goblin-1')"
    )
```

This pattern keeps loaded SLIP mechanics available while Python manages the surrounding application.

Known lexical callables, including exposed host methods, are captured when each
function definition executes. Keep a stable host gateway whose backing data can
change between calls; capturing the gateway does not snapshot its data. Rebinding
a callable name does not redirect functions already defined against it. Define a
new function or supply a callable parameter when behavior must change.

Parsed and persistently cached Code contains syntax, not another runner's callable
bindings. Each receiving runtime prepares its own function captures. Code bodies
remain inspectable and editable; defining a new function establishes a new capture
boundary. See [binding time](<01 SLIP Scripting.md#when-are-function-bindings-chosen>)
for the distinction between captured behavior, live operands, and quoted paths.

### Expose a public command API to Python

Public commands cross the persisted-object boundary introduced in full in the next section. At that boundary, `host-object id` loads a live dispatchable object, `host-data id` returns its raw stored shape, and `as-slip` explicitly rehydrates data from other sources. `|command` automates the `host-object` path for prototype-typed parameters.

When a host needs a schema for player-facing commands, keep the mechanics typed and adapt them at the boundary:

```slip
take-method: fn {actor: Persona, object: Item, original-text} [
  object.owner: actor
  object
]

take: command take-method |public
```

`|command` projects entity parameters to the `` `id` `` refinement and hydrates them through `host-object`. `|public` marks the resulting function for host discovery.

The adapter prepares its projected signatures and hydration closures once in the
original definition environment. Invocations use ordinary calls with live host
data, retaining that environment's prototypes and the caller's effects.

Put those public adapters in a small command API module instead of exposing every imported definition:

```slip
-- command-api.slip
movement: import `file://movement.slip`
combat: import `file://combat.slip`

take: command movement.take |public
put: command movement.put |public
attack: command combat.attack |public
```

Only names marked with `|public` become host-visible. Internal helpers stay inside their modules. An `` `id` `` is a string beginning with `id:` and is more specific than `` `string` `` during dispatch. Overloaded methods remain overloaded at the command boundary, and the original generic still performs typed dispatch and evaluates its `|where` guards after hydration.

### Generate the command schema

Import the module from Python and generate JSON Schema for the host-facing command format:

<!-- slip-test: setup=command-module -->
```python
from slip import ScriptRunner


with ScriptRunner() as runner:
    commands = runner.import_public_module("file://command-api.slip")
    schema = commands.json_schema(
        host_parameters={"actor", "original-text"},
    )
```

The schema describes one nested public call. By default, every JSON-compatible function parameter appears in the schema. Use `commands.commands_schema()` when you want an ordered list for compound input.

<!-- slip-test: setup=command-session -->
```python
payload = {
    "function": "take",
    "arguments": {
        "object": "id:item.apple.1",
    },
}

commands.validate_json_command(
    payload,
    host_parameters={"actor", "original-text"},
)
result = commands.run_json_command(
    payload,
    host_arguments={
        "actor": session.actor_id,
        "original-text": "take the apple",
    },
)
```

`run_json_command` accepts decoded JSON or a JSON string. It validates against the generated schema, converts JSON containers into SLIP runtime values, and invokes the marked function directly. It does not generate SLIP source code.

Trusted shortcut and UI adapters may start with one literal SLIP call instead.
`json_command_from_source` parses that call without executing it and returns the
same JSON envelope:

<!-- slip-test: setup=command-session -->
```python
payload = commands.json_command_from_source(
    "take 'id:item.apple.1'",
    host_parameters={"actor", "original-text"},
)
```

The source must contain exactly one public function call with literal arguments.
Variables, paths, blocks, multiple expressions, and private functions are
rejected. Refined `id:` values participate in overload selection, so an ID and
an ordinary string can select different public forms.

Some parameters come from trusted host context rather than JSON. The host chooses those names when generating the schema and supplies their values during execution. Host parameters are omitted from the generated schema. A `|command` adapter applies the same signature-driven hydration to IDs supplied by the host and IDs supplied by JSON.

### Keep entity IDs unchanged

The `id:` prefix is part of the canonical entity ID, not a boundary encoding. JSON, host arguments, entity `.id` fields, and registry keys use the same complete value. `|command` passes that value unchanged to `host-object`, which performs an exact lookup. Ordinary strings and lifecycle identifiers such as ULIDs are unaffected.

### Expose command execution to SLIP

A domain host can expose that utility back to SLIP as `run-json-command`. For example, a game host may treat the current actor as trusted context:

<!-- slip-test: fragment -->
```python
from slip import SLIPHost, slip_api_method


class WorldHost(SLIPHost):
    ...

    @slip_api_method
    def run_json_command(self, actor, command_json):
        result = self.commands.run_json_command(
            command_json,
            host_arguments={
                "actor": actor["id"],
                "original-text": command_json,
            },
        )
        if result.status == "err":
            raise RuntimeError(result.error_message)
        return result.slip_result
```

Then SLIP can use the host bridge normally:

```slip
actor |run-json-command command-json
```

If a public function has multiple JSON-compatible call shapes, its arguments schema uses `anyOf`. Methods that differ only by `|where` collapse to the same public shape; guards remain runtime dispatch details and are not exposed in the schema.

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
person: host-object 'id:player-1'
target: host-object 'id:goblin-1'

attack person target
```

Game logic now receives live typed objects that participate in normal dispatch.

### Use `host-data` for raw stored values

```slip
raw: host-data 'id:player-1'
raw.location
```

Use this form to inspect or manipulate the stored shape directly.

### Use `as-slip` outside the host boundary

Sometimes data comes from somewhere other than `host-object`, but you still want it to become a real SLIP object that participates in prototype dispatch.

That is what `as-slip` is for.

```slip
obj: as-slip (host-data 'id:player-1')
```

Rehydration follows these rules:

- plain dicts and lists stay plain
- `__slip__`-marked values are rehydrated recursively
- `type: "scope"` creates a real `scope`
- if `prototype` is present, it is resolved by name
- unknown prototype names create a generated prototype that is reused by the runner
- an existing non-scope binding with the prototype name raises an error

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

obj: host-object 'id:player-1'
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

#[ is-code c, run c ]
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

`run` follows these rules:

- `run` returns the final value
- writes inside `run` do not leak into the caller's scope

```slip
res: run [
  x: 1
  x + 2
]

probe: do [ x ]
#[ res, probe.status = err ]
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

A function's current scope has `meta.parent` pointing to its definition scope and
`meta.caller` pointing to the scope from which it was invoked. Library control
helpers use the caller link to execute supplied blocks against caller-local
bindings; ordinary function lookup remains lexical.

Binding forms such as `foreach` and `for` declare the zero-based argument that
introduces names in their callable metadata (`.meta.binds`). This lets preparation
retain definition-time callable captures while observing nearer loop bindings,
including runtime Sig values. Raw loop blocks are prepared once with those names;
iterations reuse the prepared code rather than rebinding it.

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
- invoke a target resolved from a runtime path or string
- perform dynamic assignment or deletion

Omitting the argument list means a zero-argument call. `call` always invokes;
use `to-path` when constructing path data.

```slip
call add #[1, 2]
```

```slip
p: to-path 'a.b'
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

Its argument follows the ordinary value rule: `(inject add)` inserts the function,
while `(inject (add 1 2))` inserts the result. Group nested expressions explicitly.

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

Put the reusable template in `mod.slip`:

```slip
x: (inject module-x)
(splice extra-stmts)
result: add (splice args)
x + result + z
```

Then load and expand it from the caller:

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
