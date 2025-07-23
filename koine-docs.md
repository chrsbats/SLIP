# Koine

_A declarative, data-driven parser generator for creating languages, ASTs, and transpilers with simple YAML._

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Koine allows you to define a complete language pipelineâ€”from validation to Abstract Syntax Tree (AST) generation to final code transpilationâ€”using a single, human-readable JSON-compatible data structure. It separates the _what_ (your language definition) from the _how_ (the parsing engine).

### Core Features

- **Declarative:** Define complex grammars entirely in YAML data. No code generation step required.
- **Pipeline-based:** Use Koine for simple validation, structured AST generation, or full transpilation.
- **Powerful:** Handles operator precedence, left/right associativity, lookaheads, and indentation-based syntax (see Roadmap).
- **Language Agnostic:** The Koine format is a specification. The engine can be implemented in any language (current implementation is Python).

---

## Installation

```bash
pip install koine
```

---

## Quick Start

Let's build a simple calculator that can parse `2 + 3` and transpile it to `(add 2 3)`.

1.  **Create your grammar file, `calc.yaml`:**

    ```yaml
    # Note: This is a simplified rule for the quick start.
    # See the full grammar below for handling precedence.
    start_rule: expression
    rules:
      expression:
        ast: { structure: "left_associative_op" }
        sequence:
          - { rule: number }
          - zero_or_more:
              sequence:
                [{ rule: _ }, { rule: add_op }, { rule: _ }, { rule: number }]
      add_op:
        ast: { leaf: true }
        literal: "+"
        transpile: { value: "add" }
      number:
        ast: { leaf: true, type: "number" }
        transpile: { use: "value" }
        regex: "\\d+"
      _:
        ast: { discard: true }
        regex: "[ \\t]*"
    ```

2.  **Use the Koine engine in `main.py`:**

    ```python
    import yaml
    from koine import Parser

    with open("calc.yaml", "r") as f:
        grammar = yaml.safe_load(f)

    parser = Parser(grammar)
    result = parser.transpile("2 + 3")

    if result['status'] == 'success':
        print(f"Input: '2 + 3'")
        print(f"Output: {result['translation']}")
    ```

3.  **Run it:**
    ```
    Input: '2 + 3'
    Output: (add 2 3)
    ```

---

### Overview

This document describes the JSON compatible grammar format for the Koine data-driven parser. The system is designed as a flexible pipeline that can be used for simple validation, structured data extraction (AST generation), or full-scale language translation (transpilation).

The core philosophy is to separate the _what_ from the _how_. You define _what_ the language looks like and _what_ the output should be and the Koine engine handles _how_ to parse and transform it.

This guide will walk through the three primary use cases, showing how to add complexity to the grammar definition at each stage using a calculator as a running example.

---

### Use Case 1: Validation

**Goal:** To answer the simple question, "Does this input string conform to my language's syntax?"

At this level, we only care about the structure of the language. We do not need an Abstract Syntax Tree (AST) or a transpiled output. Therefore, we only use the **Grammar Structure Keys**. The `ast` and `transpile` directives are not needed and can be omitted entirely.

#### Full Example: A Validation-Only Calculator Grammar

This grammar can successfully parse valid mathematical expressions, but it produces no useful output beyond "success" or "failure".

**`validation_calculator.yaml`**

```yaml
start_rule: expression

rules:
  expression:
    sequence:
      - { rule: term }
      - zero_or_more:
          sequence: [{ rule: _ }, { rule: add_op }, { rule: _ }, { rule: term }]

  term:
    sequence:
      - { rule: power }
      - zero_or_more:
          sequence:
            [{ rule: _ }, { rule: mul_op }, { rule: _ }, { rule: power }]

  power:
    sequence:
      - { rule: factor }
      - optional:
          sequence:
            [{ rule: _ }, { rule: power_op }, { rule: _ }, { rule: power }]

  factor:
    choice:
      - { rule: number }
      - sequence:
          - { literal: "(" }
          - { rule: _ }
          - { rule: expression }
          - { rule: _ }
          - { literal: ")" }

  add_op:
    choice: [{ literal: "+" }, { literal: "-" }]

  mul_op:
    choice: [{ literal: "*" }, { literal: "/" }]

  power_op:
    literal: "^"

  number:
    regex: "-?\\d+"

  _:
    regex: "[ \\t]*"
```

