# Appendix C - Design Philosophy

This appendix explains why SLIP is shaped the way it is.

It comes last on purpose. The earlier guides teach how to use the language. This appendix explains the design bets behind it.

Use the practical guides first:

- `docs/01 SLIP Scripting.md`
- `docs/02 SLIP Programs.md`
- `docs/03 SLIP Advanced.md`
- `docs/Appendix A - StdLib Reference.md`
- `docs/Appendix B - SLIP Style Guide.md`

## 1. The main goal: remove accidental complexity

Most languages ask you to carry around a lot of extra machinery:

- precedence tables
- separate rules for expressions and statements
- different syntaxes for locals, properties, keys, and queries
- one system for results, another for errors, another for side effects
- one mental model for plain functions and another for “special” language forms

Much of that complexity is historical rather than essential.

SLIP tries to cut that down by using a small number of ideas repeatedly:

- everything is expression-oriented
- paths are the main access/update abstraction
- functions do most of the work that other languages reserve for keywords
- effects and outcomes are represented explicitly
- local rebinding is preferred over mutation at a distance

The point is not minimalism for its own sake. The point is to make more of the language feel predictable.

## 2. Succinctness is power, but readability comes first

One of the core values behind SLIP is:

> Succinctness is power.

The language should let you say more with fewer moving parts.

But that is only half of the goal.

SLIP is not trying to be terse in the sense of becoming cryptic. The target is code that is:

- compact because the abstractions are better
- readable on first encounter
- close to pseudocode when possible
- understandable without mentally decoding a lot of syntax trivia

This is why the language keeps pushing toward:

- direct path-based access
- a small number of evaluation rules
- ordinary function calls in places where other languages introduce special syntax
- explicit structure instead of hidden precedence and hidden control flow

The ideal result is not “shortest possible code”. It is “the shortest code that still reads clearly the first time”.

## 3. The main lineage: Rebol, Lisp/Scheme, Forth, and Logo

SLIP borrows ideas from many languages, but its main philosophical lineage is narrower than that.

It is mainly shaped by:

- Rebol
- Lisp / Scheme
- Forth
- Logo

Everything else is more selective: useful ideas taken where they fit.

### Rebol

Rebol is one of the clearest influences on the feel of the language.

What SLIP keeps:

- readable command-like code
- a language that can feel close to pseudocode
- direct data-shaping and scripting workflows

What SLIP changes:

- it rejects greedy evaluation
- it prefers structured evaluation groups and explicit code values
- it puts more emphasis on predictable execution structure

So SLIP keeps some of Rebol's readability goals without adopting its evaluation model whole.

### Lisp / Scheme

Lisp and Scheme matter because they show what happens when a language is built from a small set of strong ideas.

What SLIP keeps:

- code as data
- metaprogramming as an ordinary activity
- a preference for uniformity over lots of special syntax

What SLIP changes:

- it does not require all-paren surface syntax
- it aims for a more line-oriented, pseudocode-like reading experience

You can think of SLIP as wanting some of Lisp's conceptual power without demanding Lisp's visual style.

### Forth

Forth matters less as a surface influence and more as an execution influence.

It emphasizes that the order in which operations happen is itself a design choice, not just an implementation detail.

SLIP is not stack-based and does not look like Forth, but it shares a related instinct:

- execution order should be simple
- the reader should not have to simulate a large hidden machine

One way to describe SLIP to language people is that it has something like a reverse-Forth instinct: the operational flow matters, but the surface syntax is designed for readability rather than stack notation.

### Logo

Logo matters because approachability matters.

SLIP is not only for children, and it is not an educational language in the narrow sense. But one of its values is that code should be readable by someone who is new, curious, or not yet carrying the full burden of conventional language habits.

That is part of why the language wants to feel like a domain-shaped instruction language rather than a pile of syntax rules.

## 4. Left-to-right evaluation is a design choice

SLIP's most visible philosophical choice is that infix evaluation is left-to-right.

```slip
10 + 5 * 2
-- => 30
```

This is deliberate.

In many languages, readers must mentally re-parse an expression before they can understand it. They look at one order on the page and a different order in their heads.

SLIP prefers a simpler rule:

- read the expression in order
- evaluate it in order
- use parentheses only when you want a different order

