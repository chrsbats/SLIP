## SLIP Implementation Specification v0.1

### Introduction

A brief overview of the document's purpose: to provide a formal and complete guide for building a correct, robust, and high-performance SLIP interpreter. This document details the internal architecture and evaluation semantics that are not part of the user-facing language reference. It is the "how" that complements the language spec's "what."

## Part I: Parsing and Transformation

This part details the two-stage process of converting raw SLIP source code into a final, high-level Abstract Syntax Tree (AST) of Python objects. This pipeline is the foundation of the entire interpreter.

1.  **Parsing:** The Koine parser is used to convert source text into a raw, intermediate, dictionary-based AST that directly reflects the language's grammar.
2.  **Transformation:** A custom "Transformer" class then walks this raw AST and converts it into a tree of dedicated Python classes (e.g., `ExpressionNode`, `PathNode`), which is the final AST used by the evaluator.

This separation of concerns makes the parsing process cleaner, more modular, and easier to debug.

## Chapter 1: The Core Grammar and Parsing Strategy

This chapter defines the parsing strategy using the Koine toolkit, the structure of the intermediate AST that the parser produces, and the role of the final transformation step.

### 1.1. The Parsing Strategy with Koine

The SLIP parser is composed of two distinct, hierarchical component grammars. This modular approach is the key to managing the language's complexity while allowing for robust, independent testing of its components.

- **`slip_grammar.yaml` (The Structural Grammar):** The top-level grammar that understands the overall "shape" of a SLIP script—expressions, blocks, and literals.
- **`slip_path.yaml` (The Path Grammar):** A subgrammar that is an expert in parsing the complex, segment-based structure of SLIP paths, including the specialized query syntax.

Koine's `subgrammar` and `PlaceholderParser` features are used to manage the integration and isolated testing of these two components. The `slip_grammar.yaml` is the main entry point, and it delegates all path parsing to the `slip_path.yaml` subgrammar. Any errors raised by the parser are considered `Syntax Errors` and should be reported to the host with a `400 Bad Request` status code.

### 1.2. The Koine AST Structure

The output of the Koine parser is a nested structure of dictionaries representing the parse tree. Each dictionary is a **node** and has a specific structure:

- `"tag"`: A string that corresponds to the name of the grammar rule that produced this node.
- `"children"`: A list of child nodes that were captured by the rule.
- `"text"` or `"value"`: For terminal nodes (tokens), this key holds the captured string from the source or its converted value (e.g., for numbers).

The following sections describe the expected Koine AST for each grammatical form.

### 1.3. Expressions and Code

The top-level result of a parse is a `code` node, which contains a list of `expr` nodes. An expression is a flat list of terms.

- **Source:** `1 + 2`
- **Koine AST:**
  ```yaml
  tag: code
  children:
    - tag: expr
      children:
        - tag: number
          value: 1
        - tag: get-path # Infix operators are parsed as simple paths
          text: +
        - tag: number
          value: 2
  ```

### 1.4. The Five Containers

Each container literal is parsed into a node with a corresponding tag by the `slip_grammar.yaml`.

- **`()` Group:**
  ```yaml
  tag: group
  children: # A list of `expr` nodes inside the group
    - tag: expr
      children: [...]
  ```
- **`[]` Code:**
  ```yaml
  tag: code
  children: # A list of `expr` nodes inside the code block
    - tag: expr
      children: [...]
  ```
- **`{}` Signature (`sig`):**
  ```yaml
  tag: sig
  children: # A list of nodes representing the signature's contents
    - tag: sig-arg
      text: x
    - tag: sig-kwarg
      children:
        - tag: sig-key
          text: y
        - tag: number # The unevaluated literal value
          value: 10
  ```
- **`#{}` Dictionary (`dict`):** A dictionary literal contains a list of expressions. It is functionally equivalent to `dict [...]`. The parser treats its contents just like a `code` block; it is the evaluator's `dict` primitive that interprets the assignment expressions to build the dictionary.
  ```yaml
  # Source: #{ name: "Kael", hp: 100 }
  tag: dict
  children: # A list of `expr` nodes
    - tag: expr
      children:
        - tag: set-path
          text: name:
        - tag: string
          value: "Kael"
    - tag: expr
      children:
        - tag: set-path
          text: hp:
        - tag: number
          value: 100
  ```
- **`#[]` List:**
  ```yaml
  tag: list
  children: # A list of `expr` nodes for each element
    - tag: expr
      children:
        - tag: number
          value: 1
  ```

### 1.5. Literals

Literals are terminal nodes that capture a value directly.

- **Source:** `123` -> `tag: number, value: 123`
- **Source:** `"hello"` -> `tag: string, value: "hello"`
- **Source:** `true` -> `tag: boolean, value: true`
- **Source:** `none` -> `tag: none`

### 1.6. Comments

Comments are identified by the lexer and must be discarded. They should not appear in the final AST.

- **Single-line:** A `--` sequence that is either at the beginning of a line (preceded only by whitespace) or is preceded by a space.
- **Multi-line:** A `{--` sequence begins a block comment, which is terminated by `--}`. Block comments must support nesting.

### 1.7. The Transformer

The Transformer is the crucial second stage of the parsing pipeline. Its role is to convert the literal, low-level Koine AST into a more semantic, class-based AST that is easier for the evaluator to work with.

- **Input:** The raw, dictionary-based AST from the Koine parser.
- **Process:** The Transformer recursively walks the input AST. It inspects the `"tag"` of each node and instantiates the corresponding Python class (e.g., if `tag` is `"group"`, it creates a `GroupNode` object). It then recursively transforms the `children` and passes them to the new class's constructor. This is also the stage where simple structural validations can occur.
- **Output:** The root of the final, Python class-based AST (e.g., an instance of `CodeNode`), which is then passed to the evaluator.

## Chapter 2: The Path Grammar (Final Version)

This chapter details the specialized `slip_path.yaml` subgrammar. Its responsibility is to parse all path-like structures in SLIP. A path is not a simple string; it is a structured sequence of components that forms a query. The grammar is designed to decompose these structures into a detailed AST node containing a flat list of distinct segment types.

### 2.1. Overall Path Structure

The grammar defines a path as having two main parts: an optional prefix and a mandatory chain of components. This structure correctly handles paths that start from the root (`/`) as a special case.

- **A path is either:**
  1.  A `root` segment (`/`), optionally followed by a `component-chain`.
  2.  Or just a `component-chain`.

This allows the grammar to parse `/`, `/a/b`, and `a/b` correctly.

- **A `component-chain` is:**

  1. A sequence of one or more `path-component`s, separated by `.` or `/`.

- **A `path-component` is:**
  1.  A **base segment** (e.g., `name`, `parent`, or `(group)`).
  2.  Followed by zero or more **follower segments** (a `query-segment` `[...]` or `group-segment` `(...)`).

This two-level structure allows the grammar to correctly parse complex components like `a[0](key)` as a single unit within the larger path.

### 2.2. Path Forms

The parser must distinguish between the five primary path forms based on their tokens and structure. The resulting AST node will have a `tag` corresponding to the path's form.

- **Get-Path:** `a.b` -> `tag: get-path`
- **Set-Path:** `a.b:` -> `tag: set-path`
- **Del-Path:** `~a.b` -> `tag: del-path`
- **Piped-Path:** `|map` -> `tag: piped-path`
- **Multi-Set Path:** `[a, b]:` -> `tag: multi-set`

### 2.3. Path Segments and Components

A `path` node's `children` list contains a sequence of segment nodes. These segments are the building blocks parsed by the `component-chain` rules.

#### 2.3.1. Name Segment

A standard identifier, separated by `.` or `/`.

- **Source:** `a.name`
- **Koine AST (for `name`):** `tag: name, text: 'name'`

#### 2.3.2. Root Segment

A leading forward slash (`/`). It can only appear at the very beginning of a path.

- **Source:** `/a`
- **Koine AST (for `/`):** `tag: root`

#### 2.3.3. Parent Segment

A `../` or `..` sequence used to traverse up the scope hierarchy. It can appear at the start of a path or in the middle.

- **Source:** `../a/b`
- **Koine AST (for `..`):** `tag: parent`