**Usage:**

```python
# Load the validation-only grammar
with open("validation_calculator.yaml", "r") as f:
    grammar = yaml.safe_load(f)

validator = Parser(grammar)
result = validator.parse("((2 + 3) * 4) ^ 5")

if result['status'] == 'success':
    # The 'ast' key will contain a raw, messy parse tree, which we ignore.
    print("Input string is a valid expression!")
else:
    print(f"Invalid: {result['message']}")
```

---

### Use Case 2: Parsing to a Semantic AST

**Goal:** To validate the input string AND convert it into a clean, structured, and meaningful data representation (an AST).

This is the most common use case for parsing complex data. To achieve this, we build on the validation grammar by adding the **`ast` directive block** to our rules. This block tells the parser how to transform the raw parse tree into a clean AST by discarding whitespace, promoting nodes, and building specific structures. The `transpile` block is still not needed.

#### Full Example: An AST-Generating Calculator Grammar

We now add directives like `discard`, `promote`, `leaf`, and `structure` to produce a useful tree.

**`ast_calculator.yaml`**

```yaml
start_rule: expression

rules:
  expression:
    ast: { structure: "left_associative_op" }
    sequence:
      - { rule: term }
      - zero_or_more:
          sequence: [{ rule: _ }, { rule: add_op }, { rule: _ }, { rule: term }]

  term:
    ast: { structure: "left_associative_op" }
    sequence:
      - { rule: power }
      - zero_or_more:
          sequence:
            [{ rule: _ }, { rule: mul_op }, { rule: _ }, { rule: power }]

  power:
    ast: { structure: "right_associative_op" }
    sequence:
      - { rule: factor }
      - optional:
          sequence:
            [{ rule: _ }, { rule: power_op }, { rule: _ }, { rule: power }]

  factor:
    ast: { promote: true }
    choice:
      - { rule: number }
      - sequence:
          - { literal: "(" }
          - { rule: _ }
          - { rule: expression }
          - { rule: _ }
          - { literal: ")" }

  add_op:
    ast: { leaf: true }
    choice: [{ literal: "+" }, { literal: "-" }]

  mul_op:
    ast: { leaf: true }
    choice: [{ literal: "*" }, { literal: "/" }]

  power_op:
    ast: { leaf: true }
    literal: "^"

  number:
    ast: { leaf: true, type: "number" }
    regex: "-?\\d+"

  _:
    ast: { discard: true }
    regex: "[ \\t]*"
```

**Usage:**

```python
# Load the AST-generating grammar
with open("ast_calculator.yaml", "r") as f:
    grammar = yaml.safe_load(f)

parser = Parser(grammar)
result = parser.parse("((2 + 3) * 4) ^ 5")

if result['status'] == 'success':
    print("Successfully parsed. AST:")
    # The result now contains a valuable 'ast' key with a clean tree
    print(json.dumps(result['ast'], indent=2))
```

**Output AST:**

```json
{
  "tag": "binary_op",
  "op": {
    "tag": "power_op",
    "text": "^",
    "line": 1,
    "col": 16
  },
  "left": {
    "tag": "binary_op",
    "op": {
      "tag": "mul_op",
      "text": "*",
      "line": 1,
      "col": 10
    },
    "left": {
      "tag": "binary_op",
      "op": {
        "tag": "add_op",
        "text": "+",
        "line": 1,
        "col": 5
      },
      "left": {
        "tag": "number",
        "text": "2",
        "line": 1,
        "col": 3,
        "value": 2
      },
      "right": {
        "tag": "number",
        "text": "3",
        "line": 1,
        "col": 7,
        "value": 3
      }
    },
    "right": {
      "tag": "number",
      "text": "4",
      "line": 1,
      "col": 12,
      "value": 4
    }
  },
  "right": {
    "tag": "number",
    "text": "5",
    "line": 1,
    "col": 18,
    "value": 5
  }
}
```

---

