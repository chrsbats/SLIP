# SLIP Language Reference v1.0

- **Describes semantics, not performance.** Implementations may cache, compile to byte‑code, or JIT as long as they preserve the rules herein.
- **Single‑threaded interpreters.** Each interpreter instance is single‑threaded; there is no shared mutable state across interpreters. Communication must occur via message passing or external channels.

This document provides a complete and formal reference for the syntax, evaluation rules, and standard library of the SLIP language.

## 0. Overview

> **"SLIP is a new scripting language that combines the clean syntax of Python with the metaprogramming power of LISP. It has no keywords like `if` or `for`; instead, you pass unevaluated code blocks to regular functions, giving you complete control over evaluation. This is all built on a simple, path-oriented system with a 'zero-precedence', left-to-right evaluation model that makes the language incredibly consistent and easy to reason about."**

### 0.1. Core Philosophy

SLIP (Path-oriented Interactive Language) is a new, dynamic programming language designed for clarity, simplicity, and powerful metaprogramming. Its philosophy is a synthesis of three core ideas:

1.  **Direct Representation (The "What You See Is What You Get" AST):** The parser converts source text into an Abstract Syntax Tree (AST) that is a direct, 1:1 representation of the code. It performs no semantic transformations like building a precedence tree or rewriting expressions into a different form (e.g., prefix notation). The evaluator, not the parser, is responsible for interpreting different syntactic structures. This makes the parser's role radically simple and transparent.

2.  **Path-Oriented Identity (No More "Symbols"):** The concept of "symbols" is replaced entirely by a first-class `path` data type. Paths are used for variable names, function names, data navigation, member access, and namespaces. This unifies the concepts of identity, location, and navigation into a single, routable address system. A traditional "symbol" is simply a path with one segment. This design also opens the door for future extensions where paths could resolve to resources in other threads, processes, or even remote computers, making distributed computing a natural extension of the language's core identity mechanism.

3.  **Function-Controlled Evaluation (No Special Forms):** Control flow is managed by standard functions that operate on unevaluated code blocks. This eliminates the need for most special forms, keywords, and macros found in other languages. Constructs like `if`, `while`, and `for` are regular functions that gain their power by receiving code as data.

SLIP is not a dialect of LISP or Rebol. Unlike LISP, it does not transform code into a single prefix form. Unlike Rebol, its evaluation is based on a structured, hierarchical s-expression model, not a linear, greedy one. The meaning of any expression is determined by the evaluator based on the types of the objects it encounters.

### 0.2. Rethinking Established Conventions: How SLIP is Different

SLIP can seem alien at first, but it is actually very simple once you understand its core concepts. The main challenge is that SLIP re-evaluates many fundamental design decisions that have become established conventions over 50 years of computer science. People often forget that these conventions—such as the idea that an Abstract Syntax Tree must be a prefix tree—are historical choices, not laws of nature.

To understand SLIP requires unlearning these assumptions. These conventions are not wrong; they are a collection of brilliant solutions and patterns that have become so standard we forget other solutions are possible. SLIP consistently challenges these choices to arrive at a smaller, more orthogonal core.

1.  **Convention: Parsers must understand precedence and build deep trees.**

    - **The Standard Way:** `a + b * c` _must_ be parsed into a tree where `*` is lower than `+`. The parser is complex and performs semantic transformations.
    - **The SLIP Way:** The parser is "dumb." It produces a flat list `[a, +, b, *, c]`. The concept of precedence is moved entirely to the evaluator's simple, left-to-right reduction loop. This is a radical simplification of the parser's role.

2.  **Convention: Languages need many special forms and statement types.**

    - **The Standard Way:** `if`, `for`, `while`, `def`, `return`, `class` are all unique keywords with their own special grammar rules.
    - **The SLIP Way:** There is **one** special syntactic pattern for assignment (`:`). Everything else is a regular function call that gains its power by operating on unevaluated `code` blocks. This is a profound commitment to uniformity.

3.  **Convention: Symbols are a distinct, atomic data type.**

    - **The Standard Way (LISP):** A symbol `'x` is a fundamental, indivisible unit.
    - **The SLIP Way:** There are no symbols. There are only **paths**. A "symbol" is just a path with one segment. This unifies identity, location, and navigation into a single, more powerful concept.

4.  **Convention: Metaprogramming requires a separate macro system.**

    - **The Standard Way:** Languages have a distinct `defmacro` or `macro_rules!` system that operates at a different "time" (compile-time) and often has its own complex rules.
    - **The SLIP Way:** Metaprogramming is just a normal, runtime activity. You build a `code` object (which is just a list of lists) and then call `run` on it. `inject` and `splice` are the only "magic," and they are part of the evaluation, not a separate system.

5.  **Convention: Assignment is a simple statement.**
    - **The Standard Way:** `x = 10` is a simple statement. `a, b = 10, 20` is a different, more complex statement type.
    - **The SLIP Way:** Assignment is a **pattern-matching operation**. The single `:` form can handle simple binding, destructuring, and even dynamic, computed targets based on the _structure_ of its left-hand side. This is a far more powerful and unified concept.

### 0.3. Why SLIP? The Case for an Embedded Language

Given that SLIP is hosted in Python, a natural question is, "Why not just use a restricted version of Python for scripting?" The answer is that SLIP is not a general-purpose language; it is a specialized tool forged to solve the unique challenges of embedded scripting far more safely and effectively than a restricted Python environment can.

- **1. True Sandboxing and Security by Default**
  SLIP is **secure by default**. It has no built-in filesystem or network access. The _only_ way a script can interact with the host system is through the explicit, whitelisted API you provide.

- **2. Designed for a Cooperative, Asynchronous World**
  SLIP's interpreter is designed to be a good citizen. The `task` primitive and **automatic yielding** in loops are built-in safety features that ensure the host application remains responsive.

- **3. The Power of "Code as Data"**
  In SLIP, a block of unevaluated code `[...]` is a first-class `code` data type. This homoiconic design is a superpower that Python cannot easily replicate, allowing behavior to be stored, passed, and executed dynamically.

- **4. A True "Dialecting" Language**
  SLIP is designed to be shaped into a Domain-Specific Language (DSL). The host defines a "dialect" of commands, allowing scripters to write logic in a language that speaks the concepts of your application.

While you can expose an API to a Python script, the code will always look like Python. SLIP is designed to be shaped into a Domain-Specific Language (DSL). The host defines a "dialect" of commands and operators, allowing scripters (who may be game designers or power-users, not programmers) to write logic in a language that speaks the concepts of your application. This mirrors the philosophy of early educational languages like Logo, where simple, powerful commands (FORWARD 100, RIGHT 90) created an intuitive and expressive environment for a specific domain.

```slip
// This is more than just a function call it's a domain-specific command.
announce "The Northern gates have fallen!"
```

In short, SLIP is chosen over restricted Python because it offers a fundamentally more secure, stable, and flexible solution purpose-built for the task of high-level, embedded scripting.

## 1. Syntax & Evaluation Model

### 1.1. Parsing: The Flat, Directly-Represented AST

In SLIP, the parser produces an Abstract Syntax Tree (AST) that is a direct, 1:1 representation of the source code. It performs no semantic transformations like building a precedence tree for operators or rewriting function calls into a different form. This "dumb parser" approach radically simplifies the parser's role and makes the language's structure completely transparent.

- **Smart Parsing:** While the parser is "dumb" about semantic precedence, it is "smart" about syntactic structure. It enforces a `prefix_call (pipe_chain)*` grammar, which means that an expression like `add 1 add 2` is a syntax error. This catches many common errors early, before the evaluator runs.

- **Flat Lists for Infix Operations:** The parser's primary job is to convert each line of code into a simple, flat list of tokens. It does not create a nested tree based on operator precedence.

  - The line `10 + 5 * 2` is parsed directly into the flat structure `[<number 10>, [path [name '+']], <number 5>, [path [name '*']], <number 2>]`.
  - _Contrast with most languages:_ A traditional parser would transform this into a tree where `*` has higher precedence than `+`, equivalent to `10 + (5 * 2)`. SLIP does not; the structure is preserved exactly as written.

- **Explicit Nesting with `()` and `[]`:** Nesting in the AST is created _only_ when the programmer uses parentheses `(...)` for an evaluation group or square brackets `[...]` for a `code` block.
  - The line `add 1 (multiply 2 3)` is parsed as `[expr [path [name 'add']], <number 1>, [expr [path [name 'multiply']], <number 2>, <number 3>]]`. The parentheses explicitly create the nested `[expr ...]` node.

This approach places all semantic intelligence in the evaluator, creating a transparent and highly consistent system.

### 1.2. Evaluation: Left-to-Right and Type-Driven

The evaluator receives the AST from the parser and processes it sequentially. The meaning of any expression is determined by the evaluator based on the types of the objects it encounters.

For expressions parsed into a flat list, such as infix arithmetic, the evaluator consumes tokens from left to right, applying each operation as it appears.

- **Example: Evaluating `result: 10 + 5 * 2`**
  1.  **Initial AST:** `[ [set-path [name 'result']], <number 10>, [path [name '+']], <number 5>, [path [name '*']], <number 2> ]`
  2.  **Assignment Detection:** The evaluator sees `[set-path [name 'result']]` as the first token. It knows this is an assignment. It will evaluate the rest of the list (`[10, +, 5, *, 2]`) to get the value for `result`.
  3.  **Evaluating `[10, +, 5, *, 2]` (Left-to-Right):**
      - Evaluator processes `10`.
      - Evaluator sees `+`. It looks up the path `+` in the environment. It finds that `+` is bound to another path object, `|add` (AST: `[path [pipe] [name 'add']]`). Because this is a piped path, an infix operation is triggered.
      - It performs the `add` operation: `(add 10 5)` evaluates to `15`.
      - The list effectively becomes `[15, *, 2]`.
      - Evaluator processes `15`.
      - Evaluator sees `*`. It looks up the path `*` in the environment, finds it is bound to `|multiply` (another piped path), and triggers another infix operation.
      - It performs the `multiply` operation: `(multiply 15 2)` evaluates to `30`.
      - The list is reduced to `[30]`.
  4.  **Final Assignment:** The value `30` is assigned to `result`.

This strict left-to-right evaluation without precedence means **parentheses are the only way to control the order of operations**: `10 + (5 * 2)` is required to perform the multiplication first.

The evaluator uses a **Uniform Call Syntax** to determine how to interpret a list based on its structure and the types of the tokens inside:

- **Prefix Call:** `[function, arg1, ...]`
  - If the first element of a list evaluates to a `function` or `bound-method`, the remaining elements are evaluated as arguments and the function is called.
- **Implicit Pipe / Infix Call:** `[<value>, <piped-path>, arg1, ...]`
  - If the first element evaluates to a non-function value, the evaluator inspects the second element. If it is a piped path (e.g., one with an AST of `[path [pipe] [name 'add']]`), a pipe operation is triggered. The first value becomes the first argument to the piped path's target function.

### 1.3. Code Blocks `[...]` vs. Evaluation Groups

SLIP has several grouping operators, which fall into two fundamental categories: those that create unevaluated `code` objects, and those that immediately evaluate their contents.

- **`[...]` – A Literal Code Block.** This is the fundamental operator for creating unevaluated code. It produces a `code` object, which is an Abstract Syntax Tree (a list of lists) that can be stored, manipulated, or passed to functions. Expressions within the block can be separated by newlines or semicolons (`;`), allowing multiple expressions on one line (e.g., `[x: 1; y: x + 3]`). The code inside is not executed until explicitly run. This is the foundation of SLIP's function-controlled evaluation and metaprogramming. Square-bracket nesting also introduces its own lexical scope for `path:` bindings made inside.