#### 2.3.4. Query Segment

A `[...]` block following a path segment. The path parser itself is responsible for parsing the contents of the brackets according to a simple, specialized grammar, and creating a `query-segment` node. This node will contain a single child node defining the specific query type.

- **Parsing Precedence:** To correctly parse a query, the following order of matching must be attempted:

  1.  **Slice Query:** First, check for a colon (`:`).
  2.  **Filter Query:** If not a slice, check for a leading comparison operator (`>`, `<`, `=`, etc.).
  3.  **Index/Key Query:** If neither of the above, parse as a single expression.

- **Slice Query Form:**

  - **Source:** `[1:4]`, `[start:end+1]`
  - **Contained Node:** `tag: slice-query`, with two optional children, `start-expr` and `end-expr`, each containing a standard `expr` node.
  - **Example Koine AST for `[1:4]`:**
    ```yaml
    tag: query-segment
    children:
      - tag: slice-query
        children:
          - tag: start-expr
            children:
              - tag: expr
                children:
                  - tag: number
                    value: 1
          - tag: end-expr
            children:
              - tag: expr
                children:
                  - tag: number
                    value: 4
    ```

- **Filter Query Form:**

  - **Source:** `[> 100]`, `[= "active"]`
  - **Contained Node:** `tag: filter-query`, with two required children: `operator` and `rhs-expr`.
  - **Example Koine AST for `[>= limit]`:**
    ```yaml
    tag: query-segment
    children:
      - tag: filter-query
        children:
          - tag: operator
            text: ">="
          - tag: rhs-expr
            children:
              - tag: expr
                children:
                  - tag: get-path
                    text: limit
    ```

- **Index/Key Query Form:**
  - **Source:** `[0]`, `["name"]`, `[my-variable]`
  - **Contained Node:** `tag: simple-query`, with a single `expr` node as its child.
  - **Example Koine AST for `[my-index]`:**
    ```yaml
    tag: query-segment
    children:
      - tag: simple-query
        children:
          - tag: expr
            children:
              - tag: get-path
                text: my-index
    ```

#### 2.3.5. Group Segment

A standard `(...)` evaluation group used as a segment within a path. This allows for dynamic, computed property access. It can appear with or without a separator.

- **Source:** `user.(get-key).name`
- **Koine AST:** The parser produces a `group` node directly as a segment in the path's children list.
  ```yaml
  # Part of the children list for user.(get-key)
  ---
  - tag: group
    children:
      - tag: expr
        children:
          - tag: get-path
            text: get-key
  ```

### 2.4. Configuration Segment

A `#( ... )` block immediately following a path. This is **not** part of the `children` list of segments; it is a separate, optional property of the path node.

- **Source:** `a/b#(timeout: 2)`
- **Koine AST:** A `path` node will have an optional `configuration` key.
  ```yaml
  tag: get-path
  children: [...] # The list of segments for a/b
  configuration:
    tag: configuration-segment
    children:
      - tag: dict
        children: [...]
  ```

---

## Chapter 3: The Signature (`sig`) Grammar

This chapter defines the specialized sub-parser for the `{...}` literal. The `sig` literal is a core part of SLIP's type and dispatch system. It is a purely declarative construct used to define function signatures, type unions, and examples.

The `sig` sub-parser is invoked by the main parser (`slip_grammar.yaml`) whenever a `{...}` block is encountered. Its grammar is distinct from the main SLIP expression grammar and is intentionally restrictive to ensure that signatures remain static and declarative.

### 3.1. Parsing Logic

The `sig` sub-parser's primary job is to analyze the comma-separated list of terms inside the `{...}` brackets and categorize them. The parser must recognize four patterns:

1.  **Simple Name:** A bareword identifier (e.g., `x`). This is parsed as a positional argument.
2.  **Key-Value Pair:** A bareword identifier followed by a colon (`:`) and a literal value or simple path (e.g., `y: 10`). This is parsed as a keyword argument.
3.  **Rest Parameter:** A bareword identifier followed by `...` (e.g., `rest...`). This is parsed as a variadic (rest) argument.
4.  **Return Arrow:** A `->` token, which signifies that the single term following it is the return annotation. This token can only appear once.

Any other structure, such as a complex expression or an operator, is a syntax error within a `sig` block.

### 3.2. The `sig` AST Node

The result of a successful parse is a single `sig` node. This node contains a list of child nodes that represent the complete, unevaluated signature information.

- **Koine AST Tag:** `sig`
- **Structure:** The `sig` node contains a list of child nodes, which can be `sig-arg`, `sig-kwarg`, `sig-rest-arg`, or `sig-return`.

### 3.3. Signature Forms and Examples

#### 3.3.1. Positional Arguments / Type Union

This is the simplest form, consisting of a comma-separated list of simple names.

- **Source (Function Parameters):** `{x, y, z}`
- **Source (Type Union):** `{int or string}`
- **Koine AST:**
  ```yaml
  tag: sig
  children:
    - tag: sig-arg
      text: x
    - tag: sig-arg
      text: y
    - tag: sig-arg
      text: z
  ```

#### 3.3.2. Keyword Arguments

This form is used for parameters with default values or for typed keys in an example.

- **Source:** `{x: 10, y: "default"}`
- **Koine AST:**
  ```yaml
  tag: sig
  children:
    - tag: sig-kwarg
      children:
        - tag: sig-key
          text: x
        - tag: number # The unevaluated literal value
          value: 10
    - tag: sig-kwarg
      children:
        - tag: sig-key
          text: y
        - tag: string
          value: "default"
  ```

#### 3.3.3. Return Annotation

The `->` token separates the parameters from the return annotation.

- **Source (Function Signature):** `{x: int -> int}`
- **Koine AST:**
  ```yaml
  tag: sig
  children:
    - tag: sig-kwarg
      children:
        - tag: sig-key
          text: x
        - tag: get-path # The unevaluated type path
          text: int
    - tag: sig-return
      children:
        - tag: get-path # The unevaluated return type path
          text: int
  ```

#### 3.3.4. Mixed Arguments

Positional and keyword arguments can be mixed. All positional arguments must come before any keyword arguments.

- **Source:** `{a, b, c: true}`
- **Koine AST:**
  ```yaml
  tag: sig
  children:
    - tag: sig-arg
      text: a
    - tag: sig-arg
      text: b
    - tag: sig-kwarg
      children:
        - tag: sig-key
          text: c
        - tag: boolean
          value: true
  ```

#### 3.3.5. Variadic (Rest) Argument

This form is used to capture a variable number of arguments.

- **Source:** `{level, parts...}`
- **Koine AST:**
  ```yaml
  tag: sig
  children:
    - tag: sig-arg
      text: level
    - tag: sig-rest-arg
      text: parts
  ```

### 3.4. Parsing Restrictions

To maintain the declarative nature of signatures, the `sig` sub-parser **must** raise a parse error for the following:

- **Complex Expressions:** `{x: 1 + 2}` is invalid. Only literals and simple paths are allowed as values.
- **Operators:** `{x or y}` is invalid.
- **Duplicate Parameter Names:** `{x, x}` or `{x: 1, x: 2}` is invalid.
- **Positional Arguments After Keyword Arguments:** `{x: 1, y}` is invalid.
- **Multiple Rest Parameters:** `{a..., b...}` is invalid.
- **Rest Parameter Not Last:** `{a..., b}` is invalid.

These restrictions ensure that the `sig` node is a simple, static container of information that the transformer and evaluator can rely on without needing to execute complex code.

### 3.5. Using sig values as metadata arguments

A sig literal is an unevaluated, declarative structure. Beyond function definitions, SLIP uses sig as the canonical way to pass meta-parameters to functions that bind variables dynamically (e.g., `foreach {vars} …`, `for {i} …`). The evaluator passes Sig objects through unchanged; callees inspect `Sig.positional`/`Sig.keywords` to bind names.

---

## Part II: Evaluation and Semantics

This part describes the core logic of the interpreter: how it walks the AST and what each node means. The central theme is that the evaluator is "smart," containing the semantic rules that give the simple AST its meaning.

## Chapter 4: The Evaluation Loop and Scopes