### Use Case 3: Full Transpilation

**Goal:** To validate the input, parse it to a clean AST, and then **transform that AST into a different string format** (e.g., from infix math to LISP-style s-expressions).

This is the full power of the pipeline. We use all three components: the grammar structure, the `ast` block, and now the **`transpile` directive block**. The `transpile` rules tell the final stage of the engine how to convert each AST node into a string.

#### Full Example: A Transpiling Calculator Grammar

We add `transpile` directives to our operator and number rules to define the target output format.

**`full_calculator_grammar.yaml`**

```yaml
start_rule: expression

rules:
  expression:
    ast: { structure: "left_associative_op" }
    sequence:
      - { rule: term }
      - zero_or_more:
          sequence: [{ rule: _ }, { rule: add_op }, { rule: _ }, { rule: term }]

  term:
    ast: { structure: "left_associative_op" }
    sequence:
      - { rule: power }
      - zero_or_more:
          sequence:
            [{ rule: _ }, { rule: mul_op }, { rule: _ }, { rule: power }]

  power:
    ast: { structure: "right_associative_op" }
    sequence:
      - { rule: factor }
      - optional:
          sequence:
            [{ rule: _ }, { rule: power_op }, { rule: _ }, { rule: power }]

  factor:
    ast: { promote: true }
    choice:
      - { rule: number }
      - sequence:
          - { literal: "(" }
          - { rule: _ }
          - { rule: expression }
          - { rule: _ }
          - { literal: ")" }

  add_op:
    ast: { leaf: true }
    choice:
      - { literal: "+", transpile: { value: "add" } }
      - { literal: "-", transpile: { value: "sub" } }

  mul_op:
    ast: { leaf: true }
    choice:
      - { literal: "*", transpile: { value: "mul" } }
      - { literal: "/", transpile: { value: "div" } }

  power_op:
    ast: { leaf: true }
    literal: "^"
    transpile: { value: "pow" }

  number:
    ast: { leaf: true, type: "number" }
    transpile: { use: "value" }
    regex: "-?\\d+"

  _:
    ast: { discard: true }
    regex: "[ \\t]*"
```

**Usage:**

```python
# Load the full grammar
with open("full_calculator_grammar.yaml", "r") as f:
    grammar = yaml.safe_load(f)

parser = Parser(grammar)
result = parser.transpile("((2 + 3) * 4) ^ 5")

if result['status'] == 'success':
    print("Parse successful. Transpiling AST...")
    print(f"Final Output: {result['translation']}")
```

**Final Output:**

```
Final Output: (pow (mul (add 2 3) 4) 5)
```

---

### Full Grammar and Directive Reference

#### Grammar Structure Keys

These keys define the actual parsing logic.

| Key                  | Description                                                                               | Value Type      | Example                                    |
| :------------------- | :---------------------------------------------------------------------------------------- | :-------------- | :----------------------------------------- |
| `literal`            | Matches an exact string of text.                                                          | `string`        | `{ literal: "if" }`                        |
| `regex`              | Matches text against a regular expression.                                                | `string`        | `{ regex: "-?\\d+" }`                      |
| `rule`               | References another rule by its name.                                                      | `string`        | `{ rule: expression }`                     |
| `sequence`           | Matches a series of rules in a specific order.                                            | `list` of rules | `{ sequence: [ {rule: A}, {rule: B} ] }`   |
| `choice`             | Matches one of several possible rules. Tries them in order.                               | `list` of rules | `{ choice: [ {rule: A}, {rule: B} }`       |
| `zero_or_more`       | Matches the given rule zero or more times (`*`).                                          | A single rule   | `{ zero_or_more: {rule: A} }`              |
| `one_or_more`        | Matches the given rule one or more times (`+`).                                           | A single rule   | `{ one_or_more: {rule: A} }`               |
| `optional`           | Matches the given rule zero or one time (`?`).                                            | A single rule   | `{ optional: {rule: A} }`                  |
| `positive_lookahead` | Asserts that the text ahead matches the rule, but does not consume text (`&`).            | A single rule   | `{ positive_lookahead: {literal: "TO"} }`  |
| `negative_lookahead` | Asserts that the text ahead does **not** match the rule, but does not consume text (`!`). | A single rule   | `{ negative_lookahead: {literal: "END"} }` |