- **Evaluation Groups & Constructor Literals: `(...)`, `#[...]`, `#{...}`, `{...}`.** These operators create and immediately evaluate a nested expression. Their result is passed to the surrounding expression.
  - `(...)` – The **general evaluation group**. Evaluates the code inside and returns the result of the final expression. Expressions within the group can be separated by newlines or semicolons (`;`). This is the primary mechanism for controlling the order of operations.
  - `#[...]` – A **list literal**. This is constructor syntax that is functionally equivalent to `list [...]`. It evaluates the code inside and returns the results as a `list`.
  - `#{...}` – An **env literal**. This is constructor syntax that is functionally equivalent to `env [...]`. It evaluates the code inside (typically assignments, which can be separated by newlines or semicolons) and returns a new `env` object linked to the current scope.
  - `{...}` – A **dict literal**. This is constructor syntax that is functionally equivalent to `dict [...]`. It evaluates the code inside (typically assignments, which can be separated by newlines or semicolons) and returns a new `env` object with its parent link severed (a simple dictionary).

## 2. Data Types, Literals, and Comments

This chapter details SLIP's fundamental data types, the syntax for creating them (literals), and how to add comments to code.

### 2.1. Comments

SLIP supports two types of comments for annotating code.

- **Single-line:** A double slash (`//`) comments out the rest of the line. To resolve the ambiguity between a comment and a path that could start with `//`, the parser enforces a safety rule: the `//` sequence is only treated as a comment if it is immediately followed by a whitespace character or the end of the line. This rule prevents accidental commenting and also prohibits paths from containing `//`.
- **Multi-line:** A slash-asterisk (`/*`) begins a block comment, which is terminated by an asterisk-slash (`*/`). Block comments are **nestable**, allowing large sections of code to be commented out safely, even if they already contain other block comments.

```slip
// This is a single-line comment.
x: 10 // Assign 10 to x.

/*
  This is a block comment.
  It can span multiple lines.
  /* Nesting is supported! */
*/
```

### 2.2. Literals and Core Data Types

The following table summarizes the literal syntax for SLIP's core data types.

| Type        | Literal Syntax       | Example                        | Description                                                                                                                                                                                                             |
| :---------- | :------------------- | :----------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **number**  | `123`, `-50`, `3.14` | `x: -99.5`                     | Represents both integers and floating-point values.                                                                                                                                                                     |
| **string**  | `"..."`, `'...'`     | `msg: "Hello, {{name}}!"`      | Double-quoted strings support `{{...}}` interpolation and automatic de-denting. Single-quoted strings are raw and do not interpolate.                                                                                   |
| **path**    | `` `path.name ``     | `` `user.profile.name ``       | An explicit path literal. An unquoted name is treated as a path to be looked up in the environment. The backtick prevents this lookup, creating a literal `path` object as a value, similar to a quoted symbol in LISP. |
| **none**    | `none`               | `result: none`                 | Represents the absence of a value. An empty evaluation group `()` also evaluates to `none`.                                                                                                                             |
| **boolean** | `true`, `false`      | `is_active: true`              | The boolean values `true` and `false`.                                                                                                                                                                                  |
| **code**    | `[...]`              | `my_code: [x + 1]`             | An **unevaluated** block of code, represented as a first-class `code` object (an AST). This is the foundation of metaprogramming.                                                                                       |
| **list**    | `#[...]`             | `items: #[1, "a"]`             | A **list literal**. The expressions inside are evaluated, and the results are collected into a new `list` object. Functionally equivalent to `list [...]`.                                                              |
| **dict**    | `{...}`              | `data: {key: "val"}`           | A **dictionary literal**. Creates a simple key-value store. It is an `env` object with no parent scope. Functionally equivalent to `dict [...]`.                                                                        |
| **env**     | `#{...}`             | `config: #{host: "localhost"}` | An **environment literal**. Creates a new `env` object that is lexically linked to its parent scope. Functionally equivalent to `env [...]`.                                                                            |

**A Note on `none`**: The `none` keyword is the canonical representation for the absence of a value. An empty evaluation group `()` also evaluates to `none`, and the expression `(eq none ())` is true.

### 2.3. Data Type Semantics

- **Path Equality:** Two `path` objects are considered equal if their canonical string representations are identical.
- **Mutable Containers:** `list`, `dict`, and `env` are mutable reference types. Assigning a container to a new variable creates a reference to the original container, not a copy. Any modifications made through one reference will be visible through all other references to that container. Use the `copy` (shallow) or `clone` (deep) functions to create a new, independent instance.

### 2.4. Dynamic Property Access with `[]`

SLIP distinguishes between static and dynamic property access. While the dot (`.`) is used for static, literal property names (`player.hp`), square brackets (`[]`) are the universal operator for dynamic access, where the key is a computed expression. This mechanism applies to all collection types, including `list`s, `string`s, `dict`s, and `env`s.

- **Positional Access (Indexing and Slicing):** For lists and strings, `[]` can be used for zero-based indexing and slicing. The expression inside the brackets is evaluated to produce a numeric index or a slice range.

  ```slip
  items: #["a", "b", "c", "d", "e"]

  // Indexing with a variable
  idx: 2
  third_item: items[idx] // -> "c"

  // Slicing
  sub_list: items[1:4] // -> #["b", "c", "d"]
  ```

- **Key-based Access (Dynamic Lookups):** For `dict` and `env` objects, `[]` retrieves a value using a key. This is the idiomatic way to access properties when the name of the property is determined at runtime (e.g., stored in a variable or iterated over).
  ```slip
  // The idiomatic way to perform dynamic lookups
  player: #{ hp: 100, mp: 50, stamina: 75 }
  foreach key ["hp", "mp", "stamina"] [
      print player[key]
  ]
  ```

This makes `[]` a powerful and consistent tool for all forms of dynamic data access.

## 3. Assignment and Functions

The two most fundamental operations in SLIP are assigning values to paths and creating functions. SLIP has a single, powerful assignment operator (`:`) that handles all binding through pattern matching, and a single function constructor (`fn`) for creating closures.

### 3.1. Assignment (`:`): The Path-Pattern Matching Model

SLIP's grammar has only one special syntactic construct: assignment, denoted by the colon (`:`). Its power comes from the fact that the Left-Hand Side (LHS) is not an expression to be evaluated, but a **literal, unevaluated pattern**. The evaluator inspects the _structure_ of this pattern to determine which of several binding strategies to apply.

This single, powerful `:` form unifies simple binding, destructuring, slice manipulation, and even dynamic, computed targets.

#### Assignment Strategies

Here are the different binding strategies determined by the pattern on the left-hand side of the `:`:

- **1. Simple Binding**

  - **Behavior:** Binds a single value to a single path. This is the most common form of assignment.
  - **Syntax:** `path.to.value: expression`
  - **Example:** `user.name: "John"`

- **2. Destructuring Binding**

  - **Behavior:** Binds elements from a list on the right to multiple paths defined in a list pattern on the left. The number of paths must match the number of elements.
  - **Syntax:** `[path1, path2, ...]: list-expression`
  - **Example:** `[x, y]: #[10, 20]`

- **3. Slice Replacement**

  - **Behavior:** Replaces a slice of a target list with the elements from another list.
  - **Syntax:** `list[start:end]: new-list-expression`
  - **Example:** `items[1:3]: #["new", "items"]`

- **4. Vectorized (Columnar) Binding**

  - **Behavior:** A "columnar" operation that sets a property on _every item_ within a list slice. If the right-hand side is a value, it's applied to all items. If it's a list, values are assigned element-wise and the list lengths must match.
  - **Syntax:** `list[start:end].property: value-or-list-expression`
  - **Example:** `users[:10].is-active: false`

- **5. Parent Scope Binding**

  - **Behavior:** Modifies a binding in an outer scope. Each leading `../` prefix climbs one level up the parent environment chain before performing the assignment.
  - **Syntax:** `../path: expression`
  - **Example:** `../counter: counter + 1`

- **6. Dynamic (Programmatic) Binding**
  - **Behavior:** The "metaprogramming" escape hatch. The parenthesized expression on the left is evaluated _first_ to produce a target pattern (e.g., a `path` or a list of `paths`). The assignment is then performed on that dynamically generated target.
  - **Syntax:** `(expression-that-yields-a-path): value-expression`
  - **Example:** `(path.join `user `name): "John"`

### 3.2. Function Definition (`fn`)

The `fn` primitive is the constructor for the `function` data type. It creates a `function` object, which is a closure that bundles a parameter list and a `code` object with the environment in which it was created.

There is no `def` keyword. To create a named function, you simply create an anonymous function with `fn` and assign it to a path using the standard `:` assignment operator.

```slip
// Create a named function 'double'
double: fn [x] [
    x * 2
]

// Create an anonymous function and store it in a dictionary
actions: {
   "on-click": fn [event] [ print "Clicked!" ],
   "on-hover": fn [event] [ print "Hovered!" ]
}
```

Use named functions for top-level, reusable logic. Use anonymous `fn` when you need a `function` object as a value, such as for an event handler or a dictionary value.

Functions can also accept a variable number of arguments. See Section 3.4 for details on defining variadic functions.

### 3.3. A Note on Truthiness

SLIP adopts Python's standard rules for what is considered "truthy" or "falsey".

A value is considered "falsey" if it is:

- The boolean `false`
- The value `none` (which an empty evaluation group `()` evaluates to)
- Numeric zero (`0` or `0.0`)
- Any empty collection, such as:
  - An empty string (`''` or `""`)
  - An empty list (`#[]`)
  - An empty dictionary (`{}`)

All other values are considered "truthy".

Example:

```slip
// An empty list is falsey, so the 'else' block runs.
active-players: #[]
if active-players [
    print "There are players online."
] [
    print "The server is empty."
]
// --- Expected Output ---
// The server is empty.
```

### 3.4. Variadic Functions (Rest Parameters)

SLIP functions can be made "variadic," meaning they can accept a variable number of arguments. This is achieved by defining a "rest" parameter, which collects all extra arguments into a list.

Syntax: To create a rest parameter, add three dots (...) after the name of the last parameter in a function's definition. A function can have only one rest parameter, and it must be the final one.

Behavior: When the function is called, all arguments provided after the regular parameters are gathered into a single list and assigned to the rest parameter.

Example: A General-Purpose Logger

```slip
// 'tags...' is a rest parameter. It will become a list.
log-event: fn [event-type, tags...] [
    print "Event: {event-type}"
    print "Tags: {tags}"
]

// Call it with several arguments
log-event "player-login" "level:5" "guild:knights" "region:west"

// --- Expected Output ---
// Event: player-login
// Tags: ["level:5", "guild:knights", "region:west"]
```

If no extra arguments are provided, the rest parameter simply becomes an empty list.

```slip
log-event "server-startup"

# --- Expected Output ---
# Event: server-startup
# Tags: []
```

This feature is the key to writing powerful, general-purpose utility functions, as seen in the core.slip library with functions like `partial` and `compose`.

---

## 4. Infix Syntax and the Pipe Operator

SLIP's intuitive, left-to-right syntax for chaining operations is not the result of special parsing rules or transformations. Instead, it emerges naturally from the evaluator's **Uniform Call Syntax** and the concept of **piped paths**.

### 4.1. The Implicit Pipe Call

The evaluator uses a simple, type-driven rule to handle function calls within a flat list:

- **Prefix Call:** If the first element is a `function`, it's a standard prefix call (e.g., `add 1 2`).
- **Implicit Pipe / Infix Call:** If the first element is a non-function value, the evaluator checks if the _second_ element is a **piped path**. If so, it triggers an implicit pipe call, using the first value as the first argument to the function indicated by the piped path.

A piped path is a path with a special `pipe` component in its AST, such as `[path [pipe] [name 'add']]`. The `|` character is the syntactic sugar for creating them (e.g., `|add`).

### 4.2. Infix Syntax in Practice

Familiar infix syntax is just a convenient way to trigger the implicit pipe call rule. Operators like `+`, `-`, and `*` are simply paths in the environment that are bound to piped paths.

**Example: Evaluating `10 + 5`**

1.  **Parsing:** The parser sees `10 + 5` and produces a flat AST: `[<number 10>, [path [name '+']], <number 5>]`.
2.  **Evaluation:**
    - The evaluator processes the list. The first item, `10`, is a value, not a function.
    - It looks at the second item, the path `+`. It resolves this path in the environment and finds it is bound to the _piped path_ `|add` (AST: `[path [pipe] [name 'add']]`).
    - This triggers the **Implicit Pipe Call** rule. The evaluator calls the `add` function, passing `10` as the first argument and `5` as the second. The expression is evaluated as if it were `add 10 5`.
    - The result is `15`.

