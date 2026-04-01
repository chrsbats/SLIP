# The SLIP JIT Performance Guide

## Introduction and Philosophy

**1. Overview**

This document outlines the architecture for a production-grade, high-performance SLIP implementation in Nim. The primary goal of this runtime is to achieve the "best of both worlds": the flexibility and dynamic nature of a scripting language with the raw execution speed of a statically-compiled systems language.

This is not accomplished by a simple Ahead-Of-Time (AOT) compiler or a simple Just-In-Time (JIT) compiler, but by a sophisticated, multi-stage **adaptive compilation pipeline**. The runtime begins with a fast, AOT-compiled baseline and then uses profile-guided, just-in-time compilation to hyper-specialize the performance-critical parts of the code ("hotspots") as the program runs.

This guide details the strategy and components of this adaptive runtime.

**2. The Enabling Language Feature: Typed Signatures**

The entire high-performance strategy is enabled by a single, crucial language feature: the ability to provide explicit, machine-readable type signatures within the multiple dispatch system.

A typed function definition in SLIP is not just a hint for the programmer. It is a verifiable, static declaration that the AOT and JIT compilers will rely on.

```slip
// This is the contract between the programmer and the compiler.
add: fn {x: int, y: int -> int} [ x + y ]
```

This declaration is the "scaffolding" for all optimizations. It allows the compiler to map a SLIP function directly to a statically-typed Nim `proc`, enabling **unboxing** (using raw machine integers instead of generic `SlipValue` objects) and native-speed operations.

**3. The Multi-Stage Compilation Pipeline**

The runtime consists of three distinct stages of execution. Code can be promoted from a lower, more flexible stage to a higher, faster stage based on runtime profiling.

**Stage 1: Ahead-Of-Time (AOT) Compilation (The Baseline)**

This stage occurs when a SLIP project is compiled by the host Nim compiler. The goal is to eliminate the SLIP AST-walking interpreter entirely and produce a fully native executable.

*   **Action 1: Compile Specialized Functions:** For every function definition with a concrete type signature (e.g., `{x: int, y: int -> int}`), the AOT compiler generates a corresponding, statically-typed Nim `proc`. This `proc` is compiled directly to optimized machine code.

*   **Action 2: Compile the Dispatcher:** For a generic function like `add`, the AOT compiler compiles the dispatch mechanism itself. This includes the list of dispatch rules and the logic for finding the most specific method. The result is a fast, compiled function that can perform the runtime type lookup.

*   **Action 3: Compile the "Slow Path":** For a function that makes a generic call where types cannot be known ahead of time (e.g., `process-data` calling `add item.a item.b`), the AOT compiler compiles a call to the **generic dispatcher function** from Action 2. This is the "slow path," but it is a slow path made of highly optimized, compiled Nim code, not an interpreter.

At the end of this stage, you have a native executable with no SLIP interpreter. All code is compiled Nim.

**Stage 2: Profiling and Hotspot Detection (The Watcher)**

This stage occurs as the compiled program runs. The AOT compiler will have woven lightweight profiling instrumentation into the generated code.

*   **Mechanism:** Every generic function call and loop is monitored. The runtime maintains "hotness" counters and tracks the types of arguments passed at generic call sites.

*   **The Trigger:** When a function is determined to be "hot" (e.g., called thousands of times) and the profiling data shows a stable, predictable type pattern (e.g., a specific call site *always* uses integers), it is placed in a queue for the JIT compiler.

**Stage 3: Just-In-Time (JIT) Compilation (The Turbocharger)**

This is a background thread that consumes the queue of hot functions. The JIT has a superpower the AOT compiler lacks: **real-world profiling data.**

*   **Action 1: Specialization and Inlining:** The JIT re-analyzes the original SLIP AST for the hot function. Using the profiling data, it performs **speculative optimization**. For example, in `process-data`, it sees that `add` is always called with integers. It then generates a new, hyper-specialized version of `process-data` in memory. In this version, the call to the generic `add` dispatcher is completely **inlined** and replaced with the direct, unboxed machine code for integer addition.

*   **Action 2: Deoptimization (The Safety Net):** The specialized function is "guarded." The JIT inserts a very fast type check at the beginning of the function. If this check ever fails (i.e., the function is unexpectedly called with strings), the JIT code immediately bails out and transfers control back to the slower, AOT-compiled version. This is called **deoptimization**, and it guarantees correctness.

*   **Action 3: The "Hot-Swap":** The runtime atomically replaces the function pointer for the original `process-data` to point to this new, hyper-specialized, JIT-compiled version.

**4. The Complete Execution Flow: A Walkthrough**

1.  **AOT:** A function `process-data` is compiled into Nim code that calls the generic `add` dispatcher (the "slow path").
2.  **Runtime (First Calls):** The program runs. `process-data` is called. It executes the compiled slow path. The `add` dispatcher is invoked, finds the correct `{int, int}` method, and calls the specialized `add_int_int` function. The profiler counts every call.
3.  **JIT Trigger:** After 1000 calls, the profiler marks `process-data` as hot and queues it for the JIT.
4.  **JIT Compilation:** The JIT thread wakes up, analyzes `process-data`, sees the stable integer pattern from the profiler, and generates a new, specialized version of the function where the `add` call is replaced by raw integer addition and a deoptimization guard.
5.  **Hot-Swap:** The function pointer for `process-data` is updated.
6.  **Runtime (Subsequent Calls):** All future calls to `process-data` now execute the hyper-specialized, native-speed version directly, achieving C-like performance as long as the type pattern remains stable.

This adaptive compilation model provides the ultimate path for SLIP's evolution from a clean, dynamic language into a world-class, high-performance runtime. The following chapters will detail the specific implementation of each component of this architecture.