```slip
10 + (5 * 2)
-- => 20
```

The tradeoff is obvious: this differs from mainstream operator precedence. But the payoff is that control becomes explicit rather than implicit.

## 5. Dumb parser, smart evaluator

SLIP also makes a strong architectural choice: parsing stays structural, not semantic.

The parser's job is to preserve what you wrote as directly as possible. The evaluator decides what it means.

That supports several other goals at once:

- simpler parsing rules
- fewer hidden rewrites
- a clearer relationship between source text and runtime behavior
- easier code-as-data workflows

This is why SLIP can treat `[...]` as first-class code and why features like `run`, `run-with`, `inject`, and `splice` fit naturally into the language rather than feeling bolted on.

## 6. Paths replace a pile of separate concepts

In many languages, these feel like separate systems:

- variable names
- object property access
- dictionary access
- filtering/query syntax
- sometimes even URL/resource access

SLIP tries to unify them under the idea of a path.

```slip
player.hp
players[.hp > 100].name
file://players.json
http://api.example.com/players
```

This does not mean every path use is identical. Read, write, delete, and pipe are still distinct forms. But the language is built around the idea that identity, navigation, and update should feel related instead of fragmented.

That is why path syntax ends up doing so much work in SLIP.

## 7. Functions instead of keywords

Another core bet is that many things usually treated as syntax should instead be ordinary callable behavior.

That is why SLIP favors constructs like:

- `if [cond] [then] [else]`
- `while [cond] [body]`
- `foreach {x} xs [body]`
- `for {i} start end [body]`

The goal is not to eliminate all special cases at any cost. The goal is to keep the language surface conceptually smaller.

This has two important consequences:

1. The language becomes easier to extend from inside the language.
2. Metaprogramming becomes normal runtime programming instead of a separate macro world.

The language still has a few unavoidable special cases. Assignment syntax is one. Short-circuiting logical operators are another. But the general direction is clear: special syntax should be rare.

## 8. Metaprogramming without a second language

SLIP keeps metaprogramming, but it tries to remove the need for a separate macro world.

That is one of the language's central philosophical choices.

In many languages, advanced abstraction means stepping into a second cognitive layer:

- macros
- template systems
- hygiene rules
- compile-time rewriting languages
- special privileged syntax transformation tools

SLIP tries to avoid that split.

Code is already data.
Evaluation is already explicit.
The language already has runtime tools like:

- `run`
- `run-with`
- `call`
- `inject`
- `splice`

So metaprogramming becomes a more normal form of programming with code values.

```slip
c: [ x + 1 ]
run c
```

This does not make advanced metaprogramming trivial. But it does mean ordinary users do not have to learn a separate macro system just to understand the language.

That is important because SLIP wants advanced machinery to stay optional.

You should be able to ignore metaprogramming for a long time and still write useful, idiomatic SLIP.

The philosophy is:

- power users can assemble and evaluate code dynamically
- ordinary users do not have to worry about dirty macros, hygiene, or a compile-time sub-language

## 9. Code is data, but that does not mean “use metaprogramming everywhere”

SLIP treats code as a first-class value because it makes the language more uniform and more extensible.

```slip
c: [ x + 1 ]
run c
```

That power supports:

- dynamic code assembly
- reusable code templates
- user-defined control abstractions
- explicit host-controlled evaluation

But the philosophy here is not “everything should be metaprogrammed”.

The preferred order is still:

1. plain function
2. closure
3. scope/prototype composition
4. only then dynamic code tools like `run`, `call`, `inject`, and `splice`

The language makes advanced code generation possible. It does not require it for ordinary work.

## 10. Shadow, don't patch

One of SLIP's strongest design principles is locality.

The guiding idea is:

> If you want different behavior in a local context, change it in that local context.

That is why local rebinding matters so much.

In practice:

- local names should be easy to shadow
- imports should compose through local adaptation
- behavior changes should stay near the code that needs them
- code should not silently change far-away behavior as a side effect

This is the reasoning behind the repository's guidance:

> Shadow, don't patch.

It is not just a style preference. It is a way of preserving locality of reasoning.

## 11. Behavior belongs in dispatch rules, not giant conditionals

SLIP uses dispatch to make behavior more declarative.