#### The `ast` Block

The `ast` block controls how the Abstract Syntax Tree is constructed for a given rule.

| Key         | Description                                                                                                                                         | Example                                     |
| :---------- | :-------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------ |
| `tag`       | Renames the node in the final AST. Useful for creating cleaner, more abstract node types.                                                           | `ast: { tag: "clone_to" }`                  |
| `discard`   | Throws away the node created by this rule. It will not appear in the AST. Essential for whitespace, comments, and syntactic sugar.                  | `ast: { discard: true }`                    |
| `promote`   | Replaces the current node with its child node in the AST. This is used to simplify the tree by removing unnecessary intermediate nodes.             | `ast: { promote: true }`                    |
| `leaf`      | Marks this as a terminal node in the AST. It will have no children, even if it's composed of other rules. Its `text` and `value` are preserved.     | `ast: { leaf: true }`                       |
| `type`      | Adds a data type hint to a leaf node. Currently, `type: "number"` will cause the system to parse the node's text as a numeric value.                | `ast: { leaf: true, type: "number" }`       |
| `name`      | In a `sequence`, assigns a name to a specific child. This causes the parent's `children` attribute in the AST to be a dictionary instead of a list. | `{ rule: path, ast: { name: "repo" } }`     |
| `structure` | A powerful directive that automatically builds complex tree structures.                                                                             | `ast: { structure: "left_associative_op" }` |

##### Why Use `tag`?

The `tag` directive provides three powerful advantages: **decoupling, abstraction, and clarity**.

1.  **Decoupling Grammar from AST:** The name of a rule often describes its **syntactic role** (what it does for parsing, like `term` or `factor`), while the tag describes its **semantic meaning** (what it _is_, like a `binary_op`). This allows the grammar to be structured for correct parsing (e.g., operator precedence) while producing a simple, semantic AST for the next stage.

2.  **Creating Abstract Concepts:** A `tag` allows you to create a single, unified AST node type from multiple different syntactic forms. For example, a language might have `let_statement` and `const_statement` rules, but both can be given the tag `variable_declaration`, simplifying the code that consumes the AST.

3.  **Improving Grammar Readability:** Sometimes, a rule needs a long, descriptive name to be clear (e.g., `statement_ending_with_optional_semicolon`), but you want a short, concise name in your AST (e.g., `statement`).

##### `structure` Types:

- `"left_associative_op"`: Automatically builds a left-leaning binary operation tree. It expects the rule to have a `sequence` with two children: the left-hand side, and a `zero_or_more` of the operator and the right-hand side.
- `"right_associative_op"`: Automatically builds a right-leaning binary operation tree. It expects the rule to have a `sequence` with two children: the left-hand side, and an `optional` recursive call containing the operator and the right-hand side.

#### The `transpile` Block

The `transpile` block controls how a finished AST node is converted into the final output string.

| Key        | Description                                                                                                                                        | Example                                           |
| :--------- | :------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------ |
| `template` | Uses a Python f-string-like template to generate the output. Placeholders like `{repo}` are filled in from the AST node's named children.          | `transpile: { template: "(call {func} {args})" }` |
| `use`      | Uses a specific property from the AST node as the output. `"use: "value"` is for numbers. `"use: "text"` is for identifiers or string literals.    | `transpile: { use: "value" }`                     |
| `value`    | Provides a hardcoded string value as the output for this node. This is perfect for converting operators like `+` into function names like `"add"`. | `transpile: { value: "add" }`                     |

## Roadmap

See our `TODO.md` for planned features, including:

- Integrated Stateful Lexer for indentation-based languages.

## Author

The Koine engine was developed by **Chris Bates**.

- https://github.com/chrsbats

## Acknowledgements

This project was made possible by the foundational ideas and early conceptual prototypes developed by **Adam Griffiths**. Their insights into creating a fully data-driven parsing pipeline were instrumental in shaping the final architecture and philosophy of Koine.

- https://github.com/adamlwgriffiths

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
