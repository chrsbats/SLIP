# SLIP Language Reference v0.1

## 0. Overview

> **"SLIP is a new scripting language designed to become the language of your application. It replaces special keywords and complex grammar with a single, consistent function-calling syntax, allowing you to build intuitive, domain-specific commands for your users. This radical simplicity, powered by a sophisticated dispatch engine, creates a language that is easy to learn, safe to embed, and powerful enough for experts."**

### 0.1. Why SLIP?

SLIP is a new scripting language designed to be simple for beginners, secure for developers, and powerful for experts. It achieves this by focusing on a few core principles that make it a uniquely practical and expressive tool.

#### For Those Who Want Code That's Simple to Learn

Learning to code often feels like memorizing a long list of special rules. SLIP is different. It’s designed to be simple and read like plain English, built on one consistent pattern: `command argument1 argument2`.

But simple doesn't mean weak. SLIP replaces entire loops with a single, expressive line. Imagine you have a list of players and want to find the ones with high health. Instead of writing a complicated loop, you just write:

```slip
-- Get the health of all players, then keep only the values over 100.
high-hp-players: players.hp[> 100]
```

This is SLIP's philosophy: provide simple, readable tools that let you do powerful things, so you can focus on your ideas, not the syntax.

#### For Programmers Who Need a Secure and Controllable Sandbox

SLIP isn't just about exposing an API; it's about creating a language. You get to define a rich, intuitive "dialect" for your application, allowing users to write domain-specific commands that are clear and expressive.

```slip
-- Instead of this...
api.system.broadcast_message(channel: "world", message: "The Northern gates have fallen!")

-- Your users can write this:
announce "The Northern gates have fallen!"
```

This expressive power is built on a rock-solid foundation of security. Scripts are sandboxed by default with no filesystem or network access. Furthermore, SLIP is designed to be a good citizen in a live application. Its asynchronous `task` primitive and automatic safety nets in loops ensure that even a long-running or infinite loop in a user's script **will not freeze your application**.

#### For Advanced Programmers Who Appreciate Elegant Design

For those who appreciate language design, SLIP offers a powerful synthesis of proven concepts, resulting in a system that is both minimalist and highly expressive.

- **A Unified Path System:** The concept of "symbols" is replaced entirely by a first-class `path` data type. Paths are used for everything: variable names, function names, member access, and data navigation. This unifies identity and location into a single, powerful concept, elegantly eliminating the distinction between accessing a local variable (`x`) and a nested property (`player.hp`).

- **The Power of "Code as Data":** In SLIP, a block of unevaluated code `[...]` is a first-class `code` data type. This homoiconic design is a superpower that Python cannot easily replicate, allowing behavior to be stored, passed, and executed dynamically as a standard, runtime activity.

- **Powerful Polymorphism via Multiple Dispatch:** All behavior emerges from a single, uniform function-calling mechanism. This is made possible by a powerful multiple dispatch engine that selects the correct function implementation based on the number, type, and even the values of the arguments provided. This provides a more flexible and expressive alternative to traditional single-dispatch OOP.

And these features are just the beginning. SLIP's design also includes:

- A clean, **prototype-based object model** with explicit inheritance and mixins.
- **Structured outcomes** (`response` objects) for robust, functional error handling.
- A built-in system for **testable examples** that serve as both documentation and unit tests.
- A declarative **data validation** library for safely ingesting data.
- A declarative **Effects-as-Data** model for testable, auditable side effects.
  ... and more!

### 0.2. Core Philosophy: A Different Way of Thinking

SLIP can seem alien at first, but it is very simple once you understand its core concepts. The main challenge is that SLIP re-evaluates many fundamental design decisions that have become established conventions. To understand SLIP requires unlearning these assumptions. Its philosophy is a synthesis of three core ideas that directly challenge these conventions:

**1. Principle: A Direct, "What You See Is What You Get" AST.**

- **The Convention:** Parsers are complex. They must understand operator precedence and transform code like `a + b * c` into a deep tree where `*` is executed before `+`.
- **The SLIP Way:** The parser is "dumb" and transparent. It produces a flat list `[a, +, b, *, c]`. The concept of precedence is moved entirely to the evaluator's simple, left-to-right reduction loop. This radically simplifies the parser's role and makes the code's structure completely explicit.

**2. Principle: Path-Oriented Identity Replaces Symbols.**

- **The Convention (LISP):** A symbol `'x` is a fundamental, indivisible unit.
- **The SLIP Way:** There are no symbols. There are only **paths**. A "symbol" is just a path with one segment. This unifies the concepts of identity, location, and data navigation into a single powerful mechanism. The same `path` structure is used to access a local variable (`my-var`) and a deeply nested property (`player.inventory.items[0]`), eliminating the distinction between them.

**3. Principle: Function-Controlled Evaluation, (Almost) No Special Forms.**