This mechanism works for chained operations as well. The expression `10 + 5 * 2` is evaluated strictly left-to-right: `(add 10 5)` is executed first, yielding `15`, which then becomes the input to the next operation, `(multiply 15 2)`, yielding `30`.

### 4.3. The Explicit Pipe Operator `|`

The pipe operator `|` is the explicit way to create a piped path and chain operations. It is not a special operator; it is syntactic sugar that modifies the path immediately following it.

- `data |map [ ... ]` is parsed as `[expr [path [name 'data']], [path [pipe] [name 'map']], [code ...]]`
- The evaluator sees `data` (a value) followed by `|map` (a piped path), triggering the same implicit pipe call rule used for infix math.

### 4.4. Operator Definitions

To define a new operator, you simply bind a path to a piped path. A forward slash `/` is used to create a path from the root environment, which is necessary for defining symbolic operators that might otherwise be misinterpreted by the parser.

```slip
// The 'add' function must already exist.
add: fn [a b] [ a + b ] // or implemented in host language

// Bind the root path '/+' to the *piped path* '|add'.
/+: |add

// Now the infix expression '10 + 20' will work.
```

The following table lists the default operator bindings provided by the standard environment.

| Operator | Bound Piped Path |
| :------- | :--------------- | ------------ |
| `+`      | `                | add`         |
| `-`      | `                | sub`         |
| `*`      | `                | mul`         |
| `/`      | `                | div`         |
| `**`     | `                | pow`         |
| `=`      | `                | eq`          |
| `!=`     | `                | neq`         |
| `>`      | `                | gt`          |
| `>=`     | `                | gte`         |
| `<`      | `                | lt`          |
| `<=`     | `                | lte`         |
| `and`    | `                | logical-and` |
| `or`     | `                | logical-or`  |

### 4.5. Controlling Order of Operations

Because SLIP evaluates strictly from left to right, you must use parentheses `()` to control the order of operations. The code inside the parentheses is evaluated as a complete, separate expression, and its final result is then used as a single value in the outer expression.

```slip
// Default left-to-right evaluation
// Equivalent to (multiply (add 10 5) 2)
result: 10 + 5 * 2  // result is 30

// Using parentheses to force a different order.
// The group (5 * 2) is evaluated first, resulting in 10.
// The expression then becomes equivalent to 10 + 10.
result: 10 + (5 * 2) // result is 20
```

This explicit, predictable system is a core feature of SLIP's design, favoring clarity and simplicity over hidden precedence rules.

### 4.6. Chained Pipe Example

The left-to-right evaluation model makes chaining multiple pipe operations highly readable and intuitive.

- **Example: `data |filter [x > 10] |map [x * 2]`**

  Assuming `data` is `#[1, 15, 20]`, the evaluation proceeds as follows:

  1.  The evaluator processes `data`, resulting in the list `#[1, 15, 20]`.
  2.  It then sees the pipe operator `|` followed by `filter`. An implicit pipe call is triggered: `filter #[1, 15, 20] [x > 10]`.
  3.  The result of the filter call is `#[15, 20]`. This value becomes the input for the next step.
  4.  The evaluator processes this new value, `#[15, 20]`, followed`. It triggers`. It triggers`. It triggers another pipe call: `map #[15, 20] [x * 2]`.
  5.  The result of the map call is `#[30, 40]`.
  6.  This is the final result of the entire expression.

## 5. The Prototype-Based Object Model

SLIP's object-oriented system is not based on classical inheritance with `class` blueprints. Instead, it uses a flexible and powerful **prototype-based model**, similar to languages like JavaScript, Self, and Lua. In this model, objects inherit behavior and data directly from other objects.

The `env` data type is the foundation of this system. Every `env` object can have a link to a `parent` environment, which acts as its **prototype**. When a path is looked up on an object (e.g., `player.hp`), the interpreter first checks the object itself. If the path is not found, it automatically searches the object's prototype, then the prototype's prototype, and so on, up the chain until it reaches the root.

### 5.1. The "Smart Dot" Method Call

The dot (`.`) in a path expression (e.g., `object.method`) enables an ergonomic and encapsulated way to call methods. This is often referred to as the "Smart Dot."

- **Mechanism:** When the evaluator resolves a path like `obj.method`, it first resolves `obj`. It then looks for `method` within the `obj` environment and its prototypes. If the final value found for `method` is a `function`, it is not returned directly. Instead, the evaluator triggers a **contextual call**.
- **Semantics:** The found function is executed immediately, and its **return value becomes the result of the entire path expression**. The base object (`obj`) is automatically passed as the first argument (conventionally named `self`). Crucially, the function executes in its original lexical scope (its closure), not the scope of the object. This preserves encapsulation, as the method can only access its own closed-over state and the state of the object passed to it via `self`. This behavior is conceptually equivalent to creating a temporary `bound-method` object at the time of the call.

### Example: Method Call vs. Pipe Call

It is important to distinguish the "smart dot" method call from a standard implicit pipe call.

```slip
// Method call:
// 1. Finds the `describe` function on `my-car` or its prototypes.
// 2. Calls it, passing `my-car` as the first argument (`self`).
// 3. Executes in the function's original definition scope, preserving encapsulation.
my-car.describe

// Pipe call:
// 1. `process` must be a function found in the CURRENT scope.
// 2. The value of `my-car` is piped in as the first argument to `process`.
// 3. This is a standard function call, not an object-oriented one.
my-car |process
```

### 5.2. The "404 Response" (Message Not Understood)

To support dynamic dispatch and resilient objects, SLIP has a built-in mechanism for handling method calls where the target method is not found. This is inspired by Smalltalk's "message not understood" concept.

If a method call `obj.method` fails because the `method` path is not found within the object or its prototype chain, the evaluator does not immediately raise an error. Instead, it performs a second search within `obj` for a special method named `handle-missing-message`.

