# SLIP: A Language for World Modeling

![alt text](https://img.shields.io/badge/Status-Alpha-orange.svg) ![alt text](https://img.shields.io/badge/Python-3.10%2B-blue.svg) ![alt text](https://img.shields.io/badge/Coverage-80%25-brightgreen.svg) ![alt text](https://img.shields.io/badge/License-Apache_2.0-blue.svg)

SLIP is a new scripting language designed specifically for the challenges of world modeling, game logic, and building domain-specific languages (DSLs). It's built to be approachable for beginners and modders, yet powerful enough to capture the interest of experienced language designers.

It achieves this by revisiting a few core assumptions of language design, resulting in a language that is highly consistent, safe to embed, and remarkably expressive.

### Dive Deeper

This README provides a high-level overview. To truly understand the project, choose your path:

- **[Start with Part 1 »](<docs/01 SLIP Scripting.md>)** — Learn just enough SLIP to be productive quickly.
- **[Read the Design Philosophy »](<docs/Appendix C - Design Philosophy.md>)** — Understand the "why" behind SLIP's design after you know the basics.
- **[See the Core Ideas Below »](#the-core-ideas)** — Continue reading for a quick, scannable summary of the key features.
- **[Get Started Immediately »](#getting-started)** — Jump to the instructions to clone the repo and run your first script.

### A Taste of SLIP

SLIP's features are designed to work together, allowing you to define the concepts of your world and then simulate them with clean, declarative code.

Imagine you want to apply a "poison" effect, but stone golems in your world are immune.

```slip
-- First, define the rules of your world using functions.
-- This is the general rule for applying poison to any character.
handle-effect: fn {target: Character, effect: `poison`} [
    target.hp: target.hp - 5
    emit "log" "{target.name} takes 5 poison damage."
]

-- This is a more specific rule that runs ONLY for Golems.
-- SLIP automatically chooses the most specific rule to run.
handle-effect: fn {target: Golem, effect: `poison`} [
    emit "log" "The Golem is immune to poison!"
]

-- Now, simulate the world using these rules.
-- Find all the goblins in the Dragon's Lair.
lair-goblins: world.dungeons.dragons-lair.creatures[.class = "Goblin"]

-- Apply the poison effect to all of them.
foreach {goblin} lair-goblins [
    handle-effect goblin `poison`
]
```

---

## The Core Ideas

SLIP's power comes from a few key concepts that make it uniquely suited for modeling complex systems.

#### 1. Model Behavior With Prototypes And Dispatch

SLIP's object model is designed for dynamic worlds where behavior is often clearer as a set of separate rules instead of one giant conditional.

**How it works:** You define functions for the cases you care about. SLIP's dispatch engine selects the best match based on the runtime arguments.

```slip
Character: scope #{}
Golem: scope #{} |inherit Character

handle-effect: fn {target: Character, effect: `poison`} [
    target.hp: target.hp - 5
]

handle-effect: fn {target: Golem, effect: `poison`} [
    print "The Golem is immune to poison!"
]
```

This is made possible by SLIP's dispatch model, which keeps fallback behavior explicit and lets you break complex logic into smaller rules.

#### 2. A Single, Powerful Tool for Finding and Changing Things

SLIP unifies variable access, object properties, and data filtering into a single, consistent syntax called a **path**. You don't need to learn separate syntaxes for each.

**How it works:** Everything from a simple variable `x` to a complex query `players[.hp > 100].name` is the same type of object: a `path`. This makes data navigation and filtering a core, native part of the language.

```slip
-- A single expression to find the names of all active warriors with low health.
wounded-warriors: players[.class = "Warrior" and .is-active = true and .hp < 50].name
```

This is SLIP's **unified path system**, where identity, location, and queries are a single, first-class concept.

#### 3. Extend the Language with Your Own Commands

In most languages, words like `for` or `if` are special keywords baked into the grammar. In SLIP, they are just regular functions. This means you can extend the language with your own control structures.

**How it works:** A block of code in square brackets `[...]` isn't run immediately. It's treated as a `code` object—a piece of data you can pass to other functions. A function like `for` simply receives this `code` object and decides when and how to run it.

```slip
-- 'for' is just a function that takes a code block as an argument
for {i} 0 5 [
    print "The number is {i}"
]
```

This is possible because SLIP is **homoiconic**. It allows for powerful, runtime metaprogramming without a separate macro system.

#### 4. User Scripts Can't Freeze Your Application

SLIP is designed to be safely embedded in a host application. A user's script should not monopolize the host just because it launches a background loop.

**How it works:** Background work runs through `task`, which integrates with the host event loop and keeps the async story focused on practical jobs like polling, timers, and maintenance work.

---

## For the Language Designer: Revisiting First Principles

SLIP's simplicity is the result of a deep architectural choice: it revisits three fundamental assumptions of conventional language design.

1.  **A "Dumb" Parser, a "Smart" Evaluator:** The parser creates a direct, 1:1 representation of the code. All semantic intelligence (including the left-to-right evaluation of infix operators) resides in the evaluator. This eliminates operator precedence and the need for most special-case grammar rules.

2.  **Paths, Not Symbols:** The `path` is the language's true primitive for identity and location. A "symbol" is just a path with one segment. This unifies variable lookup, member access, and data queries into a single, powerful mechanism.

3.  **Functions, Not Keywords:** With the exception of assignment (`:`), all control flow is handled by regular functions operating on first-class `code` objects. This makes the language's core grammar radically simple and user-extensible by default.

To read the full argument for this design, see **[Appendix C - Design Philosophy](<docs/Appendix C - Design Philosophy.md>)**.

---

### Project Status & Roadmap

This project is a **stable alpha**. The Python implementation is the active reference runtime, and the docs are now organized around practical scripting first, deeper design later.

- **Current:** Refine the language by continuing to build with the Python prototype.
- **Next:** Begin work on a high-performance implementation in a systems language with a hybrid AOT/JIT compilation strategy.
- **Known Focus Area:** The current work is on persistence boundaries, host integration, and keeping the practical documentation aligned with the real runtime.

### Getting Started

#### Prerequisites

- Python 3.10+
- Git

#### Installation & Running

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/chrsbats/SLIP.git
    cd SLIP
    ```

2.  **Create a project virtual environment and sync dependencies:**

    ```bash
    uv venv
    uv sync --extra dev
    ```

3.  **Run a script file:**
    ```bash
    uv run python slip.py test.slip
    ```
    _(Note: Running `uv run python slip.py` with no arguments will start a REPL for interactive use.)_

#### Embedding in Python

SLIP is designed to be embedded. A key advantage is that it provides a safe, simple concurrency model that doesn't require you to manage Python's complex `async` model directly in your scripts.

```python
import asyncio
from slip import ScriptRunner # Adjust import to your actual project structure

async def main():
    script = """
        -- Find players with hp over a threshold and return their names
        strong-players: players[.hp > 100]
        strong-players.name
    """

    # Provide a context with some data for the script to use
    context = {
        "players": [
            {"name": "Karl", "hp": 120, "class": "Warrior"},
            {"name": "Jaina", "hp": 45, "class": "Mage"},
        ]
    }

    runner = ScriptRunner()
    runner.root_scope["players"] = context["players"]
    result = await runner.handle_script(script)

    if result.status == 'ok':
        print(f"Script succeeded! Strong players: {result.value}")

asyncio.run(main())
```

### Documentation

The project's documentation is structured to guide you from the high-level concepts down to the implementation details.

#### Tutorial Path

- **[01 SLIP Scripting](<docs/01 SLIP Scripting.md>):** The fastest practical path to writing useful SLIP.
- **[02 SLIP Programs](<docs/02 SLIP Programs.md>):** Code organization, dispatch, testing, schemas, and program structure.
- **[03 SLIP Advanced](<docs/03 SLIP Advanced.md>):** Metaprogramming, host integration, background work, and explicit rehydration.

#### Optional Guidance

- **[04 SLIP Best Practices](<docs/04 SLIP Best Practices.md>):** Practical advice for writing clear, maintainable, moddable SLIP.

#### Appendices

- **[Appendix A - StdLib Reference](<docs/Appendix A - StdLib Reference.md>):** A practical reference for the current standard library surface.
- **[Appendix B - SLIP Style Guide](<docs/Appendix B - SLIP Style Guide.md>):** Formatting and idioms for readable SLIP code.
- **[Appendix C - Design Philosophy](<docs/Appendix C - Design Philosophy.md>):** The rationale behind SLIP's core design choices.

#### Agent Guidance

- **[OpenCode Skill: SLIP](<.opencode/skills/slip/SKILL.md>):** Repository-local skill for agents writing idiomatic SLIP.

### License

This project is licensed under the **Apache License 2.0**. See the [LICENSE](LICENSE) file for details.
