# SLIP Scripting

This guide is a quick, hands-on introduction to SLIP.

It is organized around the next practical question in the programmer's mind. Start at the top and stop as soon as you know enough to do your work.

By the end, you will be able to:
- Run a script from a file.
- Read JSON from `file://` or `http://`.
- Filter and reshape data with the Query DSL.
- Write transformed results back to disk.
- Handle errors gracefully.

---

## How do I write and run a SLIP script?

The first useful thing to know is that a SLIP script is just a sequence of expressions in a file.

Here is a complete script:

```slip
name: "Karl"
hp: 120

print "{{name}} has {{hp}} HP"

hp
```

This script:

- binds two names
- emits one line of output with `print`
- returns the value of the last expression

### Run a script file

```bash
uv run python slip.py my-script.slip
```

When you run a script file, SLIP evaluates the file from top to bottom.

### Start the REPL

```bash
uv run python slip.py
```

The REPL is useful when you want to try small expressions before writing a full script.

### What a script is made of

SLIP is intentionally small:

- everything is an expression
- there is no operator precedence
- control flow is mostly regular function calls over code blocks

This guide is about the fast path: read data, transform it, write it back, and handle failures without learning the whole language model first.

### Takeaway

To get started, think of a SLIP script as:

- a file full of expressions
- evaluated in order
- with the final expression becoming the script's result

The next thing to learn is the most important rule for reading those expressions: how evaluation works.

## How do expressions evaluate?

The next thing most readers need to know is how to read a line of SLIP correctly.

SLIP evaluates infix operators strictly left-to-right.

```slip
-- In most languages:
10 + 5 * 2 = 10 + 10 = 20

-- In SLIP:
10 + 5 * 2 = 15 * 2 = 30
```

Use parentheses `(...)` when you need a grouped sub-expression:

```slip
result: 10 + (5 * 2) -- 20
```

You can also separate multiple expressions on one line with `;`:

```slip
a: 1; b: 2
```

### Takeaway

Read SLIP exactly in the order it appears on the page.

- no hidden precedence rules
- parentheses mean "do this first"
- semicolons let you put more than one expression on a line

---

## How do I work with values and data?

Most scripts start by binding some values, shaping a little data, and moving on.

Comments use `--` for single lines and `{-- ... --}` for block comments.

### Numbers, booleans, none

```slip
count: 3
ratio: 0.75
enabled: true
missing: none
```

### Strings

SLIP has two string types:

- **raw strings**: single quotes, no templating: `'...'`
- **i-strings**: double quotes, specify templates: `"Hello {{name}}"`

```slip
name: "Karl"

msg: "Hello {{name}}"
path: '/tmp/data.json'
```

Multi-line i-strings are automatically de-dented:

```slip
greeting: "
    Hello {{name}}!
    Welcome back.
"
```

### Lists and dicts

The two most common data structures are lists and dicts.

```slip
nums: #[ 10, 20, 30 ]
player: #{ name: "Karl", hp: 120 }

#[ nums[0], player.name ]
```

### Takeaway

For basic scripting, the values to reach for first are:

- numbers
- booleans
- strings
- lists
- dicts

The next step is learning how to call functions and put those values through control flow.

---

## How do I call functions and use control flow?

Once you have values, the next question is how to do work with them.

### Function calls

Calls are space-separated (no commas):

```slip
-- The following returns 30
add 10 20  
```

### The pipe `|`

The pipe passes the value on the left as the first argument:

```slip
-- Returns 30
10 |add 20 
-- Also returns 30
10 |add 5 |mul 2
```

### Defining functions with `fn`

You define a function using a signature `{...}` and a body `[...]`:

- `{...}` is a **sig literal**: it declares parameters rather than evaluating them
- `[...]` is a code block: it is passed as code and run by `fn`

```slip
add-ten: fn {n} [
    n + 10
]
```

Call it:

```slip
result: add-ten 5
```

### Code blocks

A `[...]` block is a **code value** (unevaluated code). Control-flow functions decide when to run it.

### `if`

`if` takes:
- a condition block
- a then block
- an optional else block (if omitted, `if` returns `none` when the condition is falsey)

```slip
hp: 40

status: if [hp > 50] [
    "Healthy"
] [
    "Wounded"
]
```

### `while`

```slip
i: 3
while [i > 0] [
    print i
    i: i - 1
]
```

### `foreach`

`foreach` takes a **sig literal** for the loop variable pattern.

This is the same idea as `fn {args} [...]`: the `{...}` part tells SLIP what names to bind, not what values to compute.

```slip
items: #[ "Sword", "Shield", "Potion" ]
foreach {item} items [
    print "You have a {{item}}"
]
```

Tip: for dicts, `{k}` iterates keys; `{k, v}` iterates key/value pairs.

### Takeaway

The common pattern is:

- call functions with spaces
- pipe values when it reads more naturally
- use `fn` to define reusable behavior
- pass code blocks to control-flow functions like `if`, `while`, and `foreach`

---

## How do I query and update collections?

The next thing most scripts want to do is pull specific data out of a list or update matching items.

You can index, slice, filter, and “pluck” with path syntax.

### Filtering lists with `[ ... ]`

Inside a filter predicate:

- `.field` means “field on the current item”
- bare names are lexical variables from outside the list

```slip
players: #[
    #{ name: "Karl",  hp: 120 },
    #{ name: "Jaina", hp: 45  }
]

wounded: players[.hp < 50]
names: wounded.name
```

### Pluck (vectorized field access)

If you do `.name` on a list of dicts/scopes, you get a new list of names:

```slip
names: players.name -- #["Karl", "Jaina"]
hps: players.hp     -- #[120, 45]
```

Note: for lists, filters and plucks return normal (eager) lists in the current interpreter.

### Build new data vs update in place

When transforming JSON, you’ll usually use one of these patterns:


- **Build a new value** when you want a clean transformed result
- **Update in place** when you want to change the existing data directly

### Build a new list or dict

This pattern reads from an input list and constructs a new list of output rows.

```slip
players: #[
    #{ name: "Karl",  hp: 120 },
    #{ name: "Jaina", hp: 45  }
]

wounded: players[.hp < 50]

wounded-report: #{
    count: len wounded,
    names: wounded.name
}
```

### Update in place

If a query appears on the left side of an assignment, SLIP can update multiple items.

Assignment is an expression: it returns the value it wrote. For vectorized updates, it returns the list of new values written to the matched targets.

Example: boost HP for players with HP < 50:

```slip
players: #[
    #{ name: "Karl",  hp: 120 },
    #{ name: "Jaina", hp: 45  }
]

players.hp[< 50]: * 1.1
```

The “filter then pluck” version is equivalent:

```slip
players[.hp < 50].hp: * 1.1
```

### Takeaway

For collection work, the usual progression is:

- filter with `[...]`
- pluck with `.field`
- either build a new result or update matching values in place

---

## How do I read files and HTTP data?

This is the core scripting workflow: load data, reshape it, and save it again.

### Read from a file (`file://`)

The file extension controls parsing for structured formats:

- `.json` → JSON
- `.yaml` / `.yml` → YAML
- `.toml` → TOML

```slip
data: file://input.json
```

### Bind first, then query

In the current interpreter, **you cannot filter/pluck directly on the same `file://...` or `http://...` expression**.

This is illegal:

```slip
-- ❌ does not work (scheme GETs can't include a trailing query)
names: file://input.json[0]
```

Rule: with `file://...` and `http://...`, **bind first, then query**. Don’t attach `[...]` or `.field` directly to the scheme path; always query the bound value.

```slip
data: file://input.json
names: data.players.name
```

### Read from HTTP (`http://` / `https://`)

```slip
resp: http://api.example.com/players.json
```

Again: bind first, then query.

```slip
players: http://api.example.com/players.json

-- If the API returns a list of player objects:
names: players.name
```

### Write to a file

Write JSON by using a `.json` filename:

```slip
out: #{
    names: #[ "Karl", "Jaina" ]
}
file://out.json: out
```

### Takeaway

The standard pattern is:

1. bind the data source to a name
2. query or transform the bound value
3. write out the result if needed

---

## How do I report output, success, and failure?

Scripts usually need to do three things beyond pure calculation:

- report output
- signal success or failure
- recover from expected failure cases

SLIP scripts report output as **effects**.

- `emit <topic-or-topics> <message...>` appends an event to the script’s output log.
- Emitting does **not** mutate your variables; it’s for narration/debugging/logging.
- Your host (or CLI) decides what to do with emitted events (show them, save them, ignore them).
- `print ...` is a convenience that emits to the standard output topic.

```slip
emit "debug" "starting script"
print "Hello, world"
```

You can emit from anywhere, including loops and functions:

```slip
count-down: fn {n} [
  i: n
  while [i > 0] [
    emit "debug" "i = {{i}}"
    i: i - 1
  ]
  emit "debug" "done"
]

count-down 3
```

### Handling failures and expected errors

There are two kinds of “things that go wrong”:

1) **Script errors** (type errors, missing paths, etc.) normally stop the script.
2) **Expected failure** is handled as data (e.g., `response err ...`).

### Catching a crash with `do`

`do` runs a block and returns:

- `log.outcome`: a `response`
- `log.effects`: the emitted effects during that block

If the block returns normally, `log.outcome` is `response ok <value>`.
If the block raises an error, `log.outcome` is `response err <message>`.
If the block already returns a `response`, `do` preserves it.

Tip: `ok` and `err` are standard aliases provided by the core library.

```slip
log: do [
    10 / 0
]

if [log.outcome.status = err] [
    print "It failed: {{log.outcome.value}}"
] [
    print "It worked: {{log.outcome.value}}"
]
```

### HTTP without crashing (lite/full mode)

By default, HTTP raises an error on non-2xx. If you want to handle it yourself, request a response mode:

- preferred: `#(response-mode: \`lite\`)` returns `#[status, value]`
- preferred: `#(response-mode: \`full\`)` returns `#{ status: <int>, value: <any>, meta: #{ headers: #{...} } }`
- legacy `#(lite: true)` and `#(full: true)` are still accepted

```slip
resp: http://api.example.com/players.json#(response-mode: `lite`)
status: resp[0]
body: resp[1]

if [status != 200] [
    print "Request failed with status {{status}}"
] [
    names: body.players.name
    file://out.json: #{ names: names }
]
```

### One complete script: JSON in -> transform -> JSON out

```slip
-- 1) Read JSON
data: file://input.json

-- 2) Extract and filter
players: data.players
wounded: players[.hp < 50]

-- 3) Transform into a new shape
report: #{
    wounded-count: len wounded,
    names: wounded.name
}

-- 4) Write JSON
file://out.json: report
```

### Takeaway

For everyday scripting:

- use `print` or `emit` for output
- use `response` for expected success/failure values
- use `do` when you want to capture a failure instead of stopping immediately

If you can do these seven things, you know enough SLIP to write useful self-contained scripts.

---
