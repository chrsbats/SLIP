# Parsing with Koine: From Text to AST

```python
import yaml
from koine.parser import Parser
# 1. Load the grammars
with open("parser_calc.yaml", "r") as f:
    parser_grammar = yaml.safe_load(f)

    # 2. Instantiate the tools
    parser = Parser(parser_grammar)

    # 3. Run the pipeline
    source_code = "2 + 3"
    parse_result = parser.parse(source_code)
```

# Parsing with Koine: From Text to AST

This document is a comprehensive guide to Koine's parsing capabilities. It will show you how to define a language grammar and use Koine to transform raw source text into a clean, structured, and semantically meaningful Abstract Syntax Tree (AST).

This guide focuses _exclusively_ on the parsing pipeline: **Grammar + Text -> AST**. The subsequent step of transpiling an AST into a new string format is covered separately.

---

## 1. The Anatomy of a Grammar

A Koine grammar is a dictionary (often written in YAML for readability) with two top-level keys:

- `start_rule`: The name of the rule where parsing should begin.
- `rules`: A dictionary where each key is a rule's name and its value defines the rule's logic.

### Core Building Blocks

These are the fundamental keys you'll use to define what your language looks like.

| Key        | Description                                    |
| :--------- | :--------------------------------------------- |
| `literal`  | Matches an exact string of text.               |
| `regex`    | Matches text against a regular expression.     |
| `rule`     | References another rule by its name.           |
| `choice`   | Matches one of several possible rules.         |
| `sequence` | Matches a series of rules in a specific order. |

**Example: A Simple Greeting**

Let's define a grammar that can parse "Hello, world!" or "Hello, Alice!".

**`grammar.yaml`**

```yaml
start_rule: greeting
rules:
  greeting:
    sequence:
      - { literal: "Hello" }
      - { rule: comma_and_space }
      - { rule: target }
      - { literal: "!" }

  comma_and_space:
    regex: ",\\s+" # a comma followed by one or more spaces

  target:
    choice:
      - { literal: "world" }
      - { regex: "[A-Z][a-z]+" } # A capitalized name
```

At this stage, without any AST directives, Koine produces a raw, verbose parse tree that directly mirrors the grammar structure. It's functional but noisy. We'll clean this up next.

### Organizing Your Grammar with `subgrammar`

For larger grammars, you can split your rules across multiple files using the `subgrammar` directive to create modular, namespaced components.

The `subgrammar` directive is used inside a rule definition to delegate parsing to another, self-contained grammar file. This is for breaking a complex language into smaller, independently testable parts.

**Syntax**

A rule component that uses a subgrammar has the following structure, where `subgrammar` and `ast` are sibling keys:

```yaml
# Inside a `sequence` or `choice` list:
- subgrammar:
    file: "path/to/sub.yaml"
    rule: "entry_rule_in_sub" # optional
    placeholder: { regex: "..." } # optional
  ast:
    name: "sub_result" # optional
```

The `subgrammar` block itself contains keys to control which file to load and how to parse it:

| Key           | Description                                                                                                                                                         |
| :------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `file`        | **(Required)** The path to the self-contained `.yaml` grammar file to load.                                                                                         |
| `rule`        | (Optional) The name of the rule within the subgrammar to use as the entry point. Defaults to the subgrammar's `start_rule`.                                         |
| `placeholder` | (Optional) A rule definition (e.g., `{ regex: "..." }`) used for structural parsing with `parse_with_placeholders()`. See the section on modular development below. |

The sibling `ast` block works just like it does for any other rule component. It is most commonly used to `name` the result of the subgrammar parse within a sequence, or to `discard` it entirely.

When Koine encounters a `subgrammar` directive during a full parse (`parser.parse()`), it:

1.  Loads the subgrammar file specified in the `file` key.
2.  Namespaces all rules from the subgrammar by prefixing them with a PascalCase version of the subgrammar's filename (e.g., `rule_name` in `path_parser.yaml` becomes `PathParser_rule_name`).
3.  Merges these namespaced rules into the parent grammar.
4.  Replaces the `subgrammar` directive with a call to the subgrammar's namespaced `start_rule`.