- **If `handle-missing-message` is found:** It is called with three arguments: the original object (`obj`), the name of the missing method (as a `path` object, e.g., `` `method ``), and a `list` containing the original arguments of the failed call. This allows the object to dynamically handle the call, implement proxies, or provide more helpful error messages.
- **If `handle-missing-message` is not found:** Only then is a structured error `Response` returned. This response will have a status of `404 Not Found`, indicating the path could not be resolved within the object. (See Section 12.5 for a complete list of error codes).

### 5.3. Establishing Prototypes: `inherit` and Lexical Scoping

A prototype link is the backbone of inheritance. SLIP provides two primary ways to establish this link, offering both explicit control and contextual convenience.

#### Explicit Inheritance with `inherit`

The `inherit` function is the most direct and flexible way to set an object's prototype.

- `inherit <child-env> <parent-env>`: This function sets the `parent` link of the `child-env` to be the `parent-env`.

The most common and idiomatic way to use `inherit` is with the pipe operator (`|`) during object creation. This allows for a fluid, single-expression definition of an object and its prototype.

```slip
// Define a 'base-character' object to act as our prototype.
// We use `{...}` to ensure it has no parent of its own.
base-character: {
    hp: 100
    describe: fn [self] [ "A character with {self.hp} HP." ]
}

// Create a new 'player' object and immediately set its prototype.
player: #{ name: "Kael" } |inherit base-character

// Now, the 'player' object can access properties from 'base-character'.
player.hp          // -> 100 (found in the prototype)
player.describe    // -> "A character with 100 HP."
player.name        // -> "Kael" (found in the player object itself)
```

This pattern is powerful because it allows an object to inherit from any other object in the system, regardless of where it was defined.

#### Implicit (Lexical) Inheritance with `#{...}`

For convenience, the `env` literal (`#{...}`) automatically sets the new object's prototype to be the **current lexical scope**. This is useful for creating helper objects or namespaces that are tightly coupled to their defining context.

```slip
// The 'level' object contains some base stats.
level: #{
    monster-hp: 50

    // 'goblin' is created here. Its prototype is the 'level' env.
    goblin: #{
        name: "Gragnok"
    }

    goblin.monster-hp // -> 50 (found in the lexical parent/prototype)
}
```

While useful, the explicit `inherit` function is generally preferred for building clear and decoupled object hierarchies.

### 5.4. Composition vs. Inheritance: The `mixin` Function

Inheritance (prototyping) is about establishing an "is-a-kind-of" relationship. Composition, on the other hand, is about giving an object new capabilities, an "has-a" relationship. The `mixin` function is SLIP's primary tool for composition.

`mixin` works by **copying** all the key-value pairs from one or more source objects into a target object. It does not change the target's prototype link.

```slip
// A mixin for things that can fly. It's a simple data object.
can-fly: {
    altitude: 0
    fly: fn [self] [ self.altitude: 100 ]
}

// Our player object from before.
player: #{ name: "Kael" } |inherit base-character

// Now, give the player the ability to fly.
mixin player can-fly

// The 'fly' method and 'altitude' property are now part of the player object itself.
player.fly
player.altitude // -> 100
```

This approach keeps object relationships flat and explicit, avoiding the complexities of deep inheritance chains and making code easier to reason about.

## 6. Control Flow

In SLIP, control flow is not managed by special keywords but by standard functions that operate on unevaluated code blocks (`[...]`). This approach preserves the language's uniformity and empowers metaprogramming. While some core primitives like `if` and `while` must be provided by the host environment to control evaluation, they are called just like any other function.

### 6.1. Conditional Execution

#### `if`

The `if` primitive is the fundamental conditional. It takes three arguments: a condition code block, a `then` code block, and an `else` code block. It first evaluates the condition code block; if the result is truthy, it evaluates the `then` code block, otherwise it evaluates the `else` code block. The `else` block is not optional. Crucially, only one of the branch code blocks is ever evaluated. The `if` expression evaluates to the value of the executed code block. For a conditional without an `else` branch, see the `when` function.

```slip
age: 25
message: if [age >= 18] [
    "Access Granted"
] [
    "Access Denied"
]
// message is now "Access Granted"
```

For cases where no `else` action is needed, the `when` function (from the core library) provides a more concise alternative. The `cond` function provides a multi-branch conditional similar to a `switch` statement.

### 6.2. Looping

#### `while`

The `while` primitive executes a body code block as long as its condition code block evaluates to a truthy value. It takes two code block arguments: a condition and a body. The loop evaluates to the value of the last expression in the final iteration, or `none` if the loop never runs.

```slip
i: 3
while [i > 0] [
    print i
    i: i - 1
]
// --- Output ---
// 3
// 2
// 1
```

#### `for`

The `for` function (provided by the standard library) offers a convenient way to loop a specific number of times. It takes a control `code` block and a body `code` block. The control block specifies the loop variable and the parameters for a numeric range.

- **Looping up to a value (from 0):**

  ```slip
  // Loop with i = 0, 1, 2, 3, 4
  for [i, 5] [
      print "Looping, i is {i}"
  ]
  ```

- **Looping between two values:**

  ```slip
  // Loop with i = 2, 3, 4
  for [i, 2, 5] [
      print "Looping, i is {i}"
  ]
  ```

- **Looping with a step:**
  ```slip
  // Loop with i = 0, 2, 4, 6, 8
  for [i, 0, 10, 2] [
      print "Looping, i is {i}"
  ]
  ```

#### `foreach`

The `foreach` function is the most versatile tool for iterating over collections. It takes a variable pattern, a collection expression, and a body `code` block.

- **Iterating over a List:**
  When iterating over a list, the variable pattern is a path that is assigned each element in sequence.

  ```slip
  foreach fruit #["apple", "banana"] [
      print "I like to eat {fruit}s."
  ]
  ```

- **Iterating over a Dictionary:**
  When iterating over a dictionary, the loop yields a `[key, value]` pair. The variable pattern can be a `code` block to destructure the pair into separate variables.

  ```slip
  scores: {"Kael": 100, "Jaina": 150}
  foreach [name, score] scores [
      print "{name} has a score of {score}."
  ]
  ```

### 6.3. Function Exit

#### `return`

The `return` primitive terminates the execution of the current function and provides a return value.

- `return [value]`: Exits the function, returning the given `value` (or `none` if not provided). This is achieved by creating a `Response` object with `status: 'return'`, which is then handled by the function evaluation machinery.

## 7. Outcomes and Side Effects

A script communicates its results to the wider system in two distinct ways: by producing a final **outcome** and by generating a stream of **side effects**. SLIP provides two separate, complementary mechanisms for this: the `response` type for outcomes and the `emit` function for side effects.

### 7.1. The `response` Data Type for Outcomes

The `response` is a first-class data type that represents the structured outcome of a function call. It is the primary tool for handling both success and predictable failure cases, and it is the mechanism that powers non-local control flow.

A `response` object is an immutable structure with two components:

- **`status`**: A `path` that categorizes the outcome (e.g., `` `ok ``, `` `err ``).
- **`value`**: The payload associated with the outcome (can be any data type).

You create a `response` using the `response` constructor: `response <status-path> <value>`.

### 7.2. The `respond` and `return` Primitives

To use a `response` to control function execution, you use the `respond` primitive.

- `respond <status-path> <value>`: This is the primary function for exiting the current function with a structured outcome. It creates a `response` and immediately triggers a non-local exit, making that `response` the return value of the function.

For the common case of simply returning a value without a special status, SLIP provides the familiar `return` primitive.

- `return <value>`: This is syntactic sugar for `respond `return <value>`.

When the interpreter encounters a `response` with the status `` `return ``, it "unwraps" it, and the function call evaluates to the `response`'s inner `value`. For any other status (like `` `ok `` or `` `err ``), the `response` object itself is returned as a whole.

### 7.3. Standard Statuses and Convenience Aliases

To promote consistency, SLIP defines a set of standard canonical `path`s for common statuses.

| Canonical Path   | Typical Meaning                                                                      |
| :--------------- | :----------------------------------------------------------------------------------- |
| `` `ok ``        | The operation completed successfully. The `value` is the result.                     |
| `` `err ``       | A predictable, handleable error occurred. The `value` is an error message or object. |
| `` `not-found `` | A specific kind of error for when a requested resource does not exist.               |
| `` `invalid ``   | A specific kind of error for when input data is invalid.                             |
| `` `return ``    | The special status used by `return` for a normal function exit.                      |

To avoid the need to constantly type backticks for these common paths, the SLIP core library provides a set of convenient, unquoted aliases. These are simply variables that are bound to the canonical path literals.

```slip
// From core.slip:
ok:        `ok
err:       `err
not-found: `not-found
invalid:   `invalid
// 'return' is a primitive and does not need an alias.
```

This allows you to write cleaner, more readable code.

**Good:** `respond ok player-obj`
**Verbose:** `respond `ok player-obj`

### 7.4. `emit` for Side Effects

The `emit` function is completely separate from the `response` system. Its sole purpose is to log a side-effect event for the host application to process. It adds an event to the `ExecutionResult.side_effects` list but has **no effect on the script's control flow**.

This creates a clean separation: `respond` determines _what the function returns_, while `emit` determines _what the function tells the outside world_.

**Example: Using Both Systems Together**

```slip
find-player: fn [name] [
    player-obj: (host-object name)
    if player-obj [
        // Outcome: Success. Use the 'ok' alias.
        respond ok player-obj
    ] [
        // Side Effect: Log the failure for the server admin.
        emit "debug" "Failed to find player object for name: {name}"

        // Outcome: Failure. Use the 'not-found' alias.
        respond not-found "That player is not online."
    ]
]
```

### 7.5. Handling Outcomes with Pattern Matching

The true power of this system is realized when `response` objects are handled by pattern-matching `method`s. For the purpose of pattern matching, a `response` behaves as if it were a two-element list: `[status, value]`.

You can use the standard aliases directly in the patterns. The matcher will compare the incoming status `path` with the `path` stored in the alias variable.

```slip
// A generic function to handle the outcome of our search.
handle-find-result: method [ [ok, player] ] [] [
    // This pattern matches a response whose status is equal to the
    // value of the 'ok' variable (which is the path `ok`).
    // It destructures the response, binding its value to 'player'.
    emit "system" "Found player: {player.name}"
    player |do-something
]
handle-find-result: method [ [not-found, reason] ] [] [
    // This pattern matches a response with status `not-found`.
    emit "ui.error" reason // Show the error to the user
]
handle-find-result: method [ other ] [] [
    // A fallback for any other kind of response or value.
    emit "error" "Received an unexpected result: {other}"
]

// --- Usage ---
outcome: find-player "Kael"
handle-find-result outcome // Will call the appropriate method based on the response.
```

This combination of `emit`, `respond`, and pattern matching provides a highly robust and expressive system for managing all facets of a script's execution.

## 8. Advanced Features and Patterns

This chapter details several powerful features that build upon SLIP's core principles, enabling advanced programming patterns like multiple dispatch, programmatic data manipulation, and sophisticated string processing.

### 8.1. Multiple Dispatch (Generic Functions)

SLIP supports multiple dispatch (also known as multimethods or generic functions) as a powerful alternative to traditional single-dispatch object-orientation. This allows a function's behavior to be specialized based on dynamic properties of its arguments, not just the type of a single `self` object.

This is achieved through the `method` primitive and the standard assignment operator (`:`). There is no need for a separate `generic` function to create a dispatch container; it is handled automatically.

- **`method`**: Creates a specialized, dispatchable method. Multiple methods can be assigned to the same path to build a generic function.

#### Defining and Using Methods

1.  **Creation**: You define a method using the `method` primitive, which takes an argument list, a predicate code block, and a body code block.
    `method <arg-list> <predicate-block> <body-block>`

2.  **Assignment**: When you assign a `method` to a path for the first time, SLIP automatically creates a "generic function" container at that path and adds the new method to it.

    ```slip
    // The first assignment to 'render' creates the generic function.
    // The predicate checks if the object's `type` property is `player`.
    render: method [obj] [obj.type = `player] [
        "Player: {obj.name}"
    ]
    ```

3.  **Adding More Methods**: Subsequent assignments of a `method` to the same path add new dispatch options to the existing generic function.

    ```slip
    // This adds a new case to the 'render' generic function.
    render: method [obj] [obj.type = `item] [
        "Item: {obj.name}"
    ]
    ```

4.  **Adding a Fallback Method**: You can also assign a method with an empty predicate block to the same path. This method acts as a default implementation that is called only if no other method predicates match.

    ```slip
    // This adds a fallback for any object that doesn't match a method.
    render: method [obj] [] [
        "Unknown object: {obj.name}"
    ]
    ```

5.  **Dispatch**: When the generic function (`render`) is called, it first iterates through its list of registered methods. For each method, it executes the predicate block with the call arguments. The body of the _first_ method whose predicate returns a truthy value is executed, and its result becomes the return value of the call. If no method predicates match, the evaluator then checks for a fallback `fn`. If a fallback is present, it is called with the original arguments. If there is no fallback, it returns an error reponse.

#### Example Usage

With the methods and fallback method defined above, we can see the complete behavior:

```slip
player1: #{name: "Kael", type: `player}
sword: #{name: "Frostmourne", type: `item}
rock: #{name: "granite", type: `scenery}

render player1  // -> "Player: Kael"
render sword    // -> "Item: Frostmourne"
render rock     // -> "Unknown object: granite"
```

This pattern allows for highly extensible systems, where new behaviors can be added to existing functions without modifying their original definitions. The predicate can be any code that evaluates to a boolean, allowing for dispatch based on type, value, or any other computable condition on the arguments.

### Section 8.2: Interpolated and Formatted Strings

This section has been rewritten to detail the new Jinja2-based mechanism.

- **Interpolation:** Expressions are embedded using double curly braces `{{...}}`. The expression inside the braces is evaluated within the current SLIP environment, and its result is inserted into the string.
- **Automatic Formatting:** The de-denting and blank line trimming rules remain the same.
- **New Example:**

  ```slip
  indent_level: 4
  formatted_text: "
      This line is indented by {{ indent_level }} spaces.
      The next line is also indented.
  "
  ```

- **Updated AST Explanation:** The explanation of the parsed Abstract Syntax Tree now clarifies that the parser identifies the literal string parts and the expressions to be interpolated. The evaluator is then responsible for passing this structure, along with the current environment, to a Jinja2-like rendering engine.

  The example AST has been updated to reflect the new expression marker:

  ```
  [ [set-path [name 'formatted_text']],
    [string
      "This line is indented by ",
      [expr [path [name 'indent_level']]],
      " spaces.\nThe next line is also indented."
    ]
  ]
  ```

- **Final Result:** The resulting string remains the same, demonstrating that the underlying logic is preserved:
  `"This line is indented by 4 spaces.\nThe next line is also indented."`

These changes ensure the language reference is now consistent with your plan to use a Jinja2 engine for processing interpolated strings, leveraging its well-understood syntax and powerful features.

### 8.3. Configuring Objects with `with`

A common programming pattern is to create or retrieve an object and then immediately set multiple properties or call several methods on it. The traditional approach can be verbose and repetitive:

```slip
// The verbose, multi-statement way
config: #{ }
config.host: "domain.com"
config.port: 200
config.retries: 3
```

To make this pattern more concise and expressive, the SLIP standard library provides the `with` function. It is designed to be used with the pipe operator (`|`) to execute a block of code "within the context of" an object, making it ideal for configuration in a single, fluid expression.

- **Syntax:** `target-expression |with [ configuration-block ]`

- **Semantics:** The `with` function provides a concise way to modify an object.
  1.  The `target-expression` on the left is evaluated to produce an object.
  2.  This object is then piped as the first argument to the `with` function.
  3.  The `with` function takes the piped-in object and executes the `configuration-block` using that object as its temporary environment (via the `run-with` primitive). All assignments and method calls inside the block operate directly on the target object.
  4.  Crucially, the `with` function returns the **original target object**, not the result of the configuration block. This allows the configured object to be immediately assigned or passed to another function.

#### Example: Object Configuration

Using the `with` function, the verbose example above can be rewritten as a single, clean expression:

```slip
// Using the 'with' function for inline configuration
config: #{ } |with [
    host: "domain.com"
    port: 200
    retries: 3
]

// The value of 'config' is now the fully configured environment:
// #{ host: "domain.com", port: 200, retries: 3 }
```

The single-line version is also highly effective for concise setup:

```slip
config: #{ } |with [host: "domain.com"; port: 200; retries: 3]
```

#### `with` is Just a Function

It is important to understand that `with` is not a special keyword or operator. It is a regular function, likely provided by the host or core library, with a conceptual implementation like this:

```slip
// Conceptual implementation of the 'with' function
with: fn [obj, block] [
    // Run the code block in the context of the object
    run-with block obj

    // Return the original, now-modified object
    obj
]
```

Its power comes from combining the pipe operator for fluency with the `run-with` primitive for context switching. This pattern demonstrates how SLIP's core features can be composed to create powerful, high-level abstractions without adding complexity to the language itself.

## 9. Data Modeling and Validation

In any real-world application, data must be validated against an expected shape before being processed. SLIP provides a powerful, declarative system for this. The core principle is that **a schema is just a regular SLIP data structure**, and validation is performed by standard library functions.

### 9.1. The Schema: A Simple Dictionary

You define the "shape" of your data by creating a simple `dict` or `env`. This is your schema. The keys are the expected field names, and the values are expressions that define the type and constraints for that field.

```slip
// A schema for a User object. It's just a dictionary.
UserSchema: {
    name: string,
    age: number,
    is-active: boolean
}
```

### 9.2. The `validate` and `create` Functions

Two primary functions work with these schemas:

- **`validate <data> <schema>`**
  This function checks if the given `data` conforms to the `schema`. It does not modify the data or apply defaults. It returns a `response`:

  - `response ok ()`: If the data is valid.
  - `response err <list-of-errors>`: If the data is invalid, containing a detailed list of all errors.

- **`create <data> <schema>`**
  This is the main function for data ingestion. It validates the `data` against the `schema`, applies any default values, and returns a new, clean object. It also returns a `response`:
  - `response ok <validated-object>`: If successful, the value is the new, validated object.
  - `response err <list-of-errors>`: If validation fails.

The most idiomatic way to use these is with the pipe operator (`|`).

### 9.3. Basic Usage

```slip
// Use `create` to ingest and validate raw data.
raw-data: {name: "Alice", age: 30, is-active: true}
outcome: raw-data |create UserSchema

