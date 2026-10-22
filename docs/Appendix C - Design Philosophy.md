# Appendix C - Design Philosophy

This is the reasoning behind SLIP: its influences, the choices those influences led to, and how its parts compose. You can start here or try the language through [SLIP Scripting](<01 SLIP Scripting.md>).

Adapted from the [SLIP design article on Seerware](https://seerware.com/slip/), with additional examples and notes for the repository documentation.

## Why SLIP?

There is an old programmer's conceit that, sooner or later, every serious programmer tries to design a language.

**SLIP is mine.**

I wanted Lisp's structural power: a small language in which code remains available to the program instead of disappearing into compiler machinery. I also wanted the readability of Rebol, whose command-like programs can feel closer to instructions than notation written for a parser.

But Rebol's greedy evaluation can make it difficult to see where one call ends and another begins without already knowing the functions involved. SLIP keeps the readable, left-to-right flow while making evaluation boundaries and program structure more explicit.

I began with the syntax I wanted to write, then built an interpreter in Python. In the spirit of [Peter Norvig's small Lisp interpreter](https://norvig.com/lispy.html), that was the shortest path from an idea about language design to something I could run, break, and change. Python makes that experimentation practical; the language has its own programming model.

Forth's visible execution order and Logo's approachability also influenced the design. The common thread is that a reader should be able to follow a program without carrying a large hidden machine in their head.

The question behind SLIP is:

> **How much of a language can emerge from a few visible, composable structures?**

SLIP is a general-purpose scripting language. The current implementation is a working research prototype in which code blocks, signatures, scopes, paths, generic functions, and resolvers are implemented and tested together.

## A Small, Visible Grammar

SLIP uses different forms for different kinds of structure:

| Form | Meaning |
| --- | --- |
| `(...)` | Evaluate a grouped expression now |
| `[...]` | Preserve code for later execution |
| `{...}` | Describe names, types, and bindings with a signature |
| `#[...]` | Ordinary list data |
| `#{...}` | Ordinary dictionary data |
| `scope #{...}` | A first-class environment, object, or prototype |

Executable structure, binding structure, and ordinary data have distinct forms, and all remain available to the program.

Expressions read in the order they appear:

```slip
10 + 5 * 2
-- => 30

10 + (5 * 2)
-- => 20
```

There is no operator-precedence table rearranging the first expression. The written order is the execution order; parentheses explicitly request a different grouping. Pipes use the same left-to-right model:

```slip
10 |add 5 |mul 2
-- => 30
```

That differs from familiar arithmetic notation, so readers must learn the rule. In return, the evaluator follows one order for infix expressions, and grouping is visible on the page.

The parser preserves these structures. Evaluation gives them meaning. That separation keeps code inspection and metaprogramming close to the source the programmer wrote.

## Control Flow From Code And Signatures

Square brackets contain code without immediately executing it. Curly braces contain a signature: structured information about names to bind, along with optional types and guards.

That makes this possible:

```slip
for {i} 0 3 [
    print i
]
```

`for` is an ordinary SLIP function. `{i}` arrives as a signature value and `[...]` arrives as a code value. The function binds the requested name and decides when and where to execute the block.

This is its implementation in SLIP's standard library, followed by a call using it:

```slip
for: fn {vars, start, end, body-block} [
    var-name: extract-simple-param vars
    for-scope: current-scope
    for-scope: for-scope.meta.caller
    step: if [start <= end] [1] [-1]
    i: start

    while [if [step > 0] [i < end] [i > end]] [
        for-scope[var-name]: i
        run-with body-block for-scope
        i: i + step
    ]

    none
]

seen: #[]
for {i} 0 3 [
    seen: add seen i
]
seen
-- => #[0, 1, 2]
```

This provides macro-like extensibility through ordinary runtime values and calls. A binding form can receive a signature, inspect it, and execute code against a chosen scope.

The evaluator still has special handling where evaluation order requires it: `if` receives unevaluated branches, for example, and `and`/`or` short-circuit. The useful result is that user-defined forms such as `for` can compose with those primitives using the same code and signature values.

A block can also be stored, returned, inspected, edited, combined with other code, or executed later. `inject` and `splice` support building code from other values. Those tools are available when ordinary functions and closures are insufficient; they do not have to appear in everyday scripts.

## Scopes Are Values Too

The other side of evaluation is the environment in which code runs. In SLIP, a scope is a first-class value:

```slip
workspace: scope #{}

result: run-with [
    answer: 10 * 2
    answer
] workspace

#[result, workspace.answer]
-- => #[20, 20]
```

Both sides of evaluation are explicit: the code to execute and the scope in which its bindings should live. Scopes can be stored, passed, returned, extended, and used as module-like namespaces.

They are also the foundation of SLIP's prototype system.

## Scopes And Dispatch Compose Into An Object System

A scope can act as a prototype and inherit from another scope. Behaviour can be expressed as free generic functions whose implementations are selected by the types of their arguments:

```slip
Character: scope #{
    hp: 100
}

Player: scope #{} |inherit Character
player: create Player

heal: fn {character: Character, amount} [
    character.hp: character.hp + amount
]

heal: fn {player: Player, amount} [
    player.hp: player.hp + (amount * 2)
]

player |heal 10
-- => 120
```

Defining another implementation under the same local name adds another dispatch rule. Here the more specific `Player` implementation applies. The pipe gives the call a familiar receiver-oriented reading, while `heal` remains a free generic function.

Scopes provide state, prototypes, and inheritance; generic functions provide behaviour. Types on several arguments can participate in dispatch, and a signature can include a value guard:

```slip
Player: scope #{}
LockedDoor: scope #{
    locked: true
}

interact: fn {actor: Player, target: LockedDoor, action |where action = `open`} [
    target.locked: false
]

player: create Player
door: create LockedDoor
player |interact door `open`
door.locked
-- => false
```

A new combination of arguments or actions can be expressed as another implementation. This is useful whenever behaviour is clearer as separate cases. The object system emerges from scopes, prototype inheritance, signatures, generic functions, and the ordinary call model.

## Paths Are The Language's Connective Tissue

SLIP uses one broad path model for names, navigation, queries, updates, and resources:

```slip
player.hp
players[.hp > 100].name
file://players.json
http://api.example.com/players.json[.hp > 100].name
```

A variable name is a path with one segment. Property access, selection, and resource addressing extend that same idea. Read, write, delete, and pipe remain distinct operations, with related syntax and first-class path values.

Paths also connect to code-as-data. Reading a `.slip` file through `file://` returns code without executing it. A program can inspect or modify that code, then deliberately execute it with `run` or `run-with`. `import` combines loading and module execution when that is what the caller wants.

This makes code addressable in the same general way as other values. A future `slip://module` scheme could extend that model to language-level resources.

## Shadow, Don't Patch

First-class environments make local adaptation possible. The guiding idea is:

> If you want different behaviour in a local context, change it in that local context.

For example, a scope can define its own implementation while the original remains available:

```slip
scale: fn {value} [value * 2]
workspace: scope #{}

run-with [
    scale: fn {value} [value * 3]
] workspace

#[scale 4, workspace.scale 4]
-- => #[8, 12]
```

The same principle guides module composition: use imported definitions through local wrappers or shadowing bindings. Customisation stays near the code using it, and other callers continue to see the original behaviour.

This requires deliberate treatment of shared mutable values. Local rebinding establishes a new binding; editing an object reached through a shared binding still changes that object. Scopes make adaptation visible, but they do not make every reachable value immutable.

## Resolvers Make Ownership Explicit

First-class scopes are useful for objects and environments, but persistent multi-user systems introduce a harder question:

> **Who owns the truth, and who is allowed to change it?**

A resolver is a specialised scope that acts as the authority root for a domain. Transactions dispatch on the resolver through the reserved `this` parameter, and committed writes are rooted in that receiver:

```slip
Combat: resolver #{
    hp: #{ 'p1': 100 }
}

apply-damage: fn {this: Combat, target-id, amount} [
    next: this.hp[target-id] - amount
    if [next < 0] [next: 0]
    this.hp[target-id]: next
    return next
]

Combat |apply-damage 'p1' 10
-- => 90
```

Different resolvers can own different parts of the same application. Cross-domain reads use an explicitly read-only authority path, written `::`. Changes can be requested through transactions owned by the other resolver:

```slip
Combat: resolver #{ hp: #{ 'p1': 100 } }
Spatial: resolver #{
    room: #{ 'p1': 'room.square' }
    on-fire: #{}
}

apply-ignite: fn {this: Spatial, target-id} [
    this.on-fire[target-id]: true
]

apply-fire: fn {this: Combat, spatial: Spatial, target-id, amount} [
    room-id: spatial::room[target-id]
    this.hp[target-id]: this.hp[target-id] - amount
    spatial |apply-ignite target-id
    return room-id
]

room-id: Combat |apply-fire Spatial 'p1' 10
#[room-id, Combat.hp['p1'], Spatial.on-fire['p1']]
-- => #['room.square', 90, true]
```

The transaction reads the room through `spatial::room`; writes across that `::` boundary are rejected. It asks `Spatial` to record ignition by calling `apply-ignite` on that resolver. Ownership is expressed at the call and write sites.

Workflows, records, ledgers, policy systems, and operational applications all contain state with an authoritative owner. Resolver transactions let those ownership boundaries participate in dispatch and path access.

## Effects And Outcomes At The Host Boundary

An embedded language also needs a clear way to report what happened. Ordinary successful calls return values. `fail` signals a domain failure, `emit` records an effect, and `do` captures a value or error together with the effects produced by the block:

```slip
require-positive: fn {value} [
    if [value <= 0] [fail `invalid` 'Expected a positive value.']
    emit 'audit' value
    value
]

accepted: do [require-positive 3]
rejected: do [require-positive 0]

#[accepted.status, accepted.value, len accepted.effects, rejected.status, rejected.error.code]
-- => #[`ok`, 3, 1, `err`, `invalid`]
```

The host can inspect and route effects such as messages or audit events. `do` captures failures and effects; it does not roll back arbitrary state changes. Keeping those responsibilities distinct makes it easier to test domain behaviour without putting presentation or logging policy into every function.

The data boundary is explicit too:

- `host-data` retrieves raw host-managed data.
- `host-object` exposes live, dispatchable objects at the host boundary.
- `as-slip` explicitly rehydrates typed values from ordinary data outside that boundary.

This keeps storage-shaped data useful on its own. Turning it into runtime objects is a visible operation with a defined place in the program.

Background work follows the same approach. `task` schedules code through the host's event loop, and host-aware task tracking provides a place to manage its lifetime. This supports practical jobs such as polling, timers, and maintenance alongside the application's other work.

## What Exists Today

SLIP is an actively used research prototype. The current implementation includes:

- a Python interpreter and standard library
- left-to-right expressions, pipes, and explicit grouping
- first-class code blocks and signature literals
- runtime code execution, inspection, injection, and splicing
- first-class scopes, prototypes, and inheritance
- generic functions, multidispatch, and guarded value dispatch
- paths, collection queries, and file/HTTP resource schemes
- modules loaded from files, HTTP resources, or code
- resolvers, transactions, references, and derived cells
- asynchronous tasks, structured failures, and executable documentation tests

I am testing the language by building an interactive-fiction application. Its interacting actors, rules, paths, and long-lived state exercise the features together in a substantial domain. That application is a test of a general-purpose language, rather than a boundary around what the language is for.

The interpreter remains in Python because fast iteration still matters. Future directions include direct `slip://` addressing and Koine-based transpilers for embedding small domain-specific languages where their notation earns its place.

The design asks readers to learn some unfamiliar choices: left-to-right infix evaluation, explicit code values, and first-class scopes and paths. The intended payoff is that those same structures keep working as programs grow from small scripts into their own commands, objects, and stateful domains.

For practical use, continue with [SLIP Scripting](<01 SLIP Scripting.md>), [SLIP Programs](<02 SLIP Programs.md>), or [SLIP Advanced](<03 SLIP Advanced.md>). The [StdLib Reference](<Appendix A - StdLib Reference.md>) gives the current contracts in detail.