This chapter details the fundamental mechanics of the SLIP runtime: the left-to-right evaluation model and the `Scope` object, which is the cornerstone of the language's variable lookup, object, and type systems.

### 4.1. The Accumulator Model

SLIP's evaluation of a single expression is strictly **left-to-right** and does not use a traditional operator precedence tree. This is managed by an "accumulator" model within the evaluation loop.

- **Principle:** The evaluator processes the terms of an expression one by one. The result of each operation is stored in a temporary variable, the "accumulator," which then becomes the input for the next operation.
- **Implementation:** For any given `ExpressionNode`, the evaluator should maintain an `accumulator` variable, initialized to a special `EMPTY` state.
  1.  Iterate through the child nodes of the expression.
  2.  If the `accumulator` is `EMPTY`, evaluate the current node and store the result in the `accumulator`.
  3.  If the `accumulator` holds a value, the evaluator must inspect the _next_ node in the expression to decide what to do.
      - **If the next node is a `piped-path`** (e.g., `|map`), or a `get-path` that resolves to a `piped-path` (such as `+`, which is typically bound to `|add`), the evaluator triggers an infix call. It resolves the target of the pipe.
        - **"No Double Pipe" Rule:** If the resolved target is _itself_ a `PipedPath` object (e.g., as in `|and`, where `and` is an alias for `|logical-and`), the evaluator must raise a runtime error. This prevents redundant, confusing pipes.
        - If the target is one of the short-circuiting primitives (`logical-and` or `logical-or`), it follows special evaluation rules. For `logical-and`, if the accumulator's value is falsey, that value becomes the result and the next term in the expression is skipped. Otherwise, the next term is evaluated and its result becomes the result. The logic is inverted for `logical-or`.
        - For all other functions, the evaluator performs a standard infix call. It evaluates the _following_ term in the expression to get the second argument, then calls the target function with the accumulator's value and the second argument. The return value is stored back into the `accumulator`.
      - **If the next node is not a path that resolves to a pipe**, this is typically a runtime error (e.g., `1 2`), as the evaluator has an accumulated value but no operation to perform.
- **Final Result:** The final value left in the `accumulator` after processing all terms is the result of the entire expression. If an expression is empty (contains no terms), its result is `none`. The evaluation loop must handle the case where the `accumulator` remains in its initial `EMPTY` state by returning `none`.

**Example Trace for `10 + 5 * 2`:**

1.  `accumulator` is `EMPTY`. Evaluate `10`. `accumulator` is now `10`.
2.  Next term is `+`. This is an infix operator. The evaluator looks up its associated function (`add`).
3.  The following term is `5`. The evaluator calls `add(10, 5)`.
4.  The result is `15`. `accumulator` is now `15`.
5.  Next term is `*`. This is an infix operator. The evaluator looks up its associated function (`mul`).
6.  The following term is `2`. The evaluator calls `mul(15, 2)`.
7.  The result is `30`. `accumulator` is now `30`.
8.  End of expression. The final result is `30`.

### 4.2. The `Scope` Object

The `Scope` is the single, unified data structure for all scopes in SLIP. It is used to represent lexical scopes, function scopes, and user-defined objects (prototypes and instances).

- **Core Structure (Python):**
  ```python
  class Scope:
      def __init__(self, lexical_parent=None):
          # The primary store for user-facing data
          self.data: dict[str, Any] = {}
          # The hidden store for system-level metadata
          self.meta: dict[str, Any] = {"parent": None}
          # The immutable link to the scope where this object was defined
          self.lexical_parent: Scope | None = lexical_parent
  ```
- **Function Safety:** The `scope` primitive function takes a `dict` object for its initial data. The implementation of this function must prevent the user from overwriting the reserved `meta` property during initialization. If the `dict` passed as an argument contains a key named `"meta"`, the function must raise a runtime error.

### 4.3. Lexical Scoping and Path Resolution

All variable and type name lookups in SLIP follow lexical scoping rules. The lookup process is a recursive walk up the `lexical_parent` chain.

- **`get-path` Implementation:** When the evaluator needs to resolve a path (e.g., `my-var`), it must perform the following search:
  1.  Start in the `current_scope`.
  2.  Check if the name exists as a key in `current_scope.data`. If found, return the associated value.
  3.  If not found, move to the `current_scope.lexical_parent`.
  4.  Repeat step 2, walking up the chain until the name is found or the root scope (where `lexical_parent` is `None`) is reached.
  5.  If the name is not found after searching the entire chain, raise a `PathError`. This error should be reported to the host with a `404 Not Found` status code.
- **`set-path` Implementation:** A standard assignment (`my-var: 10`) always sets the value in the **current scope's `.data` dictionary**. It does not modify parent scopes unless the path explicitly uses the `../` parent segment.
- **Parent Segment (`../`):** When a path begins with `../`, the evaluator must first step up to the `lexical_parent` of the current scope before beginning the lookup or assignment. Each `../` corresponds to one step up the chain.

### 4.4. Control Flow Primitives

The core control flow and container constructor functions (`if`, `while`, `foreach`, `list`, `dict`) are host primitives. They do not follow the standard evaluation rule where all arguments are evaluated before the function call. Instead, the evaluator must have special-case logic for them because they conditionally evaluate their `code` block arguments.

- **Scoping Rule:** All control flow primitives execute their `code` blocks in the **current lexical scope**. They do not create a new scope. This means any variable bindings created within a control flow block (including the loop variable in a `foreach`) will be visible in the surrounding scope after the block completes.

- **`list` Implementation:**

  - `list <code-block>` or `#[]`

  1. The evaluator receives a `code` block.
  2. It iterates through each expression in the `code` block.
  3. It evaluates each expression and collects the results into a new `SlipList` object.
  4. The primitive returns the new `SlipList`.

- **`dict` Implementation:**

  - `dict <code-block>` or `#{}`

  1. The evaluator creates a new, temporary `dict` object.
  2. It then executes the provided `<code-block>` using the new `dict` as the evaluation context (similar to `run-with`).
  3. This allows assignment expressions inside the block to populate the new dictionary.
  4. The primitive returns the new, populated `dict`.

- **`if` Implementation:**

  - `if <condition-block> <then-block> <else-block>`

  1.  The evaluator must first `run` the `<condition-block>`.
  2.  If the result is truthy, it must then `run` the `<then-block>` and return its result. The `<else-block>` is **not** evaluated.
  3.  If the result is falsey, it must `run` the `<else-block>` and return its result. The `<then-block>` is **not** evaluated.

- **`while` Implementation:**

  - `while <condition-block> <body-block>`

  1.  The evaluator enters a loop.
  2.  In each iteration, it first `runs` the `<condition-block>`.
  3.  If the result is falsey, the loop terminates. The primitive returns the value of the last expression from the final iteration of the body, or `none` if the loop never ran.
  4.  If the result is truthy, the evaluator `runs` the `<body-block>`. The return value of the body is tracked for the loop's final return value, and the loop continues to the next iteration.
  5.  **Task Yielding:** If the `while` loop is running inside a `task`, it must yield control to the host event loop (`sleep 0`) at the beginning of each iteration to ensure cooperative multitasking.

- **`foreach` Implementation:**
  - `foreach <var-spec: sig> <collection> <body-block>`
    1.  The first argument must be a Sig literal; its positional names (e.g., `["item"]` or `["k","v"]`) form the binding pattern. It is not evaluated.
    2.  Evaluate the collection; iterate; destructure/bind per iteration.
    3.  Run the body Code each iteration; auto‑yield in task contexts.

Note (library helper): `for {i} start end [body]` follows the same convention. The first argument is a Sig literal with one positional name. This keeps meta-parameters uniform and obvious at the call site.

---

## Chapter 5: String Semantics and Interpolation

This chapter details the implementation of SLIP's two string types. SLIP distinguishes between raw strings (single-quoted) and interpolated strings (double-quoted). This distinction is handled by both the parser, which creates different AST nodes, and the evaluator, which applies different semantics to each.

### 5.1. Parser Behavior

The lexer is responsible for the initial differentiation between the two string types. The parser then creates a specific AST node for each.