// The `create` function returns a `response`.
// On success, the value is a clean, validated dictionary.
if (outcome.status = ok) [
    validated-user: outcome.value
    print "User created: {validated-user.name}"
]
```

### 9.4. Robust Error Handling

If the data does not match the schema, `create` and `validate` return a structured `err` response.

```slip
// Invalid data
raw-data: {name: 123, age: "thirty"} // Missing 'is-active', wrong types

// The call to `create` will not raise an error; it returns a response.
[status, errors]: raw-data |create UserSchema

// status is now `err`
// errors is a list of validation error objects:
// #[
//   {field: "name",      error: "expected type 'string', got 'number'"},
//   {field: "age",       error: "expected type 'number', got 'string'"},
//   {field: "is-active", error: "field is required"}
// ]
```

### 9.5. Advanced Schemas: Defaults and Optional Fields

The schema can use helper functions to specify more complex constraints. These helpers return special marker objects that `create` and `validate` know how to interpret.

- **`default <value>`:** Provides a default value if the field is missing from the input data.
- **`optional <type>`:** Marks a field as optional.

```slip
ConfigSchema: {
    host: string,
    port: (default 8080),
    user: (optional string)
}

// Example usage:
[ok, conf1]: {host: "localhost"} |create ConfigSchema
// conf1 is {host: "localhost", port: 8080} -- 'user' is omitted.
```

### 9.6. Composition: Nested Schemas

Schemas can be composed by using one schema as the type for a field in another. The validation is recursive.

```slip
// Define a User schema first
UserSchema: { name: string, email: string }

// Now define a Team schema that contains a User
TeamSchema: {
    team-name: string,
    leader: UserSchema, // The type is the UserSchema dictionary itself
    members: list
}

// Raw data with a nested object
raw-team-data: {
    team-name: "Dragons",
    leader: {name: "Alex", email: "alex@a.com"},
    members: #[]
}

// The validation will recursively validate the 'leader' object
// against the UserSchema.
[ok, team]: raw-team-data |create TeamSchema
```

This system provides a complete, robust, and declarative way to handle data validation, using nothing more than standard SLIP data structures and functions. It is the perfect embodiment of the language's philosophy.

## 10. Metaprogramming and Evaluation Control

In SLIP, metaprogramming is not a separate, compile-time system with special rules (like C macros or LISP's `defmacro`). It is a standard, runtime activity that leverages the fact that `code` objects are first-class data structures.

A `code` object (`[...]`) is a literal, unevaluated Abstract Syntax Tree. Because the parser creates a direct, 1:1 representation of the source code, the AST is a simple list of lists. This means you can inspect and manipulate code with standard list operations like indexing and slicing.

**Example: Manipulating Code with List Operations**

```slip
// A code block is just data.
my-code: [
    y: 1 + 2
    print y
]
```

Because the AST is a direct representation of the code, you can surgically extract parts of it:

- `my-code[0]` evaluates to a `code` object representing the first line: `[y: 1 + 2]`.
- `my-code[0][1:]` evaluates to a `code` object representing the right-hand side of the first line's expression: `[1 + 2]`. This works because the first line's AST is a list, and slicing it with `[1:]` drops the assignment target (`y:`).

This powerful feature allows code to be constructed, analyzed, and transformed programmatically at runtime. Evaluation is controlled by a small, powerful set of kernel functions.

### 9.1. Core Evaluation Functions

- `run <code>`: The primary function for executing a block of code. It evaluates the code within the current environment and returns the result of the last expression.
- `run-with <code> <env>`: Executes a code block within a specific environment.
- `list <code>`: Evaluates the expressions in a code block and collects all their results into a new `list`. This is the underlying function for the `#[...]` literal.
- `dict <code>`: Evaluates the expressions in a code block (typically assignments) and returns a new `env` object with its parent link severed. This is the underlying function for the `{...}` literal.
- `env <code>`: Evaluates the expressions in a code block and returns a new `env` object linked to the current scope. This is the underlying function for the `#{...}` literal.

### 9.2. Code Injection: `inject` and `splice`

`inject` and `splice` are special operators used inside a `code` block that is passed to `run` (or a similar function). They allow for the substitution of runtime values into the AST just before evaluation. They are used with function-call syntax.

- `(inject <path>)`: Looks up the `<path>` in the _calling_ environment (the one `run` was called from) and substitutes its value into the code being run. The value is injected as a single literal item.
- `(splice <path>)`: Similar to `inject`, but the value at `<path>` must be a `list` or `code` object. Its _contents_ are spliced into the code being run, effectively "unquoting" the list into the AST.

#### Example:

```slip
my-var: 10
my-list: #[20, 30]

run [
    result: (add (inject my-var) (splice my-list))
]
```

1.  `run` begins executing the `code` block.
2.  It finds the expression `(inject my-var)`. It looks up `my-var` in its calling scope, finds `10`, and replaces `(inject my-var)` with the literal value `<number 10>`.
3.  It finds the expression `(splice my-list)`. It looks up `my-list` in its calling scope, finds `#[20, 30]`, and replaces `(splice my-list)` with the contents of that list: `<number 20>, <number 30>`.
4.  The final expression to be evaluated becomes `(add 10 20 30)`. This evaluates to `60`, which is then assigned to `result`.

### 9.3. Dynamic Path and Function Creation

- `to-path <string>` (or `intern`): A crucial standard library function that converts a `string` into a `path` object. This is the primary mechanism for creating paths programmatically.

  - Example: `(to-path "user.name"): "John"`

- `fn <args-list> <code-body>`: The core function for creating new `function` objects (closures). `fn` captures the current lexical scope and bundles it with the argument list and the unevaluated body of code.
  - Example: `add-five: fn [x] [ x + 5 ]`

### 9.4. Operator Definition

Infix operators like `+`, `*`, `>`, etc., are not special syntax. They are simply names (paths) in the environment that are bound to `piped path` objects. The left-to-right evaluator triggers an implicit pipe call when it encounters one.

You define a new operator by binding its name to a piped path.

```slip
// The `add` function exists.
add: fn [a b] [ ... ]

// Bind the root path `+` to the *piped path* `|add`.
// Now `10 + 20` will work.
/+: |add

// This is NOT valid for infix use, as it would require a prefix call: `+ 10 20`
// /+: add
```

This demonstrates how SLIP's core evaluation rule (the implicit pipe call) is used to implement a familiar language feature without adding complexity to the parser or creating new data types.

## 11. Asynchronous Tasks

SLIP is an asynchronous language at its core, designed to integrate seamlessly with a host application's event loop (like Python's `asyncio`). This allows scripts to perform long-running operations, such as waiting for a timer, without freezing the entire application. The `task` primitive is the primary tool for managing this concurrency.

### 11.1. The `task` Primitive

The `task` primitive allows you to execute a code block in the background. The main script does not wait for the task to finish; it continues execution immediately.

- **Syntax:** `task <code-block>`
- **Behavior:**
  1.  The `<code-block>` is not evaluated immediately.
  2.  The interpreter schedules the block to be run as a new, independent, asynchronous task on the host's event loop.
  3.  The `task` command itself immediately returns a handle to the newly created task object. This handle can be stored but is often discarded.

**Example: A Delayed Action** (Assumes a host-provided `sleep` function)

```slip
// A player sets a magical, delayed trap.
print "You place a magical glyph on the floor. It will arm in 5 seconds."

task [
    // This code runs in the background.
    // `sleep` is a host function that pauses this task, but not the main script.
    sleep 5

    // After the delay, update a variable.
    world.trap-is-armed: true
    print "The glyph flashes once, now armed."
]

// The main script continues immediately without waiting for the sleep.
print "You step away from the glyph."
```

### 11.2. Task Safety and Cooperative Multitasking

A script running in a background task must be a "good citizen" and not monopolize the server's resources. SLIP's interpreter has a built-in safety mechanism to prevent infinite loops in tasks from freezing the application.

- **Automatic Yielding:** Inside a block started with `task`, the `while` and `foreach` loops will automatically "yield" control back to the host's event loop on each iteration (conceptually by performing a `sleep 0`). This allows the host to run other tasks (like processing commands from other players) before continuing the loop. This cooperative multitasking is essential for a stable multi-user environment.

**Example: A Long-Running Counter**

```slip
// A script creates a global countdown timer.
world-events: #{
    meteor-timer: 100
}

// Start a task to handle the countdown.
task [
    while [world-events.meteor-timer > 0] [
        // The `while` loop automatically yields here on each iteration,
        // preventing the server from freezing.
        world-events.meteor-timer: world-events.meteor-timer - 1
        sleep 1 // Wait one second between decrements.
    ]

    // This code runs after the loop finishes.
    print "A meteor streaks across the sky!"
]
```

### 11.3. Task Lifecycle and Management

Background tasks are tied to the `HostObject` that created them. This ensures that tasks are properly cleaned up when an object is removed from the game world (e.g., an NPC dies or a player logs out).

- **Registration:** When `task` is used, the created task is automatically registered with the `HostObject` that is the context of the current script.
- **Cancellation:** The `SLIPHost` base class provides a built-in API method, `cancel-tasks`, which can be called from SLIP or Python. This method finds all active tasks registered with that specific object and cancels them, preventing "zombie" scripts from running for objects that no longer exist.

**Example: A Player's Buff Timer**

```slip
// This script runs when the player drinks a "Potion of Strength".
print "You feel a surge of power!"

// Set the buff on the player object itself.
player.strength: player.strength + 5

// Start a task to remove the buff after 60 seconds.
// This task is automatically associated with the `player` host object.
task [
    sleep 60
    print "You feel the surge of power fade."
    player.strength: player.strength - 5
]

// If the player logs out before the 60 seconds are up, the game engine
// can call `player.cancel-tasks`, and this timer will be safely stopped.
```

### 11.4. Structured Concurrency with Channels

While tasks can communicate by modifying shared state (e.g., setting a property on a global object), this can sometimes lead to complex logic. As an alternative, SLIP supports **channels**, a powerful concurrency primitive inspired by languages like Go and Erlang.

A channel is a message queue that allows one task to safely send data to another. This is similar to a publish/subscribe system but is often used for more direct, point-to-point communication between a producer and a consumer. This pattern promotes a cleaner, more robust design for complex asynchronous workflows, following the philosophy: _"Do not communicate by sharing memory; instead, share memory by communicating."_

Channels are created and manipulated using host-provided functions.

- `make-channel`: Creates and returns a new channel object.
- `send <channel> <value>`: Sends a value into the channel. If the channel is full (if a size limit is implemented by the host), this call will **asynchronously pause** the current task until there is space.
- `receive <channel>`: Waits for and returns a value from the channel. If the channel is empty, this call will **asynchronously pause** the task until a value is available.

### Example: A Producer-Consumer Workflow

Imagine an NPC that gathers resources and a base that processes them. Channels allow them to work together without needing to know about each other's state.

```slip
// Create a channel to transport the resources between the two tasks.
resource-channel: make-channel

// --- The Gatherer NPC's Task (The Producer) ---
task [
    loop [
        // 'find-resource' is a long-running host function.
        resource: find-resource
        emit "debug" "Gatherer found {resource}."

        // Send the resource to the processing base via the channel.
        // This will pause the gatherer if the processor is busy.
        send resource-channel resource
    ]
]

// --- The Processing Base's Task (The Consumer) ---
task [
    loop [
        emit "debug" "Processor is waiting for a resource..."

        // Wait to receive a resource from the channel.
        // This will pause the processor until the gatherer sends something.
        item: receive resource-channel

        emit "debug" "Processor is handling {item}."
        process-item item
    ]
]
```

This pattern decouples the gatherer from the processor. The gatherer doesn't need a reference to the processor, and the processor doesn't need to know where the items come from. This makes the system more modular, safer, and easier to reason about.

## 12. Python Host Integration

SLIP is designed to be a safe and powerful scripting language embedded within a host Python application. The entire system is built on `asyncio`. This section details the contract and patterns for making Python objects and functions available to the SLIP interpreter.

### 12.1. The `SLIPHost` Abstract Base Class

To ensure a secure and predictable interface, any Python object you wish to expose to SLIP **must** inherit from the `SLIPHost` abstract base class. This class defines the fundamental contract for interoperability.