---

## The Nim JIT/AOT Compiler

This architecture builds upon the _algorithms_ proven in the Python reference implementation but replaces the underlying engine with native Nim structures and a Just-In-Time (JIT) compiler.

### Chapter 1: The Core Runtime - From Python Classes to Nim Objects

The foundation of the Nim implementation is a set of `ref object` types that efficiently represent SLIP's core data structures.

- **`SlipValue`:** A variant object (`object of RootObj`) is used as the base for all SLIP types, allowing for runtime type dispatch.
- **`Scope`:** The Python `Scope` class is translated into a Nim `ref object`. Its internal `.data` and `.meta` dictionaries become Nim `Table`s.
- **`GenericFunction`:** The container for methods is also a native Nim `ref object`.

This initial translation creates a Nim-based interpreter that is functionally equivalent to the Python reference version—correct, but not yet optimized. The following chapters detail the optimization strategies.

### Chapter 2: The High-Performance Object Model - Shapes (Hidden Classes)

The single most important optimization for object property access is the implementation of a "Shapes" (or "Hidden Classes") engine. This technique allows dynamic `scope` objects to be treated with the speed of static structs.

- **The Concept:** Instead of storing keys in a hash map on every object, an object's structure is described by a shared `Shape` object. The `Scope` itself only stores a flat sequence of its values.
- **The `Shape` Object:** A `Shape` is an immutable object that maps property names to their type and their **offset** within the value sequence.
  ```nim
  type Shape = ref object
    parent: Shape # For transitions
    propertyOffsets: Table[string, int]
    propertyTypes: Table[string, SlipTypeEnum]
  ```
- **The `Scope` Object (Optimized):**
  ```nim
  type Scope = ref object of SlipValue
    shape: Shape # A hidden pointer to its current shape
    values: seq[SlipValue] # A flat sequence of property values
    # ... meta, parent, lexical_parent ...
  ```
- **The Performance Gain:** A property access like `player.hp` is transformed from a slow hash lookup (`player.data["hp"]`) into a lightning-fast, direct memory access (`player.values[shape.propertyOffsets["hp"]]`).
- **Shape Transitions:** When a user adds a new property to a `scope`, the runtime doesn't modify the existing `Shape`. It creates a new `Shape` that links to the old one and updates the object's `shape` pointer. This creates chains of transitions that the JIT compiler can use to predict an object's evolution.

### Chapter 3: The High-Performance Collection Model - Native Columnar Stores

This is the native Nim equivalent of the NumPy backend from the Python implementation.

- **The `ColumnarStore` in Nim:** The `ColumnarStore` is implemented as a native Nim object.
  ```nim
  type ColumnarStore = ref object
    schema: Table[string, SlipTypeEnum]
    columns: Table[string, seq[SlipValue]] # Or even specialized seq[int], seq[float]
  ```
- **The Performance Gain:** By storing data in contiguous `seq`s of the same type, we achieve massive performance wins:
  1.  **Cache Locality:** Iterating over all `hp` values means scanning a single, contiguous block of memory, which is extremely fast for modern CPUs.
  2.  **Vectorization (SIMD):** A query like `players[hp > 100]` can be compiled down to native SIMD (Single Instruction, Multiple Data) instructions that can compare multiple HP values simultaneously.

### Chapter 4: The JIT/AOT Compiler Architecture

The JIT/AOT compiler is the engine that uses the `Shapes` and `ColumnarStore` information to generate fast, native code.

- **Ahead-of-Time (AOT) Analysis:** The compiler can analyze the SLIP code before running it. It can infer the initial `Shapes` of objects and pre-generate optimized code paths with **guards**. A guard is a fast check at the beginning of a function:

  ````nim
  # Conceptual AOT-generated code for `describe(x)`
  proc describe_optimized_for_character(x: Scope):
    # The Guard Clause
    if x.shape != PRE_COMPILED_CHARACTER_SHAPE:
      # The shape changed! Bail out to the slow interpreter.
      return describe_interpreted(x)

    # FAST PATH: The shape is what we expect.
    # Access hp via direct memory offset.
    let hp = x.values[0]
    ...
  ```

*   **Just-in-Time (JIT) Compilation:** At runtime, the interpreter includes a simple profiler that tracks "hot" functions and loops. When a piece of code is executed many times, the JIT compiler is invoked.
  *   It uses the live, runtime information about the types and `Shapes` of the variables to generate a highly specialized and optimized version of that code in machine language.
  *   The next time the function is called, the interpreter jumps directly to this new, fast machine code.
  ````

- **De-optimization:** This is the crucial safety net. If a guard fails (e.g., an object's `Shape` changes), the optimized machine code must be able to instantly bail out and transfer control back to the slow, safe interpreter, which can handle the unexpected change correctly.

### Chapter 5: Example-Driven Type Inference

The JIT's ability to generate fast code is directly proportional to how much it knows about the types of variables. The `|example` helper is a primary source for this information.

- **The Goal:** To eliminate dynamic type checks and unbox values into raw machine types (e.g., a `SlipInt` becomes a raw `int64`).
- **The Mechanism:** The JIT/AOT compiler analyzes the `meta.examples` list for a function.
  - From an example like `{x: 1, y: 2 -> 3}`, it infers a concrete signature of `(int, int) -> int`.
  - It can then generate a **specialized version** of the function that _only_ accepts raw `int`s.
  - When this function is called, the dispatcher will check the types. If they are integers, it will call the super-fast, specialized version. If they are floats, it will fall back to a slower, more generic version.
- **The Payoff:** This allows SLIP to achieve the performance of a statically-typed language for code paths that are well-described by examples or explicit type signatures, without sacrificing the flexibility of the dynamic language elsewhere.