**`path_parser.yaml`**

```yaml
# A self-contained parser for just file paths.
start_rule: path
rules:
  path:
    ast: { tag: "path" }
    sequence: [{ rule: segment }, { literal: "." }, { rule: segment }]
  segment:
    ast: { leaf: true }
    regex: "[a-z]+"
```

**`main_cli_parser.yaml`**

```yaml
start_rule: command
rules:
  command:
    ast: { tag: "command" }
    sequence:
      - { literal: "COPY" }
      - { rule: _ }
      - { subgrammar: { file: "path_parser.yaml" }, ast: { name: "source" } } # Delegate to path_parser.yaml
      - { rule: _ }
      - { subgrammar: { file: "path_parser.yaml" }, ast: { name: "dest" } }
  _:
    ast: { discard: true }
    regex: "[ \\t]+"
```

When parsing with `main_cli_parser.yaml`, a `COPY` command would expect two parts that can be parsed by `path_parser.yaml`. The `subgrammar` directive makes `path_parser.yaml` a reusable component.

### Developing with Modular Grammars: `Parser` vs. `PlaceholderParser`

The `subgrammar` directive is powerful, but it presents a challenge: how do you test a grammar file in isolation if its `subgrammar` directives make it dependent on other files?

Koine solves this by providing two different parser classes:

1.  **`Parser`**: The standard parser for production use. It fully resolves all `subgrammar` directives, merging them into a single, complete grammar for final parsing.
2.  **`PlaceholderParser`**: A parser for testing and development. It _ignores_ all `subgrammar` directives, instead using the `placeholder` definition you provide in a `subgrammar` block. This allows you to test a grammar file's local structure without needing to load its dependencies.

To enable this workflow, you provide a `placeholder` definition inside the `subgrammar` object, as described in the section above.

**How it Works:**

- `PlaceholderParser(grammar).parse(text)`: This parser uses the rule defined in the `placeholder` key inside the `subgrammar` object. It does not access the filesystem to load other files.
- `Parser(grammar).parse(text)`: This parser uses the `file` key to load, namespace, and merge any subgrammars. This is for parsing with the complete, integrated language.

#### Example: Isolated Testing with Placeholders

Imagine you are developing `main_cli_parser.yaml`, which depends on `path_parser.yaml`. You can add a `regex` placeholder to test `main_cli_parser.yaml` on its own.

**`main_cli_parser.yaml`**

```yaml
start_rule: command
rules:
  command:
    ast: { tag: "command" }
    sequence:
      - { literal: "COPY" }
      - { rule: _ }
      # This rule now includes a placeholder for structural parsing
      - subgrammar:
          file: path_parser.yaml
          placeholder: { regex: "[^\\s]+" }
        ast: { name: "source" }
      - { rule: _ }
      - subgrammar:
          file: path_parser.yaml
          placeholder: { regex: "[^\\s]+" }
        ast: { name: "dest" }
  _:
    ast: { discard: true }
    regex: "[ \\t]+"
```

**Testing Code:**

```python
from koine.parser import Parser, PlaceholderParser

# 1. Test the grammar with placeholders
# We can create a PlaceholderParser from the same file.
placeholder_parser = PlaceholderParser.from_file("main_cli_parser.yaml")
placeholder_text = "COPY source_placeholder dest_placeholder"
placeholder_result = placeholder_parser.parse(placeholder_text)
# This parse succeeds because it uses `regex: "[^\\s]+"` for the subgrammars.

# 2. Test the full grammar
# The standard Parser loads all dependencies.
full_parser = Parser.from_file("main_cli_parser.yaml")
full_text = "COPY a.b c.d"
full_result = full_parser.parse(full_text)
# This parse succeeds because it loads path_parser.yaml and uses it
# to correctly parse "a.b" and "c.d".
```

This workflow allows you to build and test each grammar file independently before combining them. Koine also performs validation when a `Parser` is created. For instance, it will raise an error if your grammar contains `rules` that can never be reached from the `start_rule`. This helps find typos and dead code in your grammar definitions.

#### Circular Dependencies