Instead of writing one function full of branching logic, you can define separate implementations for separate cases.

```slip
describe: fn {x: Character} [ "character" ]
describe: fn {x} [ "other" ]
```

The current dispatch model is intentionally simpler than earlier versions of the docs suggested.

The philosophical point is not “make dispatch maximally clever”. The point is:

- let programmers express separate cases separately
- let the runtime choose among them predictably
- keep fallback behavior explicit

This matches the broader SLIP preference for decomposing behavior into small rules rather than building large monolithic handlers.

## 12. Effects and outcomes are part of normal program design

Many languages treat output, logging, and error handling as separate concerns with different conventions and escape hatches.

SLIP tries to make them more uniform.

- `response` gives a structured way to talk about success and failure
- `do` captures both outcome and emitted effects
- `emit` represents intended side effects explicitly

This supports a style where the core logic of a program can stay inspectable and testable.

It also helps embedded use cases, because the host can decide what to do with effects rather than having every script directly own that policy.

## 13. The host boundary should be explicit

SLIP is meant to be embedded.

That means the boundary between host-managed data and live SLIP runtime values matters.

Recent language decisions in this repository push toward explicitness here too:

- host objects are exposed deliberately
- task lifecycle is host-aware
- rehydration of typed values is explicit with `as-slip` outside the host-object boundary

That last point is important.

Instead of automatically turning every dict with special structure into a live runtime object everywhere, SLIP localizes that behavior to clear boundaries.

For persisted host objects there is a useful split:

- `host-object` returns live SLIP objects
- `host-data` returns raw storage-shaped data

Outside that host boundary, explicit conversion is preferred:

```slip
obj: as-slip (host-data "player-1")
```

This matches the language's broader philosophy:

- powerful boundaries are good
- invisible magic at boundaries is less good

## 14. Background work should be practical, not ornamental

The concurrency story in current SLIP is centered on `task`.

That is a philosophy choice too.

The language is aiming at practical embedded/background work:

- maintenance jobs
- polling
- timers
- host-managed side work

Rather than collecting concurrency mechanisms for their own sake, the current design keeps the story centered on the part that has a clear product use case.

## 15. World modeling shaped the language, but it is not only for games

Historically, SLIP was shaped by the needs of world modeling and MUD-like systems.

That pressure explains a lot of its design:

- large graphs of state
- many interacting entities
- lots of rule-like behavior
- long-lived background processes
- clear separation between simulation and presentation

Even if you are not building a game, that background still matters. Many business systems have the same structural needs under different names:

- records instead of entities
- workflows instead of rules engines
- jobs instead of NPC brains
- events instead of world effects

So the philosophy is not “SLIP is only for games”. It is that a language forged for dynamic, stateful worlds often generalizes well to other complex domains.

## 16. What SLIP steals selectively

Outside its main lineage, SLIP also steals useful ideas from other places when they fit.

Examples:

- prototype-oriented object ideas
- structured outcomes similar to `Result`-style programming
- background task ideas from async systems
- host embedding patterns from practical scripting runtimes

But these are borrowed pieces, not the identity of the language.

The philosophy is not “merge every good idea ever invented”.

The philosophy is:

- steal the useful part
- remove as much surrounding complexity as possible
- make it fit the existing mental model

## 17. The tradeoff: explicitness over convention

SLIP is not trying to feel exactly like mainstream languages.

It asks the user to accept a few nonstandard choices:

- no precedence-based infix evaluation
- heavy use of paths
- code/data duality in normal programming
- function-oriented control flow

In return, it tries to make the language feel more uniform.

That is the central tradeoff:

- fewer implicit conventions
- more explicit structure
- smaller number of ideas doing more work

Whether that is “better” depends on taste and domain. But it is a coherent design direction.

## 18. The payoff: say more with fewer systems

The philosophical claim behind SLIP is that power does not come from piling on unrelated features.

It comes from having a small number of abstractions that compose well.

When that works, the benefits are practical:

- shorter explanations
- smaller APIs
- simpler extension points
- less ceremony around common tasks
- clearer adaptation of behavior to local context

That is the real goal of the language.

Not novelty.

Not purity.

Just a tool that lets you focus more directly on the world, system, or workflow you are trying to model.
