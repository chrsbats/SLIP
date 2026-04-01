# Appendix A - StdLib Reference

This appendix is a practical reference for the current SLIP standard library surface.

It is not a tutorial. For a guided introduction, start with:

- `docs/01 SLIP Scripting.md`
- `docs/02 SLIP Programs.md`

Source of truth for this appendix:

- `slip/root.slip`
- `slip/slip_runtime.py`
- focused tests, especially `tests/test_chapter_014.py`

## Reading This Reference

- Call shapes are shown in normal SLIP syntax, not formal grammar.
- Many functions are generic and have multiple methods.
- Infix operators like `+` and `>` are aliases for piped core functions.
- Some names are implemented in `root.slip`, others are host primitives. Both are part of the user-facing stdlib.

## Status Aliases And Operators

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

### Standard statuses

- `ok`
- `err`
- `not-found`
- `invalid`

These are path literals used in `response` values and status checks.

Example:

```slip
response ok 123
```

## Core Introspection And Conversion

### `type-of value`

- Returns the SLIP type as a path literal.
- Common results include `` `int` ``, `` `float` ``, `` `string` ``, `` `i-string` ``, `` `list` ``, `` `dict` ``, `` `scope` ``, `` `function` ``, `` `path` ``, `` `none` ``.

Example:

```slip
type-of #[1, 2, 3]
```

### `status value`

- If `value` is a `response`, returns its status.
- Otherwise returns `ok`.

Example:

```slip
#[ status 1, status (response err "bad") ]
```

### `to-str value`

- Converts a value to a string.
- Byte streams are decoded as UTF-8.

Example:

```slip
to-str u8#[65, 66, 67]
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
- Does not mutate program values.

Example:

```slip
emit "debug" "starting"
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

### `return value?`

- Exits the current function early.
- Also works at top level.

### `response status value`

- Creates a `response` value.

### `respond status value`

- Exits the current function with a `response`.

### `do code`

- Runs a code block and captures both effects and outcome.
- Returns a log-like structure with:
  - `.outcome`
  - `.effects`

Behavior:

- normal return -> `response ok value`
- thrown error -> `response err message`
- existing `response` is preserved

### `run code`

- Executes a code block in the current lexical context.

### `run-with code target-scope`

- Executes code in the provided scope.
- Useful for configuration and controlled evaluation.

### `current-scope`

- Returns the current lexical scope.

### `get-body function sig`

- Returns the code body for the implementation matching `sig`.
- Useful for advanced reflection and tooling.

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
p: create Player |with [ hp: 150 ]
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
- Returns `response ok normalized-data` or `response err errors`.

## Testing Helpers

### `|example { ... -> ... }`

- Attaches an example to a function implementation.

### `test function?`

- Runs examples for one function.
- Returns a `response`.

### `test-all scope?`

- Runs examples across the current scope or a provided scope.
- Returns a `response` containing a summary.

## Resources, Imports, And External I/O

### `import locator`

- Loads a module from a `file://`, `http://`, or code source.
- Returns a fresh shadow scope over the module exports.

### `host-object id`

- Loads a host-managed object by id.
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

- `http://...` and `https://...`
  - Direct GET by default.
  - Non-2xx responses raise errors unless you request an alternate response mode.

- `http://...<- value`
  - Direct POST form.

### Response modes

- Default mode, or explicit:

```slip
#(response-mode: `none`)
```

  - Return the body directly.
  - Non-2xx errors raise.

- Lite mode:

```slip
#(response-mode: `lite`)
```

  - Return `#[status, value]`.

- Full mode:

```slip
#(response-mode: `full`)
```

  - Return `#{ status: ..., value: ..., meta: #{ headers: ... } }`.

- Legacy flags `#(lite: true)` and `#(full: true)` are still accepted.

## Tasks And Time

### `task [code]`

- Launches a background task.
- Use this for background work, polling, maintenance jobs, and cron-like behavior.

### `sleep seconds`

- Async sleep helper.

### `time`

- Returns the current time.

### `random`
### `random-int a b`

- Random number helpers.

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
if [probe.outcome.status = err] [
  print probe.outcome.value
]
```

### Configure an object fluently

```slip
p: create Player |with [ hp: 150 ]
```

### Data-first collection piping

```slip
#[1, 2, 3] |map (fn {x} [ x + 1 ])
```