Koine's `subgrammar` system fully supports circular dependencies. A subgrammar can reference a rule that is defined in its parent grammar. This is useful for building languages where different modules need to call back and forth to each other.

When resolving rule references, Koine first checks for a rule within the subgrammar's own `rules` block. If not found, it then checks the parent grammar's rules. This allows a subgrammar to seamlessly use rules from its parent's scope.

**Example:**

**`parent.yaml`**

```yaml
start_rule: a
rules:
  a:
    sequence:
      - { literal: "a_start" }
      - subgrammar:
          file: "child.yaml"
          placeholder: { regex: "..." }
  # This rule is only defined in the parent.
  parent_only_rule:
    literal: "parent_text"
```

**`child.yaml`**

```yaml
start_rule: b
rules:
  b:
    sequence:
      - { literal: "b_start" }
      - { rule: parent_only_rule } # This will correctly resolve to the rule in parent.yaml
```

When calling `parser.parse()` on `parent.yaml`, the text `a_start b_start parent_text` will parse successfully.

---

## 2. Building a Clean AST with the `ast` Directive

The raw parse tree is messy. The `ast` block is a dictionary you add to a rule to control how it's represented in the final AST. This lets you discard noise, simplify the structure, and add semantic meaning.

| Key       | Description                                                                                                                                                                                                                                                                                                                                                                                                |
| :-------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `discard` | Completely removes the node from the AST. Essential for whitespace and punctuation.                                                                                                                                                                                                                                                                                                                        |
| `promote` | Replaces the node with its child or children, then applies the parent's other `ast` directives (like `tag` or `type`) to the result. This allows you to "re-tag" a child node without an extra layer of hierarchy. On a **`sequence`** or **quantifier** (`zero_or_more`, `one_or_more`, `optional`), it _always_ returns a list of children. On a **`choice`**, it promotes the single chosen child node. |
| `leaf`    | Marks a node as a terminal. Its text is captured, but its children aren't processed.                                                                                                                                                                                                                                                                                                                       |
| `tag`     | Renames the node in the AST, decoupling syntax from semantic meaning.                                                                                                                                                                                                                                                                                                                                      |
| `type`    | On a `leaf` node, converts its text to a `number`, `bool`, or `null` value.                                                                                                                                                                                                                                                                                                                                |

**Example: A Clean "Key-Value Pair" AST**

Let's parse `version = "1.0"` into a clean AST with typed values.

**`grammar.yaml`**

```yaml
start_rule: pair
rules:
  pair:
    sequence:
      - { rule: identifier }
      - { rule: _ }
      - { literal: "=", ast: { discard: true } }
      - { rule: _ }
      - { rule: value }

  identifier:
    ast: { leaf: true }
    regex: "[a-zA-Z_]+"

  value:
    ast: { promote: true } # We don't need a 'value' node, just what's inside
    choice:
      - { rule: string_literal }
      - { rule: number_literal }

  string_literal:
    ast: { promote: true }
    sequence:
      - { literal: '"', ast: { discard: true } }
      - { rule: string_content }
      - { literal: '"', ast: { discard: true } }

  string_content:
    ast: { tag: "string", leaf: true } # Tag the important part
    regex: '[^"]*'

  number_literal:
    ast: { tag: "number", leaf: true, type: "number" } # Add type conversion
    regex: "\\d+(\\.\\d+)?"

  _: # A common convention for discardable whitespace
    ast: { discard: true }
    regex: "[ \\t]*"
```

**Input Text**: `version = "1.0"`
**Resulting AST**:

```json
{
  "tag": "pair",
  "text": "version = \"1.0\"",
  "line": 1,
  "col": 1,
  "children": [
    {
      "tag": "identifier",
      "text": "version",
      "line": 1,
      "col": 1
    },
    {
      "tag": "string",
      "text": "1.0",
      "line": 1,
      "col": 11
    }
  ]
}
```

### Combining `promote` with other directives

The `promote` directive is especially powerful because it applies the parent's `ast` directives _after_ promoting the child. This lets you change the `tag`, `type`, or other properties of a node without adding an extra layer of nesting to your grammar.

