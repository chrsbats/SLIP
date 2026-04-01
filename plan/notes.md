# Notes

## Resolver model: locality, authority boundaries, and vectorized updates

Book 1 does not teach the resolver/authority model. This section states the language
contract that enables a resolver architecture where committed mutation is centralized.

### Local values and mutation

Within a local scope, scripts may freely mutate *values* (dict/list/table) using structural
navigation:

- Structural segments: `.` and `[]`
- Value mutation is allowed:
  - `player.hp: 100`
  - `players[.hp < 50].hp: * 1.1`

This supports data-oriented scripting, initialization, and bulk reshaping.

### Authority boundaries and the `::` operator

`::` is an explicit authority boundary hop into an authoritative namespace (e.g. a resolver).

- Reads across `::` are allowed:
  - `scene::position[agent-id]`
- Writes must never cross `::`.

Any write path (SetPath, DelPath, PostPath, etc.) that contains `::` is illegal:

- `scene::position[agent-id]: next` is a Syntax/Runtime error
- `~scene::position[agent-id]` is a Syntax/Runtime error

This prevents direct mutation of authoritative state through boundary hops.

### Resolver transactions and `this`

Resolvers commit state changes only through transactions: functions whose first parameter
is `this: ResolverType`.

Committed writes are permitted only inside such a transaction, and only when the write
target path is *syntactically rooted at `this`*:

- legal:   `this.position[agent-id]: next`
- illegal: `pos: this.position ; pos[agent-id]: next`  (not rooted at `this`)
- illegal: any write target containing `::`

This makes the resolver the single owner of its namespace: other code can read resolver
state via `::`, and can request changes only by calling resolver transactions.
