# SLIP Architect Guide: Programs and Code Structure

As your scripts grow, you will eventually run into the limits of a single file. This guide introduces tools for organizing code into multiple files, sharing behavior through prototypes, and centralizing authority with resolvers.

---

## 1. Multi-file scripting with `import`

**The Problem:** "My script is 500 lines long and it's getting hard to find the logic I need."

**The Solution:** Split your code into modules and use `import`.

When you `import` a module, SLIP gives you a **fresh shadow scope** over that module's exports.

That detail matters because it supports one of SLIP's core design ideas:

> **Shadow, don't patch.**
>
> If you want different behavior in a local context, rebind names in that local context. Do not rely on changing shared definitions at a distance.

In practice, this means:

- imported code is a source of definitions
- local customization stays local
- one import can be adapted without silently changing another import somewhere else

So when you want to customize imported behavior for testing or composition, the normal move is to **shadow** names in your local scope or in a wrapper scope.

```slip
math: import `file://math.slip`

-- Use it normally
result: math.add 10 20

-- Customize locally by shadowing (does not modify `math`)
add: fn {a, b} [ math.add a b + 1 ]

result2: add 10 20
```

### 1.1 Import forms

`import` accepts a **locator**, which tells SLIP where to find the module. You can provide this as:

- a **path literal** like `` `file://combat.slip` ``
- a **string** like `"file://combat.slip"` or `"https://..."`

```slip
combat: import `file://combat.slip`
spatial: import "file://spatial.slip"
```

Rule of thumb: use `file://...` to make imports relative to the current script or module directory.

Tips:

- Bind imported modules to `kebab-case` names. They are namespaces, not types.
- Avoid cyclic imports. A common pattern is: `main.slip` imports `world.slip`, and `world.slip` imports subsystem modules.
- Keep module locators static. Don't build them dynamically unless you are doing something explicitly advanced.

### 1.2 Customize locally

The point of shadowing is locality.

If you rebind a name in your current scope, that change applies in your current scope. It does not create hidden action at a distance.

This is true for ordinary local code too:

```slip
f: fn {x} [ 'global' ]

runner: fn {} [
  f: fn {x} [ 'local' ]
  f 10
]

#[ f 10, runner ]
-- => #['global', 'local']
```

The same idea makes imports composable:

```slip
math1: import `file://math.slip`
math2: import `file://math.slip`

math1.value: 100

#[ math1.value, math2.value ]
-- => #[100, 7]
```

Treat imported modules as providers of definitions. Adapt them by rebinding locally.

### 1.3 A minimal project layout

A simple way to organize a small program:

- `main.slip` - entry point
- `world.slip` - wires modules together (your public program API)
- `combat.slip` - combat rules (functions)
- `spatial.slip` - movement rules (functions)

### 1.4 Example: Wiring modules through a `world` module

This example uses plain dict/list state and mutates it in place.

**File: `combat.slip`**

```slip
apply-damage: fn {state, target-id, amount} [
  state.hp[target-id]: state.hp[target-id] - amount
  response ok state.hp[target-id]
]
```

**File: `world.slip`**

```slip
combat: import `file://combat.slip`

-- One place to re-export your program API
apply-damage: combat.apply-damage
```

**File: `main.slip`**

```slip
world: import `file://world.slip`

state: #{
  hp: #{ "p1": 120 }
}

-- Before:
-- state.hp["p1"] == 120

new-hp: world.apply-damage state "p1" 10

-- After:
-- new-hp == 110
-- state.hp["p1"] == 110
```

That is enough to build multi-file programs today.

### 1.5 Wrapper scope pattern

For larger programs, a wrapper scope is often the cleanest way to customize one dependency while keeping the rest unchanged.

```slip
math: import `file://math.slip`

better-math: scope #{}
run-with [
  add: fn {a, b} [ math.add a b + 1 ]
  mul: math.mul
] better-math

#[ better-math.add 2 3, better-math.mul 2 3 ]
```

This is still just structured shadowing: reuse most of the original module, but replace the names you want locally.

---

## 2. Prototypes: Share defaults and behavior

**The Problem:** “I’m creating many player objects, and I'm copying the same default HP and helper functions into every single one.”

**The Solution:** Use **named scopes** and `inherit` to create prototypes.

### 2.1 Define a prototype

```slip
Character: scope #{
  hp: 100
  stamina: 100
}
```

### 2.2 Create instances that inherit

```slip
Player: scope #{} |inherit Character

p: create Player
#[ p.hp, p.stamina, is-a? p Character ]
```

### 2.3 Add behavior with free functions

As your program grows, you’ll want behavior that works differently for different prototypes. In SLIP, the usual pattern is:

- define **free functions**
- let dispatch select the right implementation based on the receiver’s prototype

This keeps data (prototypes/scopes) and behavior (functions) loosely coupled.

#### Example: behavior for `Player`

```slip
-- Prototype
Character: scope #{
  hp: 100
  stamina: 100
}