**Example: Re-tagging and re-typing a promoted node**

Imagine you have a rule that parses any sequence of digits, but in one context you want to treat it as a special `user_id` and ensure it's a number.

**`grammar.yaml`**

```yaml
start_rule: get_user
rules:
  get_user:
    ast: { tag: "get_user" }
    sequence:
      - { literal: "USER", ast: { discard: true } }
      - { rule: _ }
      - { rule: user_id }

  user_id:
    # Promote the child, but override its tag and ensure its type.
    ast: { promote: true, tag: "user_id", type: "number" }
    rule: identifier

  identifier:
    # This rule produces a generic "identifier" node.
    ast: { tag: "identifier", leaf: true }
    regex: "[a-zA-Z0-9_]+"

  _:
    ast: { discard: true }
    regex: "\\s+"
```

**Input Text**: `USER 123`
**Resulting AST**:
Without the parent `user_id` rule's `ast` directives, `identifier` would produce a node like `{"tag": "identifier", "text": "123"}`. With the new `promote` logic, the `user_id` rule promotes this node and then applies its own directives to it. The `user_id` node within the final AST will look like this:

```json
{
  "tag": "user_id",
  "text": "123",
  "line": 1,
  "col": 6,
  "value": 123
}
```

The final node has its tag changed to `user_id` and its value converted to a number. This avoids creating an extra wrapper rule and keeps the grammar clean and intuitive.

**Example: Typed `bool` and `null` values**

The `type` key also supports `bool` and `null` conversions.

**`grammar.yaml`**

```yaml
start_rule: config_item
rules:
  config_item:
    sequence:
      - { rule: identifier }
      - { rule: _ }
      - { literal: "=", ast: { discard: true } }
      - { rule: _ }
      - { rule: value }

  value:
    ast: { promote: true }
    choice:
      - { rule: bool_literal }
      - { rule: null_literal }

  bool_literal:
    ast: { tag: "boolean", leaf: true, type: "bool" }
    regex: "true|false"

  null_literal:
    ast: { tag: "null", leaf: true, type: "null" }
    literal: "null"

  identifier:
    ast: { leaf: true }
    regex: "[a-zA-Z_]+"

  _:
    ast: { discard: true }
    regex: "[ \\t]*"
```

**Input Text 1**: `enabled = true`
**Resulting AST 1**:

```json
{
  "tag": "config_item",
  "children": [
    { "tag": "identifier", "text": "enabled", ... },
    { "tag": "boolean", "text": "true", "value": true, ... }
  ]
}
```

**Input Text 2**: `user = null`
**Resulting AST 2**:

```json
{
  "tag": "config_item",
  "children": [
    { "tag": "identifier", "text": "user", ... },
    { "tag": "null", "text": "null", "value": null, ... }
  ]
}
```

---

## 3. Handling Repetition and Optional Parts

Koine uses quantifiers to handle parts of your grammar that can repeat or be absent.

| Key            | Description                       |
| :------------- | :-------------------------------- |
| `optional`     | Matches zero or one time (`?`).   |
| `zero_or_more` | Matches zero or more times (`*`). |
| `one_or_more`  | Matches one or more times (`+`).  |

**Example: A list of tags**

Let's parse a comma-separated list like `[urgent, "customer-issue"]`. This pattern—`item (separator item)*`—is very common for lists.

**`grammar.yaml`**

```yaml
start_rule: tag_list
rules:
  tag_list:
    sequence:
      - { literal: "[", ast: { discard: true } }
      - { rule: _ }
      - optional: # The list can be empty
          sequence:
            - { rule: tag }
            - zero_or_more:
                sequence:
                  - { rule: _ }
                  - { literal: ",", ast: { discard: true } }
                  - { rule: _ }
                  - { rule: tag }
      - { rule: _ }
      - { literal: "]", ast: { discard: true } }

  tag:
    ast: { tag: "tag", leaf: true }
    regex: "[a-zA-Z-]+"
    # A full implementation would also handle quoted strings.

  _:
    ast: { discard: true }
    regex: "[ \\t]*"
```

**Input Text**: `[urgent, critical]`
**Resulting AST**:

```json
{
  "tag": "tag_list",
  "text": "[urgent, critical]",
  "line": 1,
  "col": 1,
  "children": [
    { "tag": "tag", "text": "urgent", "line": 1, "col": 2 },
    { "tag": "tag", "text": "critical", "line": 1, "col": 10 }
  ]
}
```

---

## 4. Advanced AST Construction

Koine offers powerful `structure` directives to automatically build complex AST nodes.

### Associative Operators: `left_associative_op` and `right_associative_op`

For parsing mathematical or logical expressions, handling operator precedence and associativity is crucial. Koine automates this.

- `left_associative_op`: For operators like `+`, `-`, `*`, `/`. `a - b - c` is parsed as `(a - b) - c`.
- `right_associative_op`: For operators like `^` (power). `a ^ b ^ c` is parsed as `a ^ (b ^ c)`.

**Example: A Simple Calculator**

This grammar correctly handles precedence (`*` before `+`) and associativity.

**`grammar.yaml`**

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
      - { rule: factor }
      - zero_or_more:
          sequence:
            [{ rule: _ }, { rule: mul_op }, { rule: _ }, { rule: factor }]
  factor:
    ast: { promote: true }
    choice:
      - { rule: number }
      - sequence:
          - { literal: "(" }
          - { rule: _ }
          - { rule: expression }
          - { rule: _ }
          - { literal: ")", ast: { discard: true } }
  add_op: { ast: { leaf: true }, choice: [{ literal: "+" }, { literal: "-" }] }
  mul_op: { ast: { leaf: true }, choice: [{ literal: "*" }, { literal: "/" }] }
  number: { ast: { leaf: true, type: "number" }, regex: "\\d+" }
  _: { ast: { discard: true }, regex: "[ \\t]*" }
```

**Input Text**: `1 + 2 * 3`
**Resulting AST**:

```json
{
  "tag": "binary_op",
  "op": { "tag": "add_op", "text": "+", ... },
  "left": { "tag": "number", "value": 1, ... },
  "right": {
    "tag": "binary_op",
    "op": { "tag": "mul_op", "text": "*", ... },
    "left": { "tag": "number", "value": 2, ... },
    "right": { "tag": "number", "value": 3, ... }
  }
}
```

### Declarative `structure` and `map_children`

This is the most powerful way to build a custom AST node. You define the shape of your node and map children from the parsing rule into it. This is robust to optional or discarded children.

- `tag`: The tag for the new AST node.
- `map_children`: A dictionary where keys are the desired child names in the AST, and values (`{from_child: <index>}`) specify the 0-based index of the child rule within the `sequence` list.

**Example: A `let` statement**

Let's parse `let version = "1.0"` into a clean node with named `name` and `value` children.

**`grammar.yaml`**

```yaml
start_rule: declaration
rules:
  declaration:
    ast:
      structure:
        tag: "variable_declaration"
        map_children:
          # 'identifier' is the 2nd item in the sequence (index 1)
          name: { from_child: 1 }
          # 'expression' is the 4th item (index 3)
          value: { from_child: 3 }
    sequence:
      # Whitespace rules would be here but are omitted for brevity.
      - { literal: "let", ast: { discard: true } }
      - { rule: identifier }
      - { literal: "=", ast: { discard: true } }
      - { rule: expression }

  identifier:
    ast: { leaf: true }
    regex: "[a-zA-Z_]+"

  expression:
    ast: { promote: true }
    choice:
      - { rule: string_literal }

  string_literal:
    ast: { tag: "string", promote: true }
    sequence:
      - { literal: '"', ast: { discard: true } }
      - { rule: string_content }
      - { literal: '"', ast: { discard: true } }

  string_content:
    ast: { leaf: true }
    regex: '[^"]*'