```python
from slip_production import SLIPHost, slip_api_method

class MyGameObject(SLIPHost):
    def __init__(self, name):
        super().__init__() # Important: Initializes task management
        self._data = {'name': name, 'hp': 100}

    # --- Contract Implementation ---
    def __getitem__(self, key):
        if key.startswith('_'): raise KeyError("Private access denied.")
        return self._data[key]

    def __setitem__(self, key, value):
        if key.startswith('_'): raise KeyError("Private access denied.")
        self._data[key] = value

    def __delitem__(self, key):
        if key.startswith('_'): raise KeyError("Private access denied.")
        del self._data[key]

    # --- API Method ---
    @slip_api_method
    def some_action(self, arg):
        # ...
```

### 12.2. Data Access (`__getitem__`, `__setitem__`, `__delitem__`)

SLIP's property accessors (`.` and `[]`) and assignment (`:`) are mapped directly to Python's standard dictionary-style "magic methods."

- **SLIP `obj.hp` and `obj["hp"]`**: Both forms call `obj.__getitem__("hp")`. The dot is for static, literal keys, while brackets are for dynamic, evaluated keys.
- **SLIP `obj.hp: 80` and `obj["hp"]: 80`**: Both forms call `obj.__setitem__("hp", 80)`.
- **SLIP `del obj.hp`**: Calls `obj.__delitem__("hp")`.

This pattern provides a single, secure gateway for all data interaction between SLIP and your Python objects.

### 12.3. Method Access (`@slip_api_method` Decorator)

To prevent accidental exposure of internal methods, only functions explicitly marked with the `@slip_api_method` decorator are visible to the SLIP interpreter.

- **The Contract:** Any method on a `SLIPHost` subclass that should be callable from SLIP **must** have the `@slip_api_method` decorator.
- **Security:** If the decorator is omitted, the SLIP interpreter cannot see or call the method, even if it's public in Python. This provides a "secure by default" model.

```python
class MyGameObject(SLIPHost):
    # ...

    @slip_api_method
    def take_damage(self, amount: int):
        """This method is visible and callable from SLIP."""
        self.hp -= amount

    def internal_calculation(self):
        """This method is NOT visible to SLIP."""
        # ...
```

### 12.4. Kebab-case to Snake_case Conversion

SLIP scripts use `kebab-case` for function and variable names as a stylistic convention. Python uses `snake_case`. The interpreter bridges this gap automatically.

- **SLIP Code:** `player |take-damage 10`
- **Python Lookup:** The interpreter automatically converts `take-damage` to `take_damage` before searching for the method on the host object.

### 12.5. The `host-object` Gateway Function

While SLIP scripts can pass around handles to host objects they already have, they cannot create them or pull them out of thin air. The host application must provide a single, global gateway function for this purpose.

- **The Contract:** Your host application must provide a SLIP function named `host-object`.
- **Implementation:** This function should take a single argument (usually a string ID) and look it up in a central registry of all active game entities. If found, it returns the live `SLIPHost` instance.

```python
# In your main application setup
GAME_WORLD_OBJECTS = {
    "player-kael": Kael_Object,
    "room-throne": Throne_Room_Object
}

@slip_api_method
def host_object(object_id: str):
    """The global gateway for SLIP to access game objects."""
    return GAME_WORLD_OBJECTS.get(object_id)

# This function would be registered in the root scope of your ScriptRunners.
```

---

## 13. The Execution Result: Understanding Script Outcomes

The SLIP interpreter is designed to be a safe, sandboxed environment. It never raises a Python exception that could crash the host application. Instead, every script execution, whether it succeeds or fails, returns a consistent `ExecutionResult` object to the host.

This object is the primary data structure for communicating the outcome of a script back to the host Python code, providing not just a return value but also rich diagnostic information and a structured log of side effects.

#### 13.1. The `ExecutionResult` Object Structure

An `ExecutionResult` contains the following fields:

- **`status: str`**
  The most important field. It will be one of three possible strings:

  - `'success'`: The script or expression completed without any errors.
  - `'error'`: The script was halted due to a syntax or runtime error.
  - `'return'`: The script executed a `return` statement, exiting a function early.

- **`value: Any`**
  If the status is `'success'` or `'return'`, this field holds the final return value of the script or expression. For a script with multiple lines, this is the value of the last expression evaluated. If there is no return value, this will be `none`.

- **`error_message: Optional[str]`**
  If the status is `'error'`, this field contains a human-readable string describing the error.

- **`error_token: Optional[Token]`**
  If the status is `'error'`, this field contains the `Token` object at which the error occurred. This is crucial for diagnostics, as the token contains the line and column number of the problem.

- **`side_effects: List[Dict]`**
  A chronologically ordered list of all side-effect events generated during the script's execution, primarily via the `emit` function. Each event is a dictionary, typically containing `{'topics': [...], 'message': ...}`.

#### 13.2. Error Reporting

The interpreter provides rich diagnostic information for errors. The host can use the `format_error()` method on the `ExecutionResult` object to get a clean, user-friendly error message that includes the line and, where possible, the precise column of the error.

**Example: Handling an Error in Python**

```python
runner = ScriptRunner(my_host_object)
result = await runner.handle_script("x: 1 + 'a'") # This will cause a TypeError

if result.status == 'error':
    # format_error() will produce a clean, user-friendly message.
    # e.g., "Error on line 1: Runtime error in 'add': unsupported operand type(s)..."
    log_to_server_console(result.format_error())
```

#### 13.3. The `emit` Function and Side Effects

In an interactive application, many actions don't have a meaningful return `value` but do have an effect on the world (e.g., displaying a message, playing a sound, dealing damage). The `emit` function is the standard mechanism for reporting these events in a structured way.

The `emit` function is provided by the host and is not part of the core language. This ensures that all I/O and world interaction is managed by the host's context-aware logic.

- **Syntax:** `emit <topic_or_topics> <message>`
- **Behavior:** The `emit` function generates a side-effect event that is appended to the `ExecutionResult`'s `side_effects` list. This list preserves the exact order of all events.
  - `<topic_or_topics>`: A string or a list of strings that categorizes the event (e.g., `"combat"`, `"debug"`, `["visual", "sound"]`).
  - `<message>`: The data payload for the event, typically a string.

**Example: A SLIP Script Generating Events**

```slip
// A script for a "fireball" spell
emit "combat" "{player.name} hurls a fireball at the goblin!"
emit #["visual", "sound"] "An explosion of fire and sound erupts!"

damage: roll "3d6"
goblin.hp: goblin.hp - damage

emit "combat" "The goblin takes {damage} fire damage."
```

**Example: The Host Processing the Result**
The host receives the final `ExecutionResult`, which contains an ordered list of all events generated by the script.

```python
# result.side_effects might look like this:
# [
#     {'topics': ['combat'], 'message': 'Kael hurls a fireball at the goblin!'},
#     {'topics': ['visual', 'sound'], 'message': 'An explosion of fire and sound erupts!'},
#     {'topics': ['combat'], 'message': 'The goblin takes 14 fire damage.'}
# ]

for effect in result.side_effects:
    message = effect['message']
    # The host can now route this event based on its topics
    if 'combat' in effect['topics']:
        send_to_player_combat_log(message)
    if 'visual' in effect['topics']:
        visual_engine.play_effect("fireball_explosion")
    if 'sound' in effect['topics']:
        sound_engine.play("explosion.wav")
```

This powerful pattern creates a clean separation between a script's logical execution and the various ways its effects are presented to the user, while preserving a perfect, chronologically ordered record of every event.

#### 13.4. In-Script Error Handling

SLIP does not have a try/catch mechanism for handling runtime errors. This is a deliberate design choice to maintain simplicity and ensure that unexpected errors (like type mismatches or calling a non-existent function) always halt the script and report a clear error to the host. Such errors are considered bugs in the script that should be fixed, not silently ignored.

For predictable, recoverable failures (e.g., an item not being found, an action being on cooldown), the idiomatic pattern in SLIP is for functions to return the `none` value. The calling script can then use a standard if expression to check for this outcome.

**Example: A Host Function That Can Fail**

Imagine a host function `find-enemy [name]` that returns the enemy object if found, and `none` if not. A script would handle this as follows:

```slip
// Attempt to find the goblin.
target: find-enemy "goblin"

// Check if the function returned none
if [target = none] [
   // The 'then' block handles the failure case.
   print "There are no goblins here to attack."
] [
   // The 'else' block runs if a target was found.
   print "You attack the goblin!"
   target |take-damage 10
]
```

### 13.5. Error Status Codes

When a script encounters an error, the `ExecutionResult` returned to the host contains a structured error inspired by HTTP status codes. This provides clear, machine-readable information about the nature of the failure. The error information is primarily located in the `error_message` and `error_token` fields, but is categorized by a status code.

The status codes fall into two main categories:

- **`4xx` Codes (Client Errors):** These errors indicate a problem with the script's code itself, such as a syntax mistake or a logical error that the interpreter can detect.

  - **`400 Bad Request` (Syntax Error):** The parser was unable to understand the script's source code. This can be due to mismatched brackets, invalid operators, or other grammatical errors. The error message will provide details from the parser.
  - **`404 Not Found` (Path Error):** A path could not be resolved in the current environment. This is the most common runtime error, occurring when a variable or function name does not exist. This is also the error returned from a method call when the method name is not found and no `handle-missing-message` fallback exists.

- **`5xx` Codes (Interpreter Errors):** These errors indicate a problem that occurred during the evaluation of valid code. This is analogous to a server error in a web context.
  - **`500 Internal Error` (Runtime Error):** A general-purpose error for when an operation fails during execution. This includes type mismatches (e.g., `1 + "a"`), calling a non-function value, or an error raised from within a host (Python) function. The `error_message` will contain a specific traceback.
  - **`501 Not Implemented`:** The script attempted to use a feature that is not implemented in the current host environment.

## 14. Reference

This section details the core components of the SLIP language, from the fundamental evaluation rules to the high-level libraries that provide its rich functionality.

### 14.1. The Language Kernel (Core Primitives)

While most of SLIP's standard library can be written in SLIP itself, a minimal set of functions and operators—the "kernel"—must be provided by the host environment (e.g., in Python, Go, or Rust). These primitives form the irreducible core of the language upon which all other functionality is built.

- **Assignment (`:`)**: The core binding mechanism. This is the one special syntactic form in the language. The host interpreter must have a native understanding of how to parse and handle `set-path` and `multi-set` AST nodes produced by the `:` operator.

- **Evaluation Primitives**: These functions control how and where code is executed.

  - `run <code>`: The primary function for executing a block of code within the current environment.
  - `run-with <code> <env>`: Executes a code block within a specific, user-provided environment, allowing for sandboxing or context-specific execution.
  - `current-env`: A function that returns the `env` object representing the current lexical scope.

- **Function & Call Primitives**: These primitives are the foundation of SLIP's functional nature.

  - `fn <args-list> <code-body>`: The core function for creating new `function` objects (closures). It must capture the current lexical scope at the time of its creation and bundle it with the provided argument list and unevaluated body of code.
  - `method <arg-list> <predicate-block> <body-block>`: Creates a dispatchable method, a specialized function used for building generic functions (see "Multiple Dispatch"). It bundles the arguments, a predicate for matching, and a body.
  - `call <function> <arg-list>`: Programmatically invokes a function with a list of arguments.
  - `call-with <function> <arg-list> <env>`: Programmatically invokes a function with a specific context. It **prepends the context object (`env`) to the argument list** and then executes the function within that context. This is the powerful primitive that underlies the "smart dot" method call mechanism, automatically providing the `self` argument.

- **Control Flow Primitives**: These functions are the basis of all logic and iteration.

  - `if <condition-block> <then-block> <else-block>`: The fundamental conditional. It first evaluates the `<condition-block>`. If the result is truthy, it then evaluates the `<then-block>`. Otherwise, it evaluates the `<else-block>`. It is crucial that only one of the two branch code blocks is ever evaluated.
  - `while <condition-block> <body-block>`: The fundamental loop. It repeatedly evaluates the `condition-block` and, if the result is true, runs the `body-block`.
  - `return [value]`: Terminates the execution of the current function and returns the given `value` (or `none` if not provided). This is achieved by creating a `Response` object with `status: 'return'`, which is then handled by the function evaluation machinery.
  - `task <code-block>`: Executes a code block asynchronously on the host's event loop. Inside a `task`, `while` and `foreach` loops automatically yield control (`sleep 0`) on each iteration to prevent blocking the host.