- **The Convention:** Languages need many special keywords and statement types (`if`, `for`, `def`, `class`) with their own unique grammar and evaluation rules.
- **The SLIP Way:** There is **one** special syntactic pattern for assignment (`:`). Everything else, from control flow (`if`) to object creation (`scope`), is a regular function call that gains its power by operating on unevaluated **`code` blocks**. Metaprogramming is not a separate macro system; it's a normal runtime activity of building a `code` object and calling `run` on it.

  To make this work, SLIP makes one pragmatic exception for intuitive syntax: the **`logical-and`** and **`logical-or`** primitives are true special forms that short-circuit (they don't always evaluate all their arguments). With that exception, all other "specialness" is handled by the parser creating distinct data types, not by the evaluator having special rules.

## 1. Syntax & Evaluation Model

### 1.1. Parsing: The Flat, Directly-Represented AST

In SLIP, the parser produces an Abstract Syntax Tree (AST) that is a direct, 1:1 representation of the source code. It performs no semantic transformations like building a precedence tree for operators or rewriting function calls into a different form. This "dumb parser" approach radically simplifies the parser's role and makes the language's structure completely transparent.

- **Uniform Parsing of Expressions:** The parser treats all expressions as a simple, flat list of terms. It does not know if a path like `add` will evaluate to a function or a value. Therefore, an expression like `add 1 add 2` is **not a syntax error**. It is parsed successfully into a flat list. The `prefix_call (pipe_chain)*` grammar is a pattern enforced by the **evaluator**, which will likely raise a runtime error if it encounters a function where it expects a value, which is the correct behavior. This maintains the strict separation of concerns between parsing and evaluation.

- **Flat Lists for Infix Operations:** The parser's primary job is to convert each line of code into a simple, flat list of tokens. It does not create a nested tree based on operator precedence.

  - The line `10 + 5 * 2` is parsed directly into the flat structure `[<number 10>, [get-path [name '+']], <number 5>, [get-path [name '*']], <number 2>]`.
  - _Contrast with most languages:_ A traditional parser would transform this into a tree where `*` has higher precedence than `+`, equivalent to `10 + (5 * 2)`. SLIP does not; the structure is preserved exactly as written.

- **Explicit Nesting with `()` and `[]`:** A core philosophy of SLIP's syntax is to be as powerful as LISP, but without requiring parentheses for every operation. Simple expressions are written on a single line without nesting. However, if an argument to a function is itself a complex expression, or if an expression spans multiple lines, it **MUST** be enclosed in parentheses `(...)` to form an explicit evaluation group. This makes it unambiguously clear to both the reader and the evaluator which code should be executed to produce an argument.
  - This is a key difference from languages like Rebol, where `add 1 multiply 2 3` would be valid. In SLIP, the correct form is `add 1 (multiply 2 3)`. The parentheses signal that `multiply 2 3` should be evaluated first, and its result passed as the second argument to `add`.
  - The line `add 1 (multiply 2 3)` is parsed as `[expr [get-path [name 'add']], <number 1>, [group [expr [get-path [name 'multiply']], <number 2>, <number 3>]]]`. The parentheses explicitly create the nested `[group ...]` node. Square brackets `[...]` also create a nested node, but one that represents an unevaluated `code` block.

This approach places all semantic intelligence in the evaluator, creating a transparent and highly consistent system.

### 1.2. Evaluation: Left-to-Right and Type-Driven

The evaluator receives the AST from the parser and processes it sequentially. The meaning of any expression is determined by the evaluator based on the types of the objects it encounters.

For expressions parsed into a flat list, such as infix arithmetic, the evaluator consumes tokens from left to right, applying each operation as it appears.

- **Example: Evaluating `result: 10 + 5 * 2`**
  1.  **Initial AST:** `[ [set-path [name 'result']], <number 10>, [get-path [name '+']], <number 5>, [get-path [name '*']], <number 2> ]`
  2.  **Assignment Detection:** The evaluator sees `[set-path [name 'result']]` as the first token. It knows this is an assignment. It will evaluate the rest of the list (`[10, +, 5, *, 2]`) to get the value for `result`.
  3.  **Evaluating `[10, +, 5, *, 2]` (Left-to-Right):**
      - Evaluator processes `10`.
      - Evaluator sees `+`. It looks up the path `+` in the scope. It finds that `+` is bound to a `piped-path` object (`|add`). Because this resolves to a `piped-path`, an infix operation is triggered.
      - It performs the `add` operation: `(add 10 5)` evaluates to `15`.
      - The list effectively becomes `[15, *, 2]`.
      - Evaluator processes `15`.
      - Evaluator sees `*`. It looks up the path `*` in the scope, finds it is bound to `|multiply` (another piped path), and triggers another infix operation.
      - It performs the `multiply` operation: `(multiply 15 2)` evaluates to `30`.
      - The list is reduced to `[30]`.
  4.  **Final Assignment:** The value `30` is assigned to `result`.

This strict left-to-right evaluation without precedence means **parentheses are the only way to control the order of operations**: `10 + (5 * 2)` is required to perform the multiplication first.

The evaluator uses a **Uniform Call Syntax** to determine how to interpret a list based on its structure and the types of the tokens inside:

- **Prefix Call:** `[function, arg1, ...]`
  - If the first element of a list evaluates to a `function` or `bound-method`, the remaining elements are evaluated as arguments and the function is called.
- **Implicit Pipe / Infix Call:** `[<value>, <piped-path>, arg1, ...]`
  - If the first element evaluates to a non-function value, the evaluator inspects the second element. If it is a `piped-path` node or resolves to a `piped-path` object, a pipe operation is triggered. The first value becomes the first argument to the piped path's target function.

### 1.3. Container Literals and Evaluation

SLIP has several container literals, which fall into two fundamental categories based on how they handle their contents: those that create **unevaluated** data structures (code or signatures), and those that **evaluate** their contents to create runtime values.

- **Unevaluated Literals:** These operators capture their contents as-is, without execution, producing data structures that represent code or declarations.

  - **`[...]` – A Literal `code` Block.** This is the fundamental operator for creating unevaluated code. It produces a `code` object, which is an Abstract Syntax Tree (a list of lists) that can be stored, manipulated, or passed to functions. Expressions within the block can be separated by newlines or semicolons (`;`), allowing multiple expressions on one line (e.g., `[x: 1; y: x + 3]`). The code inside is not executed until explicitly run. This is the foundation of SLIP's function-controlled evaluation and metaprogramming. When a `code` block is executed (e.g., by `run` or as part of a control flow structure like `if`), its expressions are evaluated within the **current lexical scope**. Bindings created inside the block will therefore modify the current scope. New lexical scopes are created only when a function body is executed.
  - **`{...}` – A `sig` (Signature) Literal.** This creates an unevaluated `sig` object. It is used for function signatures, type unions/examples, and as a meta-parameter for functions that dynamically bind variables (e.g., `fn {…} […]`, `foreach {…} … […]`, `for {…} … […]`). A sig literal is never evaluated; it is inspected as data.

- **Evaluation Groups & Constructor Literals:** These operators create and immediately evaluate a nested expression. Their result is passed to the surrounding expression.
  - `(...)` – The **general evaluation group**. Evaluates the code inside and returns the result of the final expression. Expressions within the group can be separated by newlines or semicolons (`;`). This is the primary mechanism for controlling the order of operations.
  - `#[...]` – A **list literal**. This is constructor syntax that is functionally equivalent to `list [...]`. It evaluates the code inside and returns the results as a `list`.
  - `#{...}` – A **`dict` (dictionary) literal**. This is constructor syntax that is functionally equivalent to `dict [...]`. It evaluates the code inside (typically assignments) and returns a new `dict` object. This is the primary literal for creating simple key-value data structures.

---

#### The Script as an Implicit Code Block

The concept of the `code` block is fundamental to how SLIP is executed. A complete SLIP script file is treated by the interpreter as a single, **implicit `code` block**. Conceptually, the `ScriptRunner` wraps the entire contents of the file in `[` and `]` before execution.

This has several important implications:

- A script can contain multiple expressions, separated by newlines, just like an explicit `[...]` block.
- The script is evaluated within the scope provided by the host environment.
- Any bindings created at the top level of the script will modify that host scope, establishing the script's global environment.

This design choice reinforces SLIP's consistency: the rules that govern a small, literal `code` block are the same rules that govern an entire program.

### 1.4. Valid Expression Forms

An expression is a sequence of terms evaluated by the interpreter. Expressions are terminated by a newline, a semicolon (`;`), or the end of a block (`]`, `)`). While the parser is flexible enough to parse many combinations, the evaluator enforces specific structural rules for an expression to be valid at runtime.

An expression must conform to one of the following patterns:

1.  **Assignment Expression:**

    - The **first** term must be a `set-path` or `multi-set-path` pattern (e.g., `x:`, `[a,b]:`).
    - The rest of the expression is evaluated, and its result is assigned to the target pattern.
    - **Example:** `my-var: 10 + 20`
    - Return value: An assignment expression evaluates to the value that was written. This makes assignment composable in larger expressions and enables in-place updates.

2.  **Standalone Expression:**
    - The expression is evaluated, and its result is returned (or discarded if it's not the last expression in a block).
    - It typically starts with a `get-path` that resolves to a function (a prefix call) or a value (which may start an infix chain). A `del-path` is also a valid standalone expression.
    - **Example:** `add 10 20`
    - **Example:** `10 + 20`
    - **Example:** `~my-var`

**Invalid Forms (Common Runtime Errors):**

- A `set-path` cannot appear anywhere other than the first position in an expression.
  - **Invalid:** `10 + my-var: 20`
- A `piped-path` cannot be the first term of an expression, as it has nothing to receive as input.
  - **Invalid:** `|map my-list` (The correct form is `my-list |map [...]`)
- A `del-path` cannot be part of a larger expression.
  - **Invalid:** `~my-var + 10`

## 2. Data Types, Literals, and Comments

This chapter details SLIP's fundamental data types, the syntax for creating them (literals), and how to add comments to code.

### 2.1. Comments

SLIP supports two types of comments for annotating code.

- **Single-line:** A double slash (`--`) comments out the rest of the line.
- **Multi-line:** A slash-asterisk (`{--`) begins a block comment, which is terminated by an asterisk-slash (`--}`). Block comments are **nestable**, allowing large sections of code to be commented out safely, even if they already contain other block comments.

```slip
-- This is a single-line comment.
x: 10 -- Assign 10 to x.

{--
  This is a block comment.
  It can span multiple lines.
  {-- Nesting is supported! --}
--}
```

### 2.2. Literals and Core Data Types

The following table summarizes the literal syntax for creating SLIP's core data values. These are the fundamental building blocks of data in the language.

| Type             | Literal Syntax    | Example                   | Description                                                                                                                                                     |
| :--------------- | :---------------- | :------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **int**          | `123`, `-50`      | `level: 99`               | Represents integer (whole number) values.                                                                                                                       |
| **float**        | `3.14`, `-99.5`   | `pi: 3.14159`             | Represents floating-point values.                                                                                                                               |
| **i-string**     | `"..."`           | `msg: "Hello, {{name}}!"` | An **interpolated string**. The content is processed for `{{...}}` variable substitution.                                                                       |
| **raw-string**   | `'...'`           | `path: 'C:\Users\Me'`     | A **raw string**. The content is treated as literal text with no interpolation, useful for file paths or code snippets.                                         |
| **path-literal** | `` `some-path` `` | `my-path: `user.name``    | Creates a path object as a first-class value, preventing it from being immediately looked up by the evaluator. This is similar to a quasiquoted symbol in LISP. |
| **none**         | `none`            | `result: none`            | Represents the absence of a value. An empty evaluation group `()` also evaluates to `none`.                                                                     |
| **boolean**      | `true`, `false`   | `is-active: true`         | The boolean values `true` and `false`.                                                                                                                          |
| **code**         | `[...]`           | `my-code: [ x + 1 ]`      | An **unevaluated** block of code, represented as a first-class `code` object (an AST). This is the foundation of metaprogramming.                               |
| **sig**          | `{...}`           | `my-sig: { a, b: int }`   | A **signature literal**. Creates an **unevaluated** `sig` object used for function signatures, type definitions, and examples.                                  |
| **list**         | `#[...]`          | `items: #[ 1, "a" ]`      | A **list literal**. The expressions inside are evaluated, and the results are collected into a new `list` object. Functionally equivalent to `list [...]`.      |
| **dict**         | `#{...}`          | `data: #{ key: "val" }`   | A **dictionary literal**. Creates a simple key-value store by evaluating the expressions inside. Functionally equivalent to `dict [...]`.                       |
| **byte-stream**     | e.g., `u8#[]`, `i16#[]`, `u32#[]`, `u64#[]`, `f32#[]`, `f64#[]`, `b1#[]` | `u8#[65, 66, 67]` | Typed binary constructors. Produce bytes for unsigned/signed ints, floats, and bit-packed booleans (`b1`). Little‑endian for 16/32/64‑bit ints and floats. |

**A Note on Byte-streams**

For binary data manipulation, SLIP provides a family of typed byte-stream constructors. These literals evaluate the expressions within them and serialize the results into a raw `bytes` object. The available types include unsigned integers (`u8#[]`, `u16#[]`, `u32#[]`, `u64#[]`), signed integers (`i8#[]`, `i16#[]`, `i32#[]`, `i64#[]`), and floating-point numbers (`f32#[]`, `f64#[]`). For consistency, all multi-byte numeric types use little-endian encoding.

Additionally, the `b1#[]` constructor provides bit-packing for boolean values. It packs eight truthy or falsey values into a single byte, processing them from Most Significant Bit (MSB) to LSB. If the total number of values is not a multiple of eight, the final byte is left-padded with zeros.

These byte-stream objects can be converted to strings using `to-str` (which decodes them as UTF-8) or written directly to disk using `file://` paths, making them a powerful tool for low-level I/O and data serialization.


**A Note on I-Strings**: `i-string`s are automatically "de-dented," meaning common leading whitespace is removed from every line, making them easy to format in your code.

**A Note on `none`**: The `none` keyword is the canonical representation for the absence of a value. An empty evaluation group `()` also evaluates to `none`, and the expression `(eq none ())` is true.

#### Paths

In SLIP, paths are more than just variable names; they are a core syntactic feature for identity, location, and action. The parser recognizes several distinct path-based forms, each instructing the evaluator to perform a different operation.

| Path Type          | Syntax               | Example             | Description                                                                                                                                         |
| :----------------- | :------------------- | :------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Get Path**       | `path.to.value`      | `player.hp`         | The default form. Instructs the evaluator to read or "get" a value from a location.                                                                 |
| **Set Path**       | `path.to.value:`     | `player.hp: 100`    | The assignment form. The trailing colon (`:`) marks it for writing a value _to_ a location.                                                         |
| **Multi-Set Path** | `[path1, path2]:`    | `[x, y]: #[10, 20]` | The destructuring assignment form. Binds multiple values from a collection to multiple paths at once.                                               |
| **Delete Path**    | `~path.to.value`     | `~player.old_token` | The unbinding form. The leading tilde (`~`) marks it for removing a binding from a scope.                                                           |
| **Piped Path**     | `\|path.to.function` | `data \|map [...]`  | The pipe form. The leading pipe (`\|`) marks a path that will trigger an implicit function call, using the value on its left as the first argument. |
| Post Path         | `url<-`                    | `http://api/items#(headers: #{...})<- #{id: 1}` | The POST form. Parses to a PostPath node and triggers an HTTP POST. The url may include a transient `#(...)` config that is applied to the operation. |

### 2.3. The `scope` Data Type

In addition to the types created by literals, SLIP has a fundamental object type called `scope`. A `scope` is a "live" object that is lexically linked to its creation scope, forming the foundation for all object-oriented programming, prototypes, and type definitions.

Unlike `dict`s or `list`s, a `scope` is **not** created by a literal. It is created exclusively by calling the `scope` function.

```slip
-- Create a `scope` object that will serve as a prototype.
Character: scope #{
    hp: 100
}
```

The `scope` object is the cornerstone of SLIP's object model, which is detailed in Section 5.

### 2.4. Data Type Semantics

The different path forms (`get-path`, `set-path`, `del-path`, `piped-path`, `post-path`, and `multi-set-path`) are all distinct, first-class data types. The evaluator inspects an object's type to determine how to act on it. For example, encountering a `SetPath` object as the first term of an expression triggers an assignment. Two path objects are considered equal if they are of the same type and their canonical string representations are identical.

Like paths, other containers such as `list`, `dict`, and `scope` are mutable reference types. Assigning a container to a new variable creates a reference to the original, not a copy. Modifications made through one reference will be visible through all others. To create a new, independent instance, use the `copy` (shallow) or `clone` (deep) functions.

### 2.5. Querying Collections with `[...]`

SLIP distinguishes between static property access (`player.hp`) and dynamic queries. Square brackets (`[]`) are the entry point to a powerful **Query DSL** that goes beyond simple indexing to enable filtering and slicing on all collection types.

The query DSL supports three primary forms:

- **1. Index/Key:** Retrieves a single element from a collection.

  - For lists and strings, this is a zero-based numeric index.
  - For `dict`s and `scope`s, this is a key lookup.

  ```slip
  my-list: #[10, 20, 30]
  my-list[1] -- Returns 20

  my-dict: #{ name: "Kael" }
  my-dict["name"] -- Returns "Kael"
  ```

- **2. Slice:** Extracts a sub-list from a list or string.

  ```slip
  my-list: #[10, 20, 30, 40, 50]
  my-list[1:4] -- Returns #[20, 30, 40]
  ```

- **3. Filter:** Returns a new list containing only the elements that match a condition. The syntax consists of a comparison operator (`>`, `<`, `=`, `!=`, etc.) followed by a value.
  ```slip
  numbers: #[15, 7, 100, 42]
  numbers[> 20] -- Returns #[100, 42]
  ```

#### Advanced Filtering

The filter predicate inside the square brackets is a powerful feature that allows for complex, multi-part conditions. The content of the filter is a complete expression that is evaluated for each item in the collection.

Within this expression, a special syntax is used to distinguish between accessing a property of the item being filtered and accessing a variable from the surrounding lexical scope:

- **Dot-prefixed paths** (e.g., `.hp`, `.name`) refer to properties of the current item being processed.
- **Bare names** (e.g., `threshold`, `class-name`) refer to variables in the current lexical scope.

You can combine multiple conditions using the standard `and` and `or` operators. This allows for highly expressive, readable queries.

```slip
-- A list of player objects
players: #[
  #{ name: "Karl", class: "Warrior", hp: 120 },
  #{ name: "Jaina", class: "Mage", hp: 110 },
  #{ name: "Thrall", class: "Warrior", hp: 95 }
]

-- Find all Warriors with HP over 100
strong-warriors: players[.class = "Warrior" and .hp > 100]

-- Project their names
strong-warrior-names: strong-warriors |map (fn {p} [ p.name ])
-- strong-warrior-names is now #["Karl"]
```

A key feature of the query system is the **vectorized pluck**. When you access a property on a collection of objects, SLIP automatically "plucks" that property from each object and returns a new list of the results. This new list can then be queried.

This allows for incredibly expressive, single-line data manipulation.

```slip
-- A list of player objects
players: #[
    #{ name: "Kael", hp: 75 },
    #{ name: "Jaina", hp: 120 },
    #{ name: "Thrall", hp: 90 }
]

-- 1. "Pluck" the `hp` from every player. This yields a temporary list: #[75, 120, 90].
-- 2. Filter that new list, keeping only values > 100.
-- The result is a list containing only Jaina's HP.
high-hp-players: players.hp[> 100] -- Returns #[120]
```

This makes `[...]` a powerful and consistent tool for all forms of dynamic data access and filtering.

### 2.6. Strings: i-strings and raw-strings

SLIP provides two string literal forms with different semantics:

- i-strings: Written with double quotes, e.g., "..."

  - Behavior: These are interpolated strings that are automatically dedented and support Mustache-style templating using double braces.
  - Dedent: Common leading indentation is removed from every line, making multi-line strings easy to author inline.
  - Templating: Placeholders of the form {{ expression }} are evaluated in the current scope and the result is inserted into the string.
  - Example:
    ```slip
    name: "Kael"
    banner: "
      Welcome, {{name}}!
      The time is {{time}}."
    -- 'banner' is automatically dedented to:
    -- "Welcome, Kael!\nThe time is 1720000000.0."  (example)
    ```

- raw-strings: Written with single quotes, e.g., '...'
  - Behavior: Raw strings are not evaluated or escaped at all. Their contents are taken verbatim.
  - Use cases: Ideal for regular expressions, file paths, or any text where backslashes and braces must be preserved exactly.
  - Examples:
    ```slip
    pattern: '\d+\s+\w+'              -- backslashes are preserved literally
    windows-path: 'C:\Users\Me\file'  -- no escaping, no interpolation
    braces: '{{not a placeholder}}'   -- stays exactly as typed
    ```

Notes:

- Choose i-strings for user-facing text and templates where you want interpolation and clean multi-line formatting.
- Choose raw-strings when you need exact byte-for-byte text with no processing, such as regex patterns or OS paths.

## 3. Assignment and Functions

The two most fundamental operations in SLIP are assigning values to paths and creating functions. SLIP has a single, powerful assignment operator (`:`) that handles all binding through pattern matching, and a single function constructor (`fn`) for creating closures.

### 3.1. Assignment (`:`): The Path-Pattern Matching Model

SLIP's grammar has only one special syntactic construct: assignment, denoted by the colon (`:`). Its power comes from the fact that the Left-Hand Side (LHS) is not an expression to be evaluated, but a **literal, unevaluated pattern**. The evaluator inspects the _structure_ of this pattern to determine which of several binding strategies to apply.

This single, powerful `:` form unifies simple binding, destructuring, slice manipulation, and even dynamic, computed targets.

An assignment is an expression that evaluates to the value being assigned. This enables a concise "update" pattern where the right-hand side of the assignment is an operation on the path's current value. The interpreter reads the value, applies the operation, writes the result back, and returns the new value, all in one step.

```slip
-- Simple update with an infix operator
counter: 1
counter: + 1  -- Reads 1, computes 1+1, writes 2, returns 2

-- Unary update with a piped function
heal: fn {n} [ n + 10 ]
hp: 40
hp: |heal     -- Reads 40, computes heal(40), writes 50, returns 50
```

#### Assignment Strategies

Here are the different binding strategies determined by the pattern on the left-hand side of the `:`:

- **1. Simple Binding**

  - **Behavior:** Binds a single value to a single path. This is the most common form of assignment.
  - **Syntax:** `path.to.value: expression`
  - **Example:** `user.name: "John"`

- **2. Generic Function Merging**

  - **Behavior:** Adds a new method implementation to an existing generic function. If a function (created by `fn`) is assigned to a path that already holds a generic function, its method is merged into the existing container. This is the core mechanism for creating multi-method functions.
  - **Syntax:** `function-name: fn {signature} [body]`
  - **Example:**
    ```slip
    -- 1. Creates a generic function `render`.
    render: fn {data: string} [ ... ]
    -- 2. MERGES a new method into the existing `render` function.
    render: fn {data: number} [ ... ]
    ```

- **3. Scope Registration**

  - **Behavior:** Registers a new `scope` object as a formal type. The first time a `scope` is assigned to a path, the system registers it by giving it a unique type ID and a canonical name in its `.meta` property.
  - **Syntax:** `TypeName: scope #{...}`
  - **Example:** `Character: scope #{ hp: 100 }`

- **4. Destructuring Binding**

  - **Behavior:** Binds elements from a list on the right to multiple paths defined in a list pattern on the left. The number of paths must match the number of elements.
  - **Syntax:** `[path1, path2, ...]: list-expression`
  - **Example:** `[x, y]: #[10, 20]`

- **5. Slice Replacement**

  - **Behavior:** Replaces a slice of a target list with the elements from another list.
  - **Syntax:** `list[start:end]: new-list-expression`
  - **Example:** `items[1:3]: #[ "new", "items" ]`

- **6. Vectorized (Columnar) Binding**

  - **Behavior:** A "columnar" operation that sets a property on _every item_ within a list slice. If the right-hand side is a value, it's applied to all items. If it's a list, values are assigned element-wise and the list lengths must match.
  - **Syntax:** `list[start:end].property: value-or-list-expression`
  - **Example:** `users[:10].is-active: false`

This pattern also supports update-style expressions. The operation on the right-hand side is applied to each matching element individually.

**Example:**
```slip
-- Give +10 hp to all players with less than 50 hp
players.hp[< 50]: + 10
```

- **7. Parent Scope Binding**

  - **Behavior:** Modifies a binding in an outer scope. Each leading `../` prefix climbs one level up the parent scope chain before performing the assignment.
  - **Syntax:** `../path: expression`
  - **Example:** `../counter: counter + 1`

- **8. Dynamic (Programmatic) Binding**
  - **Behavior:** The "metaprogramming" escape hatch. The parenthesized expression on the left is evaluated _first_ to produce a target pattern (e.g., a `path` or a list of `paths`). The assignment is then performed on that dynamically generated target.
  - **Syntax:** `(expression-that-yields-a-path): value-expression`
  - **Example:** `(join `user` `name`): "John"`

### 3.2. Deletion (`~`): Unbinding a Path

Complementing the `set-path` (`:`) for binding is the `del-path` (`~`) for unbinding. The tilde is not an operator but part of an atomic `del-path` term recognized by the tokenizer. This creates a `DelPath` object that instructs the evaluator to perform the unbinding.

- **Behavior:** Unbinds a name from its scope. The target of the deletion can be a static path or a dynamic expression that resolves to a path. If the unbinding results in an empty `scope` object, the now-empty `scope` is pruned from its parent, and this pruning can cascade up the path chain.
- **Syntax:** `~path.to.value` or `~(expression-that-yields-a-path)`
- **Example (Static):** `~user.old-session-token`
- **Example (Dynamic):** `~(join `user `session-token)`

Like other path types, `del-path` also supports runtime configuration via a metadata block.

- **Example:** `~database/records/123#(soft-delete: true)`

### 3.3. Functions: Generics and Multiple Dispatch

In SLIP, there is no distinction between a simple function and a "method." All functions are **generic functions** (also known as multimethods), which are containers for one or more implementations. The SLIP runtime uses a powerful **multiple dispatch** system to automatically select the correct implementation based on the number and types of the arguments provided in a call.

This single, unified system is used for everything from simple function calls to complex, type-based polymorphism and arity-based overloading (optional arguments).

#### The `fn` Constructor

You create a function implementation using the `fn` constructor. To create a named function, you simply assign the result of `fn` to a path.

- **Syntax:** `function-name: fn {signature} [body]`
  - `signature`: A `sig` literal (`{...}`) that defines the parameters and their optional types.
  - `body`: A `code` block (`[...]`) containing the function's logic.

````slip
-- Defines a function 'add' that takes two arguments.
add: fn {x, y} [ x + y ]

#### Variadic Arguments (Rest Parameters)

SLIP supports variadic functions through a "rest parameter" syntax. By appending `...` to the final parameter name in a signature, you indicate that it should collect all remaining arguments from a call into a single `list`. The rest parameter must be the last one in the signature. If no extra arguments are provided, it will be bound to an empty list.

```slip
-- Example of a variadic function
log-message: fn {level, parts...} [
    -- `parts` will be a list of all arguments after `level`.
    full-message: join parts " "
    emit level full-message
]

-- Call with multiple arguments
log-message "info" "User" "Kael" "logged in."
-- Inside the function:
--   level -> "info"
--   parts -> #["User", "Kael", "logged in."]
````

#### Generic Functions

The first time you define a function (e.g., `render`), you are implicitly creating a generic function container and adding its first method. You can then add more methods to the same generic function by defining another function with the same name but a different signature.

The dispatcher will select the correct implementation based on the types of the arguments.

```slip
-- 1. Creates a generic function `render` and adds a method for `string`s.
render: fn {data: `string`} [
    "Textual data: {data}"
]

-- 2. Adds a new method to the SAME `render` function for `number`s.
render: fn {data: `number`} [
    "Numeric data: {data}"
]

-- 3. Adds a fallback method for any other type.
render: fn {data} [
    "Some other data."
]

-- --- Dispatch in action ---
render "hello"  -- Returns "Textual data: hello"
render 123      -- Returns "Numeric data: 123"
render #[]      -- Returns "Some other data."
```

#### Arity Overloading (Optional Arguments)

The multiple dispatch system is also the mechanism for handling functions with different numbers of arguments (arity). There is no special syntax for "optional arguments." Instead, you simply define multiple methods with the same name but different numbers of parameters.

This is commonly used for constructor-like functions, where some arguments can be omitted.

```slip
-- The standard library `create` function is a great example.

-- Method 1: No arguments. Creates an empty scope.
create: fn {} [ scope #{} ]

-- Method 2: One argument. Creates a scope that inherits from a prototype.
create: fn {prototype} [ scope #{} |inherit prototype ]

-- Method 3: Two arguments. Creates a scope, inherits, and then runs a
-- configuration block on it.
create: fn {prototype, config-block} [
    (scope #{} |inherit prototype) |with config-block
]

-- --- Dispatch in action based on arity ---
my-obj-1: create                      -- Calls method 1
my-obj-2: create Player               -- Calls method 2
my-obj-3: create Player [ name: "Kael" ] -- Calls method 3
```

This approach makes function behavior explicit and easy to reason about, as each combination of arguments is handled by its own distinct implementation.

### 3.4. A Note on Truthiness

SLIP adopts Python's standard rules for what is considered "truthy" or "falsey".

A value is considered "falsey" if it is:

- The boolean `false`
- The value `none` (which an empty evaluation group `()` evaluates to)
- Numeric zero (`0` or `0.0`)
- Any empty collection, such as:
  - An empty string (`''` or `""`)
  - An empty list (`#[]`)
  - An empty dictionary (`#{}`)

All other values are considered "truthy".

Example:

```slip
-- An empty list is falsey, so the 'else' block runs.
active-players: #[]
if active-players [
    print "There are players online."
] [
    print "The server is empty."
]
-- --- Expected Output ---
-- The server is empty.
```

### 3.5. Meta-parameters with Signature Literals

In SLIP, some functions require arguments that are declarative metadata rather than expressions to be evaluated. A clear convention is used for this: the argument is provided as a signature literal (`{...}`). This signals to both the reader and the interpreter that the argument is a pattern or declaration to be inspected, not a value to be computed.

This pattern is used consistently by core functions:

- **`fn {args} [body]`**: The `{args}` block is a parameter declaration.
- **`foreach {vars} collection [body]`**: The `{vars}` block is a pattern for destructuring items from the collection.
- **`for {i} 0 10 [body]`**: The `{i}` block declares the loop index variable.

This convention makes the code's intent obvious. When you see `my-func {pattern} data`, you immediately understand that `{pattern}` is providing metadata to control how `my-func` operates on `data`.

---

## 4. Infix Syntax and the Pipe Operator

SLIP's intuitive, left-to-right syntax for chaining operations is not the result of special parsing rules or transformations. Instead, it emerges naturally from the evaluator's **Uniform Call Syntax** and the concept of **piped paths**.

### 4.1. The Implicit Pipe Call

The evaluator uses a simple, type-driven rule to handle function calls within a flat list:

- **Prefix Call:** If the first element is a `function`, it's a standard prefix call (e.g., `add 1 2`).
- **Implicit Pipe / Infix Call:** If the first element is a non-function value, the evaluator checks if the _second_ element is a **piped path**. If so, it triggers an implicit pipe call, using the first value as the first argument to the function indicated by the piped path.

A `piped-path` is a distinct data type created by the `|` syntax. At the AST level, this is a `piped-path` node (e.g., `[piped-path [name 'add']]`), which the transformer converts into a `PipedPath` object for the evaluator.

### 4.2. Infix Syntax in Practice

Familiar infix syntax is just a convenient way to trigger the implicit pipe call rule. Operators like `+`, `-`, and `*` are simply paths in the scope that are bound to piped paths.

**Example: Evaluating `10 + 5`**

1.  **Parsing:** The parser sees `10 + 5` and produces a flat AST: `[<number 10>, [get-path [name '+']], <number 5>]`.
2.  **Evaluation:**
    - The evaluator processes the list. The first item, `10`, is a value, not a function.
    - It looks at the second item, the path `+`. It resolves this path in the current scope and finds it is bound to the _piped path_ `|add` (AST: `[piped-path [name 'add']]`).
    - This triggers the **Implicit Pipe Call** rule. The evaluator calls the `add` function, passing `10` as the first argument and `5` as the second. The expression is evaluated as if it were `add 10 5`.
    - The result is `15`.

This mechanism works for chained operations as well. The expression `10 + 5 * 2` is evaluated strictly left-to-right: `(add 10 5)` is executed first, yielding `15`, which then becomes the input to the next operation, `(multiply 15 2)`, yielding `30`.

### 4.3. The Explicit Pipe Operator `|`

The pipe operator `|` is the explicit way to create a piped path and chain operations. It is not a special operator but syntactic sugar that modifies the path immediately following it.

- `data |map [ ... ]` is parsed as `[expr [get-path [name 'data']], [piped-path [name 'map']], [code ...]]`
- The evaluator sees `data` (a value) followed by `|map` (a piped path), triggering the same implicit pipe call rule used for infix math.
The pipe can also be used for unary calls. When a piped path appears without a right-hand argument, it is treated as a unary call where the value on the left becomes the single argument to the function. For example, `hp |heal` is equivalent to `heal hp`.

### 4.4. Operator Definitions

To define a new operator, you simply bind a path to a piped path. A forward slash `/` is used to create a path from the root scope, which is necessary for defining symbolic operators that might otherwise be misinterpreted by the parser.

```slip
-- The `add` function is a host primitive. The `+` path is bound
-- to the *piped path* `|add`.
/+: |add

-- The division operator `/` is also bound.
/: |div

-- Now the infix expressions '10 + 20' and '20 / 2' will work.
```

The following table lists the default operator bindings provided by the standard root scope.

| Operator | Bound Piped Path |
| :------- | :--------------- |
| `+`      | `\|add`          |
| `-`      | `\|sub`          |
| `*`      | `\|mul`          |
| `/`      | `\|div`          |
| `**`     | `\|pow`          |
| `=`      | `\|eq`           |
| `!=`     | `\|neq`          |
| `>`      | `\|gt`           |
| `>=`     | `\|gte`          |
| `<`      | `\|lt`           |
| `<=`     | `\|lte`          |
| `and`    | `\|logical-and`  |
| `or`     | `\|logical-or`   |

### 4.5. The "No Double Pipe" Rule

To maintain clarity, the explicit pipe operator `|` cannot be applied to a path that is already an alias for a piped path, such as an infix operator.

The `and` operator, for example, is just an alias for the piped path `|logical-and`. Applying another pipe to it (`|and`) would be redundant—a "double pipe"—and is disallowed by the interpreter.

This rule enforces a clear separation of concerns:

- Use infix operators (`+`, `and`, etc.) directly for their intended purpose: `1 + 2`, `true and false`.
- Use the explicit pipe `|` only on standard, non-piped functions to create a data processing chain: `data |map [...]`.

- **Correct:** `a and b`
- **Correct:** `data |map [...]`
- **Incorrect (Runtime Error):** `a |and b` -- `and` is already an alias for a pipe

### 4.6. Controlling Order of Operations

Because SLIP evaluates strictly from left to right, you must use parentheses `()` to control the order of operations. The code inside the parentheses is evaluated as a complete, separate expression, and its final result is then used as a single value in the outer expression.

```slip
-- Default left-to-right evaluation
-- Equivalent to (multiply (add 10 5) 2)
result: 10 + 5 * 2  -- result is 30

-- Using parentheses to force a different order.
-- The group (5 * 2) is evaluated first, resulting in 10.
-- The expression then becomes equivalent to 10 + 10.
result: 10 + (5 * 2) -- result is 20
```

This explicit, predictable system is a core feature of SLIP's design, favoring clarity and simplicity over hidden precedence rules.

### 4.7. Chained Pipe Example

The left-to-right evaluation model makes chaining multiple pipe operations highly readable and intuitive.

- **Example: `data |filter [ x > 10 ] |map [ x * 2 ]`**

  Assuming `data` is `#[1, 15, 20]`, the evaluation proceeds as follows:

  1.  The evaluator processes `data`, resulting in the list `#[1, 15, 20]`.
  2.  It then sees the pipe operator `|` followed by `filter`. An implicit pipe call is triggered: `filter #[1, 15, 20] [ x > 10 ]`.
  3.  The result of the filter call is `#[15, 20]`. This value becomes the input for the next step.
  4.  The evaluator processes this new value, `#[15, 20]`, followed by `|map`. It triggers another pipe call: `map #[15, 20] [ x * 2 ]`.
  5.  The result of the map call is `#[30, 40]`.
  6.  This is the final result of the entire expression.

## 5. The SLIP Object Model

SLIP's object system is built on a powerful, dispatch-oriented model that clearly separates data from behavior. It avoids the complexities of classical inheritance in favor of a more flexible system built on a few core, orthogonal concepts. There are no `class` blueprints. Instead, you compose objects and behaviors using a small set of standard functions.

This model is built on five pillars:

1.  **`scope`**: The function for creating all objects.
2.  **Generic Functions**: Global, dispatchable functions that define behavior.
3.  **`create`**: A helper function for instantiating objects.
4.  **`inherit` and `mixin`**: Two distinct functions for establishing "is-a" vs. "has-a" relationships.
5.  **`.meta`**: A reserved property for introspection and metadata.

### 5.1. Pillar 1: The `scope` Function for Prototypes

The `scope` function is the fundamental tool for creating objects. It produces a `scope` object, which is a "live" data structure that is lexically linked to its creation scope and can serve as a prototype for other objects.

The `scope` function takes a `dict` as an argument to define the object's initial data. For safety, the `.meta` property is reserved for the system and cannot be provided in the initial data.

```slip
-- Create a prototype object for all characters.
-- It is created by calling `scope` and is assigned to a PascalCase name.
Character: scope #{
    hp: 100,
    stamina: 100
}
```

### 5.2. Pillar 2: Generic Functions for Behavior

In SLIP, behavior is not stored on the objects themselves. There are no "methods" attached to an object's data. Instead, behavior is defined in **global generic functions** that dispatch based on the type of their arguments.

This cleanly separates an object's data (what it _is_) from its behavior (what it can _do_).

```slip
-- This is a global generic function. It defines a `describe` behavior
-- that can operate on any `Character` object.
describe: fn {subject: Character} [
    "A character with {subject.hp} HP and {subject.stamina} stamina."
]

-- The behavior is invoked with a standard function call.
player: create Character
describe player -- Returns "A character with 100 HP and 100 stamina."
```

### 5.3. Pillar 3: Creating Instances with `create`

The standard library provides a `create` helper function which is the canonical way to create a new instance that inherits from a prototype. It is a simple helper that combines `scope` and `inherit`.

```slip
-- Create a new instance of a Character.
-- `create` returns a new, empty `scope` object whose prototype
-- is now `Character`.
player: create Character

-- You can then customize the instance.
player.hp: 150

-- The instance inherits properties from its prototype.
player.stamina -- Returns 100

-- Generic functions work on instances as well as prototypes.
describe player -- Returns "A character with 150 HP and 100 stamina."
```

### 5.4. Pillar 4: `inherit` vs. `mixin`

SLIP provides two distinct and explicit tools for building objects from parts, avoiding the ambiguity of multiple inheritance.

#### `inherit`: The "is-a" Relationship

The `inherit` function establishes an object's single, foundational identity. It sets the immutable `meta.parent` property, which is used for property lookup and type dispatch.

- **The "Inherit-Once" Rule:** To ensure a clear and simple prototype chain, `inherit` can only be called **once** on any given object. Attempting to set a new parent on an object that already has one will result in an error.

```slip
-- A `Player` is-a `Character`.
Player: scope #{ title: "Adventurer" }
inherit Player Character

-- A `Warrior` is-a `Player`.
Warrior: scope #{}
inherit Warrior Player
```

#### `mixin`: The "has-a" Relationship

The `mixin` function is for composition. It establishes a live, dynamic link between a target object and one or more `scope` objects that provide shared capabilities. This is a reference-based relationship, not a copy operation. It does not affect the object's parent or identity.

When properties are looked up on the target object, the system will search through its mixins (in the order they were added) before searching its parent prototype.

- **Repeatable:** You can call `mixin` multiple times on the same object to layer on new capabilities.

```slip
-- Define some modular capabilities as scopes. These can have their own parents.
CanFly: scope #{
    fly: fn {self} [ self.altitude: 100 ]
}
CanTalk: scope #{
    greet: fn {self, target} [ "Hello, {target.name}!" ]
}

-- Create an instance.
griffon: create Character

-- Add capabilities by mixing them in. This creates a link, not a copy.
mixin griffon CanFly
mixin griffon CanTalk

-- The griffon can now use the `fly` and `greet` functions via the lookup chain.
griffon.fly
griffon.greet
```

This clear distinction—a single, immutable inheritance for identity and repeatable mixins for capabilities—is a cornerstone of SLIP's explicit and easy-to-reason-about object model.

### 5.5. Pillar 5: The `.meta` Property for Introspection

Every `scope` object has a reserved `.meta` property, which is a dictionary containing data _about_ the object. This is the primary mechanism for runtime introspection.

The `.meta` property contains system-managed information:

- `.meta.name`: The fully-qualified name of the object if it has been assigned to a path (e.g., `"main.Character"`).
- `.meta.parent`: A direct reference to the object's prototype, set by `inherit`.
- `.meta.type`: For a function, this holds the `sig` object that defines its signature.

You can also add your own metadata, such as documentation.

```slip
-- Add a docstring to the Character prototype.
Character.meta.doc: "The base prototype for all characters."

-- Introspect the object at runtime.
print Character.meta.name -- Returns "main.Character"
print Player.meta.parent  -- Returns (The Character scope object)
```

### 5.6. Introspection with `is-a?`

The standard library provides an `is-a?` function to check the prototype chain of an object.

- `is-a? <object> <prototype>`: Returns `true` if the `<prototype>` scope exists anywhere in the `<object>`'s parent chain. It returns `false` for non-scope objects or if the prototype is not found.
- `is-schema? <object>`: Returns `true` if the object inherits from the base `Schema` prototype.

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
-- message is now "Access Granted"
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
-- --- Output ---
-- 3
-- 2
-- 1
```

#### `loop`

For convenience, the core library provides a `loop` function that creates an infinite loop. It is a simple alias for `while [true] [...]`. A `return` or other non-local exit is required to break out of the loop.

```slip
-- A simple server loop that never exits.
loop [
    connection: (accept-connection)
    task [
        handle-request connection
    ]
]
```

#### `foreach`

The `foreach` function is the most versatile tool for iterating over collections. It takes a variable pattern, a collection expression, and a body `code` block. The loop returns `none`.

- **Iterating over a List:**
  When iterating over a list, the variable pattern is a path that is assigned each element in sequence.

  ```slip
  foreach {fruit} #["apple", "banana"] [
      print "I like to eat {fruit}s."
  ]
  ```

- **Iterating over a Dictionary (or Scope):**
  When iterating over a mapping, a single-variable pattern iterates keys. Use a two‑variable pattern to destructure key/value pairs. To iterate values or explicit pairs, use the helpers `(values mapping)` and `(items mapping)`.

  ```slip
  scores: #{"Kael": 100, "Jaina": 150}

  -- Single variable → keys (fetch values on demand)
  foreach {name} scores [
      print "{name} -> {scores[name]}"
  ]

  -- Two variables → key/value pairs
  foreach {name, score} scores [
      print "{name} has a score of {score}."
  ]

  -- Explicit values iteration
  foreach {score} (values scores) [
      print "Score: {score}"
  ]

  -- Explicit items iteration (pairs)
  foreach {name, score} (items scores) [
      print "{name}: {score}"
  ]
  ```

### 6.3. Dispatch: Algorithm and Example

While `if` is useful, the most powerful and idiomatic way to handle complex logic in SLIP is to use the **multiple dispatch system**. By defining multiple methods for a single generic function, you can select behavior based on argument types, arity, and even argument values using `|guard` clauses.

This section provides a complete, MUD-themed example showing how all these features work together.

#### The Dispatch Algorithm: Specificity First

The dispatcher supports three match kinds per annotated parameter, in this order of specificity:

1. Exact instance

- The argument is the exact same scope object as the annotation (identity match).

2. Mixin capability

- The argument has the annotated scope in its `meta.mixins` list, or via a mixin’s own `meta.parent` chain.

3. Prototype inheritance

- The annotated scope appears on the argument’s `meta.parent` chain.

Scoring and selection:

- For each argument, compute a pair `(kind_rank, distance)`:
  - exact: `(0, 0)`
  - mixin: `(1, d)` where `d` is `0` for a direct mixin, otherwise the number of parent steps on the mixin object to reach the annotated scope
  - inherit: `(2, d)` where `d` is the number of parent steps from the instance to the annotated prototype
- A candidate method’s score is the element‑wise sum across its annotated parameters. The dispatcher selects the method with the lowest score.
- Ties are broken by lower total distance, then by definition order (earlier wins).

Guards:

- `|guard` clauses must evaluate to a truthy value for a method to be a candidate.

This supports instance‑specific overrides, capability‑based dispatch (mixins), and prototype‑based dispatch, with deterministic behavior.

#### Example: `apply-damage`

This example models a combat system. The `apply-damage` function behaves differently based on the target's type and the damage type.

**Step 1: Define Prototypes and a Type Alias**

First, we define our object prototypes (`Character`, `Player`) and create a `DamageType` alias for a set of path literals. This makes our function signatures clean and readable.

```slip
-- Define base prototypes.
Character: scope #{ name: "Entity", hp: 100 }
Player: scope #{ title: "Hero" } |inherit Character

-- Create a type alias for a union of damage types.
-- This is just a variable assigned to a `sig` object.
DamageType: { `physical`, `fire`, `ice` }
```

**Step 2: Define the Generic Function with Multiple Methods**

Define the `apply-damage` generic function by providing several method implementations.

```slip
-- Method 1: The most general case for physical damage.
apply-damage: fn {target: Character, type: DamageType, amount: number} [
    target.hp: target.hp - amount
    emit "combat" "{target.name} takes {amount} {type} damage."
] |guard [ type = `physical` ]


-- Method 2: A specific method for Players taking fire damage.
-- This is MORE SPECIFIC than the general fire method below.
apply-damage: fn {target: Player, type: DamageType, amount: number} [
    -- Players have fire resistance from their gear.
    final-damage: amount * 0.5
    target.hp: target.hp - final-damage
    emit "combat" "{target.name} resists, taking only {final-damage} fire damage."
] |guard [ type = `fire` ]


-- Method 3: A general method for any Character taking fire damage.
-- This will be chosen for Monsters, but not for Players, because
-- the method above is more specific for them.
apply-damage: fn {target: Character, type: DamageType, amount: number} [
    target.hp: target.hp - amount
    emit "combat" "{target.name} is burned for {amount} fire damage."
] |guard [ type = `fire` ]


-- Method 4: A guard to prevent "healing" via negative damage.
-- This method has no type constraints, so it applies to any arguments,
-- but its guard will only pass for non-positive amounts.
apply-damage: fn {target, type, amount} [
    emit "debug" "Damage amount must be positive."
] |guard [ amount <= 0 ]
```

This single, declarative structure replaces a complex nested `if/else if/else` block. The dispatch system automatically handles the logic of selecting the correct implementation based on both type and value, leading to cleaner, more maintainable, and more expressive code. This is the idiomatic way to model complex behavior in SLIP.

### 6.4. Function Exit

#### `return`

The `return` primitive terminates the execution of the current function and provides a return value.

- `return <value>`: Exits the function, returning the given `value` (or `none` if not provided). This is achieved by creating a `Response` object with `status: 'return'`, which is then handled by the function evaluation machinery.

## 7. Outcomes and Side Effects

A script communicates its results to the wider system in two distinct ways: by producing a final **outcome** and by generating a stream of **side effects**. SLIP provides two separate, complementary mechanisms for this: the `response` type for outcomes and the `emit` function for side effects.

### 7.1. The `response` Data Type for Outcomes

The `response` is a first-class data type that represents the structured outcome of a function call. It is the primary tool for handling both success and predictable failure cases, and it is the mechanism that powers non-local control flow.

A `response` object is an immutable structure with two components:

- **`status`**: A `GetPathLiteral` that categorizes the outcome (e.g., `` `ok ``, `` `err ``).
- **`value`**: The payload associated with the outcome (can be any data type).

You create a `response` using the `response` constructor: `response <status-path> <value>`.

### 7.2. The `respond` and `return` Primitives

To use a `response` to control function execution, you use the `respond` primitive.

- `respond <status-path> <value>`: This is the primary function for exiting the current function with a structured outcome. It creates a `response` and immediately triggers a non-local exit, making that `response` the return value of the function.

For the common case of simply returning a value without a special status, SLIP provides the familiar `return` primitive.

- `return <value>`: This is syntactic sugar for `respond `return <value>`.

When the interpreter encounters a `response` with the status `` `return ``, it "unwraps" it, and the function call evaluates to the `response`'s inner `value`. For any other status (like `` `ok `` or `` `err ``), the `response` object itself is returned as a whole.

### 7.3. Standard Statuses and Convenience Aliases

To promote consistency, SLIP defines a set of standard canonical `GetPathLiteral` values for common statuses.

| Canonical Path    | Typical Meaning                                                                      |
| :---------------- | :----------------------------------------------------------------------------------- |
| `` `ok` ``        | The operation completed successfully. The `value` is the result.                     |
| `` `err` ``       | A predictable, handleable error occurred. The `value` is an error message or object. |
| `` `not-found` `` | A specific kind of error for when a requested resource does not exist.               |
| `` `invalid` ``   | A specific kind of error for when input data is invalid.                             |
| `` `return` ``    | The special status used by `return` for a normal function exit.                      |

To avoid the need to constantly type backticks for these common paths, the SLIP core library provides a set of convenient, unquoted aliases. These are simply variables that are bound to the canonical `GetPathLiteral` values.

```slip
-- From root.slip:
ok:        `ok`
err:       `err`
not-found: `not-found`
invalid:   `invalid`
-- 'return' is a primitive and does not need an alias.
```

This allows you to write cleaner, more readable code.

**Good:** `respond ok player-obj`
**Verbose:** ` respond ``  `ok` `` player-obj`

### 7.4. `emit` for Side Effects

The `emit` function is completely separate from the `response` system. Its sole purpose is to log a side-effect event for the host application to process. It adds an event to the `ExecutionResult.side_effects` list but has **no effect on the script's control flow**.

This creates a clean separation: `respond` determines _what the function returns_, while `emit` determines _what the function tells the outside world_.

**Example: Using Both Systems Together**

```slip
find-player: fn {name} [
    player-obj: (host-object name)
    if player-obj [
        -- Outcome: Success. Use the 'ok' alias.
        respond ok player-obj
    ] [
        -- Side Effect: Log the failure for the server admin.
        emit "debug" "Failed to find player object for name: {name}"

        -- Outcome: Failure. Use the 'not-found' alias.
        respond not-found "That player is not online."
    ]
]
```

### 7.5. Capturing Outcomes with `with-log`

While `emit` is used to report side effects to the host application, the `with-log` primitive provides a way to capture and inspect the outcome and effects of a code block *from within a script*. This makes it an invaluable tool for testing, debugging, and creating higher-level abstractions that need to observe the behavior of a piece of code.

- **Syntax:** `with-log <code-block>`
- **Behavior:**
  1.  Executes the provided `code` block.
  2.  Intercepts all side effects generated by `emit` *only from within that block*.
  3.  Captures the final outcome of the block, normalizing it into a `response` object. A raw return value becomes `response ok <value>`, and a runtime error becomes `response err <message>`.
- **Return Value:** A dictionary-like object with two keys:
  - `outcome`: A `response` object representing the final outcome of the block.
  - `effects`: A list of side-effect events emitted within the block.

**Example: Inspecting a Code Block**

```slip
-- Use with-log to run a block of code and inspect its results.
log: with-log [
  emit "debug" "Performing an action..."
  10 + 20
]

-- The `log` object now contains the captured results.
-- `log.outcome` holds a `response` object with status `ok` and value `30`.
-- `log.effects` holds a list containing one side-effect event.

-- We can now inspect the `response` object's properties.
if [log.outcome.status = ok] [
    print "The block succeeded with value: {log.outcome.value}"
]
```

`with-log` cleanly separates the execution of the code from the observation of its results, isolating its effects from the main script's side-effect log. This makes it a powerful tool for building robust, introspective systems.

### 7.6. Handling Outcomes with Multiple Dispatch

The true power of this system is realized when `response` objects are handled by a generic function that uses `|guard` clauses to dispatch based on the response's status.

For this pattern to work, the function must take the response object as a named parameter so the guard clauses can inspect it.

```slip
-- Method 1: Handles the `ok` case using a guard clause.
handle-find-result: fn {response-obj} [
    -- Access properties using standard dot notation.
    player: response-obj.value
    emit "system" "Found player: {player.name}"
    player |do-something
] |guard [response-obj.status = ok]

-- Method 2: Handles the `not-found` case.
handle-find-result: fn {response-obj} [
    reason: response-obj.value
    emit "ui.error" reason
] |guard [response-obj.status = not-found]

-- Method 3: A fallback for any other value.
-- This will be selected if no other guards match.
handle-find-result: fn {other} [
    emit "error" "Received an unexpected result: {other}"
]

-- --- Usage ---
outcome: find-player "Kael"
handle-find-result outcome -- Will call the appropriate method based on the response.
```

This combination of `emit`, `respond`, and pattern matching provides a highly robust and expressive system for managing all facets of a script's execution.

You are 100% right. My apologies. I was pattern-matching to other languages and failed to apply SLIP's own radical consistency. You are absolutely correct on all points.

1.  **It should be a path, not a string.** This is a more powerful and consistent design. The location of a module is part of the language's path system, not just a piece of string data.
2.  **It should be `kebab-case`**. A module is a namespace, not a prototype. It should follow the standard variable naming convention.

Thank you for the sharp correction. Let's get it right. This is a much more elegant and "SLIP-like" design.

Here is the completely rewritten section that accurately reflects this superior model.

---


### 7.7. Modularity and Code Organization

In SLIP, modularity is not handled by special keywords. Instead, code organization is managed by a powerful `import` **function**, which is provided by the host environment as part of the standard library. This function leverages SLIP's path system to locate and load modules.

#### The `import` Function

The `import` function is the standard way to load and use code from other files. It takes a single **path literal** as an argument, which specifies the module's location using a scheme-based syntax.

- **Syntax:** `` variable-name: import `scheme://path/to/module`  ``
- **Behavior:**
  1.  The `import` function receives a `path-literal` object (e.g., `` `file://modules/math.slip` ``).
  2.  It asks the host application to inspect this path. The host is responsible for implementing the logic for different schemes (the first segment of the path, like `file:` or `https:`).
  3.  The host executes the module's code **exactly once** in a new, dedicated `scope`.
  4.  The host then **caches** this new scope. If `import` is called again with the same path, the host immediately returns the cached scope without re-running the code.
  5.  The `import` function returns the module's scope, which is then assigned to a local variable.

This host-driven approach provides maximum security and flexibility. The host can implement custom logic to load modules from a virtual filesystem, a network location, or a database, and can add support for new schemes (`git://`, `db://`, etc.) without changing the language itself.

#### A Note on Naming Conventions

The standard stylistic convention in SLIP is to use `kebab-case` for all variables, including those that hold imported modules. A module is a namespace, not a prototype, so it should not be capitalized.

```slip
-- Correct, idiomatic SLIP:
math: import `file://math.slip`
my-utils: import `https://sliplang.com/utils.slip`
```

#### Example Workflow

This example shows how a `main.slip` file can import and use functions from both a local and a remote module.

**File: `math.slip`** (Located locally)

```slip
-- This file is a module. It defines functions that will be
-- available to any script that imports it.

add: fn {a, b} [ a + b ]
subtract: fn {a, b} [ a - b ]
```

**File: `main.slip`**

```slip
-- Import the local math module using the 'file://' scheme.
-- The result is assigned to a standard, kebab-case variable.
math: import `file://math.slip`

-- Import a utility module from a remote web server.
utils: import `https://sliplang.com/utils.slip`

-- Now 'math' and 'utils' are scope objects in our environment. We can
-- access the functions defined within them using standard path syntax.
result: math.add 5 3  -- result is 8

utils.log "Calculation complete."
```

## 8. Advanced Features and Patterns

This chapter details several powerful features that build upon SLIP's core principles, enabling advanced programming patterns like transient path configuration and example-driven development.

### 8.1. Transient Path Configuration with `#(...)`

SLIP provides a special syntax, the `#(...)` block, for providing **transient, operational configuration** to a path-based call. This metadata is attached to a single operation and is not stored on the object itself.

This provides a clean separation between an object's persistent state (its data and `.meta` properties) and the temporary options for a single action.

#### Evaluator and Host Logic

The evaluator's role is to act as a dispatcher.

1.  It encounters a `get-path` or `del-path` node with a configuration block.
2.  It invokes the host system's path resolution mechanism.
3.  It passes the operation type (`GET` or `DELETE`), the path itself, and the configuration dictionary from the `#(...)` block to the host resolver.

The host resolver contains the intelligence to interpret the configuration dictionary and perform the appropriate action.

#### Practical Examples

**A. Configuring API Calls**

The configuration can contain any parameters the host resolver understands, such as timeouts, retries, or credentials.

```slip
-- Get a remote value with a custom timeout and API key.
api-response: http://domain.com/api/data#(
    timeout: 2,
    api-key: env.API_KEY
)
```

**B. Configuring Deletion**

The configuration allows for nuanced and safer deletion operations.

```slip
-- Perform a "soft delete" for auditing purposes in a database.
~db/users/123#(
    soft-delete: true,
    deleted-by: current-user.id
)
```

### 8.2. Example-Driven Development with `|example`

The standard library provides an `|example` helper function that offers a "triple benefit": it provides documentation, enables testing, and can be used to define method signatures implicitly.

An example is attached directly to a **specific method definition** at the moment it is created with `fn`.

#### The Triple Benefit

1.  **Documentation:** The `|example` block serves as clear, executable documentation.
2.  **Testing:** The SLIP test runner automatically discovers and executes these examples.
3.  **Implicit Type Signatures:** The `|example` block is a first-class citizen in the multiple dispatch system. If a method is defined without explicit types, the system will **infer a type signature from each example** and use those signatures to register one or more methods in the dispatch table.

#### How Examples Create Signatures

The SLIP dispatcher uses a simple, generative rule: **it creates one new method for each unique signature implied by the examples.**

1.  If the `fn` block contains **explicit type annotations** (e.g., `fn {x: int}`), that signature is used to create a single method. Any attached examples must be compatible with this signature.

2.  If the `fn` block has **no explicit types**, the system inspects each attached `|example` block individually. It derives a signature from the types in that example and registers a new method for that specific signature. All generated methods share the same underlying code block.

**Example: Creating Separate `int` and `float` Methods**

By providing two examples with different types, you generate two distinct methods.

```slip
-- Define ONE method body with TWO examples.
add: fn {a, b} [
    a + b
] |example { a: 2, b: 3 -> 5 }          -- Implies signature {a: int, b: int}
  |example { a: 2.0, b: 3.0 -> 5.0 }    -- Implies signature {a: float, b: float}

-- The system registers TWO methods in the 'add' dispatch table:
-- 1. A method for {a: int, b: int}
-- 2. A method for {a: float, b: float}

-- --- Dispatch in action ---
add 2 3        -- Works, calls the int method.
add 2.5 3.5    -- Works, calls the float method.
add 2 3.5      -- FAILS to dispatch. No method matches {int, float}.
```

#### Handling Mixed Types Explicitly

This model gives the programmer precise control. If you want to support mixed-type operations, you must provide an example for that specific combination.

```slip
-- To support mixed-type addition, we add more examples.
add: fn {a, b} [
    a + b
] |example { a: 2, b: 3 -> 5 }                  -- Method 1: {int, int}
  |example { a: 2.0, b: 3.0 -> 5.0 }            -- Method 2: {float, float}
  |example { a: 2, b: 3.5 -> 5.5 }              -- Method 3: {int, float}
  |example { a: 2.5, b: 3 -> 5.5 }              -- Method 4: {float, int}

-- Now, the call 'add 2 3.5' will succeed, matching the third method.
```

This explicit, example-driven approach is safer and more predictable than automatic type generalization. It ensures that a function only ever accepts the exact combinations of types that you have documented and tested.

### 8.3. The SLIP Test Framework

The `|example` helper is not just for documentation and type inference; it is the foundation of SLIP's built-in test framework. The standard library provides two functions, `test` and `test-all`, that execute these examples and report on their success or failure.

#### Testing a Single Function with `test`

The `test` function runs all examples attached to a single function (or generic function container).

-   **Syntax:** `test <function-object>`
-   **Behavior:** It iterates through all `|example` blocks, executes the function with the example's inputs, and compares the result against the expected output.
-   **Return Value:** It returns a `response` object summarizing the outcome.
    -   **Success:** `response ok <count>`, where `<count>` is the number of examples that passed.
    -   **Failure:** `response err <list-of-failures>`, where each item in the list is a dictionary detailing a failed example, e.g., `#{ index: 1, expected: 3, actual: 2 }`.

```slip
-- Define a function with one passing and one failing example
add: fn {x, y} [ x + y ]
  |example { x: 2, y: 3 -> 5 }    -- Passes
  |example { x: 1, y: 1 -> 3 }    -- Fails

-- Test the function
result: test add

-- The result is a response object indicating failure:
-- response err #[ #{ index: 1, expected: 3, actual: 2 } ]
```

#### Testing a Module with `test-all`

The `test-all` function scans an entire scope, finds all functions with examples, and runs `test` on each one.

-   **Syntax:** `test-all <scope-object>`
-   **Behavior:** Aggregates the results from all tests within the scope into a single summary report.
-   **Return Value:** It returns a summary inside a `response` object. The status is `ok` if all tests passed, and `err` otherwise. The value is a summary dictionary.

```slip
-- Define a module scope to hold our functions
math-mod: scope #{}

run-with [
  add: fn {a, b} [ a + b ] |example { a: 1, b: 2 -> 3 }
  mul: fn {a, b} [ a * b ] |example { a: 2, b: 3 -> 5 } -- This will fail
] math-mod

-- Test all functions in the module
summary-response: test-all math-mod

-- summary-response.status is `err`
-- summary-response.value is a dictionary like this:
-- #{
--   with-examples: 2,
--   passed: 1,
--   failed: 1,
--   details: #[
--     #{ name: "mul", failures: #[ #{ index: 0, expected: 5, actual: 6 } ] }
--   ]
-- }
```

This integrated test framework makes it trivial to verify the correctness of your code, turning documentation directly into a comprehensive test suite.

### 8.4. Reusing Method Implementations

A core principle of good software design is "Don't Repeat Yourself" (DRY). In SLIP, you can easily share the implementation logic of one method with another, even if they have completely different type signatures. This is achieved by composing SLIP's core primitives for introspection and evaluation.

The pattern relies on the `get-body` introspection primitive, which looks up a specific method and returns its implementation as a first-class `code` object.

#### The Pattern: Dynamic Body Definition

The idiomatic way to reuse a method's body is to dynamically provide it to the `fn` constructor at definition time. The `fn` constructor expects a `code` block for its body, and an evaluation group `(...)` is a perfect way to produce that `code` block on the fly.

**Example: Reusing a `float` Implementation for `int`s**

Let's assume we have an `add` method that is already defined for floats.

```slip
-- Step 1: The original float method already exists.
add: fn {a: float, b: float} [
    a + b
]
```

Now, we want to create a new method for integers that uses the exact same logic (`[a + b]`) without retyping it.

```slip
-- Step 2: Define the new int method by reusing the float method's body.
add: fn {a, b} (get-body add {a: float, b: float}) |example { a: 2, b: 3 -> 5 }
```

#### How It Works: A Step-by-Step Breakdown

This single, powerful expression is evaluated once, at definition time:

1.  `get-body add {a: float, b: float}` is executed. This looks up the existing float method and returns its body, the `code` object `[a + b]`.
2.  `fn {a, b} ...` is called. It receives the signature `{a, b}` and the `code` object `[a + b]` that was just returned from `get-body`.
3.  A new function is created. The result is a complete function object whose body is literally `[a + b]`.
4.  `|example { a: 2, b: 3 -> 5 }` is applied. It inspects the new function, sees it has no explicit types, and infers the signature `{a: int, b: int}` from the example.
5.  `add: ...` registers the new method. The final, fully-formed method with its `{int, int}` signature and `[a + b]` body is added to the `add` generic function's dispatch table.

This pattern is a demonstration of SLIP's consistency. It composes the language's fundamental building blocks—function creation, evaluation groups, and introspection—to achieve a powerful result in a single, elegant expression.

## 9. Data Modeling and Validation

In any real-world application, data must be validated against an expected shape before being processed. SLIP provides a powerful, declarative system for this. The core principle is that **a schema is just a regular SLIP data structure**, and validation is performed by standard library functions.

### 9.1. The Schema: A Specialized `scope`

You define the "shape" of your data using the `schema` function. This creates a specialized `scope` object that serves as your schema. It inherits from a base `Schema` type, which allows for powerful features like schema inheritance and type checking with `is-schema?`.

The keys in the schema are the expected field names, and the values are expressions that define the type and constraints for that field.

```slip
-- A schema for a User object.
UserSchema: schema #{
    name: `string`,
    age: `number`,
    is-active: `boolean`
}
```

### 9.2. The `validate` Function

The primary function for data modeling is `validate`. It is the main tool for data ingestion: it checks `data` against a `schema`, applies any default values specified in the schema, and returns a new, clean object.

- **`validate <data> <schema>`**
  This function returns a `response`:
  - `response ok <validated-object>`: If successful, the `value` is the new, validated object.
  - `response err <list-of-errors>`: If validation fails, the `value` contains a detailed list of all errors.

The most idiomatic way to use this function is with the pipe operator (`|`).

### 9.3. Basic Usage

```slip
-- Use `validate` to ingest and validate raw data.
raw-data: #{name: "Alice", age: 30, is-active: true}
outcome: raw-data |validate UserSchema

-- The `validate` function returns a `response`.
-- On success, the value is a clean, validated dictionary.
if (outcome.status = ok) [
    validated-user: outcome.value
    print "User created: {validated-user.name}"
]
```

### 9.4. Robust Error Handling

If the data does not match the schema, `validate` returns a structured `err` response.

```slip
-- Invalid data
raw-data: #{name: 123, age: "thirty"} -- Missing 'is-active', wrong types

-- The call to `validate` will not raise an error; it returns a response.
outcome: raw-data |validate UserSchema

-- outcome.status is now `err`
-- outcome.value is a list of validation error objects:
-- #[
--     #{field: "name",      error: "expected type 'string', got 'number'"},
--     #{field: "age",       error: "expected type 'number', got 'string'"},
--     #{field: "is-active", error: "field is required"}
-- ]
```

### 9.5. Advanced Schemas: Defaults and Optional Fields

The schema can use helper functions to specify more complex constraints. These helpers return special marker objects that `validate` knows how to interpret.

- **`default <value>`:** Provides a default value if the field is missing from the input data.
- **`optional <type>`:** Marks a field as optional.

```slip
ConfigSchema: schema #{
    host: `string`,
    port: (default 8080),
    user: (optional `string`)
}

-- Example usage:
conf1: (#{host: "localhost"} |validate ConfigSchema).value
-- conf1 is #{host: "localhost", port: 8080} -- 'user' is omitted.
```

### 9.6. Composition: Nested Schemas

Schemas can be composed by using one schema as the type for a field in another. The validation is recursive. Because schemas are `scope` objects, they can also inherit from each other.

```slip
ContactInfoSchema: schema #{ email: `string` }

UserSchema: create ContactInfoSchema [
    name: `string`
]

Now define a Team schema that contains a user-schema
TeamSchema: schema #{
    team-name: `string`,
    leader: `UserSchema`, -- The type is the UserSchema scope itself
    members: `list`
}

-- Raw data with a nested object
raw-team-data: #{
    team-name: "Dragons",
    leader: #{name: "Alex", email: "alex@a.com"},
    members: #[]
}

-- The validation will recursively validate the 'leader' object
-- against the UserSchema.
team: (raw-team-data |validate TeamSchema).value
```

This system provides a complete, robust, and declarative way to handle data validation, using nothing more than standard SLIP data structures and functions. It is the perfect embodiment of the language's philosophy.

## 10. Metaprogramming and Evaluation Control

In SLIP, metaprogramming is not a separate, compile-time system with special rules (like C macros or LISP's `defmacro`). It is a standard, runtime activity that leverages the fact that `code` objects are first-class data structures.

A `code` object (`[...]`) is a literal, unevaluated Abstract Syntax Tree. Because the parser creates a direct, 1:1 representation of the source code, the AST is a simple list of lists. This means you can inspect and manipulate code with standard list operations like indexing and slicing.

**Example: Manipulating Code with List Operations**

```slip
-- A code block is just data.
my-code: [
    y: (1 + 2)
    print y
]
```

Because the AST is a direct representation of the code, you can surgically extract parts of it. An operation like `x: my-code[0][1]` binds the AST node for the `(1 + 2)` part of the first expression to `x`. The variable `x` would now hold a `group` node, which can be manipulated like any other piece of data.

This powerful feature allows code to be constructed, analyzed, and transformed programmatically at runtime.

### 10.1. AST Node Types as Data

When you inspect a `code` object, its contents are not just simple lists. The elements are themselves structured data, known as **AST Nodes**. These nodes are a distinct category of data from first-class runtime types like `number` or `list`.

Each AST node has a type, identified by a `tag` (e.g., `expr`, `group`, `set-path`, `path`). You encounter and manipulate these nodes primarily during metaprogramming. For example, the operation `x: my-code[0]` will bind the AST node for the first expression in `my-code` to `x`. This value can then be inspected or used to build new `code` objects.

A full reference of these node types and their structure can be found in Appendix C. Evaluation is controlled by a small, powerful set of kernel functions.

### 10.2. Core Evaluation Functions

- `run <code>`: The primary function for executing a block of code. It evaluates the code within the current scope. If the `code` block is empty, it returns `none`; otherwise, it returns the value of the last expression.
- `run-with <code> <scope>`: Executes a code block within a specific, user-provided scope. Writes are contained within the target scope, but lookups for unbound names (like functions or operators) will resolve through the caller's scope.
- `list <code>`: Evaluates the expressions in a code block and collects all their results into a new `list`. This is the underlying function for the `#[...]` literal.
- `dict <code>`: Evaluates the expressions in a code block (typically assignments) and returns a new `dict` object. This is the underlying function for the `#{...}` literal.

### 10.3. Code Injection: `inject` and `splice`

`inject` and `splice` are special operators used inside a `code` block that is passed to `run` (or a similar function). They allow for the substitution of runtime values into the AST just before evaluation. They are used with function-call syntax.

- `(inject <path>)`: Looks up the `<path>` in the _calling_ scope (the one `run` was called from) and substitutes its value into the code being run. The value is injected as a single literal item.
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

### 10.4. Dynamic Path and Function Creation

- `call <path-literal | string> [<arg-list>]`: A powerful metaprogramming primitive.
  - **Path Creation**: When called with a string like `"user.name"`, it returns a `PathLiteral` (`\`user.name\``).
  - **Dynamic Invocation**: When called with a path and an argument list (`#[...]`), it resolves the path to a function and calls it.
  - **Dynamic Assignment/Deletion**: It can execute `SetPath` or `DelPath` literals.
    - `(call \`x:\`) 2` is equivalent to `x: 2`.
    - `(call \`~x\`)` is equivalent to `~x`.

- `fn {signature} [body]`: The core function for creating new `function` objects (closures). `fn` captures the current lexical scope and bundles it with the argument list and the unevaluated body of code.
  - Example: `add-five: fn {x} [ x + 5 ]`

### 10.5. Operator Definition

Infix operators like `+`, `*`, `>`, etc., are not special syntax. They are simply names (paths) in the current scope that are bound to `piped path` objects. The left-to-right evaluator triggers an implicit pipe call when it encounters one.

You define a new operator by binding its name to a piped path.

```slip
-- The `add` function is a host primitive. To define a new operator,
-- you bind its path to a function's piped path.
/+: |add
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
-- A player sets a magical, delayed trap.
print "You place a magical glyph on the floor. It will arm in 5 seconds."

task [
    -- This code runs in the background.
    -- `sleep` is a host function that pauses this task, but not the main script.
    sleep 5

    -- After the delay, update a variable.
    world.trap-is-armed: true
    print "The glyph flashes once, now armed."
]

-- The main script continues immediately without waiting for the sleep.
print "You step away from the glyph."
```

### 11.2. Task Safety and Cooperative Multitasking

A script running in a background task must be a "good citizen" and not monopolize the server's resources. SLIP's interpreter has a built-in safety mechanism to prevent infinite loops in tasks from freezing the application.

- **Automatic Yielding:** Inside a block started with `task`, the `while` and `foreach` loops will automatically "yield" control back to the host's event loop on each iteration (conceptually by performing a `sleep 0`). This allows the host to run other tasks (like processing commands from other players) before continuing the loop. This cooperative multitasking is essential for a stable multi-user environment.

**Example: A Long-Running Counter**

```slip
-- A script creates a global countdown timer.
world-events: #{
    meteor-timer: 100
}

-- Start a task to handle the countdown.
task [
    while [world-events.meteor-timer > 0] [
        -- The `while` loop automatically yields here on each iteration,
        -- preventing the server from freezing.
        world-events.meteor-timer: world-events.meteor-timer - 1
        sleep 1 -- Wait one second between decrements.
    ]

    -- This code runs after the loop finishes.
    print "A meteor streaks across the sky!"
]
```

### 11.3. Task Lifecycle and Management

Background tasks are tied to the `HostObject` that created them. This ensures that tasks are properly cleaned up when an object is removed from the game world (e.g., an NPC dies or a player logs out).

- **Registration:** When `task` is used, the created task is automatically registered with the `HostObject` that is the context of the current script.
- **Cancellation:** The `SLIPHost` base class provides a built-in API method, `cancel-tasks`, which can be called from SLIP or Python. This method finds all active tasks registered with that specific object and cancels them, preventing "zombie" scripts from running for objects that no longer exist.

**Example: A Player's Buff Timer**

```slip
-- This script runs when the player drinks a "Potion of Strength".
print "You feel a surge of power!"

-- Set the buff on the player object itself.
player.strength: player.strength + 5

-- Start a task to remove the buff after 60 seconds.
-- This task is automatically associated with the `player` host object.
task [
    sleep 60
    print "You feel the surge of power fade."
    player.strength: player.strength - 5
]

-- If the player logs out before the 60 seconds are up, the game engine
-- can call `player.cancel-tasks`, and this timer will be safely stopped.
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
-- Create a channel to transport the resources between the two tasks.
resource-channel: make-channel

-- --- The Gatherer NPC's Task (The Producer) ---
task [
    loop [
        -- 'find-resource' is a long-running host function.
        resource: find-resource
        emit "debug" "Gatherer found {resource}."

        -- Send the resource to the processing base via the channel.
        -- This will pause the gatherer if the processor is busy.
        send resource-channel resource
    ]
]

-- --- The Processing Base's Task (The Consumer) ---
task [
    loop [
        emit "debug" "Processor is waiting for a resource..."

        -- Wait to receive a resource from the channel.
        -- This will pause the processor until the gatherer sends something.
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
from slip import SLIPHost, slip_api_method

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
- **SLIP `~obj.hp`**: Calls `obj.__delitem__("hp")`.

This pattern provides a single, secure gateway for all data interaction between SLIP and your Python objects.

### 12.3. Method Access (`@slip_api_method` Decorator)

To prevent accidental exposure of internal methods, only functions explicitly marked with the `@slip_api_method` decorator are visible to the SLIP interpreter.

- **The Contract:** Any method on a `SLIPHost` subclass that should be callable from SLIP must have the `@slip_api_method` decorator.
- **Security:** If the decorator is omitted, the SLIP interpreter cannot see or call the method, even if it's public in Python. This provides a "secure by default" model.
- **Exposure model:** Exported methods are bound into the script scope as top-level functions using kebab-case names; you call `take-damage 10` directly (no `host-object` prefix).

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

- **SLIP Code:** `take-damage 10`
- **Binding:** The interpreter exposes Python `@slip_api_method` methods as top-level functions using kebab-case names derived from the Python name (e.g., `take_damage` -> `take-damage`).

### 12.5. The `host-object` Gateway Function

While SLIP scripts can pass around handles to host objects they already have, they cannot create them or pull them out of thin air. The host application must provide a single, global gateway function for this purpose.

- **The Contract:** Your host application must provide a SLIP function named `host-object`.
- **Implementation:** This function should take a single argument (usually a string ID) and look it up in a central registry of all active game entities. If found, it returns the live `SLIPHost` instance.
- **Note:** Methods exported via `@slip_api_method` are exposed as top-level SLIP functions; `host-object` is used to obtain host objects as data (so you can read/write their fields via `.__getitem__`/`.__setitem__`).

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
  - `<message>`: The data payload for the event, which can be any SLIP data type (e.g., a string, number, or dictionary).

**Example: A SLIP Script Generating Events**

```slip
-- A script for a "fireball" spell
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
-- Attempt to find the goblin.
target: find-enemy "goblin"

-- Check if the function returned none
if [target = none] [
   -- The 'then' block handles the failure case.
   print "There are no goblins here to attack."
] [
   -- The 'else' block runs if a target was found.
   print "You attack the goblin!"
   target |take-damage 10
]
```

### 13.5. Protocol Status Codes (Host-provided, optional)

When interacting with external resources via scheme paths like `file://` or `http://`, it can be useful to receive structured status information instead of just a return value or a script error. SLIP supports this through an opt-in mechanism using transient path configuration.

By default, a successful operation like `http://example.com/api` returns the response body directly, while a failure (e.g., a 404 or 500 error) raises a runtime script error. However, you can request a structured response by adding a configuration block to the path:

- **Lite Mode**: `path#(lite: true)` returns a two-element list `#[status, value]`.
- **Full Mode**: `path#(full: true)` returns a dictionary `#{status: <int>, value: <any>, meta: #{...}}`, which may contain additional metadata like HTTP headers.

The meaning of the `status` code depends on the protocol. For HTTP, it is the standard HTTP status code (e.g., `200`, `404`). For the filesystem, `0` typically indicates success, while other values may represent OS-level error codes. This feature allows scripts to handle I/O failures gracefully without halting execution.

```slip
-- Request a lite response to handle potential errors
[status, body]: http://api/items#(lite: true)
if [status != 200] [
    emit "error" "API request failed with status {status}"
]
```

Note that this behavior is specific to host-provided scheme path handlers and does not change the interpreter's own `ExecutionResult` status, which will still be `'success'` as long as the script itself runs without error.

## 14. Reference

This section details the core components of the SLIP language, from the fundamental evaluation rules to the high-level libraries that provide its rich functionality.

### 14.1. Core: Kernel Semantics and Required Built-ins

While most of SLIP's standard library can be written in SLIP itself, a minimal set of functions and operators—the "kernel"—must be provided by the host environment (e.g., in Python, Go, or Rust). These primitives form the irreducible core of the language upon which all other functionality is built.

#### Paths

SLIP's core notion of identity and navigation is the path. The language defines several distinct path data types, each signaling a specific intent to the evaluator.

- **`get-path`**: The default path form, used to read or look up a value (e.g., `user.name`). It can contain various segments, including names, root (`/`), parent (`../`), dynamic groups (`(...)`), and query segments (`[...]`). It may also carry a transient configuration block (`#(...)`) that the host can interpret for a single operation.
- **`set-path`**: Marked by a trailing colon (`:`), this path is the head of an assignment expression, used to write a value (e.g., `user.name:`). It supports the same segments as a `get-path` and powers simple binding, slice replacement, and vectorized updates.
- **`del-path`**: Marked by a leading tilde (`~`), this path instructs the evaluator to unbind or delete a value (e.g., `~user.old_token`). A `del-path` is a standalone expression and cannot be part of a larger chain.
- **`multi-set-path`**: A destructuring assignment pattern used to bind multiple targets at once from a collection (e.g., `[a, b, c]:`).
- **`piped-path`**: Marked by a leading pipe (`|`), this path triggers an implicit pipe call when it appears in the second position of an expression (e.g., `data |map [...]`). Infix operators like `+` and `and` are aliases for piped paths.
- **`post-path`**: Marked by a trailing arrow (`<-`), this path is the head of an HTTP POST expression (e.g., `http://api/items<- ...`).

#### Scheme Paths: Filesystem and HTTP

The host can provide handlers for scheme-based paths, such as `file://` and `http://`, to enable seamless I/O. These paths behave like regular SLIP paths and can be used for reading, writing, and deleting.

**Shorthand Writes**: A `get-path` with a scheme can be used as the head of an expression to perform a shorthand write. The evaluator interprets this as a write operation:
- `http://example.com/data: "body"` performs an HTTP PUT.
- `file:///tmp/out.txt: "text"` writes to a file.

**File I/O (`file://`)**: The `file://` scheme provides access to the local filesystem (sandboxed by the host).
- **Reading**: `file:///path/to/file.txt` reads a file. The content is automatically deserialized based on the file extension (`.json`, `.yaml`, etc.) or returned as text. Reading a `.slip` file returns an unevaluated `code` block. Reading a directory returns a dictionary-like view of its contents.
- **Writing**: `file:///path/to/out.json: #{ a: 1 }` serializes the data based on the extension and writes it to disk. You can override the serialization format by providing a `content-type` in a metadata block, e.g., `file://out.txt#(content-type: "application/json"): ...`.

**Path Resolution**: The `file://` scheme supports several forms for path resolution:
- **Absolute paths**: `file:///path/to/file` is resolved from the filesystem root.
- **Home directory**: `file://~/documents/file.txt` expands `~` to the user's home directory.
- **Current working directory**: `file://./relative/path` is resolved relative to the directory where the SLIP interpreter was started.
- **Source-file relative**: `file://relative/path` and `file://../parent/path` are resolved relative to the directory of the SLIP source file currently being executed. If not executed from a file (e.g., in a REPL), this falls back to the current working directory. This allows modules to refer to local resources portably.

**HTTP I/O (`http://`, `https://`)**: The `http://` scheme enables network requests.
- **GET**: `http://example.com/api/data` performs an HTTP GET and returns the response body.
- **PUT**: `http://example.com/api/data: #{ a: 1 }` serializes the payload to JSON (the default) and performs an HTTP PUT.
- **POST**: `http://example.com/api/data<- #{ a: 1 }` performs an HTTP POST.
- **DELETE**: `~http://example.com/api/data` performs an HTTP DELETE.

**Configuring Scheme Paths**

Scheme path operations can be configured on a per-call basis using a transient `#(...)` block. This allows for fine-grained control over network requests and filesystem I/O. Common options for `http://` requests include `timeout` and `retries`, which have sensible defaults (timeout: 5.0 seconds, retries: 2) but can be overridden when needed.

The `resource` function is a convenient wrapper that lets you create a handle with "baked-in" configuration, which is then applied to all subsequent operations on that handle.

A particularly important configuration option is `content-type`. When provided for a write operation (`PUT`, `POST`), it serves two critical functions:

1.  **Header Promotion**: The value is automatically set as the `Content-Type` header in the outgoing HTTP request.
2.  **Automatic Serialization**: It instructs the runtime to serialize the request body using the appropriate format. For example, a `content-type` of `"application/json"` will cause a SLIP `dict` or `list` to be automatically converted to a JSON string.

This applies to all forms of HTTP writes, including shorthand assignments, direct `post-path` (`<-`) operations, and calls using a `resource` handle.

```slip
-- Create a configured resource handle for a JSON API
admin-api: resource `http://api/items#(
    content-type: "application/json",
    timeout: 5
)`

-- The content-type and timeout are automatically applied to this PUT.
put admin-api #{ name: "new-item" }

-- The configuration can also be applied directly to a post-path.
http://api/items#(content-type: "application/json")<- #{ name: "another" }
```

**The `resource` Fluent API**

For convenience, the standard library provides a `resource` function that creates a pre-configured handle for a URL. This handle can then be used with `get`, `put`, `post`, and `del` functions for a more readable, fluent API style.

- `resource <url-path>`: Creates a resource handle. The URL path can include a transient configuration block (`#(...)`).
- `get <resource>`: Performs an HTTP GET.
- `put <resource> <data>`: Performs an HTTP PUT with the data.
- `post <resource> <data>`: Performs an HTTP POST with the data.
- `del <resource>`: Performs an HTTP DELETE.

**Example:**
```slip
-- Create a configured resource handle for a JSON API
admin-api: resource `http://api/items#(content-type: "application/json")`

-- Use the handle to perform operations
item: get admin-api
put admin-api #{ name: "new-item" }
del admin-api
```


#### Evaluation Primitives

These functions control how and where code is executed.

- `run <code>`: The primary function for executing a block of code within the current scope. If the `code` block is empty, it returns `none`; otherwise, it returns the value of the last expression.
- `run-with <code> <scope>`: Executes a code block within a specific, user-provided scope, allowing for sandboxing or context-specific execution.
- `current-scope`: A function that returns the `scope` object representing the current lexical scope.
- `list <code>`: Evaluates the expressions in a code block and collects all their results into a new `list`. This is the underlying function for the `#[...]` literal.
- `dict <code>`: Evaluates the expressions in a code block (typically assignments) and returns a new `dict` object. This is the underlying function for the `#{...}` literal.

#### Function & Call Primitives

These primitives are the foundation of SLIP's functional nature.

- `fn {signature} [body]`: The core constructor for creating functions. It creates a `Function` object, which is a closure that captures the current lexical scope and bundles it with the provided signature (`sig` literal) and the unevaluated body (`code` block). The `set-path` assignment primitive is responsible for placing this `Function` into a `GenericFunction` container, creating the container if one does not already exist.
- `call <function> <arg-list>`: Programmatically invokes a function with a list of arguments, triggering the multiple dispatch algorithm.

#### Control Flow Primitives

These functions are the basis of all logic and iteration.

- `if <condition-block> <then-block> <else-block>`: The fundamental conditional. It first evaluates the `<condition-block>`. If the result is truthy, it then evaluates the `<then-block>`. Otherwise, it evaluates the `<else-block>`. It is crucial that only one of the two branch code blocks is ever evaluated.
- `while <condition-block> <body-block>`: The fundamental loop. It repeatedly evaluates the `condition-block` and, if the result is true, runs the `body-block`.
- `foreach <var-spec: sig> <collection> <body-block>`: The first argument is a sig literal (e.g., `{x}` or `{k, v}`). It is never evaluated; its positional names are bound/destructured per iteration.
- `for <var-spec: sig> <start> <end> [body-block]` (library): Idiomatic helper built on `while`/`foreach`. The first argument is a sig literal (e.g., `{i}`).
- `logical-and <lhs> <rhs>`: A short-circuiting logical AND. It evaluates its first argument. If the result is falsey, it returns that value immediately without evaluating the second argument. If the first argument is truthy, it evaluates the second argument and returns its result. The `and` operator is an alias for this primitive. Note: This short-circuiting behavior makes `logical-and` a special form, as it breaks the standard rule of evaluating all arguments before a function call. This is a pragmatic exception made for intuitive syntax.
- `logical-or <lhs> <rhs>`: A short-circuiting logical OR. It evaluates its first argument. If the result is truthy, it returns that value immediately without evaluating the second argument. If the first argument is falsey, it evaluates the second argument and returns its result. The `or` operator is an alias for this primitive. Note: Like `logical-and`, this is a special form.
- `return <value>`: Terminates the execution of the current function and returns the given `value` (or `none` if not provided). This is achieved by creating a `Response` object with `status: 'return'`, which is then handled by the function evaluation machinery.
- `task <code-block>`: Executes a code block asynchronously on the host's event loop. Inside a `task`, `while` and `foreach` loops automatically yield control (`sleep 0`) on each iteration to prevent blocking the host.
- `loop <body-block>`: Provides an infinite loop. This is an alias for `while [true] [...]`. A `return` or other non-local exit is required to break out of the loop.
- `cond <clauses>`: A multi-branch conditional that takes a list of `[condition-block, result-expression]` pairs. It executes the first `condition-block` that returns a truthy value and then returns the corresponding `result-expression`.

#### Outcome and Response Primitives

These primitives manage structured outcomes.

- `response <status> <value>`: The core constructor for creating a `response` object, which is a structured outcome with a `status` (a `get-path-literal`) and a `value`.
- `respond <status> <value>`: Creates a `response` object and immediately triggers a non-local exit, making that `response` the return value of the current function.
- `with-log <code>`: Executes the code block, returning a dict-like object #{ outcome: <response>, effects: #[...] } where outcome reflects the block’s result (normalized to response ok/err/...) and effects is the list of side-effect events emitted during the block.

#### Metaprogramming Primitives

These functions enable runtime code generation and manipulation.

- `inject <path>`: Substitutes a value from the _calling_ scope into a code block being executed by `run`.
- `splice <path>`: Splices the contents of a list from the _calling_ scope into a code block being executed by `run`.

#### Object Model Primitives

These functions are the foundation of SLIP's object system.

- `scope <initial-data: dict>`: Creates a new `scope` object, which is a live, lexically-linked object that serves as the basis for prototypes and instances. The initial data is provided by a `dict`.
- `inherit <child-scope> <parent-scope>`: Sets the parent (prototype) link of the `child-scope` to be the `parent-scope`. This is the primary mechanism for establishing an "is-a" relationship and can only be performed once per object.
- `mixin <target-scope> <source-scopes...>`: Establishes a "has-a" relationship by adding one or more `source-scopes` to the `target-scope`'s list of mixins. This is a dynamic link, not a copy. Property lookups will search through mixins before checking the target's parent. This mechanism can be used multiple times to layer capabilities.
- `with <object> <config-block>`: Executes a code block within the context of a given object, then returns the object. It is ideal for fluent configuration and is typically used with the pipe operator.
  ```slip
  -- Create a scope, then configure it fluently using 'with'
  my-char: (create Character) |with [
      name: "Kael"
      hp: 150
  ]
  ```

- `guard <function> [condition-block]`: A helper function used with `fn` to add a conditional guard to a method definition. The method is only considered for dispatch if the `condition-block` evaluates to a truthy value.
- `example <function> {example-sig}`: A helper function used with `fn` to attach an executable example to a function definition. It provides documentation, enables testing, and can be used by a compiler for type inference.

#### Type System Primitives

These functions allow the language to be introspective.

- `call <string>` (also called `intern`): Converts a string into a `path` object. This is essential for creating paths dynamically.
- `type-of <value>`: Returns a `path` representing the type of the value (e.g., `` `core.number` ``, `` `core.list` ``).

#### Core Data Operations

- Base Arithmetic & Comparison: The fundamental functions for numbers and logic (`+`, `-`, `*`, `/`, `>`, `<`, `=`, etc.) must be provided as primitives.
- List & Dict Manipulation: The most basic operations for containers (e.g., getting length, accessing an index, setting a key in a `dict`) must also be provided by the host environment.

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

#### String and Path Utilities

- `join`: A generic function for combining elements.
  - `join <list-of-strings> <separator>`: Joins the elements of a list into a single string.
  - `join <segments...>`: Joins multiple path segments, path literals, or strings into a single `get-path-literal`. This is the primary tool for programmatic path construction.
- `split <string> <separator>`: Splits a string by a separator into a list of strings.
- `find <haystack> <needle> [<start-index>]`: Finds the first occurrence of a substring.
- `replace`: A generic function for replacing values.
  - `replace <string> <old> <new>`: Returns a new string with all occurrences of `old` replaced by `new`.
  - `replace <list|code> <old-list> <new-list>`: Replaces all occurrences of `old-list[0]` with `new-list[0]` in the target list or code block.
- `indent <string> <prefix>`: Adds a prefix to the beginning of each line.
- `dedent <string>`: Removes common leading whitespace from every line.

#### Collection Utilities

- `len <collection>`: Returns the length of a list, `dict`, or string.
- `range [<start=0>] <stop> [<step=1>]`: Generates a list of numbers. It can be called in three ways:
  - `(range <stop>)`: Generates numbers from 0 to stop-1.
  - `(range <start> <stop>)`: Generates numbers from start to stop-1.
  - `(range <start> <stop> <step>)`: Generates numbers from start to stop-1, incrementing by step.
- `keys <dict|scope>`: Returns a new list containing the keys of the dictionary or scope.
- `values <dict|scope>`: Returns a new list containing the values of the dictionary or scope.
- `items <dict|scope>`: Returns a list of `#[key, value]` pairs.
- `copy <collection>`: Returns a **shallow copy** of a list, dictionary or code block. Nested collections within the copied structure will still refer to the original nested collections.
- `clone <collection>`: Returns a **deep copy** of a list, dictionary or code block. All nested collections are also recursively copied, creating a completely independent duplicate of the original structure.
- `reverse <list>`: Returns a new list with the elements in reverse order.
- `sort <list>`: Returns a new, sorted list.

#### Functional Helpers

These functions provide common higher-order operations for working with collections.

- `map <function> <list>`: Applies a function to each item in a list, returning a new list of the results. Also supports a data-first overload for piping: `list |map <function>`.
- `filter <predicate> <list>`: Returns a new list containing only the items for which the predicate function returns a truthy value. Also supports a data-first overload: `list |filter <predicate>`.
- `reduce <reducer> <accumulator> <list>`: Reduces a list to a single value by applying the `reducer` function cumulatively. The reducer takes two arguments: the accumulator and the current item.
- `zip <list-a> <list-b>`: Combines two lists into a list of pairs. The resulting list's length is determined by the shorter of the two input lists.

#### Function Composition

These helpers create new functions from existing ones.

- `partial <function> <partial-args...>`: Creates a new function that, when called, will invoke the original function with the pre-supplied arguments, followed by any new arguments.
- `compose <functions...>`: Composes functions, returning a new function that applies them from right to left. `(compose f g h)(x)` is equivalent to `f(g(h(x)))`.

#### Data Modeling

- `validate <data> <schema>`: Validates `data` against a `schema`, applies any default values, and returns a new, clean object. Returns `response ok <new-object>` on success or `response err <list-of-errors>` on failure.
- `default <value>`: Provides a default value for a field.
- `optional <type>`: Marks a field as optional.

#### Object Model

- `guard <function> [condition-block]`: A helper function used with `fn` to add a conditional guard to a method definition. The method is only considered for dispatch if the `condition-block` evaluates to a truthy value.
- `example <function> {example-sig}`: A helper function used with `fn` to attach an executable example to a function definition. It provides documentation, enables testing, and can be used by a compiler for type inference.

#### Asynchronous Operations

- `make-channel`: Creates and returns a new channel object for structured concurrency.
- `send <channel> <value>`: Sends a value into a channel, pausing asynchronously if the channel is full.
- `receive <channel>`: Receives a value from a channel, pausing asynchronously if it is empty.
- `sleep <seconds>`: Pauses the current task for `<seconds>` (can be a float) without blocking the host event loop. `sleep 0` yields control to the event loop, allowing other tasks to run.

#### Side Effects and I/O

- `emit <topic_or_topics> <message>`: Generates a side-effect event that is appended to the `ExecutionResult`'s `side_effects` list. This is the primary mechanism for a script to communicate events to the host application.
- `time`: Returns the current system time as a high-precision float (Unix timestamp).

#### Type Conversion

- `to-str <value>`: Converts any value to its string representation. This operation never fails.
- `to-int <value>`: Attempts to convert a value (e.g., a string or a float) to an integer. If the conversion is not possible, it returns `none`.
- `to-float <value>`: Attempts to convert a value (e.g., a string or an integer) to a float. If the conversion is not possible, it returns `none`.
- `to-bool <value>`: Converts any value to a strict `true` or `false` based on SLIP's truthiness rules (see Section 3.4). This operation never fails.

#### Import and Modules

- `import <module-path: path>`: Loads a module specified by a path literal that includes a scheme (e.g., `file://math.slip`, `https://example.com/utils.slip`). The host environment implements scheme handlers, executes the module exactly once in a fresh scope, caches that scope by canonical path, and returns the cached scope on subsequent imports.
  - The argument must be a path literal (not a string), keeping module locations within SLIP's path system.
  - The returned value is a `scope` that contains the module's bindings. Bind it to a kebab-case variable.
  - Example:
    ```slip
    math: import file://math.slip
    utils: import https://sliplang.com/utils.slip
    ```

### 14.2. Host Integration: `host-object` and `task`

Every SLIP runtime must provide two core functions that bridge the gap between the script and the host application.

The **`host-object`** function serves as a gateway for scripts to retrieve live `SLIPHost` instances from the application. The host implements this function to take an identifier (typically a string) and return the corresponding object handle, or `none` if not found. This allows scripts to access and modify host object data via the `__getitem__`, `__setitem__`, and `__delitem__` contract. Note that methods decorated with `@slip_api_method` are exposed as top-level SLIP functions and are called directly (e.g., `take-damage 10`); `host-object` is used only to get a handle to an object as data.

The **`task`** primitive integrates with the host's asynchronous event loop. Calling `task [...]` schedules the code block to run concurrently and immediately returns a task handle. To ensure the host remains responsive, `while` and `foreach` loops inside a task automatically yield control on each iteration. The host is responsible for managing the task lifecycle. When a task is created in the context of a `SLIPHost` object, it is registered with that object. The base `SLIPHost` class provides a `cancel-tasks` method (exposed to SLIP) so the host can clean up all active tasks associated with an object when it is no longer needed (e.g., on player logout).

For the full SLIPHost contract and binding rules, see Chapter 12.

### 14.3. The SLIP Core Library (`root.slip`)

SLIP extends its built-in functionality with a core library written in SLIP itself. This file is loaded automatically by the interpreter and provides a rich set of higher-order functions and utilities. This demonstrates the power of the language to build upon its own primitives.

There is nothing special about `root.slip` other than the fact that all functions are set in the root scope and that it is automatically loaded before any other script is run.

---

## 15. The SLIP Execution Model: Declarative Effects-as-Data

The previous chapters have described the syntax and primitives of the SLIP language. This final chapter explains the **philosophy of execution**—the recommended way to structure a SLIP program to be safe, testable, and robust. This model is not an accident; it is the central design principle around which the language is built.

The model is simple: **Core logic should be pure; side effects should be declarative data.**

### 15.1. The Two Halves of a SLIP Program

A well-structured SLIP program is divided into two distinct parts:

1.  **The Pure Core:** These are functions that perform the actual business logic. They take data as input and produce new data as output (often wrapped in a `response` object). They contain calculations, decisions, and data transformations. Crucially, they **do not perform side effects directly**.

2.  **The Effect Descriptions:** When a pure function needs to interact with the outside world (deal damage, play a sound, log a message), it does not call a host function that _does_ the action. Instead, it calls `emit` to create a **declarative description of the desired effect**.

The `emit` function does not perform the effect. It simply serializes a description of the effect as a piece of data and places it into the `ExecutionResult`'s side-effect queue.

### 15.2. The Host as the Effect Handler

This separation creates a powerful, one-way flow of information:

1.  The host calls a SLIP script.
2.  The script executes its pure logic. As it runs, it populates the `side_effects` queue with descriptions of desired effects.
3.  The script finishes and returns a final `response` and the completed `side_effects` queue to the host.
4.  The host now iterates through the `side_effects` queue and **is the only component that actually executes the effects**.

The host is the ultimate authority. It is the "impure" part of the system that interacts with the world, acting on a clear, unambiguous list of instructions provided by the pure SLIP script.

### 15.3. A Complete Example

Consider a function that calculates the result of a spell attack.

```slip
-- This is a PURE function. It has no direct side effects.
calculate-fireball-impact: fn {caster, target, area} [
    -- 1. Pure calculations
    base-damage: 50
    final-damage: base-damage - target.fire-resistance

    -- 2. Describe the desired effects using 'emit'
    emit "visual" {effect: "explosion", position: target.position}
    emit "sound"  {sound: "fireball_hit.wav", volume: 1.0}
    emit "combat" {
        type:   `damage`,
        target: target.id,
        amount: final-damage,
        element: `fire`
    }

    -- 3. Return the new state of the target as pure data
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

### 15.4. The Benefits of This Model

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
-- preferred, reads left-to-right
4 ** 2 + 2 * 5 / 4
```

Parentheses are only needed to deliberately alter this natural flow, making their use a strong, explicit signal to the reader.

For cases where direct transcription of a complex mathematical formula is required, a future version of SLIP may include a special grammar or keyword to evaluate a block of code using traditional PEMDAS rules. For general-purpose programming, the left-to-right model is considered superior.

---

# Appendix C: Abstract Syntax Tree (AST) Reference

This appendix provides a formal reference for the structure of the Abstract Syntax Tree (AST) that the SLIP parser generates. The evaluator's behavior is driven by the tags and structure of these nodes. The fundamental structure is a "tagged list," where the first element is a `string` that identifies the node's type.

**A Note on Notation:** In the following examples, `<type value>` (e.g., `<number 10>`) is used to represent literal value tokens like numbers and user-facing strings. Structural parts of the AST are represented as tagged lists like `[tag ...]`. For brevity and clarity, the literal string or number values inside path components (e.g., the `'user'` in `[name 'user']` or the `5` in `[slice 5 10]`) are shown directly, rather than using the more verbose `<string "user">` or `<number 5>` notation.

### Expressions and Code

An expression is represented by a list tagged with `expr`. A `code` block is tagged with `code`. The difference is that the evaluator executes an `[expr ...]` immediately, while a `[code ...]` is treated as a literal value.

- **Source:** `(add 1 2)`

  - **AST:** `[expr [get-path [name 'add']], <number 1>, <number 2>]`

- **Source:** `[add 1 2]`
  - **AST:** `[code [expr [get-path [name 'add']], <number 1>, <number 2>]]`
  - Note: A `code` block contains a list of zero or more `expr` nodes. An empty `code` block is valid.

### Container Literals

- **Source:** `#[1, 2]` (List)

  - **AST:** `[list <number 1>, <number 2>]`
  - The evaluator processes this by evaluating each element and collecting the results into a `list` object.

- **Source:** `#{ a: 1 }` (Dictionary)

  - **AST:** `[dict [expr [set-path [name 'a']], <number 1>]]`
  - The evaluator executes the expressions inside a new `dict` object and returns it.

- **Source:** `{ a: int }` (Signature)
  - **AST:** `[sig [sig-kwarg [sig-key 'a'] [get-path [name 'int']]]]`
  - The `sig` block is not evaluated; it is parsed into a literal `sig` data structure.

### Paths and Assignment

Paths and assignment patterns are represented by two distinct but related AST nodes.

#### The `get-path` Node (for Reading)

A `get-path` node represents a location to read a value from. It is an expression that is evaluated.

- **AST Structure:** `[get-path <segment1>, <segment2>, ..., configuration: [dict ...]]`
- **`configuration`:** An optional dictionary-like structure, parsed from a `#(...)` suffix, that provides transient options for the operation.
- **Segments:** A `get-path` is composed of one or more segments.

  - `[root]`: A leading forward slash `/`, indicating a path starting from the root scope.
  - `[name '...']`: A dot-separated name, e.g., `user`.
  - `[query [ ... ]]`: A query segment, e.g., `[0]` or `[> 10]`. It contains a single child node that specifies the type of query:
    - **Index/Key Query:** `[simple-query [expr ...]]`
    - **Slice Query:** `[slice-query [expr ...] [expr ...]]`
    - **Filter Query:** `[filter-query <operator> [expr ...]]`
  - `[parent]`: The parent scope operator `../`.
  - `[group ...]`: A dynamic, computed segment, e.g., `(get-index)`.

- **Source:** `user.name`

  - **AST:** `[get-path [name 'user'], [name 'name']]`

#### The `piped-path` Node

A `piped-path` node represents a path that will trigger an implicit pipe call when it appears in the second position of an expression.

- **AST Structure:** `[piped-path <segment1>, <segment2>, ...]`
- **Segments:** A `piped-path` can contain the same segments as a `get-path`.
- **Source:** `|user.name`
  - **AST:** `[piped-path [name 'user'], [name 'name']]`

#### The `set-path` Node (for Writing)

A `set-path` node represents a location to write to. For a simple assignment like `user.name:`, the parser generates a `set-path` node which the `SlipTransformer` converts into a `SetPath` object. For destructuring assignment (`[a, b]:`), the parser generates a `multi-set` node which the transformer converts to a `MultiSetPath` object.

- **AST Structure (Simple):** The transformer converts a `set-path` node from the parser into a `SetPath` object. This object, not the raw AST, is what the evaluator receives.

  - **Segments:** A `SetPath` object contains the same segments as a `GetPath` object.
  - **`configuration`:** An optional dictionary-like structure, parsed from a `#(...)` suffix, that provides transient options for the operation.
  - **Source (Simple):** `user.name: "John"`
  - **AST passed to evaluator:** A `SetPath` object and a `string` object.

- **AST Structure (Destructuring):** The transformer converts a `multi-set` node from the parser into a `MultiSetPath` object. This object holds a list of the `SetPath` targets for the assignment.
  - **Source (Destructuring):** `[x, y]: #[10, 20]`
  - **AST passed to evaluator:** A `MultiSetPath` object and a `List` object.

---

# Appendix D: Final Review: The SLIP Philosophy in Context (v1.0)

Let's do a final review to confirm, addressing your checklist directly. We can summarize the journey by looking at the "great ideas" from other languages and seeing how SLIP has interpreted them.

A mature language is defined as much by what it _is_ as by what it is _not_. SLIP's design is a synthesis of powerful concepts from decades of language evolution, adapted to fit its core philosophy of simplicity, safety, and metaprogramming clarity.

Here is a summary of how SLIP has addressed the core ideas from its most significant influences:

| Language                | "The Great Idea"                     | SLIP's Interpretation or Stance                                                                                                                                            |
| :---------------------- | :----------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| **LISP / Scheme**       | **Homoiconicity (Code as Data)**     | **Directly Adopted.** The first-class `code` type (`[...]`) is the heart of SLIP's metaprogramming.                                                                        |
|                         | **Macros (`defmacro`)**              | **Replaced.** SLIP uses runtime functions (`run`, `inject`, `splice`) on `code` objects, avoiding a separate compile-time macro system.                                    |
|                         | **Continuations (`call/cc`)**        | **Explicitly Rejected.** Replaced with safer, more structured alternatives: `task` for concurrency and `response` for non-local exits.                                     |
| **Smalltalk**           | **Pure Message Passing**             | **Adapted.** The implicit pipe call (`data                                                                                                                                 | map`) is SLIP's ergonomic form of message passing. |
|                         | **The "Image" (Persistence)**        | **Delegated to Host.** This is a powerful host-level pattern, not a language feature, preserving the language's simplicity.                                                |
| **Erlang / Elixir**     | **Pattern Matching in Functions**    | **Adapted and Adopted** as generic functions. Dispatch can be made conditional on argument _values_ using `                                                                | guard` clauses, achieving a similar goal.          |
|                         | **Actor Model / Channels**           | **Adopted as a Library Pattern.** The `task` primitive provides the actors, and `make-channel`, `send`, `receive` provide the safe communication, implemented by the host. |
| **JavaScript / Self**   | **Prototype-Based OOP**              | **Directly Adopted.** The `scope` object with its `parent` link _is_ a prototype system. `inherit` makes this explicit.                                                    |
| **Logo**                | **Domain-Specific "World"**          | **Adopted as Core Philosophy.** This is the entire purpose of SLIP as an embedded language: the host provides a "world" of commands, creating a DSL.                       |
| **Rebol**               | **Linear, Greedy Evaluation**        | **Explicitly Rejected.** SLIP uses a structured, hierarchical evaluation model for function calls, providing more predictable behavior.                                    |
| **Prolog / miniKanren** | **Logic Programming & Backtracking** | **Delegated as a Library.** The core evaluator is deterministic. Logic programming is a powerful but distinct paradigm best provided by a host library.                    |
| **Rust / Haskell**      | **The `Result` Type (`ok`/`err`)**   | **Directly Adopted** and formalized as the first-class `response` type, which is handled elegantly by generic functions with `                                             | guard` clauses.                                    |

### Conclusion

This document has detailed the features and philosophy of SLIP v1.0, a language designed through a careful synthesis of powerful ideas from across the history of computer science, distilled into a simple, consistent, and powerful whole.

At its heart, SLIP is defined by a few core principles that diverge from convention to achieve greater clarity: a transparent, directly-represented AST that puts the evaluator in control; a unified `path` system that replaces symbols for identity and navigation; and a uniform, function-based model for all control flow, eliminating the need for special keywords.

From this foundation, SLIP deliberately adopts and adapts some of the most successful patterns from other languages.

- It embraces the **homoiconicity of LISP**, treating `code` as a first-class data type to enable powerful runtime metaprogramming.
- It adopts the **prototype-based object system of Self**, using generic functions to cleanly separate data from behavior.
- From modern functional languages like **Erlang and Rust**, it inherits robust patterns for concurrency with `task` and channels, as well as structured error handling via the `response` data type.
- Finally, it is guided by the spirit of **Logo**, designed from the ground up to be an embedded language where the host creates a rich, domain-specific dialect for users.

The result of this synthesis is not a complex amalgamation, but a coherent and minimalist system. Its features work together to promote a specific style of programming: one that separates pure logic from side effects, describing those effects as declarative data via the `emit` function. This "effects-as-data" model makes SLIP scripts inherently more testable, auditable, and secure.

This reference document defines the complete and stable feature set for SLIP version 1.0. With its clear syntax, powerful object model, robust outcome handling, and safe concurrency primitives, SLIP provides a complete toolkit for building the next generation of embedded, domain-specific languages.
