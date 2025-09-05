# SLIP: A Language for World Modeling

![alt text](https://img.shields.io/badge/Status-Alpha-orange.svg) ![alt text](https://img.shields.io/badge/Python-3.10%2B-blue.svg) ![alt text](https://img.shields.io/badge/Coverage-80%25-brightgreen.svg) ![alt text](https://img.shields.io/badge/License-Apache_2.0-blue.svg)

SLIP is a new scripting language designed specifically for the challenges of world modeling, game logic, and building domain-specific languages (DSLs). It's built to be approachable for beginners and modders, yet powerful enough to capture the interest of experienced language designers.

It achieves this by revisiting a few core assumptions of language design, resulting in a language that is highly consistent, safe to embed, and remarkably expressive.

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

#### 1. Model Behavior with Components, Not Rigid Classes

SLIP's object model is designed for dynamic worlds where an object's capabilities can change at any moment. Instead of a strict inheritance hierarchy, you compose objects from a collection of mixins, much like the **Entity-Component-System (ECS)** pattern used in modern game development.

**How it works:** You define a function for a specific combination of components. SLIP's dispatch engine automatically runs the correct logic for any object that has that exact set of components.

```slip
-- A rule that only applies to objects that are both a Player and Poisoned.
-- This is like a "system" that runs on entities with these two "components".
handle-tick: fn {target: (Player and Poisoned)} [
    target.hp: target.hp - 5
]
```

This is made possible by a powerful **multiple dispatch** engine that selects behavior based on the runtime state of all arguments.

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

SLIP is designed to be safely embedded in a host application (like a game server). A user's script with an infinite loop won't lock up the entire program.

**How it works:** Inside a concurrent `task`, SLIP's loops (`loop`, `while`, `foreach`) automatically and transparently "yield" control back to the host on every single iteration. This **cooperative multitasking** is built-in, ensuring the host always remains responsive.

---

## For the Language Designer: Revisiting First Principles

SLIP's simplicity is the result of a deep architectural choice: it revisits three fundamental assumptions of conventional language design.

1.  **A "Dumb" Parser, a "Smart" Evaluator:** The parser creates a direct, 1:1 representation of the code. All semantic intelligence (including the left-to-right evaluation of infix operators) resides in the evaluator. This eliminates operator precedence and the need for most special-case grammar rules.

2.  **Paths, Not Symbols:** The `path` is the language's true primitive for identity and location. A "symbol" is just a path with one segment. This unifies variable lookup, member access, and data queries into a single, powerful mechanism.

3.  **Functions, Not Keywords:** With the exception of assignment (`:`), all control flow is handled by regular functions operating on first-class `code` objects. This makes the language's core grammar radically simple and user-extensible by default.

To read the full argument for this design, see **[The SLIP Design Philosophy](<docs/SLIP Design Philosophy.md>)**.

---

### Project Status & Roadmap

This project is a **stable alpha**. The language design is feature-complete, and the Python prototype is being actively **battle-tested** as the scripting engine for a complex application. This real-world usage is driving the final refinements to the syntax and standard library.

- **Current:** Refine the language by continuing to build with the Python prototype.
- **Next:** Begin work on a high-performance implementation in a systems language with a hybrid AOT/JIT compilation strategy.
- **Known Limitation:** The query system currently builds new lists when filtering (e.g., `players[...]`). The final design calls for lazy "views" for maximum performance, which is on the roadmap.

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

2.  **Install the project in editable mode:**
    This command will also automatically install any required dependencies.

    ```bash
    pip install -e .
    ```

3.  **Run a script file:**
    ```bash
    python slip.py test.slip
    ```
    _(Note: Running `python slip.py` with no arguments will start a REPL for interactive use.)_

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

    runner = ScriptRunner(context)
    result = await runner.run(script)

    if result.status == 'success':
        print(f"Script succeeded! Strong players: {result.value}")

asyncio.run(main())
```

### Documentation

The project's documentation is structured to guide you from the high-level concepts down to the implementation details.

#### Primary Documents (Start Here)

- **[The SLIP Design Philosophy](<docs/SLIP Design Philosophy.md>):** An introduction to the core philosophy and the argument for SLIP's design. Start here to understand the "why" behind the language.
- **[The SLIP Language Reference](<docs/SLIP Language Reference.md>):** The complete, detailed technical manual for the language syntax, core library, and features.

#### Additional Guides

- **[SLIP Style Guide](<docs/SLIP Style Guide.md>):** A guide to writing clean, effective, and idiomatic SLIP code. Essential reading for contributing to the standard library or for team projects.
- **[Implementation Guide](<docs/SLIP Implementation.md>):** For those interested in the interpreter's internals. This document details the architecture of the parser, evaluator, and host interface.

### License

This project is licensed under the **Apache License 2.0**. See the [LICENSE](LICENSE) file for details.