- **Metaprogramming Primitives**: These functions enable runtime code generation and manipulation.

  - `inject <path>`: Substitutes a value from the _calling_ scope into a code block being executed by `run`.
  - `splice <path>`: Splices the contents of a list from the _calling_ scope into a code block being executed by `run`.

- **Type System Primitives**: These functions allow the language to be introspective.

  - `to-path <string>` (also called `intern`): Converts a string into a `path` object. This is essential for creating paths dynamically.
  - `type-of <value>`: Returns a `path` representing the type of the value (e.g., `` `core.number ``, `` `core.list ``).
  - **Type Predicates**: A family of functions (`is-number?`, `is-list?`, `is-path?`, etc.) that return `true` or `false`. These are typically implemented in the standard library using `type-of`.

- **Core Data Operations**:
  - **Base Arithmetic & Comparison**: The fundamental functions for numbers and logic (`+`, `-`, `*`, `/`, `>`, `<`, `=`, etc.) must be provided as primitives.
  - **List & Env Manipulation**: The most basic operations for containers (e.g., getting length, accessing an index, setting a key in an `env`) must also be provided by the host environment.

### 14.2. Standard Library (Host Primitives)

The following functions are generally provided by the host environment to form a useful standard library. They provide essential primitives for data manipulation, math, and interaction with the system.

#### Math and Logic

- `add a b`: Adds numbers. If an operand is a string, performs string concatenation. If an operand is a list, performs list concatenation.
- `sub a b`: Subtracts numbers.
- `mul a b`: Multiplies numbers.
- `div a b`: Divides numbers.
- `pow base exponent`: Raises base to the power of exponent.
- `eq a b`: Checks for equality.
- `neq a b`: Checks for inequality.
- `gt a b`: Greater than.
- `gte a b`: Greater than or equal to.
- `lt a b`: Less than.
- `lte a b`: Less than or equal to.
- `not x`: Inverts a boolean value.
- `exp x`: Returns e raised to the power of x (e^x).
- `log x`: Returns the natural logarithm (base e) of x.
- `log10 x`: Returns the base-10 logarithm of x.
- `random`: Returns a random float between 0.0 and 1.0.
- `random-int <min> <max>`: Returns a random integer in the range `[min, max]` (inclusive).

#### String Utilities

- `join <list-of-strings> <separator>`: Joins the elements of a list into a single string.
- `split <string> <separator>`: Splits a string by a separator into a list of strings.
- `find <haystack> <needle> [<start-index>]`: Finds the first occurrence of a substring.
- `replace <string> <old> <new>`: Returns a new string with all occurrences of `old` replaced by `new`.
- `indent <string> <prefix>`: Adds a prefix to the beginning of each line.
- `dedent <string>`: Removes common leading whitespace from every line.

#### Collection Utilities

- `del <path>`: Deletes a value from an environment. The argument is an unevaluated path expression. After deleting the terminal value, `del` will prune any now-empty `env` objects from the parent environment, cascading this pruning up the path chain.
- `len <collection>`: Returns the length of a list, `dict`, or string.
- `range [<start=0>] <stop> [<step=1>]`: Generates a list of numbers. It can be called in three ways:
  - `(range <stop>)`: Generates numbers from 0 to stop-1.
  - `(range <start> <stop>)`: Generates numbers from start to stop-1.
  - `(range <start> <stop> <step>)`: Generates numbers from start to stop-1, incrementing by step.
- `keys <dict|env>`: Returns a new list containing the keys of the dictionary or environment.
- `values <dict|env>`: Returns a new list containing the values of the dictionary or environment.
- `copy <collection>`: Returns a **shallow copy** of a list, dictionary or code block. Nested collections within the copied structure will still refer to the original nested collections.
- `clone <collection>`: Returns a **deep copy** of a list, dictionary or code block. All nested collections are also recursively copied, creating a completely independent duplicate of the original structure.

#### Data Modeling

- `validate <data> <schema>`: Validates that a `data` object conforms to a `schema` dictionary. Returns `response ok ()` or `response err <list-of-errors>`.
- `create <data> <schema>`: Validates `data` against a `schema`, applies defaults, and returns a new, clean object. Returns `response ok <new-object>` or `response err <list-of-errors>`.
- `default <value>`: A helper for schemas that provides a default value for a field.
- `optional <type>`: A helper for schemas that marks a field as optional.

#### Object Model

- `inherit <child-env> <parent-env>`: Sets the `parent` (prototype) link of the `child-env` to be the `parent-env`. This is the primary mechanism for inheritance.
- `mixin <target> <sources...>`: Copies all key-value pairs from one or more source environments (`sources...`) into a target environment. This is the primary mechanism for composition.

#### Asynchronous Operations

- `make-channel`: Creates and returns a new channel object for structured concurrency.
- `send <channel> <value>`: Sends a value into a channel, pausing asynchronously if the channel is full.
- `receive <channel>`: Receives a value from a channel, pausing asynchronously if it is empty.
- `sleep <seconds>`: Pauses the current task for `<seconds>` (can be a float) without blocking the host event loop. `sleep 0` yields control to the event loop, allowing other tasks to run.

#### Side Effects and I/O

- `emit <topic_or_topics> <message>`: Generates a side-effect event that is appended to the `ExecutionResult`'s `side_effects` list. This is the primary mechanism for a script to communicate events to the host application.
- `time`: Returns the current system time as a high-precision float (Unix timestamp).

#### Type Conversion

- `to-str <value>`: Converts any value to its string representation.
- `to-int <value>`: Attempts to convert a value (e.g., a string or a float) to an integer. Raises a `TypeError` if the conversion is not possible.
- `to-float <value>`: Attempts to convert a value (e.g., a string or an integer) to a float. Raises a `TypeError` if the conversion is not possible.
- `to-bool <value>`: Attempts to convert a value (e.g., a string or an integer) to a bool. Raises a `TypeError` if the conversion is not possible.

### 14.3. The SLIP Core Library (`core.slip`)

SLIP extends its built-in functionality with a core library written in SLIP itself. This file is loaded automatically by the interpreter and provides a rich set of higher-order functions and utilities. This demonstrates the power of the language to build upon its own primitives.

```slip
/*
    SLIP Core Library v1.0

    This library provides a set of common, high-level utilities
    written in pure SLIP. It is loaded into the global scope.
*/

// --- Operator and Alias Definitions ---
// Note: The core functions (add, sub, etc.) are host primitives.
// These bindings make them available as infix operators.
/+: |add
/-: |sub
/*: |mul
//: |div
/**: |pow
/=: |eq
/!=: |neq
/>: |gt
/>=: |gte
/<: |lt
/<=: |lte
and: |logical-and
or: |logical-or

// Common aliases
print: fn [msg] [ emit stdout msg ]


// --- List & Sequence Utilities ---

// Reverses a list by iterating through it and prepending
// each item to a new list.
reverse: fn [data-list] [
    result: #[]
    // For each item in the original list (from start to end)...
    foreach item data-list [
        // ...prepend it to the front of our result list.
        result: add #[item] result
    ]
    result
]

// Applies a function to each item in a list and returns a new
// list containing the results.
map: fn [func, data-list] [
    results: #[]
    foreach item data-list [
        results: add results (func item)
    ]
    results
]

// Filters a list, returning a new list containing only the items
// for which the predicate function returns a truthy value.
filter: fn [predicate, data-list] [
    results: #[]
    foreach item data-list [
        if [predicate item] [
            results: add results item
        ]
    ]
    results
]

// Reduces a list to a single value by applying a function cumulatively.
reduce: fn [reducer, accumulator, data-list] [
    foreach item data-list [
        accumulator: reducer accumulator item
    ]
    accumulator
]

// Combines two lists into a list of pairs. The resulting list's
// length is determined by the shorter of the two input lists.
zip: fn [list-a, list-b] [
    results: #[]
    limit: if [len list-a < len list-b] [len list-a] [len list-b]
    i: 0
    while [i < limit] [
        results: add results #[#[list-a[i], list-b[i]]]
        i: i + 1
    ]
    results
]

// --- Function Utilities ---

// Creates a new function that, when called, will invoke the original
// function with the pre-supplied arguments, followed by any new arguments.
partial: fn [func, partial-args...] [
    fn [new-args...] [
        // `add` creates a new list by concatenating the pre-supplied
        // arguments with any new arguments.
        all-args: add partial-args new-args
        call func all-args
    ]
]

// Composes functions, returning a new function that applies them from
// right to left. (compose f g h)(x) is equivalent to f(g(h(x))).
compose: fn [funcs...] [
    fn [initial-arg] [
        result: initial-arg
        foreach func (reverse funcs) [
            result: func result
        ]
        result
    ]
]

// --- Control Flow ---

// Provides a conditional branch without a required 'else' block.
when: fn [condition, then-block] [
    if condition then-block []
]

// A multi-branch conditional, like a switch statement. It takes a list of
// [condition-block, result-expression] pairs. It executes the first
// condition-block that returns a truthy value, and then returns the
// corresponding result-expression.
// Example:
//   x: 5
//   cond #[
//       #[[x < 5], "less"],
//       #[[x > 5], "greater"],
//       #[true, "equal"]
//   ]  // returns "equal"
cond: fn [clauses] [
    foreach clause clauses [
        [condition-block, result-expr]: clause

        // Execute the condition block. If it's truthy...
        if [run condition-block] [
            // ...return the associated result expression.
            return result-expr
        ]
    ]
    // If no conditions match, return none.
    ()
]

// Executes a block of code within the context of a given object,
// then returns the object. Ideal for fluent configuration.
// Example: obj |with [ name: "new" ]
with: fn [obj, block] [
    // Run the code block in the context of the object
    run-with block obj

    // Return the original, now-modified object
    obj
]
```

---

## 17. The SLIP Execution Model: Declarative Effects-as-Data

The previous chapters have described the syntax and primitives of the SLIP language. This final chapter explains the **philosophy of execution**—the recommended way to structure a SLIP program to be safe, testable, and robust. This model is not an accident; it is the central design principle around which the language is built.

The model is simple: **Core logic should be pure; side effects should be declarative data.**

### 17.1. The Two Halves of a SLIP Program

A well-structured SLIP program is divided into two distinct parts:

1.  **The Pure Core:** These are functions that perform the actual business logic. They take data as input and produce new data as output (often wrapped in a `response` object). They contain calculations, decisions, and data transformations. Crucially, they **do not perform side effects directly**.

2.  **The Effect Descriptions:** When a pure function needs to interact with the outside world (deal damage, play a sound, log a message), it does not call a host function that _does_ the action. Instead, it calls `emit` to create a **declarative description of the desired effect**.

The `emit` function does not perform the effect. It simply serializes a description of the effect as a piece of data and places it into the `ExecutionResult`'s side-effect queue.

### 17.2. The Host as the Effect Handler

This separation creates a powerful, one-way flow of information:

1.  The host calls a SLIP script.
2.  The script executes its pure logic. As it runs, it populates the `side_effects` queue with descriptions of desired effects.
3.  The script finishes and returns a final `response` and the completed `side_effects` queue to the host.
4.  The host now iterates through the `side_effects` queue and **is the only component that actually executes the effects**.

The host is the ultimate authority. It is the "impure" part of the system that interacts with the world, acting on a clear, unambiguous list of instructions provided by the pure SLIP script.

### 17.3. A Complete Example

Consider a function that calculates the result of a spell attack.

```slip
// This is a PURE function. It has no direct side effects.
calculate-fireball-impact: fn [caster, target, area] [
    // 1. Pure calculations
    base-damage: 50
    final-damage: base-damage - target.fire-resistance

    // 2. Describe the desired effects using 'emit'
    emit "visual" {effect: "explosion", position: target.position}
    emit "sound"  {sound: "fireball_hit.wav", volume: 1.0}
    emit "combat" {
        type:   `damage,
        target: target.id,
        amount: final-damage,
        element: `fire
    }

    // 3. Return the new state of the target as pure data
    new-target-state: clone target
    new-target-state.hp: target.hp - final-damage
    respond ok new-target-state
]
```