- **Single-quoted strings (`'...'`):** The lexer should produce a `RAW_STRING` token. The parser will then create a `raw-string` node.
- **Double-quoted strings (`"..."`):** The lexer should produce an `I_STRING` token. The parser will then create an `i-string` node.

The Koine AST for these nodes should be:

- **`raw-string` Node:**

  - **Koine AST:** `tag: raw-string, value: "the raw content"`
  - Contains the literal string content exactly as it appears in the source.

- **`i-string` Node:**
  - **Koine AST:** `tag: i-string, value: "the raw template with {{...}} markers"`
  - **Crucial Rule:** The parser does **not** attempt to parse the content inside the `{{...}}` interpolation markers. It treats the entire string, including the markers, as a single, opaque piece of text. This adheres to the "dumb parser" philosophy and delegates the complex task of interpolation to the evaluator.

### 5.2. Evaluator Behavior

The evaluator must handle the two string node types differently.

#### 5.2.1. Evaluating a `raw-string` Node

This is the simple case. When the evaluator encounters a `raw-string` node:

1.  It retrieves the raw string value from the node.
2.  It applies the automatic de-denting algorithm (see Section 5.3).
3.  It creates a final `str` runtime object with the de-dented content.

#### 5.2.2. Evaluating an `i-string` Node (Templating)

This is a more sophisticated process that relies on an integrated template rendering engine (e.g., a Python implementation of Mustache).

When the evaluator encounters an `i-string` node:

1.  It retrieves the raw string _template_ from the node.
2.  It applies the automatic de-denting algorithm to this template.
3.  It invokes the **template engine's `render` function**, passing it two arguments:
    a. The de-dented string template.
    b. The **`current_scope` object** itself as the rendering context.
4.  The template engine is responsible for parsing the `{{...}}` markers, looking up the paths (e.g., `user.name`) in the provided context, and substituting the values.
5.  The final, fully rendered string returned by the template engine is used to create the final `IString` runtime object.

For this to work, the `Scope` object must be compatible with the template engine's context expectations. This is achieved by implementing Python's mapping protocol.

**Type System Note:** The `IString` class is an internal implementation detail used by the evaluator to signal the need for interpolation. From the perspective of the SLIP type system, it must be treated as a `string`. Any `type-of` or `is-string?` primitive must identify an `IString` object as being of type `` `core.string` ``.

#### 5.2.3. The `Scope` Mapping Protocol Implementation

The `Scope` class must implement the `__getitem__` special method. This method will contain the logic for SLIP's full, lexically-scoped variable lookup.

```python
class Scope:
    # ... (other methods like __init__) ...

    def __getitem__(self, key: str) -> Any:
        """
        Allows the Scope to be used like a dictionary by the template engine.
        This is the core of the variable lookup logic.
        """
        current = self
        while current is not None:
            # 1. Check the current scope's own data.
            if key in current.data:
                return current.data[key]

            # 2. If not found, move to the lexical parent.
            current = current.lexical_parent

        # 3. If not found after searching the entire chain, raise an error.
        # The template engine should catch this and report a missing variable.
        raise KeyError(f"Name '{key}' not found in any scope.")
```

This design is highly efficient as it avoids creating a new, flattened dictionary for every interpolation. It simply passes a reference to the existing scope, guaranteeing that name resolution within a string is identical to name resolution everywhere else in the language.

### 5.3. Automatic De-denting

Both string types support automatic de-denting to allow for clean, indented multi-line strings in the source code.

- **Implementation:** For a Python-based interpreter, this feature should be implemented using the standard library's **`textwrap.dedent`** function. It provides a robust and correct implementation of the required de-denting logic.
- **Behavior:** The `dedent` function's behavior is the canonical requirement for any SLIP implementation. It inspects the string to find the minimum common leading whitespace among all non-empty lines and removes that prefix from every line.
- **Timing:** This de-denting step must be performed by the evaluator on the raw string content from the AST node **before** any other processing (such as interpolation).

---

### Byte stream literals (runtime behavior)

- The evaluator constructs bytes from typed lists:
  - u8/i8 write single bytes (i8 wraps to 0–255).
  - u16/i16, u32/i32, u64/i64 pack little‑endian integers.
  - f32/f64 pack little‑endian IEEE floats.
  - b1 packs bits MSB‑first per byte; the last partial byte is left‑padded.
- `to-str` decodes bytes using UTF‑8 (replacement on errors).
- File I/O: `file://…` writes these bytes verbatim.
- See tests/test_bytestream_literals.py for coverage.

## Chapter 6: Views and the Query Engine

This chapter details the implementation of the Query DSL, which is invoked when a `QuerySegment` (`[...]`) is present in a path. It also describes the "vectorized pluck" operation, a key semantic rule that makes the query system powerful and consistent.

The core principle of the query engine is **lazy evaluation**: a query operation does not immediately filter or slice a collection. Instead, it creates a lightweight `View` object that represents the _promise_ of a future computation.

### 6.1. The Vectorized "Pluck" Operation

Before describing the query engine, we must define a new core semantic rule for the `get-path` primitive. This rule is what makes queries like `players.hp[> 100]` possible.