```

**Input Text**: `let version = "1.0"`
**Resulting AST**:

```json
{
  "tag": "variable_declaration",
  "text": "let version = \"1.0\"",
  "line": 1,
  "col": 1,
  "children": {
    "name": {
      "tag": "identifier",
      "text": "version",
      "line": 1,
      "col": 5
    },
    "value": {
      "tag": "string",
      "text": "1.0",
      "line": 1,
      "col": 15
    }
  }
}
```

### `name`: Simple Child Naming

As a simpler alternative to a full `structure` block, you can add `ast: { name: "..." }` to a rule within a `sequence`. If any child in a sequence is named, the parent's `children` becomes a dictionary mapping the names to the child nodes, instead of a list.

**Example: A `clone` Command** using `name`.

**`grammar.yaml`**

```yaml
start_rule: clone_statement
rules:
  clone_statement:
    ast: { tag: "clone" }
    sequence:
      - { literal: "CLONE", ast: { discard: true } }
      - { rule: _ }
      - { rule: path, ast: { name: "source" } } # Name this child
      - { rule: _ }
      - { literal: "TO", ast: { discard: true } }
      - { rule: _ }
      - { rule: path, ast: { name: "destination" } } # And this one

  path:
    ast: { leaf: true }
    regex: "[^\\s]+"

  _:
    ast: { discard: true }
    regex: "[ \\t]+"
```

**Input Text**: `CLONE /a/b TO /c/d`
**Resulting AST**:

```json
{
  "tag": "clone",
  "text": "CLONE /a/b TO /c/d",
  "line": 1,
  "col": 1,
  "children": {
    "source": {
      "tag": "path",
      "text": "/a/b",
      "line": 1,
      "col": 7
    },
    "destination": {
      "tag": "path",
      "text": "/c/d",
      "line": 1,
      "col": 17
    }
  }
}
```

---

## 5. Advanced Logic with Lookaheads

Lookaheads let you check for patterns _without consuming text_. This is essential for resolving ambiguity.

- `positive_lookahead`: Succeeds if the pattern matches ahead (`&`).
- `negative_lookahead`: Succeeds if the pattern does **not** match ahead (`!`).

**Example: Distinguishing Two Commands**

Let's define a grammar for a `CLONE` command that can have two forms: `CLONE <path>` or `CLONE <path> TO <path>`. A greedy parser might incorrectly match the start of the longer command with the rule for the shorter one. We must try the more specific `clone_to_statement` first, and we use lookaheads to ensure each rule only matches the correct syntax.

**`grammar.yaml`**

```yaml
start_rule: statement
rules:
  statement:
    ast: { promote: true }
    choice:
      - { rule: clone_to_statement } # Must try this one first!
      - { rule: clone_statement }

  clone_to_statement:
    # This rule only matches if "TO" is present later on.
    ast: { tag: "clone_to" }
    sequence:
      - positive_lookahead:
          sequence:
            [
              { rule: clone_keyword },
              { rule: _ },
              { rule: path },
              { rule: _ },
              { rule: to_keyword },
            ]
      # If the lookahead succeeds, we parse the full command.
      - { rule: clone_keyword }
      - { rule: _ }
      - { rule: path, ast: { name: "source" } }
      - { rule: _ }
      - { rule: to_keyword }
      - { rule: _ }
      - { rule: path, ast: { name: "destination" } }

  clone_statement:
    ast: { tag: "clone" }
    sequence:
      - { rule: clone_keyword }
      - { rule: _ }
      - { rule: path, ast: { name: "source" } }
      # And now we ensure "TO" does NOT follow.
      - negative_lookahead:
          sequence: [{ rule: _ }, { rule: to_keyword }]

  path: { ast: { leaf: true }, regex: "[^\\s]+" }
  clone_keyword: { ast: { discard: true }, literal: "CLONE" }
  to_keyword: { ast: { discard: true }, literal: "TO" }
  _: { ast: { discard: true }, regex: "[ \\t]+" }
