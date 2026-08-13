# Appendix A - StdLib Reference

This appendix is a practical reference for the current SLIP standard library surface.

It is not a tutorial. For a guided introduction, start with:

- [SLIP Scripting](<01 SLIP Scripting.md>)
- [SLIP Programs](<02 SLIP Programs.md>)

## Reading This Reference

- Call shapes are shown in normal SLIP syntax, not formal grammar.
- Many functions are generic and have multiple methods.
- Infix operators like `+` and `>` are aliases for piped core functions.
- Some names are implemented in `root.slip`, others are host primitives. Both are part of the user-facing stdlib.

### Categories

- [Statuses and operators](#outcome-statuses-and-operators)
- [Introspection and conversion](#core-introspection-and-conversion)
- [Output and effects](#output-and-effects)
- [Predicates and types](#predicates-and-type-helpers)
- [Strings and paths](#strings-and-paths)
- [Collections](#collections-and-sequence-helpers)
- [Control flow](#control-flow-helpers)
- [Functions and code](#functions-and-code)
- [Objects, scopes, and resolvers](#object-scope-and-resolver-helpers)
- [Schemas and validation](#schemas-and-validation)
- [Host command APIs](#host-command-apis)
- [Testing](#testing-helpers)
- [Resources and I/O](#resources-imports-and-external-io)
- [Tasks and time](#tasks-and-time)
- [Byte streams](#byte-stream-literals)
- [Common patterns](#frequently-used-patterns)

## Outcome Statuses And Operators

### Operators

- `+`, `-`, `*`, `/`, `**`
  - Arithmetic aliases for the core numeric operations.
  - Example: `10 + 5`

- `=`, `!=`, `>`, `>=`, `<`, `<=`
  - Comparison aliases.
  - Example: `hp > 0`

- `and`, `or`
  - Logical operators.
  - These short-circuit.
  - Example: `ready and has-target`

- `not`
  - Boolean negation.
  - Example: `not done`

### Outcome statuses

- `ok`
- `err`

These path literals appear in `Outcome.status`.

### Common failure codes

- `not-found`
- `invalid`

Failure codes are ordinary path literals. Applications can define codes that fit their own domain.

Example:

```slip
if [result.status = ok] [ result.value ]
```

## Core Introspection And Conversion

### `type-of value`

- Returns the SLIP type as a path literal.
- Common results include `` `int` ``, `` `float` ``, `` `string` ``, `` `i-string` ``, `` `list` ``, `` `dict` ``, `` `scope` ``, `` `function` ``, `` `path` ``, `` `none` ``.
- Because the result is a path literal, type guards should compare with backticked literals such as `` `string` ``, not quoted strings.
- Raw single-quoted strings have type `` `string` ``; double-quoted interpolated strings have type `` `i-string` ``.

Example:

```slip
#[
  type-of #[1, 2, 3],
  (type-of 'item-1') = `string`,
  (type-of "item-1") = `i-string`
]
```

### `to-str value`

- Converts a value to a string.
- Byte streams are decoded as UTF-8.

Example:

```slip
to-str u8#[65, 66, 67]
```

### `to format data`

- Serializes `data` to a text format.
- Current built-in formats: `` `json` ``, `` `yaml` ``, `` `toml` ``.
- `format` may be a path literal or a string.

Example:

```slip
to `json` #{ name: "Karl", hp: 120 }
```

### `from format text`

- Parses `text` into SLIP data.
- Current built-in formats: `` `json` ``, `` `yaml` ``, `` `toml` ``.
- `format` may be a path literal or a string.

Example:

```slip
from `json` '{"name": "Karl", "hp": 120}'
```

### `to-path value`

- Converts a raw string, interpolated string, or get-path literal to a path literal.
- URL-like and special path strings remain a single path segment; ordinary dotted or slash-separated strings become segmented paths.

Example:

```slip
#[
  to-path 'player.hp',
  to-path "Combat::hp",
  to-path `items[0]`
]
```

### `call func args`

- Calls `func` with a list of arguments.
- Useful when arguments are already assembled as a list.

Example:

```slip
call add #[1, 2]
```

### `as-slip value`

- Explicitly rehydrates serialized SLIP values from plain data.
- Plain dict/list/scalar data stays plain.
- Values marked with `__slip__` are converted into live SLIP runtime values.
- Version 1 supports `scope` rehydration.
- Use this for explicit boundary conversion outside the host-object gateway.

Example:

```slip
obj: as-slip #{
  "__slip__": #{ type: "scope", prototype: "Character" },
  hp: 10
}
```

## Output And Effects

### `emit topics message...`

- Appends a side-effect event to the script log.
- `topics` may be a string or a list of topics.
- Topic lists are flat tags, not hierarchy. A common convention is `"self"` and `"others"` for audience targeting.
- A single structured message, such as a dict or list, is preserved as native data in the event `message`.
- Does not mutate program values.
- If called as `emit topics format data`, the payload is serialized first using `to`-style formatting rules for supported formats such as `` `json` ``, `` `yaml` ``, and `` `toml` ``.

Example:

```slip
emit "debug" "starting"
emit #["self", "others"] #{ msg_id: 'move.resolved', sentence: 'You move it.' }
emit "stdout" `json` #{ hp: 120, mana: 30 }
```

### `print msg`

- Convenience wrapper for `emit "stdout" msg`.

### `stderr msg`

- Convenience wrapper for `emit "stderr" msg`.

## Predicates And Type Helpers

### Predicates from `root.slip`

- `is-number? x`
- `is-string? x`
- `is-list? x`
- `is-dict? x`
- `is-scope? x`
- `is-path? x`
- `is-fn? x`
- `is-code? x`
- `is-boolean? x`
- `is-none? x`

These return booleans based on `type-of`.

Example:

```slip
#[ is-list? #[], is-path? `a.b`, is-code? [1] ]
```

### Type unions used in stdlib signatures

- `ordered`
  - `{ code or list or dict or scope }`

- `mapping`
  - `{ dict or scope }`

- `number`
  - `{ int or float }`

These are used by stdlib methods such as `replace`, `map`, and `filter`.

## Strings And Paths

### `join xs sep`

- If `xs` is a list of strings, joins them with `sep`.

Example:

```slip
join #['a', 'b', 'c'] ', '
```

### `join first-path rest...`

- Path variant.
- Concatenates path values into one path.

Example:

```slip
join `a` `b.c`
```

### `split string sep`

- Splits a string into a list.

Example:

```slip
split 'a,b,c' ','
```

### `replace s old new`

- String replacement.

Example:

```slip
replace 'foo bar foo' 'foo' 'baz'
```

### `replace src old new`

- Ordered-sequence variant.
- Returns a modified copy with items equal to `old[0]` replaced by `new[0]`.

### `find haystack needle start?`

- Finds a substring starting at an optional offset.

### `indent string prefix`

- Prefixes each line with `prefix`.

### `dedent string`

- Removes common leading indentation.

## Collections And Sequence Helpers

### `len collection`

- Returns the length of a list, dict, scope, code block, string, or similar collection.

### `range end`
### `range start end`
### `range start end step`

- Returns a list of integers.
- Mirrors Python-style half-open ranges.

Example:

```slip
#[ range 3, range 1 4, range 1 5 2 ]
```

### `sort data`

- Returns a sorted list.

### `reverse ordered`

- Returns a reversed copy of an ordered collection.

### `map func data-list`
### `map data-list func`

- Applies `func` to each item and returns a new list.
- Supports both function-first and data-first forms.

Example:

```slip
#[1, 2, 3] |map (fn {x} [ x + 1 ])
```

### `filter predicate data-list`
### `filter data-list predicate`

- Returns a new list of items for which `predicate` is truthy.

### `reduce reducer accumulator data-list`

- Folds a sequence into one value.

### `zip list-a list-b`

- Returns a list of pairs up to the shorter input length.

### `keys mapping`

- Returns the keys of a dict or scope as a list.

### `values mapping`

- Returns the values of a dict or scope as a list.

### `items mapping`

- Returns key/value pairs.

### `has-key? mapping key`

- Returns true if the key exists.
- Works for dicts and scopes.

### `update target patch`

- Shallow-updates a dict or scope from another mapping.
- Mutates and returns `target`.

Example:

```slip
target: #{ hp: 100 }
update target #{ hp: 80, mana: 20 }
```

### `copy value`

- Shallow copy.

### `clone value`

- Deep copy.

Example:

```slip
orig: #{ nested: #[1, #{ z: 9 }] }
shallow: copy orig
deep: clone orig
```

## Control Flow Helpers

### `if [condition] [then] [else?]`

- Evaluates the condition block.
- Runs the then block if truthy, else the else block.
- Returns `none` when falsey and no else block is provided.

### `when [condition] [then]`

- Shorthand for one-branch conditionals.
- Returns `none` when the condition is falsey.

### `while [condition] [body]`

- Repeats while the condition block is truthy.
- Returns the last body value, or `none` if it never runs.

### `foreach {vars} data [body]`

- Iterates lists, dicts, and scopes.
- `{x}` over dict/scope yields keys.
- `{k, v}` yields key/value pairs.

### `for {i} start end [body]`

- Counted loop.
- End-exclusive.
- Counts up or down automatically.
- Binds the loop variable in the current scope.
- Returns `none`.

Example:

```slip
for {i} 1 4 [ print i ]
```

### `loop [body]`

- Infinite loop helper.
- Equivalent to `while [true] [body]`.

### `cond clauses`

- Multi-branch conditional.
- `clauses` is a list of pairs: `#[ #[ [condition], result ], ... ]`
- Runs the first truthy condition.
- If `result` is a code block, it is run.
- If nothing matches, returns `none`.

## Functions And Code

### `fn {sig} [body]`

- Constructs a function.
- Functions are generic containers: multiple definitions with the same name add implementations.

### `partial function args...`

- Returns a function with `args` pre-supplied.
- Arguments passed to the returned function follow the pre-supplied arguments.

### `compose functions...`

- Returns a function that applies `functions` from right to left.
- `compose f g h` produces a function equivalent to `f(g(h(value)))`.

### `return value?`

- Exits the current function early.
- Also works at top level.
- Accepts zero or one value. If the returned value is a call, comparison, or logical expression, wrap it in parentheses so it is passed as one value.

Examples:

```slip
sum: fn {} [ return (add 1 2) ]
is-storm?: fn {weather} [ return (weather = `storm`) ]
is-day?: fn {nighttime?} [ return (not nighttime?) ]

#[sum, is-storm? `storm`, is-day? false]
-- => #[3, true, true]
```

### `fail data`
### `fail code data`

- Signals a structured domain failure.
- With one argument, the code defaults to `error`.
- With two arguments, `code` is a path or string and `data` may be any value.
- A mapping without its own `message` uses the code as the error message.

Example:

```slip
fail `not-found` #{ item-id: "item-1" }
```

### `do code`

- Runs a code block and captures both effects and outcome.
- Returns an `Outcome` directly with `.status`, `.value`, `.error`, and `.effects`.

Behavior:

- normal completion sets `.status` to `ok` and `.value` to the block's ordinary value
- `fail` and runtime errors set `.status` to `err` and provide structured `.error` details
- `.effects` contains effects emitted while the block ran
- `return` passes through `do` and exits the surrounding function

### `run code`

- Executes code in a fresh sandbox that can see the root language environment.
- Caller values must be supplied with `inject` or `splice`.
- Writes do not leak into the caller. Use `run-with` to target a specific scope.

### `run-with code target-scope`

- Executes code in the provided scope.
- Useful for configuration and controlled evaluation.

### `current-scope`

- Returns the current lexical scope.

### `get-body function sig`

- Returns the code body for the implementation matching `sig`.
- Useful for advanced reflection and tooling.

### `get-sig function`

- Returns a detached copy of the function's `Sig`.
- The callable must have exactly one method.
- The returned Sig is dict-accessible. Its ordered `.parameters` are the canonical parameter representation, with `name` and, for typed parameters, `type`.
- Changing `parameter.type` changes that detached signature without changing the source function.
- `.positional`, `.keywords`, and `.param-order` are derived compatibility views.

### `sig value`

- Validates and copies an existing `Sig`.
- Also constructs a Sig from a mapping with `parameters`, `rest`, `return-annotation`, and `where` fields.
- A grouped call can provide a computed signature to `fn`.

Example:

```slip
description: get-sig source-method
description.parameters[0].type: `string`

adapter: fn (sig description) [
  -- The computed parameter names are bound in this call scope.
  current-scope
]
```

## Object, Scope, And Resolver Helpers

### `scope mapping`

- Creates a scope object.

### `resolver mapping`

- Creates a resolver scope.
- Resolvers are the authority roots for `this:` transactions.

### `inherit obj proto`

- Sets the parent prototype.
- The current contract allows inheritance to be set once.

### `create`
### `create prototype`
### `create prototype [config-block]`

- Canonical instance constructor.
- Returns a new scope, optionally inheriting from a prototype and applying a config block.

### `with obj [config]`
### `with obj mapping`

- Runs configuration in the context of `obj`, then returns `obj`.
- Useful for fluent object setup.

Example:

```slip
Player: scope #{}
p: create Player |with [ hp: 150 ]
p.hp
-- => 150
```

### `is-a? obj proto`

- Checks whether `obj` is the same as or inherits from `proto`.

### `ref path`

- Creates a read-only reference to a path.

### `cell {inputs} [body]`

- Creates a derived value from refs or other inputs.
- Used for reactive/derived reads.

## Schemas And Validation

### `Schema`

- Base prototype for schemas.

### `schema config`

- Constructs a schema scope.

### `is-schema? obj`

- True if `obj` is a schema.

### `default value`

- Marker for schema defaults.

### `optional type`

- Marker for optional schema fields.

### `validate data schema`

- Validates a mapping against a schema.
- Returns normalized data when valid.
- Signals an `invalid` failure with the errors as structured data when validation fails.

## Host Command APIs

### `|public`

- Marks a function or generic function as part of a host-visible public command API.
- Intended for command API modules that re-export only player-facing operations.
- Returns a marked callable value without mutating the imported function, so it works with the normal shadowing style.

Example:

```slip
movement: import `file://movement.slip`

take: movement.take |public
put: movement.put |public
```

### `|command`

- Adapts every method of a function to an entity-ID host command boundary.
- Prototype-typed parameters become `` `id` `` parameters in projected signatures.
- `` `id` `` matches strings beginning with `id:` and is more specific than `` `string` ``.
- Calls `host-object` with each complete ID unchanged before invoking the original generic function.
- The original generic performs typed dispatch and evaluates its `|where` guards after hydration.
- Is implemented in SLIP using `get-sig`, `sig`, closures, and `current-scope`.
- Use `|public` separately to expose the adapter to a host.

```slip
take: take-method |command |public
```

## Testing Helpers

### `|example { ... -> ... }`

- Attaches an example to a function implementation.

### `test function?`

- Runs examples for one function.
- Returns the number of passing examples.
- Signals a structured `test-failed` failure when an example fails.

### `test-all scope?`

- Runs examples across the current scope or a provided scope.
- Returns a summary mapping when all examples pass.
- Signals `test-failed` with the summary as failure data when any function fails.

## Resources, Imports, And External I/O

### `import locator`

- Loads a module from a `file://`, `http://`, or code source.
- Returns a fresh shadow scope over the module exports.

### `host-object id`

- Loads a host-managed object by id.
- Entity IDs retain their canonical `id:` prefix and are looked up exactly as supplied.
- Auto-rehydrates `__slip__`-marked data into live SLIP objects.
- Use this when you want dispatchable runtime objects.

### `host-data id`

- Loads host-managed data by id.
- Returns the raw dict/list/value storage shape untouched.
- Use this when you want persistence-shaped data.

### `resource locator`

- Creates a reusable resource handle.
- Useful for fluent `get`/`put`/`post`/`del` workflows.

Example:

```slip
api: resource `http://example/items#(content-type: "application/json")`
get api
```

### `get target`
### `put target data`
### `post target data`
### `del target`

- Generic resource operations.
- Work with resource handles and compatible targets.

### Direct scheme paths

- `file://...`
  - Read files or directories.
  - Structured files such as `.json`, `.yaml`, `.yml`, and `.toml` are parsed automatically.
  - Writing serializes based on extension or explicit content type.
  - Reading a `.slip` file returns `code`, not the executed result.
  - A read may continue directly into bracket queries and field access, such as `file://players.json[0].name`.

- `http://...` and `https://...`
  - Direct GET by default.
  - A successful request returns the decoded body.
  - A non-2xx response signals a structured protocol failure.
  - A read may continue directly into bracket queries and field access.

- `http://...<- value`
  - Direct POST form.

### Full HTTP response mode

- The default is the decoded body on success or a structured protocol failure on non-2xx.
- Request full mode only when you need the HTTP response envelope:

```slip
http://api.example.com/data#(response-mode: `full`)
```

- Returns `#{ status: ..., value: ..., meta: #{ headers: ... } }`.
- Non-2xx responses are returned in the same full envelope for explicit handling.

## Tasks And Time

### `task [code]`

- Launches a background task.
- Use this for background work, polling, maintenance jobs, and cron-like behavior.

### `sleep seconds`

- Async sleep helper.

### `time`

- Returns the current time.

### `random`

- Returns a random float in the range `0 <= value < 1`.

### `random-int a b`

- Returns a random integer in the inclusive range `a` through `b`.

### `seed-random seed`

- Seeds the current runner's random number generator.
- The same seed reproduces the same sequence in the same runtime implementation.
- Each runner has isolated random state; imported modules share their runner's stream.
- Without an explicit seed, a runner starts nondeterministically.

```slip
seed-random 42
first: #[random, random-int 1 6]

seed-random 42
second: #[random, random-int 1 6]

first = second
-- => true
```

Do not depend on a particular numeric sequence across different SLIP runtime implementations unless a portable RNG algorithm is specified in the future.

## Byte-Stream Literals

SLIP supports typed binary constructors:

- `u8#[...]`, `u16#[...]`, `u32#[...]`, `u64#[...]`
- `i8#[...]`, `i16#[...]`, `i32#[...]`, `i64#[...]`
- `f32#[...]`, `f64#[...]`
- `b1#[...]`

Notes:

- integer and float streams use little-endian encoding for multi-byte values
- `b1#[...]` packs booleans/bits into bytes
- these values can be written directly to files or converted with `to-str`

Example:

```slip
u8#[65, 66, 67]
```

## Frequently Used Patterns

### Read, transform, write

```slip
data: file://input.json
names: data.players.name
file://out.json: #{ names: names }
```

### Safe capture with `do`

```slip
probe: do [ risky-call ]
if [probe.status = err] [
  print probe.error.message
]
```

### Configure an object fluently

```slip
Player: scope #{}
p: create Player |with [ hp: 150 ]
p.hp
-- => 150
```

### Data-first collection piping

```slip
#[1, 2, 3] |map (fn {x} [ x + 1 ])
```
