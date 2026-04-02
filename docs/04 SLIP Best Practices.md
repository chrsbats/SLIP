# SLIP Best Practices

This guide is optional reading after `docs/03 SLIP Advanced.md`.

It is not about learning what the language can do. It is about writing SLIP that stays clear, maintainable, and easy to mod.

Use it when:

- you already know the language features
- you are starting to structure real mechanics or content
- you want code that other people can read and extend safely

This guide complements, but does not replace:

- `docs/Appendix B - SLIP Style Guide.md` for formatting and naming
- `docs/Appendix C - Design Philosophy.md` for rationale

## Keep The Common Path Simple

Prefer ordinary Part 1 and Part 2 style code when it is enough.

- plain functions before metaprogramming
- plain data before clever object structure
- direct path updates before elaborate helper layers

If a feature is powerful but makes the code harder to read on first pass, use it only when it earns its keep.

Good:

```slip
apply-damage: fn {state, target-id, amount} [
  state.hp[target-id]: state.hp[target-id] - amount
  response ok state.hp[target-id]
]
```

Only reach for the advanced machinery once the simpler form starts to fight the problem.

## Prefer Local Rebinding

Shadow, don't patch.

- adapt imported behavior locally
- use wrapper scopes when needed
- avoid changing shared definitions at a distance

This keeps changes local and makes mods safer.

```slip
combat: import `file://combat.slip`

better-combat: scope #{}
run-with [
  apply-damage: fn {state, target-id, amount} [
    combat.apply-damage state target-id (amount + 1)
  ]
] better-combat
```

## Use Resolvers For Authority

Use resolvers when one place should own the truth for a domain.

Good candidates:

- combat state
- spatial state
- inventory ledgers
- reputation or faction state

If many different scripts need to touch the same important state, a resolver is usually clearer than open mutation everywhere.

Use plain dict/list mutation for temporary or local data. Use resolvers when the state has real ownership rules.

## Use Dispatch For Rules, Not Cleverness

Dispatch is great for rules that naturally break into separate cases.

Examples:

- different behavior by prototype
- different damage kinds
- guarded rule variants

Avoid turning dispatch into a puzzle. If a simple `if` is clearer, keep the simple `if`.

Good use:

```slip
apply-damage: fn {this: Combat, target-id, amount, kind |where kind = 'fire'} [
  this.hp[target-id]: this.hp[target-id] - (amount * 2)
  response ok none
]
```

Bad use is when the reader has to reverse-engineer which of ten overlapping methods will run before they can understand the rule.

## Use `ref` And `cell` For Observation

When you want to observe world state without owning it:

- use `ref` to point at it
- use `cell` to derive from it

This keeps read-side logic separate from commit-side logic.

```slip
p1-hp: ref Combat::hp["p1"]
p1-wounded?: cell {hp: p1-hp} [ hp < 50 ]
```

## Keep Host Boundaries Explicit

Use the host boundary tools intentionally:

- `host-object` for live dispatchable objects
- `host-data` for raw persisted data
- `as-slip` for explicit rehydration outside that host boundary

Do not rely on hidden magical conversion of plain data into runtime objects.

## Prefer `host-object` For Live Entities

If your game logic wants to treat something like an entity, NPC, room, or item, prefer `host-object` so the value already participates in normal SLIP behavior.

Use `host-data` when you are manipulating persistence-shaped data directly.

That rule keeps gameplay code straightforward:

- entities and rooms should usually arrive as `host-object`
- raw persistence plumbing should stay at the boundary

## Keep Infrastructure In Python

SLIP is a strong fit for:

- game rules
- combat logic
- item/spell/skill behavior
- world scripting
- moddable content logic

Python is usually a better fit for:

- networking
- process lifecycle
- database adapters
- deployment/runtime infrastructure
- admin and ops tooling

That split keeps SLIP focused on mechanics and rules.

For a MUD, this usually means:

- Python owns networking, sessions, persistence, process lifecycle
- SLIP owns combat, skills, items, AI rules, quests, and moddable world behavior

## Use Metaprogramming Sparingly

SLIP makes metaprogramming available without a separate macro language.

That is a strength, but it does not mean every problem should be solved that way.

Prefer this order:

1. plain function
2. closure
3. scope/prototype composition
4. only then `run`, `call`, `inject`, `splice`

The language gives you these tools so you can solve the hard cases without inventing a second macro language. It does not mean every mechanic should be written that way.

## Write Modding Code For First-Read Clarity

If a modder or designer sees the code for the first time, they should be able to understand the rule without tracing hidden machinery.

Good modding code should:

- read like a rule
- keep host plumbing out of sight
- avoid unnecessary metaprogramming
- use explicit names
- use examples and tests for behavior

Succinctness is power, but only when the result is still readable.

## Final Rule

If you are choosing between two working SLIP designs, prefer the one that a modder can understand on first reading.