- **Rule:** When a `get-path` operation with a `.name` segment is applied to a collection (`List` or `Dict`), the evaluator performs a **"pluck" operation**. This rule does not apply to `Scope` objects; property access on a `scope` is always a standard lookup on that object following the property lookup chain (instance, mixins, parent).
- **Implementation:**
  1.  The evaluator iterates through the elements (for a `List`) or values (for a `Dict`) of the source collection.
  2.  For **each item** in the collection, it performs a **full, standard property lookup** for the property specified by the `.name` segment. This lookup must follow the object property lookup chain as defined in Chapter 9.3 (checking the instance's data, then recursively searching its parent chain).
  3.  It collects the resulting values from each lookup into a **new `List`**.
  4.  This new list is the result of the `get-path` operation.

### 6.2. The `View` Object

The `View` is the central data structure of the query engine. It is a lightweight, intermediate object that encapsulates a query before it is executed.

- **Core Structure (Python):**

  ```python
  class View:
      def __init__(self, source: Any, query_path: list):
          # A reference to the original source collection (e.g., a Scope or SlipList).
          self.source = source
          # A list of parsed QueryNode objects, representing the "recipe" for the view.
          self.query_path = query_path

      def __repr__(self):
          return f"<View on {self.source}>"
  ```

- **Immutability:** `View` objects should be immutable. Chaining a new query operation (e.g., `my_view[0]`) does not modify the existing view; it creates and returns a _new_ `View` with the additional operation appended to its `query_path`.

### 6.3. Lazy Evaluation

The `get-path` primitive must be implemented to support lazy evaluation for queries.

- **Rule:** When the path resolver encounters a `QuerySegment` (`[...]`), it does **not** immediately execute the query.
- **Implementation:**
  1.  The resolver first evaluates the path _up to_ the query segment (e.g., `players.hp`). This may trigger a "pluck" operation, resulting in a source collection.
  2.  It then takes the parsed `QueryNode` from the `QuerySegment` (e.g., a `FilterQueryNode`).
  3.  It creates and returns a `View` object, storing the source collection and the `QueryNode` in its `query_path`.
  4.  If the path contains chained queries (e.g., `players.hp[>100][0]`), this process is repeated. The second query operation takes the first `View` as its source and creates a new, chained `View`.

### 6.4. Materialization

A view is "materialized" (i.e., the query is finally executed) only when the evaluator requires a concrete value from it. This happens in specific contexts like an assignment, a function call, or a control flow statement.

- **Implementation:** The `View` object must have a `resolve()` method that the evaluator calls during materialization. This method is responsible for executing the query recipe.
  1.  The `resolve()` method starts with the view's original `source` object.
  2.  It iterates through the `QueryNode`s in its `query_path` list.
  3.  For each `QueryNode`, it applies the corresponding operation (filter, slice, index, or key lookup) to the current intermediate data.
  4.  The final result after all operations have been applied is returned.

Note on filter predicate evaluation

Only dot-prefixed names (.field) resolve against the current item within a filter. Bare names are lexical only. The evaluator normalizes .field to field and rewrites bare names to ../name so evaluation in the item overlay cannot shadow lexical names. If evaluating in the overlay scope fails (e.g., legacy pipeline predicates), the runtime falls back to the historical behavior of evaluating the predicate as a pipeline with the item used as the left-hand side (e.g., [item] + predicate). The older “vectorized pluck then filter” style like players.hp[> 100] is deprecated in favor of object-relative predicates.

### 6.5. Writable Views

The `set-path` primitive must be able to handle a `View` as its target. This enables vectorized assignment.

- **Rule:** A `set-path` operation on a view modifies the original source collection, not the view itself.
- **Implementation:**
  1.  The `View` object needs a `resolve_to_locations()` method. Unlike `resolve()`, this method doesn't return the _values_; it returns a list of "pointers" to the locations in the source data that match the query. A "pointer" could be a `(collection_object, key_or_index)` tuple.
  2.  The `set-path` primitive calls `resolve_to_locations()` on the target view to get the list of locations to modify.
  3.  It then evaluates the right-hand side of the assignment.
  4.  **Broadcast Logic:**
      - If the right-hand side value is a single, non-list value, it iterates through all resolved locations and assigns that same value to each one.
      - If the right-hand side value is a `SlipList`, it must check that its length is equal to the number of resolved locations. If they match, it iterates through both lists simultaneously, assigning the corresponding value to each location. If the lengths do not match, it must raise a runtime error.

## Chapter 7: The Dispatch System

This chapter describes the implementation of SLIP's core calling convention: the multiple dispatch system. All function calls in SLIP are routed through this mechanism. The system is responsible for managing "generic functions," which are containers for multiple method implementations, and for selecting the single, most appropriate method to execute based on the arguments provided at runtime.

### 7.1. `Function` and `GenericFunction`

The dispatch system is built on two object types: `Function` and `GenericFunction`.

- **`Function`:** The result of the `fn` primitive. This is a single closure object that bundles the function's signature, its unevaluated code body, and the lexical scope where it was defined.
- **`GenericFunction`:** A container object that holds one or more `Function` implementations that share the same name. This is the object that is actually bound to a name in a `Scope`.

- **Core `GenericFunction` Structure (Python):**

  ```python
  class GenericFunction:
      def __init__(self, name: str):
          self.name = name
          # A list of all method implementations.
          self.methods: list[Function] = []
          # The metadata for the generic function as a whole.
          self.meta: dict[str, Value] = {}
  ```

- **Creation and Merging by `set-path`:** The `set-path` primitive is responsible for managing these containers. When a `Function` object is being assigned to a path:
  1.  It resolves the path to find what, if anything, is already there.
  2.  If the path holds a `GenericFunction`, it appends the new `Function` to the existing container's `methods` list.
  3.  If the path is empty or holds a non-function value, it creates a **new `GenericFunction`**, adds the `Function` as its first method, and binds the new container to the path.

#### Synthesis from Examples at Assignment

When assigning a `Function` (SlipFunction) without explicit typed annotations but with attached examples (`meta.examples`), `set-path` must synthesize typed methods from those examples before merging into the `GenericFunction`:

- Detect explicit types:
  - If `func.meta['type']` is a `Sig` with keyword annotations, add the method as-is (no synthesis).
- Otherwise, if `func.meta.examples` exists:
  - Only keyworded examples are used for synthesis. Each example `Sig` with keywords produces one method:
    - For each declared parameter name (from the function’s `Sig` positional names; or legacy `Code` args), find the matching example keyword entry.
    - Evaluate the example’s value spec in the function’s closure; if not found, in the current scope.
    - Infer a primitive type name from the evaluated value using the standard mapping (`int`, `float`, `string`, `i-string`, `list`, `dict`, `scope`, `function`, `code`, `path`, `boolean`, `none`). Unknowns fall back to `string`.
    - Build a typed `Sig` containing only keyword annotations `{param: `type-name`}` in the original parameter order, with no rest.
    - Clone the function (same args/body/closure), set `clone.meta['type']` to the new `Sig`, and keep `clone.meta['examples'] = [that example]` for test discovery.
  - If at least one clone is produced, merge only those clones into the `GenericFunction` (do not add the original untyped function).
  - If no clones are produced (e.g., no usable keyword examples), fall back to adding the original untyped function.

Notes:

- Positional-only examples (e.g., `{x, y -> want}`) are not used for synthesis; they remain for documentation/testing.
- Container-level examples (attached to the `GenericFunction`) are not synthesized; they are discovered by the test runner only.

### 7.2. The `DispatchRule` (Internal Representation)

While not a user-facing concept, the interpreter should pre-process each method's signature into a more efficient internal form for applicability and scoring. This can be done when the method is first added to the `GenericFunction`.

Core structure (Python-ish shape):

- `method`: a reference to the SlipFunction
- `arity`: the total number of fixed (non-rest) parameters
- `compiled_sig`: pre-compiled per-parameter annotations suitable for fast checks, e.g.:
  - For scope annotations: a record identifying the scope object to match and its precomputed “family” (prototype/mixin closure) if helpful.
  - For primitive annotations: a record identifying the primitive name (int, float, string, …).
  - For unions/conjunctions: nested compiled items.
- `guards`: the list of guard Code blocks (if any)

Note: The compiled form is not a score; it only encodes what the annotation means so we can:

- run the applicability check quickly (all required types present in the argument’s family), and
- build the coverage fraction for that parameter during scoring:
  coverage_j = size(signature_family_for_param_j) / size(argument_family_for_arg_j)

### 7.3. The Dispatch Algorithm (Applicability + Lexicographic Scoring)

#### 7.3.1 Candidate Collection (Applicability Gates)

For each method in the generic function:

1. Arity gate

- Partition methods by whether the call’s argument count matches the method’s fixed arity (exact tier) or is ≥ fixed arity when rest is present (variadic tier).
- Consider only the highest-preference tier that has any candidates (exact over variadic). If neither tier has candidates, fall back to untyped methods if your implementation supports them; otherwise “No matching method”.

2. Type/annotation applicability

- For each explicitly typed, non-variadic parameter:
  - Resolve the annotation to its “required types” (scope(s), primitives, or union/conjunction thereof).
  - Compute the argument’s family set (for scopes: the set containing the instance, its ancestors, all mixins and their ancestors; for primitives: a singleton identifying the primitive).
  - The parameter is applicable iff all required types for that parameter are present in the argument’s family set (unions are satisfied if any branch is applicable).
- If any typed parameter is inapplicable, the method is not a candidate.

3. Guards

- If the method has guard blocks, evaluate them (once) with parameters bound. If any guard is falsey, the method is not a candidate.

All methods that pass these gates form the candidate set for scoring.

#### 7.3.2 Scoring and Selection (Lexicographical Score Vectors)

For each candidate method, build a Score Vector V of length equal to the number of call arguments. For index j:

- If parameter j is explicitly typed and non-variadic:
  - Let S_j be the signature family for parameter j (union of family sets for all required types in that position, de-duplicated).
  - Let A_j be the argument’s family set for the j-th argument.
  - The coverage fraction is:
    coverage_j = |S_j| / |A_j|
- If parameter j is untyped or covered by the variadic rest, define coverage_j = 0.0

Compare candidates by their Score Vectors lexicographically, left-to-right:

- At the first index k where vectors differ, the candidate with the greater coverage_k wins.
- If all positions are equal, proceed to tie-breaking.

This vector-based, lexicographic comparison is stable and fair: a change to later arguments (e.g., adding an unrelated mixin) does not affect the outcome if an earlier argument already distinguishes the candidates.

Example:

- [1.0, 0.5] beats [0.25, 1.0] because 1.0 > 0.25 at position 0; later positions do not matter.

Note: This scoring is identical to the Language Reference’s “Lexicographical Vector Comparison” (Chapter 6.3 and Appendix D). Implementers should verify test cases using that spec’s examples.

#### 7.3.3 Tie-Breaking

If two or more candidates have identical Score Vectors:

1. Guarded over plain

- Prefer the candidate that has guard(s) over candidates without guards.

2. Greater detail (signature specificity)

- Prefer the candidate with the larger total count of required types across all parameters (e.g., conjunctions contribute more detail than single types).

3. Larger signature family size

- Prefer the candidate whose union of signature families across all parameters is larger.

4. Final resolution

- If a tie still remains, raise “Ambiguous method call”.

#### 7.3.4 Worked Example (Lexicographic Comparison)

Call: interact my_player my_weapon

Methods:

- A: fn {p: Player, i: Item}
- B: fn {b: Being, w: Weapon}

Assume family sizes:

- Player family size = 4 (e.g., Player, Character, Being, Object)
- Being family size = 4
- Item family size = 2 (Item, Object)
- Weapon family size = 2 (Weapon, Item)

Score vectors:

- A: [|{Player,...}|/|A_p|, |{Item,...}|/|A_i|] = [4/4, 2/2] = [1.0, 1.0] (or [1.0, 0.5] if Item family is 1 of 2; adjust per your family definition)
- B: [|{Being,...}|/|A_p|, |{Weapon,...}|/|A_i|] = [1/4, 2/2] = [0.25, 1.0]

Compare lexicographically:

- First elements: 1.0 vs 0.25 → A wins immediately.

Add unrelated mixin IsLegendary to the weapon (weapon family size increases):

- A: [4/4, 1/3] = [1.0, 0.33]
- B: [1/4, 2/3] = [0.25, 0.66]

Compare again:

- First elements: 1.0 vs 0.25 → A still wins. Outcome is stable.

---

## Part III: The Object Model

This part describes the implementation of the high-level semantics of SLIP's object-oriented features. The core of the system is the "christening" process, where the simple act of assigning a `scope` or `sig` to a name gives it a formal identity within the type system.

## Chapter 8: Type Creation and Registration

This chapter details the "magic under the hood" that powers SLIP's dynamic type system. The central principle is that **assignment creates identity**. The `set-path` primitive is not just a simple binding operator; it is the primary engine for registering new types and type aliases.

### 8.1. The "Christening" Process

A `scope` object created in isolation (e.g., on the right-hand side of an expression, or as a return value) is "anonymous." It does not represent a formal type. It is "christened" as a type the first time it is assigned to a named path. This process is the responsibility of the `set-path` primitive.

- **Trigger:** The `set-path` logic must check if the value being assigned is an instance of `Scope`.
- **Condition:** The christening process only runs if the `Scope` object has not _already_ been christened. The implementation must check for the absence of a `"type_id"` key in the scope's `.meta` dictionary.
- **Implementation Steps:** If the trigger and condition are met, `set-path` must perform the following actions **before** the final assignment:
  1.  **Resolve Canonical Path:** Determine the fully-qualified, absolute path of the assignment target. For a top-level assignment `Character: ...` in a file `/game/character.slip`, the canonical path would be `"/game/character.Character"`.
  2.  **Generate `TypeID`:** Request a new, unique integer from the interpreter's global `TypeID` generator.
  3.  **Populate Metadata:**
      - Set `value.meta["name"]` to a `SlipString` containing the canonical path.
      - Set `value.meta["type_id"]` to a `SlipInt` containing the new `TypeID`.
  4.  **Update Global Registry:** Add a new entry to the interpreter's `global_type_registry`, mapping the canonical path string to the new `TypeID` integer.

**Example Trace for `Character: scope #{}`:**

1.  `set-path` is called for the target `Character`.
2.  The `scope #{}` expression is evaluated, creating a new, anonymous `Scope` object.
3.  `set-path` checks the object. It is a `Scope` and its `meta` store has no `"type_id"`.
4.  The canonical path is resolved to `"/main.Character"`.
5.  A new ID, e.g., `101`, is generated.
6.  The `Scope`'s metadata is updated: `meta["name"] = "main.Character"`, `meta["type_id"] = 101`.
7.  The global registry is updated: `global_type_registry["/main.Character"] = 101`.
8.  Finally, the name `Character` in the current scope is bound to this newly christened `Scope` object.

### 8.2. Type Aliases

A type alias is a name that refers to a `Signature` object (which represents a type union). The process for creating an alias is a simpler form of assignment.

- **Mechanism:** The user writes a standard assignment expression, `MyAlias: {type1, type2}`.
- **`set-path` Logic:** The `set-path` primitive evaluates the right-hand side, which results in a `Signature` object. It then simply binds the name `MyAlias` to this object in the current scope's `.data` dictionary.
- **No Registration:** Unlike with `scope`s, no `TypeID` is generated for a `Signature` alias. The alias is simply a named reference to the signature object itself. The dispatcher is responsible for resolving this alias at definition time and compiling a rule based on the `TypeID`s of the _members_ of the signature.

### 8.3. Shadowing

The implementation of shadowing requires no special logic. It is a natural consequence of SLIP's lexical scoping rules.

- **Principle:** Type name resolution is standard lexical variable lookup performed within the function's definition scope.
- **Implementation:** To resolve a type annotation (e.g., the `Character` in `fn {x: Character}`), the dispatcher performs a **lexical lookup** for that name. This lookup **MUST** start in the function's closure (the `closure` property of the `Function` object) and walk up the parent chain from there. This ensures that a function's meaning is fixed when it is defined and does not change based on where it is called.
- **Timing:** This resolution can happen eagerly (at definition time, as suggested in Chapter 7.2) or lazily (at dispatch time). The crucial rule is that the lookup context is always the function's definition scope.
- **Effect:** If a scope defines a name `Component` that is also defined in an outer scope, any function defined _within_ that scope will resolve `Component` to the inner definition. The outer `Component` is shadowed. This ensures that type resolution correctly and automatically respects lexical shadowing.

---

## Chapter 9: Inheritance and Composition

This chapter details the implementation of the two primitives that allow users to build complex objects from simpler parts: `inherit` and `mixin`. These two functions provide distinct mechanisms for two different user intents. `inherit` is for establishing an object's single, foundational identity, while `mixin` is for layering on additional, modular capabilities.

### 9.1. The `inherit` Primitive

The `inherit` function is responsible for setting an object's single, primary prototype. It establishes the "is-a" relationship.

- **Signature:** `inherit (target: scope, parent: scope)`
- **Core Logic:** The implementation of the `inherit` primitive must adhere to the **"inherit-once" rule**.

  1.  **Check for Existing Parent:** The function must first inspect the `target` scope's `meta` dictionary. It should check if the value associated with the key `"parent"` is `None` (or the equivalent null value).
  2.  **If a parent already exists** (i.e., the value is not `None`), the function must raise a runtime `InheritanceError`. This should be reported as a `500 Internal Error`.
  3.  **If no parent exists,** the function sets `target.meta["parent"]` to be a reference to the `parent` scope object.
  4.  The function should return the modified `target` object to allow for chaining.

- **`create` Helper:** The standard library `create` helper function is the primary user-facing entry point for this primitive. Its implementation is a simple composition:
  ```slip
  create: fn {prototype} [ (scope #{}) |inherit prototype ]
  ```
  The `create` function first constructs a new, anonymous `scope` and then immediately calls the `inherit` primitive on it.

### 9.2. The `mixin` Primitive

The `mixin` function is responsible for composing an object by establishing live links to other `scope` objects. It establishes the "has-a" or "can-do" relationship. This is a reference-based operation, not a copy.

- **Signature:** `mixin (target: scope, source1: scope, source2: scope, ...)`
  - The function must accept one `target` `Scope` and one or more `source` `Scope` objects. It should raise a `TypeError` if a non-`Scope` object is provided as a source.
- **Core Logic:** The implementation adds references to the source scopes into the target's metadata.
  1.  The function must ensure a list named `"mixins"` exists in the `target` scope's `meta` dictionary.
  2.  For each `source` scope provided in the arguments, append a reference to it to the `target.meta["mixins"]` list.
  3.  The order of mixins is significant and must be preserved, as it defines the property lookup order.
- **Important Note:** The `mixin` function does **not** copy any data. It modifies the target's metadata to create a dynamic link that is resolved at property-lookup time.

### 9.3. The Property Lookup Chain

The evaluator's `get-path` primitive must be implemented to respect the full object-oriented lookup chain, which includes mixins. When resolving a property on a `Scope` object (either directly or as part of a "pluck" operation), the search must be performed in this precise, recursive order:

1.  **Instance `data`:** Check for the key in the object's own `.data` dictionary. If found, return the value immediately.

2.  **Mixins Chain:** If the key is not found, check if the object has a `meta.mixins` list.

    - If it does, iterate through the mixin `scope`s in that list **in the order they were added**.
    - For each mixin, perform a **recursive `get-path` call** on the mixin object itself.
    - If this recursive call finds a value, return that value immediately. The search does not proceed to subsequent mixins or the parent.

3.  **Parent Chain:** If the key is not found in the instance's `data` or any of its mixins, check the `meta.parent` property.
    - If `meta.parent` refers to a `Scope` object, perform a **recursive `get-path` call** on that parent object.

If the property is not found after searching the entire chain (instance, mixins, and parents), the lookup for that property fails, and the evaluator must raise a `PathError`. This behavior is identical to the failure mode for lexical variable lookup, providing a consistent error model.

## Chapter 10: The `example` Helper and Implicit Typing

This chapter details the implementation requirements for the `example` standard library helper function and the compiler/JIT features it enables. The `example` function is not a primitive; it is a standard library function with special significance to the toolchain (test runners and compilers).

### 10.1. The `example` Function Implementation

The `example` function itself is a simple metaprogramming utility.

- **Signature:** `example (target: Function|GenericFunction, example_sig: sig)`
- **Behavior:** Appends `example_sig` to `target.meta.examples` (or, for a `GenericFunction`, to the container’s meta). Returns the original target to allow chaining. The runtime will synthesize typed methods from method-level examples at assignment time as described in 10.4.
- **Core Logic:**
  1.  The function receives a `target` object, which must be a `Function` (the result of an `fn` call).
  2.  It also receives an `example_sig` object, which is a `Signature` containing the concrete example.
  3.  The function accesses the target's metadata store (`target.meta`).
  4.  It ensures a list named `"examples"` exists in the metadata (`target.meta.setdefault("examples", SlipList())`).
  5.  It appends the `example_sig` to this `"examples"` list.
  6.  It must return the original `target` object to allow for the `|example` chaining pattern.

### 10.2. The `guard` Helper Function

The `guard` helper is a metaprogramming utility that attaches a conditional predicate to a specific `Function` implementation. The dispatch system will only consider the function as a candidate for a call if its guard condition evaluates to a truthy value.

- **Signature:** `guard (target: Function, condition_block: code)`
- **Core Logic:**
  1.  The function receives a `target` object, which must be a `Function` (the result of an `fn` call).
  2.  It also receives a `condition_block`, which is a `code` object containing the predicate expression.
  3.  The function accesses the target's metadata store (`target.meta`).
  4.  It ensures a list named `"guards"` exists in the metadata (e.g., `target.meta.setdefault("guards", SlipList())`).
  5.  It appends the `condition_block` to this `"guards"` list.
  6.  It must return the original `target` object to allow for the `|guard` chaining pattern.

This mechanism is the foundation of value-based dispatch and allows for highly expressive and declarative conditional logic, as detailed in the dispatch algorithm in Chapter 7.

### 10.3. The Test Runner's Responsibility

A standard SLIP test runner tool must be implemented with the following logic:

1.  It should be able to discover all functions and prototypes within a given file or project.
2.  For each discovered object, it must inspect its `meta.examples` list.
3.  For each `sig` object found in the list, it must:
    - Extract the input arguments (from the `positional_args` and `keyword_args` of the `sig`).
    - Extract the expected return value (from the `return_annotation` of the `sig`).
    - Execute the function with the extracted input arguments.
    - Compare the actual return value with the expected return value.
    - Report a pass or failure.

The test runner discovers examples from both method-level `meta.examples` and container-level (`GenericFunction`) `meta.examples`. It evaluates example argument and expected value expressions in the caller’s scope by default (falling back to a method’s closure for paths and code), then calls the function and compares the actual result to the expected value. The runner does not create or register methods; synthesis happens at assignment time (see 10.4).

### 10.4. Runtime Synthesis from Examples (Implicit Typing)

The interpreter upgrades untyped methods at definition time, using examples to create typed implementations:

- Trigger: On assigning a `Function` to a name, if it has no explicit typed keywords in its `Sig` but has `meta.examples`, the runtime generates one typed implementation per keyworded example and merges those into the `GenericFunction`.
- Source of truth: Example values are evaluated (closure first, then current scope), and their runtime types are mapped to primitive annotation names using the same mapping as `type-of` and dispatch checks.
- Granularity: No unification across examples is performed. Each example produces a separate typed variant (e.g., `{int,int}`, `{float,float}`, `{int,float}`, …). Coverage is explicit; missing combinations do not dispatch.
- Constraints: Only keyworded examples participate in synthesis. Positional-only examples do not.
- Fallback: If synthesis yields no typed variants, the original function is added untyped.

Future optimization (optional): A compiler/JIT may still unify across examples to produce union annotations for specialization. This is not required for correctness and does not change runtime dispatch semantics.

---

## Part IV: Advanced Evaluation Semantics

This part covers specialized evaluation rules that are handled by specific primitives, extending the core evaluation loop with powerful metaprogramming and asynchronous capabilities.

## Chapter 11: Metaprogramming and `run`

This chapter details the implementation of SLIP's runtime metaprogramming features, which are centered on the `run` primitive and its handling of the special `inject` and `splice` forms. While SLIP does not have a compile-time macro system, `run` provides a powerful "macro expansion" phase just before evaluation.

### 11.1. The `run` Primitive

The `run` primitive executes a Code block. In the common case, Code created from an inline literal was already expanded at definition time and is executed as-is. If a Code value was created outside the evaluator (e.g., parsed from file:// or built by a tool), `run` will expand it first (only when needed), and then execute it.

- Expansion: If the Code has not been expanded yet, `run` invokes `Evaluator._expand_code_literal(code, caller_scope)` to resolve inject/splice using the caller’s lexical scope, producing a list of expressions.
- Execution: `run` evaluates those expressions in a hermetic sandbox whose parent is the root scope; writes in the block do not leak to the caller.

The `run-with` variant behaves analogously (see 11.2 for expansion rules and 10.4 for execution semantics): it expands unexpanded Code using the caller’s scope, and then executes the expressions in the provided target scope (writes go to the target). A temporary link to the caller scope may be used to resolve operators/names; it is removed afterward.

### 11.2. Expansion Semantics for `inject` and `splice`

SLIP performs a single, unified expansion for inject/splice via `Evaluator._expand_code_literal`. Expansion happens at one of two times, depending on how the Code object was created:

1) Definition-time expansion (the default)
   - When the evaluator encounters an inline Code literal (`[...]`), it immediately calls `Evaluator._expand_code_literal(code, current_scope)` to produce a pure list-of-expressions and returns a new `Code` value marked as expanded (e.g., `code._expanded = True`).
   - This is the normal, lexical expansion rule: inject/splice resolve against the current lexical scope at the point where the code literal is defined.

2) Execution-boundary expansion (fallback for externally created Code)
   - If a Code value is created outside the evaluator (e.g., by parsing a `.slip` file via `file://`), it will not have been expanded yet.
   - `run` and `run-with` detect this case (by checking the marker) and, only then, expand the Code before executing it:
     - `run`: calls `Evaluator._expand_code_literal(code, caller_scope)`, then evaluates the resulting expressions in a hermetic sandbox whose parent is the root scope.
     - `run-with`: calls `Evaluator._expand_code_literal(code, caller_scope)`, then evaluates the expressions in the provided target scope; writes go to the target. Expansion uses the caller’s scope, not the target.