```

With this logic, `CLONE /a TO /b` matches `clone_to_statement`, while `CLONE /c` correctly matches `clone_statement`.

**Input 1**: `CLONE /a TO /b`
**Resulting AST 1**:

```json
{
  "tag": "clone_to",
  "children": {
    "source": { "tag": "path", "text": "/a", ... },
    "destination": { "tag": "path", "text": "/b", ... }
  }
}
```

**Input 2**: `CLONE /c`
**Resulting AST 2**:

```json
{
  "tag": "clone",
  "children": {
    "source": { "tag": "path", "text": "/c", ... }
  }
}
```

---

## 6. Using a Lexer for Tokens and Indentation

For some languages, especially those with significant whitespace, comments, or context-sensitive keywords, pre-processing the text into a stream of **tokens** is better. This is done with the top-level `lexer` block.

When a `lexer` is defined:

1.  The input text is first tokenized according to the `lexer` rules.
2.  The parser then works on this stream of tokens, not the raw text.
3.  Grammar rules must change from using `literal` and `regex` to using `token` to match token types.

### Defining Tokens

The `tokens` key contains an ordered list of token definitions. For each position in the text, Koine finds the token definition whose `regex` matches the longest string of text. Each token definition is a dictionary with the following keys:

| Key      | Description                                                                                                                              |
| :------- | :--------------------------------------------------------------------------------------------------------------------------------------- |
| `regex`  | **(Required)** The regular expression used to match the token's text.                                                                    |
| `token`  | The type name for the created token (e.g., `NAME`, `NUMBER`). Required unless `action` is `skip`.                                        |
| `action` | Special behavior. `skip` discards the matched text (for whitespace/comments). `handle_indent` manages indentation tokens.                |
| `ast`    | An `ast` block that is applied directly to the token. This is useful for `type` conversion (e.g., `{type: "number"}`) or even `discard`. |

### `handle_indent`: For Indentation-Based Syntax

Koine's lexer has built-in support for indentation-based languages like Python.
Using `action: "handle_indent"` on a newline-matching regex will automatically generate `INDENT` and `DEDENT` tokens.

**Example: A Simple Python-like Function**

**`grammar.yaml`**

```yaml
lexer:
  tokens:
    - { regex: "[ \\t]+", action: "skip" }
    - { regex: "\\n[ \\t]*", action: "handle_indent" } # The magic
    - { regex: "def", token: "DEF" }
    - { regex: "return", token: "RETURN" }
    - { regex: "[a-zA-Z_]+", token: "NAME" }
    - { regex: ":", token: "COLON" }
    - { regex: "\\(", token: "LPAREN" }
    - { regex: "\\)", token: "RPAREN" }

start_rule: function_definition
rules:
  function_definition:
    ast:
      {
        structure:
          {
            tag: "function",
            map_children: { name: { from_child: 1 }, body: { from_child: 5 } },
          },
      }
    sequence:
      - { token: "DEF", ast: { discard: true } }
      - { rule: identifier } # 'identifier' now just wraps a NAME token
      - { token: "LPAREN", ast: { discard: true } }
      - { token: "RPAREN", ast: { discard: true } }
      - { token: "COLON", ast: { discard: true } }
      - { rule: suite }

  suite:
    ast: { promote: true }
    sequence:
      - { token: "INDENT", ast: { discard: true } }
      - { rule: statements }
      - { token: "DEDENT", ast: { discard: true } }

  statements:
    ast: { tag: "statements" }
    one_or_more: { rule: statement }

  statement:
    ast: { promote: true }
    choice:
      - { rule: return_statement }

  return_statement:
    ast: { promote: true }
    sequence:
      - { token: "RETURN" }

  identifier:
    ast: { promote: true }
    sequence: [{ token: "NAME" }]
```

**Input Text**

```python
def my_func():
    return
```

The lexer first turns this into a token stream like: `DEF NAME LPAREN RPAREN COLON INDENT RETURN DEDENT`. The parser then easily consumes this token stream to build the correct AST.

**Resulting AST**

```json
{
  "tag": "function",
  "text": "def my_func():\\n    return",
  "line": 1,
  "col": 1,
  "children": {
    "name": {
      "tag": "NAME",
      "text": "my_func",
      "value": "my_func",
      "line": 1,
      "col": 5
    },
    "body": {
      "tag": "statements",
      "text": "return",
      "line": 2,
      "col": 5,
      "children": [
        {
          "tag": "RETURN",
          "text": "return",
          "value": "return",
          "line": 2,
          "col": 5
        }
      ]
    }
  }
}
```
