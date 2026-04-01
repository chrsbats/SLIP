---
name: slip
description: Write idiomatic SLIP code for this repository using current runtime semantics, local rebinding, task-based background work, and explicit as-slip rehydration.
---

# SKILL.md

This file teaches an LLM how to write good SLIP for this repository.

It is not a full language reference. It is a compact authoring guide.

Read these first if you need more detail:

- `docs/01 SLIP Scripting.md`
- `docs/02 SLIP Programs.md`
- `docs/03 SLIP Advanced.md`
- `docs/Appendix A - StdLib Reference.md`
- `docs/Appendix B - SLIP Style Guide.md`

## 1. What SLIP optimizes for

SLIP is designed for:

- direct, readable scripting
- left-to-right evaluation
- path-based access and updates
- local rebinding instead of mutation-at-a-distance
- simple function calls instead of many special forms
- host embedding and domain-specific scripting

When generating SLIP, optimize for:

- simple direct code
- locality
- explicit data flow
- small surface area

Do not generate clever code just because metaprogramming exists.

## 2. Core execution model

Important mental model:

- everything is an expression
- infix evaluation is left-to-right
- parentheses change order explicitly
- `[...]` is code data, not immediate execution
- `{...}` is a sig literal used for parameter declarations and other metadata-like binding patterns

Examples:

```slip
10 + 5 * 2
-- => 30

10 + (5 * 2)
-- => 20
```

## 3. Prefer normal calls first

Default to ordinary function calls and pipes.

```slip
add 10 20
10 |add 20
players |map [ ... ]
```

Do not reach for `call`, `run`, `inject`, or `splice` unless the target truly needs to be dynamic.

## 4. Paths are central

SLIP uses paths for:

- reading values
- writing values
- deleting values
- piping values into functions

Common forms:

- `x`
- `player.hp`
- `x:`
- `~x`
- `|map`

When you need to update data, prefer path updates over rebuilding whole structures manually.

## 5. Assignment and update patterns

Assignment is an expression.

- `x: 10` writes and returns `10`
- update patterns like `x: + 1` are idiomatic
- vectorized updates are preferred when changing matching fields in collections

Examples:

```slip
counter: 0
counter: + 1

players.hp[< 50]: * 1.1
```

When writing collection code, prefer SLIP's query/update forms over hand-written loops if the query is simple.

## 6. Queries and collection style

For reading:

- use filters with `[...]`
- use pluck with `.field`
- compose them directly

Examples:

```slip
players[.hp > 100]
players[.class = 'Warrior'].name
players.hp[< 50]
```

For writing:

```slip
players[.hp < 50].hp: * 1.1
players.hp[< 50]: * 1.1
```

Use the clearest form for the task. Do not introduce extra temporaries unless readability improves.

## 7. Function style

Use `fn {args} [body]`.

Preferred style:

- `kebab-case` for normal functions and values
- `PascalCase` for prototypes, schemas, and type-like names
- keep simple functions short
- use explicit `return` in longer multi-line bodies when it improves clarity

Examples:

```slip
add-ten: fn {n} [ n + 10 ]

apply-damage: fn {state, target-id, amount} [
    state.hp[target-id]: state.hp[target-id] - amount
    response ok state.hp[target-id]
]
```

## 8. Dispatch rules to follow

Current dispatch model:

- typed methods are considered before untyped methods
- untyped methods are fallback-only
- exact arity beats variadic
- guards refine ties within a tier
- last-defined wins among matching peers

Do not describe dispatch with old “complex scoring” language.

Good use cases for dispatch:

- behavior differs by prototype/type
- behavior differs by a small guarded condition set
- replacing brittle `if` ladders with separate methods

Example:

```slip
describe: fn {x: Character} [ "character" ]
describe: fn {x} [ "other" ]
```

## 9. Shadow, don't patch

This is a core design principle.

When adapting behavior:

- prefer local rebinding
- prefer wrapper scopes
- prefer composition over mutation of shared definitions

Especially with imports:

- treat imported modules as providers of definitions
- customize locally by shadowing names
- avoid action at a distance

Example:

```slip
math: import `file://math.slip`
add: fn {a, b} [ math.add a b + 1 ]
```

Do not generate code that relies on mutating shared imported definitions as the default technique.

## 10. Program structure patterns

Use these as the default building blocks:

- `scope` for objects/prototypes
- `create` for instances
- `inherit` for prototype linkage
- `with` for fluent configuration
- `resolver` for authority-rooted transactional writes
- `ref` and `cell` for derived/observed values

Example:

```slip
Character: scope #{ hp: 100 }
Player: scope #{} |inherit Character

p: create Player |with [ hp: 150 ]
```

## 11. Outcomes and effects

Use outcomes explicitly.

- `response status value`
- `respond status value`
- `do [ ... ]` to capture outcome and effects

Use `print` for standard output.
Use `emit` when you want structured side-effect topics.

Example:

```slip
probe: do [ risky-call ]
if [probe.outcome.status = err] [
    print probe.outcome.value
]
```

Do not model all errors as strings in ordinary values when a `response` is the clearer contract.

## 12. Host integration

Use host integration when the script needs to cross into Python-managed state or behavior.

Patterns:

- mapping-style host objects for path reads/writes
- top-level exposed host methods in `kebab-case`
- gateway functions like `host-object "id"` and `host-data "id"`

Prefer a narrow gateway over exposing a large host graph directly.

## 13. `as-slip` for typed rehydration

When host or database data is plain dict/list/scalar data but should become a typed SLIP object, use `as-slip`.

Current contract:

- looks for `__slip__`
- version 1 supports `scope`
- optional `prototype` is resolved by name
- unknown prototypes should error clearly

Example shape:

```json
{
  "__slip__": {
    "type": "scope",
    "prototype": "Character"
  },
  "hp": 77
}
```

Example usage:

```slip
obj: as-slip (host-data "player-1")
describe obj
```

Prefer `as-slip` over magical implicit promotion.

When the data comes from the host persistence boundary, prefer:

- `host-object` for live, dispatchable objects
- `host-data` for raw storage-shaped data

## 14. Background work

Use `task` for background work.

Good uses:

- maintenance jobs
- polling
- timers
- periodic checks
- host-managed background jobs

Example:

```slip
task [
    loop [
        sleep 60
        print "tick"
    ]
]
```

Do not use channels. They are being removed from the language surface.

## 15. Metaprogramming rules

Use metaprogramming only when normal functions, closures, scopes, or imports are not enough.

Use:

- `run` to execute code in an isolated lexical context
- `run-with` to execute code against a target scope
- `inject` to insert one value into code
- `splice` to insert many values or statements
- `call` for runtime-selected targets

Prefer the smallest powerful tool:

- closure before metaprogramming
- static call before `call`
- ordinary module composition before runtime code assembly

## 16. Style defaults

Follow the style guide.

Important defaults:

- 4-space indentation
- no space before `:` in assignments
- whitespace before `|`, none after it
- Egyptian-style multi-line blocks
- comments use `--`
- use sig literals for declarative binding arguments like `fn {args}`, `foreach {x}`, `for {i}`

## 17. Common mistakes LLMs make

Avoid these:

- assuming operator precedence exists
- overusing `run` or `call`
- explaining old dispatch semantics instead of the current simple contract
- mutating imported modules instead of shadowing locally
- using complex metaprogramming when closures or functions are enough
- forgetting that `[...]` is code, not an eager list literal
- forgetting that `#{...}` and `#[...]` are data constructors while `dict [...]` and `list [...]` are function forms
- treating plain dicts as typed scopes without `as-slip`
- reaching for channels instead of `task`

## 18. Good defaults checklist

When asked to write SLIP, prefer this order of thought:

1. Can this be a plain function?
2. Can this be a local scope/prototype design?
3. Can this be expressed as a path/query/update directly?
4. Can I solve this with local rebinding instead of patching shared state?
5. Do I really need dynamic code or runtime-selected paths?
6. If data came from a host/db, should it stay plain data or be explicitly rehydrated with `as-slip`?

If you follow those defaults, the generated SLIP will usually match the language well.