Semantics of the forms:
- inject: `(inject X)` evaluates `X` in the expansion scope (see above) and substitutes the resulting value verbatim into the AST.
- splice:
  - In expression position: `(splice X)` requires `X` to evaluate to a list; its elements are spliced into the surrounding argument list.
  - As a standalone statement: `(splice X)` accepts a list or a Code; its contents are spliced in as sibling expressions in the surrounding block.

Implementation hooks:
- The single expander is `Evaluator._expand_code_literal`.
- Inline Code literals are expanded by the evaluator and marked with a private `_expanded` flag.
- `StdLib._run` and `StdLib._run_with` expand only when the flag is not present/true, using the caller’s scope. They then iterate the expanded expressions for execution.
- The legacy runtime-time preprocessor has been removed; `StdLib._preprocess_code_for_run` no longer exists.

## Chapter 12: Asynchronous Execution (`task`)

This chapter details the implementation requirements for SLIP's core concurrency primitive, `task`. The entire SLIP interpreter is designed to be a non-blocking component within a larger asynchronous host application (like one built on Python's `asyncio`).

### 12.1. The `task` Primitive

The `task` primitive is the user's entry point into concurrency. It does not execute its code block synchronously.

- **Signature:** `task <code-block>`
- **Core Logic:**
  1.  When the evaluator encounters a `task` call, it does **not** `run` the `<code-block>` immediately.
  2.  Instead, it must call a method on the host system, something like `host.schedule_task(code_block_ast, current_scope)`.
  3.  The `host` is responsible for wrapping the execution of this code block in an asynchronous task (e.g., using `asyncio.create_task` in Python) and adding it to its event loop. The execution of the `code_block_ast` must be done using a new instance of the evaluator's main `run` or `eval` method, and it must be executed within the `current_scope` that was passed along.
  4.  The `task` primitive itself immediately returns a handle to the newly created task. This handle is an opaque object provided by the host.