Player: scope #{} |inherit Character

 -- Free function dispatching on the receiver type
heal: fn {p: Player, amount} [
  p.hp: p.hp + amount
  response ok p.hp
]

p: create Player
p |heal 10
```

You can define multiple implementations with the same name; dispatch chooses the best match:

```slip
heal: fn {c: Character, amount} [
  c.hp: c.hp + amount
  response ok c.hp
]

heal: fn {p: Player, amount} [
  -- players heal 2x
  p.hp: p.hp + (amount * 2)
  response ok p.hp
]

c: create Character
p: create Player

#[ (c |heal 10).value, (p |heal 10).value ]
```

### 2.4 Configure an instance fluently

A common pattern is to create and configure in one expression:

```slip
p: create Player [ hp: 150 ]
p.hp
```


---

## 3. Centralize state updates with a Resolver

**The Problem:** "I have modules for combat and health regeneration, but they both touch `player.hp` directly. If I want to add a 'max health' rule or a 'death' log, I have to find every single line of code in every file that modifies HP."

**The Solution:** Use a **resolver** to own the state and the rules for changing it.

In larger programs, you want one place to own the "truth" for a domain.

Here’s a small example of how this gets messy:

```slip
-- combat.slip
apply-damage: fn {state, target-id, amount} [
  if [state.hp[target-id] - amount < 0] [ amount: state.hp[target-id] ]  -- clamp
  state.hp[target-id]: state.hp[target-id] - amount
]
```

Later, another module might update HP differently:

```slip
-- regen.slip
apply-regen: fn {state, target-id, amount} [
  state.hp[target-id]: state.hp[target-id] + amount
]
```

Now the rules for HP (clamping, max HP, death rules, logging) are scattered across files.

### 3.1 Step 1: Put the state in one place

Create a resolver that owns one piece of state: HP by entity id.

```slip
Combat: resolver #{
  hp: #{
    "p1": 120,
    "p2": 45
  }
}
```

### 3.2 Step 2: write one transaction that changes that state

Write an `apply-*` function. In the resolver model, it takes `this` first.

Idiomatic SLIP style is to define transactions as **free functions** that dispatch on the resolver type (rather than attaching them to the resolver scope).

**Committed writes are legal only when the write target path is syntactically rooted at `this`.** You cannot commit through aliases (e.g. `pos: this.position; pos[id]: ...`), and you can never commit to a path containing `::`.

```slip
apply-damage: fn {this: Combat, target-id, amount} [
  next: this.hp[target-id] - amount
  if [next < 0] [ next: 0 ]
  this.hp[target-id]: next
  response ok next
]
```

### 3.3 Step 3: call the transaction

Preferred (idiomatic) call form:

```slip
Combat |apply-damage "p1" 10
```

Non-idiomatic but supported (property access + explicit receiver):

```slip
Combat.apply-damage: apply-damage
Combat |Combat.apply-damage "p1" 10
```

You now have exactly one place to change HP, and one place to enforce HP rules.


---

## 4. Add rules and errors in the transaction

**The Problem:** "My `apply-damage` function works, but it allows negative damage, which heals the player. I need to validate the input and stop the script if something is wrong."

**The Solution:** Use `response err` to reject invalid requests.

### 4.1 Step 1: reject invalid input

Update the transaction to return `response err ...` for bad calls.

```slip
apply-damage: fn {this: Combat, target-id, amount} [
  if [amount <= 0] [
    return (response err "invalid" "damage must be positive" #{ amount: amount })
  ]

  next: this.hp[target-id] - amount
  if [next < 0] [ next: 0 ]

  this.hp[target-id]: next
  response ok next
]
```

### 4.2 Step 2: call it and handle failures

```slip
out: Combat |apply-damage "p1" 10
if [out.status = ok] [
  print "new hp: {{out.value}}"
] [
  print "damage failed: {{out.value}}"
]
```


---

## 5. Cross boundaries by calling transactions

**The Problem:** "My `Combat` resolver needs to know which room a player is in to calculate range, but the `Spatial` resolver owns the room data. I don't want `Combat` to be able to accidentally move players."

**The Solution:** Read through `::`, and request cross-resolver changes by calling the owner’s transactions.

### 5.1 Step 1: define a second owner

In the resolver model, you split domains. For example:

* `Combat` owns HP
* `Spatial` owns rooms / positions

### 5.2 Step 2: read from another resolver, but don’t write into it

Reading is fine (authoritative read via `::`):

```slip
apply-fire: fn {this: Combat, spatial: Spatial, target-id, amount} [
  room-id: spatial::room[target-id]
  response ok room-id
]
```

Writing directly into another authority is not.

```slip
apply-fire: fn {this: Combat, spatial: Spatial, target-id, amount} [
  -- illegal: write targets may not contain `::` (ever)
  spatial::on-fire[target-id]: true
]
```

Even without `::`, committing into another resolver’s namespace is still illegal here, because committed writes must be rooted at `this`:

```slip
apply-fire: fn {this: Combat, spatial: Spatial, target-id, amount} [
  -- illegal: not rooted at `this`
  spatial.on-fire[target-id]: true
]
```

### 5.3 Step 3: submit a transaction to the owner

Instead, ask the owning resolver to do it:

```slip
apply-fire: fn {this: Combat, spatial: Spatial, target-id, amount} [
  spatial |apply-ignite target-id
  response ok none
]
```

---

## 6. Derived values with `ref` and `cell`

**The Problem:** "I have a UI that needs to show if a player is 'wounded'. I'm currently calculating `hp < 50` every time I draw the screen. If I change the definition of wounded, I have to update the UI code."

**The Solution:** Use `ref` to point at state and `cell` to define pure, derived logic.

### 6.1 Step 1: point at committed state with `ref`

```slip
p1-hp: ref Combat::hp["p1"]
```

Reading `p1-hp` gives the current HP. There is no write-through.

`ref` can point at any readable path, including:

- ordinary local or nested paths like `` `d.user.hp` ``
- authoritative reads through `::`
- even code loaded from a `file://...` path

### 6.2 Step 2: derive a value with `cell`

```slip
p1-wounded?: cell {hp: p1-hp} [
  hp < 50
]
```

`cell` inputs may be:

- refs, like `p1-hp`
- path literals directly, like `` {hp: `Combat::hp["p1"]`} ``

### 6.3 Step 3: commit, then read again

```slip
Combat: resolver #{
  hp: #{
    "p1": 55
  }
}

apply-damage: fn {this: Combat, target-id, amount} [
  next: this.hp[target-id] - amount
  if [next < 0] [ next: 0 ]
  this.hp[target-id]: next
  response ok next
]

p1-hp: ref Combat::hp["p1"]
p1-wounded?: cell {hp: p1-hp} [ hp < 50 ]

p1-wounded? -- false

Combat |apply-damage "p1" 10

p1-wounded? -- true
```


---

## 7. Replace `if` chains with dispatch

**The Problem:** "My `apply-damage` function is becoming a giant mess of `if` and `else` blocks to handle different damage types like fire, ice, and physical."

**The Solution:** Use multiple function definitions and let dispatch pick the right one.

In current SLIP, dispatch is simpler than the old reference may suggest. The practical rules are:

- typed methods are considered before untyped methods
- untyped methods are fallback-only
- exact arity beats variadic methods
- guards (`|where`) refine ties within a tier
- last-defined wins among equally matching peers

For day-to-day programming, the main idea is simple: write small methods for distinct cases instead of one giant conditional.

### 7.1 Step 1: start with a plain fallback

```slip
apply-damage: fn {this: Combat, target-id, amount, kind} [
  this.hp[target-id]: this.hp[target-id] - amount
  response ok none
]
```

This is the general case. It matches any `kind`.

### 7.2 Step 2: add guarded variants with `|where`

Default style: put the `|where` clause directly inside the function signature.

```slip
apply-damage: fn {
    this: Combat, 
    target-id, 
    amount, 
    kind 
    |where kind = 'physical'
} [
    this.hp[target-id]: this.hp[target-id] - amount
    response ok none
]

apply-damage: fn {
    this: Combat, 
    target-id, 
    amount, 
    kind 
    |where kind = 'fire'
} [
    this.hp[target-id]: this.hp[target-id] - (amount * 2)
    response ok none
]
```

Try calling both:

```slip
#[
  Combat |apply-damage "p1" 10 `physical`,
  Combat |apply-damage "p1" 10 `fire`
]
```

When a guard passes, that guarded method can beat an unguarded fallback.

### 7.3 Step 3: keep overlapping rules separate

When several methods could apply, prefer distinct methods over nested conditionals.

```slip
apply-damage: fn {
    this: Combat, 
    target-id, 
    amount, 
    kind 
    |where kind = 'fire'
} [
    this.hp[target-id]: this.hp[target-id] - amount
    response ok none
]

apply-damage: fn {
    this: Combat, 
    target-id, 
    amount, 
    kind 
    |where kind = 'fire' and amount > 10
} [
    this.hp[target-id]: this.hp[target-id] - (amount * 3)
    response ok none
]
```

Try both calls:

```slip
#[
  Combat |apply-damage "p1" 10 `fire`,
  Combat |apply-damage "p1" 20 `fire`
]
```

If more than one guarded method passes within the same tier, the most recently defined one wins.

### 7.4 Typed methods beat untyped fallback methods

This is the most important dispatch rule for program design.

```slip
Character: scope #{}
Player: scope #{} |inherit Character

describe: fn {x: Player} [ "player" ]
describe: fn {x} [ "something else" ]

p: create Player

#[ describe p, describe 123 ]
-- => #["player", "something else"]
```

Even though the untyped method is broader, it is a fallback. It should not steal calls that match a typed method.

### 7.5 Exact arity beats variadic

```slip
format-msg: fn {x: `string`} [ "exact" ]
format-msg: fn {x: `string`, rest...} [ "variadic" ]

#[
  format-msg 'hello',
  format-msg 'hello' 1 2
]
-- => #["exact", "variadic"]
```

If a call has too many arguments and no variadic method matches, dispatch fails with `No matching method`.

### 7.6 Design advice

Use dispatch when:

- the behavior differs by type
- the behavior differs by a small set of guarded conditions
- you want to replace brittle `if`/`else` ladders with separate named cases

Avoid putting your whole control structure into one method body. In SLIP, separate methods are often the clearer design.


---

## 8. The Tick Loop: Commit then Observe

**The Problem:** "I'm building a game loop. I need a clear order of operations so that I don't have 'glitches' where the UI shows old data while the combat logic is half-finished."

**The Solution:** Structure your program into a two-stage "Tick".

1. **Commit Stage:** Call transactions to change state.
2. **Observe Stage:** Read `cells` and `refs` to update the UI or log events.

### 8.1 Logging conventions (channels and payload shape)

Pick a small set of channels and use them consistently:

- `"combat"` for combat events
- `"movement"` for spatial/movement events
- `"ui"` for user-facing narration
- `"debug"` for debug-only output

Prefer structured payloads (dicts) for events you may want to test or replay:

```slip
emit "combat" #{ type: `damage`, target: "p1", amount: 10 }
emit "ui" "You hit p1 for 10"
```

### 8.2 Resolver transactions should emit audit events

A resolver transaction can emit an audit trail while it commits:

```slip
apply-damage: fn {this: Combat, target-id, amount} [
  next: this.hp[target-id] - amount
  if [next < 0] [ next: 0 ]
  this.hp[target-id]: next

  emit "combat" #{ type: `damage`, target: target-id, amount: amount, hp: next }

  response ok next
]
```

Because emitted events are data and are ordered, a host can persist them for audit or deterministic replay.

### 8.3 Where emit fits: stage 1 vs stage 2

- Stage 1 (commit): emits are typically “what happened” events (audit trail).
- Stage 2 (observe): emits are typically “what to show” events (UI/debug).

### 8.4 Step 1: commit

```slip
Combat |apply-damage "p1" 10
```

### 8.5 Step 2: read derived values and emit UI output

```slip
if [p1-wounded?] [
  emit "ui" "Player p1 is wounded"
]
```

### 8.6 Example: one tick using Chapter 6 values

```slip
-- Commit stage
Combat |apply-damage "p1" 10

-- Observe stage
if [p1-wounded?] [
  emit "ui" "Player p1 is wounded"
]
```

### 8.7 Testing and replay: assert on emitted events

Because emits are collected as data, tests can assert on them directly:

- assert the transaction returns `response ok ...`
- assert a `"combat"` event was emitted with expected fields
- assert UI narration was emitted in order

---

## 9. Test your modules with `|example` and `test`

**The Problem:** "I'm worried that my 'fix' for the math module broke something else. I need a way to verify my functions work as expected without running the whole game."

**The Solution:** Attach examples directly to your functions.

### 9.1 Add examples to functions

Attach examples to a function using `|example { ... -> ... }`.

```slip
add: fn {x, y} [ x + y ]
add |example { x: 2, y: 3 -> 5 }
```

### 9.2 Run tests for one function: `test`

`test <function>` runs all attached examples and returns a `response`:

- `response ok <count>` when all examples pass
- `response err <failures>` when any example fails

```slip
res: test add

if [res.status = ok] [
  emit "test" "add passed {{res.value}} example(s)"
] [
  emit "test" "add failed"
  emit "debug" res.value
]
```

### 9.3 Run tests for a whole module scope: `test-all`

`test-all <scope>` scans a scope for functions that have examples and runs tests for each one.

```slip
math-mod: scope #{}

run-with [
  add: fn {x, y} [ x + y ] |example { x: 1, y: 2 -> 3 }
  mul: fn {x, y} [ x * y ] |example { x: 2, y: 3 -> 6 }
] math-mod

summary: test-all math-mod
```

`test-all` returns a `response` whose `.value` is a summary dict, including a per-function failure list when failures occur.

---