**The Host's Role:**

The host calls this function and receives the `ExecutionResult`. The `result.side_effects` list might look like this:

```
[
    {'topics': ['visual'], 'message': {'effect': 'explosion', ...}},
    {'topics': ['sound'],  'message': {'sound': 'fireball_hit.wav', ...}},
    {'topics': ['combat'], 'message': {'type': 'damage', ...}}
]
```

The host can now loop through this list and dispatch each effect to the appropriate engine: the graphics engine, the sound engine, the combat state manager.

### 17.4. The Benefits of This Model

This architecture is the culmination of the best ideas from modern language design, providing enormous benefits:

- **Testability:** The `calculate-fireball-impact` function can be tested in complete isolation. You don't need to mock a game world. You just call the function and assert that the returned `response` and the list of emitted events are correct.
- **Auditability and Replayability:** The `side_effects` list is a perfect, serializable, chronological log of exactly what the script intended to do. It can be saved, inspected for bugs, or even replayed.
- **Security and Control:** The host has the final say. It can inspect an effect before executing it. It could, for example, decide to ignore a `damage` event if the target is in a safe zone.
- **Simplicity:** This model achieves the primary goal of pure functional programming—separating logic from effects—without requiring the complex abstractions of monads. It is a pragmatic, "effects-as-data" approach that is easy to understand and use.

This is the intended way to use SLIP. It is not just a scripting language; it is an engine for building safe, testable, and declarative logic components within a larger host application.

---

# Appendix A: What SLIP is NOT

To avoid common misconceptions, it is crucial to understand how SLIP differs from other language paradigms:

- **Not a Traditional LISP:** SLIP does not use explicit parentheses for every function call, nor does its parser transform infix expressions into a prefix-only AST. Its AST directly reflects the source code's visual structure.
- **Not a Rebol:** SLIP uses a structured, hierarchical evaluation model (like LISP's s-expressions) for its function calls, unlike Rebol's linear, greedy evaluation.
- **No Macros (in the LISP sense):** SLIP achieves metaprogramming power through first-class `code` objects and functions like `run`, `inject`, and `splice`, rather than a separate macro system that operates at compile-time.
- **No Operator Precedence (in the parser):** The parser does not assign precedence to operators like `+` or `*`. It simply parses them as names in a flat list. All evaluation order for infix operations is strictly left-to-right, handled by the evaluator. Parentheses `()` are the only way to force evaluation order.

# Appendix B: Arithmetic Style Guidance (Normative)

SLIP's strictly left-to-right evaluation for infix math is a core design feature, not a limitation. It is intended to be more cognitively natural than traditional operator precedence models (e.g., PEMDAS), which are historical artifacts that can introduce ambiguity and cognitive load.

The SLIP model has no such ambiguity. Evaluation proceeds in the same order the expression is read. The philosophy is to embrace a simple learning curve: a programmer accustomed to other languages may make a mistake once, but will quickly adapt to the SLIP mindset and benefit from its consistency. This is analogous to programmers learning to use prefix notation in LISP—a different way of thinking that, once adopted, becomes powerful.

Therefore, the recommended style is to embrace linear, parenthese-free arithmetic for clarity.

Recommended style:

```slip
// preferred, reads left-to-right
4 ** 2 + 2 * 5 / 4
```

Parentheses are only needed to deliberately alter this natural flow, making their use a strong, explicit signal to the reader.

For cases where direct transcription of a complex mathematical formula is required, a future version of SLIP may include a special grammar or keyword to evaluate a block of code using traditional PEMDAS rules. For general-purpose programming, the left-to-right model is considered superior.

---

# Appendix C: Abstract Syntax Tree (AST) Reference

This appendix provides a formal reference for the structure of the Abstract Syntax Tree (AST) that the SLIP parser generates. The evaluator's behavior is driven by the tags and structure of these nodes. The fundamental structure is a "tagged list," where the first element is a `path` that identifies the node's type.

**A Note on Notation:** In the following examples, `<type value>` (e.g., `<number 10>`) is used to represent literal value tokens like numbers and user-facing strings. Structural parts of the AST are represented as tagged lists like `[tag ...]`. For brevity and clarity, the literal string or number values inside path components (e.g., the `'user'` in `[name 'user']` or the `5` in `[slice 5 10]`) are shown directly, rather than using the more verbose `<string "user">` or `<number 5>` notation.

### Expressions and Code

An expression is represented by a list tagged with `expr`. A `code` block is tagged with `code`. The difference is that the evaluator executes an `[expr ...]` immediately, while a `[code ...]` is treated as a literal value.

- **Source:** `(add 1 2)`

  - **AST:** `[expr [path [name 'add']], <number 1>, <number 2>]`

- **Source:** `[add 1 2]`
  - **AST:** `[code [expr [path [name 'add']], <number 1>, <number 2>]]`
  - Note: A `code` block contains a list of one or more `expr` nodes.

### Container Literals

The literals for `list`, `env`, and `dict` are syntactic sugar for nodes that instruct the evaluator to build these containers. They are semantically equivalent to calling `list`, `env`, or `dict` as functions.

- **Source:** `#[1, 2]`

  - **AST:** `[list <number 1>, <number 2>]`
  - The evaluator processes this by evaluating each element and collecting the results into a `list` object.

- **Source:** `#{ a: 1 }`

  - **AST:** `[env [expr [set-path [name 'a']], <number 1>]]`
  - The evaluator executes the expressions inside a new environment that is linked to the current scope, then returns that environment.

- **Source:** `{ a: 1 }`
  - **AST:** `[dict [expr [set-path [name 'a']], <number 1>]]`
  - The evaluator executes the expressions inside a new, un-linked environment, returning it as a simple dictionary.

### Paths and Assignment

Paths and assignment patterns are represented by two distinct but related AST nodes.

#### The `path` Node (for Reading)

A `path` node represents a location to read a value from. It is an expression that is evaluated.

- **AST Structure:** `[path <segment1>, <segment2>, ...]`
- **Segments:** A `path` is composed of one or more segments.

  - `[pipe]`: The pipe operator `|`. Can only appear as the first segment.
  - `[name '...']`: A dot-separated name, e.g., `user`.
  - `[index <number>]`: An index access, e.g., `[0]`.
  - `[slice <start> <end>]`: A slice access, e.g., `[1:5]`.
  - `[parent]`: The parent scope operator `../`.
  - `[expr ...]`: A dynamic, computed segment, e.g., `(get-index)`.

- **Source:** `user.name`

  - **AST:** `[path [name 'user'], [name 'name']]`

- **Source:** `|user.name`
  - **AST:** `[path [pipe], [name 'user'], [name 'name']]`

#### The `set-path` and `multi-set` Nodes (for Writing)

A `set-path` node represents the pattern on the left-hand side of an assignment (`:`). It describes a location to write to.

- **AST Structure:** `[set-path <segment1>, <segment2>, ...]`
- **Segments:** A `set-path` uses the same segments as a `path` node, **with the critical exception that `[pipe]` is not allowed.**

- **Source:** `user.name: "John"`
  - **AST:** `[expr [set-path [name 'user'], [name 'name']], <string "John"> ]`

A `multi-set` node is used for destructuring assignment. It contains one or more `set-path` nodes.

- **Source:** `[x, y]: #[10, 20]`
  - **AST:** `[expr [multi-set [set-path [name 'x']] [set-path [name 'y']]], [list <number 10>, <number 20>] ]`

---

# Appendix D: Final Review: The SLIP Philosophy in Context (v1.0)

Let's do a final review to confirm, addressing your checklist directly. We can summarize the journey by looking at the "great ideas" from other languages and seeing how SLIP has interpreted them.

A mature language is defined as much by what it _is_ as by what it is _not_. SLIP's design is a synthesis of powerful concepts from decades of language evolution, adapted to fit its core philosophy of simplicity, safety, and metaprogramming clarity.

Here is a summary of how SLIP has addressed the core ideas from its most significant influences:

| Language                | "The Great Idea"                     | SLIP's Interpretation or Stance                                                                                                                                            |
| :---------------------- | :----------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| **LISP / Scheme**       | **Homoiconicity (Code as Data)**     | **Directly Adopted.** The first-class `code` type (`[...]`) is the heart of SLIP's metaprogramming.                                                                        |
|                         | **Macros (`defmacro`)**              | **Replaced.** SLIP uses runtime functions (`run`, `inject`, `splice`) on `code` objects, avoiding a separate compile-time macro system.                                    |
|                         | **Continuations (`call/cc`)**        | **Explicitly Rejected.** Replaced with safer, more structured alternatives: `task` for concurrency and `response` for non-local exits.                                     |
| **Smalltalk**           | **Pure Message Passing**             | **Adapted.** The "smart dot" (`obj.method`) and the pipe (`                                                                                                                | `) are SLIP's ergonomic forms of message passing. |
|                         | **"Message Not Understood"**         | **Directly Adopted** as the `handle-missing-message` protocol, enabling dynamic dispatch and robust objects.                                                               |
|                         | **The "Image" (Persistence)**        | **Delegated to Host.** This is a powerful host-level pattern, not a language feature, preserving the language's simplicity.                                                |
| **Erlang / Elixir**     | **Pattern Matching in Functions**    | **Adapted and Adopted** into the `method` primitive, allowing dispatch based on the structure of arguments.                                                                |
|                         | **Actor Model / Channels**           | **Adopted as a Library Pattern.** The `task` primitive provides the actors, and `make-channel`, `send`, `receive` provide the safe communication, implemented by the host. |
| **JavaScript / Self**   | **Prototype-Based OOP**              | **Directly Adopted.** The `env` object with its `parent` link _is_ a prototype system. `inherit` makes this explicit.                                                      |
| **Logo**                | **Domain-Specific "World"**          | **Adopted as Core Philosophy.** This is the entire purpose of SLIP as an embedded language: the host provides a "world" of commands, creating a DSL.                       |
| **Rebol**               | **Linear, Greedy Evaluation**        | **Explicitly Rejected.** SLIP uses a structured, hierarchical evaluation model for function calls, providing more predictable behavior.                                    |
| **Prolog / miniKanren** | **Logic Programming & Backtracking** | **Delegated as a Library.** The core evaluator is deterministic. Logic programming is a powerful but distinct paradigm best provided by a host library.                    |
| **Rust / Haskell**      | **The `Result` Type (`Ok`/`Err`)**   | **Directly Adopted** and formalized as the first-class `response` type, which is handled elegantly by pattern-matching `method`s.                                          |

### Conclusion

This document has detailed the features and philosophy of SLIP v1.0, a language designed through a careful synthesis of powerful ideas from across the history of computer science, distilled into a simple, consistent, and powerful whole.

At its heart, SLIP is defined by a few core principles that diverge from convention to achieve greater clarity: a transparent, directly-represented AST that puts the evaluator in control; a unified `path` system that replaces symbols for identity and navigation; and a uniform, function-based model for all control flow, eliminating the need for special keywords.

From this foundation, SLIP deliberately adopts and adapts some of the most successful patterns from other languages.

- It embraces the **homoiconicity of LISP**, treating `code` as a first-class data type to enable powerful runtime metaprogramming.
- It channels the flexible object-oriented design of **Smalltalk and Self**, using a prototype-based model with message passing and a protocol for handling unknown messages.
- From modern functional languages like **Erlang and Rust**, it inherits robust patterns for concurrency with `task` and channels, as well as structured error handling via the `response` data type.
- Finally, it is guided by the spirit of **Logo**, designed from the ground up to be an embedded language where the host creates a rich, domain-specific dialect for users.

The result of this synthesis is not a complex amalgamation, but a coherent and minimalist system. Its features work together to promote a specific style of programming: one that separates pure logic from side effects, describing those effects as declarative data via the `emit` function. This "effects-as-data" model makes SLIP scripts inherently more testable, auditable, and secure.

This reference document defines the complete and stable feature set for SLIP version 1.0. With its clear syntax, powerful object model, robust outcome handling, and safe concurrency primitives, SLIP provides a complete toolkit for building the next generation of embedded, domain-specific languages.