### 12.2. Host Responsibilities: Task Management

The host application has a critical role in managing the lifecycle of tasks.

- **Registration:** The `SLIPHost` base class must maintain a list of active tasks associated with that specific host object instance. When the host's `schedule_task` method is called, it should add the newly created task to this list.
- **Cancellation:** The `SLIPHost` must provide an API method (e.g., `cancel_tasks`) that iterates through its list of registered tasks and cancels them. This is essential for cleanup when a game object is destroyed or a player logs out, preventing orphaned tasks from running.

### 12.3. Automatic Yielding in Loops

To ensure cooperative multitasking and prevent a single script from freezing the host application, the `while` and `foreach` primitives must have a special behavior when running inside a task.

- **Context Check:** The evaluator must maintain a flag, `is_in_task_context`, which is set to `true` when evaluating code scheduled by the `task` primitive.
- **Implementation in `while` and `foreach`:**
  - At the beginning of each iteration, both the `while` and `foreach` loop implementations must check the `is_in_task_context` flag.
  - If the flag is `true`, the loop must `await` a call to a host-provided `yield_control()` function (which would typically be implemented as `asyncio.sleep(0)` in Python).
  - This brief pause returns control to the host's event loop, allowing other tasks to run before the loop continues.

This automatic yielding is a critical safety feature and a non-negotiable part of the `task` implementation.

