## The SLIP Python Performance Guide

### Introduction

The SLIP Implementation Specification describes how to build a _correct_ reference interpreter. This guide describes how to build a _fast_ one.

This document is divided into two parts. Part 1 focuses on strategies for building a high-performance Python interpreter by leveraging the **NumPy library** for its columnar data store. This provides a fast reference implementation and a clear, translatable model for the future Nim JIT/AOT compiler, which is detailed in Part 2.

---

### The Core Problem: The Cost of Dynamic Python Objects

A naive interpreter using pure Python objects and dictionaries for large collections is inherently slow due to memory overhead, slow hash lookups, and poor CPU cache performance. The solution is to transparently switch the internal storage of homogeneous collections to a highly efficient, C-backed columnar format provided by the NumPy library.

### Why NumPy and Not Pandas?

- **Pandas** is a high-level data analysis library. While powerful, it is a "black box" that hides the core logic of table and view management. Using it would make the Python implementation a poor blueprint for the Nim version.
- **NumPy** is the perfect choice. It provides the core, high-performance building block—the C-backed `ndarray`—without hiding the surrounding logic. The implementer must still write the "DataFrame-like" management code, making the logic clear and easily translatable to Nim's `seq` and memory management, while still gaining the raw speed of C for numerical operations.

### Chapter 1: The Hybrid Data Model

The key to performance is to enhance the `SlipList` object to support a hybrid internal model. The user only ever interacts with the standard SLIP `list` type.

#### 1.1. The Hybrid List

A `SlipList` object can operate in two modes:

- **Generic Mode (Default):** The list internally stores a standard Python `list` of `SlipValue` objects.
- **Optimized Columnar Mode:** If the list is "promoted," it will contain a reference to a `ColumnarStore` object, which is built on NumPy.

```python
import numpy as np

class SlipList:
    def __init__(self, initial_elements: list):
        self._generic_store: list[Value] = initial_elements
        self._columnar_backend: ColumnarStore | None = None

    @property
    def is_optimized(self) -> bool:
        return self._columnar_backend is not None
```

#### 1.2. The NumPy-backed Columnar Store

The `ColumnarStore` is a Python object that represents the table-like data using NumPy arrays.

```python
class ColumnarStore:
    def __init__(self, schema: dict):
        # Describes the columns, e.g., {"hp": np.int32, "name": object}
        self.schema = schema

        # The actual data, stored as a dictionary of NumPy arrays.
        self.columns: dict[str, np.ndarray] = {
            col_name: np.array([], dtype=dtype) for col_name, dtype in schema.items()
        }
```

### Chapter 2: Optimistic Columnarization (The "Promotion" Heuristic)

The runtime should automatically detect when to optimize a list.

- **The Trigger:** Promotion should be considered the first time a potentially slow operation, like a **filter query (`[...]`)**, is performed on a `SlipList`.
- **The Heuristic:**
  1.  Inspect the list's elements to determine if they are homogeneous (a high percentage are `scope`s with the same keys and value types).
  2.  If they are, derive a **schema**, mapping column names to appropriate NumPy `dtype`s (e.g., `np.int64`, `np.float64`, `object` for strings or other SLIP types).
- **The Promotion Process:**
  1.  Create a new `ColumnarStore` based on the derived schema.
  2.  Create empty NumPy arrays for each column.
  3.  Iterate through the original `SlipList` and populate the NumPy arrays. This is the one-time cost of conversion.
  4.  Attach the new `ColumnarStore` to the `SlipList`'s `_columnar_backend` property and clear the generic store.

### Chapter 3: The De-optimization Trigger

The system must safely handle cases where the user breaks the homogeneous pattern.

- **The Trigger:** The `append` and `set-item` primitives for `SlipList` must check if the list is optimized.
- **The Logic:** If an optimized list is modified with a non-conforming `scope` (e.g., different keys or types that cannot be coerced):
  1.  The system must **de-optimize**.
  2.  It reconstructs the generic Python `list` of `Scope` objects from the data in the `ColumnarStore`.
  3.  It discards the `ColumnarStore` backend.
  4.  It proceeds with the operation on the now-generic list.
- **Consequence:** This guarantees correctness at the cost of a predictable "performance cliff."

### Chapter 4: Implementing Views and Queries with NumPy

This is where the performance gain is realized. The Query DSL is translated directly into highly efficient NumPy operations.

- **The `View` Object:** A `View` on an optimized list no longer holds a complex recipe. It holds two key things:

  1.  A reference to the source `ColumnarStore`.
  2.  A NumPy array of **integer indices** or a **boolean mask** that represents the selected rows.

- **Query Execution:** A SLIP query chain is fused and translated into a highly efficient NumPy expression.

  - **Source:** `players.hp[> 100]`
  - **Explanation:** This operation involves two steps: a "pluck" (`players.hp`) followed by a filter (`[> 100]`). For an optimized columnar list, the interpreter can fuse these into a single, high-performance operation.
  - **Implementation:**
    1.  Get the `hp` column from the `players` list's `ColumnarStore`: `hp_array = source_store.columns["hp"]`.
    2.  Perform the vectorized comparison in C: `mask = hp_array > 100`. This returns a boolean array (`[True, False, True]`).
    3.  Create and return a new `View` containing this `mask`. This is extremely fast.

- **Writable Views:** Setting a view becomes a single, powerful NumPy operation called "boolean array indexing."
  - **Source:** `wounded-players.status: "Wounded"`
  - **Implementation:**
    1.  The `wounded-players` view contains a boolean mask (e.g., `[False, True, False]`).
    2.  The assignment becomes a single, fast C-level operation: `source_store.columns["status"][mask] = "Wounded"`. This broadcasts the value to all `True` locations in the mask.

By using NumPy as the foundation for the columnar backend, the Python interpreter can achieve genuine high performance for data manipulation tasks, while providing a clear and valuable architectural blueprint for the future Nim implementation.

### Chapter 5: Handling Inheritance and Property Shadowing

A key challenge is ensuring the `ColumnarStore` correctly implements SLIP's "live" prototype inheritance model without sacrificing performance. Simply copying parent properties into the columnar store at promotion time is not an option, as this would create stale data if the prototype is modified later.

The solution is to implement a "shadowing" lookup that mirrors the main SLIP object model.

- **Store the Prototype:** The promotion process must identify the common `prototype` `Scope` for the objects in the list and store a reference to it within the `ColumnarStore`.

- **Implement Shadowing Lookup:** When a "pluck" operation (e.g., `players.hp`) is performed on an optimized list, the query engine must follow this logic:
    1.  **Check for Instance Column:** First, it checks if a column for the property (`hp`) exists in the `ColumnarStore`'s instance-level NumPy arrays.
    2.  **Fallback to Prototype:** If the column does not exist, the property is assumed to be uniformly inherited. The engine looks up the property on the stored `prototype` object (e.g., `prototype.hp`). The result is a new array of that single inherited value, broadcast to match the number of rows in the store.
    3.  **Handle Overridable Properties:** For properties that can be either instance-level or inherited (the most common case), the implementation is more nuanced. The instance column in the `ColumnarStore` must exist, but it must use a **sentinel value** (e.g., `np.nan` for floats, a special object for others) to mark rows that do not have an instance-specific override. On access, the query engine retrieves this column, and then dynamically replaces the sentinel values with the current value from the prototype.

This shadowing model correctly preserves live inheritance. Changes to a prototype are immediately visible on the next property access from any `View` or `ColumnarStore` that inherits from it, blending correctness with high performance.