### 15.5. do: Structured Capture of Outcome and Effects

The do primitive wraps the execution of a code block, capturing the emitted events and returning them alongside a normalized outcome.

API:

- do <code> → returns a dict-like object with:
  - outcome: Response(PathLiteral(`ok|err|...`), value)
  - effects: list of events emitted during the run

Algorithm (host/runtime reference):

1. Validate/resolve argument to a Code object.
2. Record the current length of evaluator.side_effects (start index).
3. Execute the block via evaluator.\_eval(code.ast, scope):
   - On successful completion:
     - If the result is a Response:
       - If it is a return response (status == `return`):
         - If inner value is a Response, outcome := inner.
         - Else outcome := response ok inner.
       - Else outcome := the response as-is.
     - If the result is not a Response, outcome := response ok result.
   - On exception:
     - outcome := response err "<message>" (message is the raised error’s string).
4. effects := copy of evaluator.side_effects[start:].
5. Return a new dict-like object (e.g., SlipDict) with keys "outcome" and "effects".

Notes:

- do does not remove entries from the global side_effects list; it returns a snapshot slice of the events generated during the wrapped execution only.
- The block runs in the current lexical scope; any writes inside the block affect that scope just like a normal run.

## Appendix A: Abstract Syntax Tree (AST) Reference

This appendix provides a formal reference for the structure of the Abstract Syntax Tree (AST) that the SLIP parser generates. The evaluator's behavior is driven by the tags and structure of these nodes. The fundamental structure is a "tagged list," where the first element is a string that identifies the node's type.

Note on notation
- In examples, <type value> (e.g., <number 10>) represents literal value tokens like numbers and user-facing strings.
- Structural parts of the AST are represented as tagged lists like [tag ...].
- For brevity, the literal string or number values inside path components (e.g., the 'user' in [name 'user'] or the 5 in [slice 5 10]) are shown directly.

### Expressions and Code

An expression is represented by a list tagged with expr. A code block is tagged with code. The difference is that the evaluator executes an [expr ...] immediately, while a [code ...] is treated as a literal value.

- Source: (add 1 2)
  - AST: [expr [get-path [name 'add']], <number 1>, <number 2>]

- Source: [add 1 2]
  - AST: [code [expr [get-path [name 'add']], <number 1>, <number 2>]]
  - Note: A code block contains a list of zero or more expr nodes. An empty code block is valid.

### Container Literals

- Source: #[1, 2] (List)
  - AST: [list <number 1>, <number 2>]
  - The evaluator processes this by evaluating each element and collecting the results into a list object.

- Source: #{ a: 1 } (Dictionary)
  - AST: [dict [expr [set-path [name 'a']], <number 1>]]
  - The evaluator executes the expressions inside a new dict-like object and returns it.

- Source: { a: int } (Signature)
  - AST: [sig [sig-kwarg [sig-key 'a'] [get-path [name 'int']]]]
  - The sig block is not evaluated; it is parsed into a literal sig data structure.

### Paths and Assignment

Paths and assignment patterns are represented by distinct AST nodes.

#### The get-path Node (for Reading)

- AST Structure: [get-path <segment1>, <segment2>, ..., configuration: [dict ...]]
- configuration: An optional dictionary-like structure parsed from a #(…) suffix for transient options.
- Segments:
  - [root]: leading /
  - [name '...']: dot- or slash-separated name
  - [query-segment …]: bracketed query (index/key, slice, filter)
  - [parent]: ../
  - [group …]: dynamic segment (…)

Examples:
- Source: user.name
  - AST: [get-path [name 'user'], [name 'name']]

#### The piped-path Node

- AST Structure: [piped-path <segment1>, <segment2>, ...]
- Segments: same as get-path
- Source: |user.name
  - AST: [piped-path [name 'user'], [name 'name']]

#### The set-path Node (for Writing)

- Simple assignment like user.name: "John" is parsed as a set-path node, which the transformer converts into a SetPath object before evaluation.
  - Segments: same as get-path
  - configuration: optional #(…) block, same semantics as for get-path
  - Source: user.name: "John"
  - AST passed to evaluator: a SetPath object and a string value

- Destructuring: [a, b]: #[10, 20] is parsed as a multi-set path and converted into a MultiSetPath object before evaluation.
  - AST passed to evaluator: a MultiSetPath object and a List object

### Query Segments (Structure Recap)

Parsing precedence inside [...] must try:
1) slice-query before
2) filter-query before
3) simple-query

- Slice Query
  - Source: [1:4], [:end]
  - AST: [query-segment [slice-query [start-expr [expr …]] [end-expr [expr …]]]]

- Filter Query
  - Source: [> 100], [= "active"]
  - AST: [query-segment [filter-query [operator '>'] [rhs-expr [expr …]]]]

- Index/Key Query
  - Source: [0], ["name"], [my-variable]
  - AST: [query-segment [simple-query [expr …]]]

### Group Segment

Groups can appear as a path segment for dynamic access:
- Source: user.(get-key).name
- AST fragment:
  - [group [expr [get-path [name 'get-key']]]]

### Configuration Segment

The #( … ) block immediately following a path is represented as a meta/configuration child on the path node and is not part of the segment list.

- Source: a/b#(timeout: 2)
- AST: [get-path [name 'a'], [name 'b'], configuration: [dict …]]

Notes
- The SLIP transformer normalizes these parser nodes into the runtime datatypes (GetPath, SetPath, DelPath, PipedPath, MultiSetPath, Group, Index, Slice, FilterQuery, PathLiteral, etc.) before evaluation.
- See Part I (Parsing and Transformation) for how Koine AST nodes map to runtime datatypes and how subgrammars are wired.
