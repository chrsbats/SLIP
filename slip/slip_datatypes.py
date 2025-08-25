
"""
Defines the core data types for the SLIP language runtime.

This module provides classes for all first-class and metaprogramming
data types that the SLIP interpreter will work with.
"""

from abc import ABC
from typing import List, Dict, Any, Optional, Union, TYPE_CHECKING
import collections.abc

class PathNotFound(Exception):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key

# =================================================================
# Abstract Base Classes
# =================================================================

class SlipCallable(ABC):
    """Abstract base class for all objects callable within SLIP."""
    pass


class PathSegment(ABC):
    """Abstract base class for all components of a Path."""
    pass


class SlipBlock(collections.abc.MutableSequence):
    """
    Abstract base class for Code, Group, and List which are sequence-like
    types that hold AST nodes.
    """
    def __init__(self, ast_nodes: List[Any]):
        self.nodes = list(ast_nodes)

    def __getitem__(self, index):
        return self.nodes[index]

    def __setitem__(self, index, value):
        self.nodes[index] = value

    def __delitem__(self, index):
        del self.nodes[index]

    def __len__(self) -> int:
        return len(self.nodes)

    def insert(self, index, value):
        self.nodes.insert(index, value)

    @property
    def ast(self):
        """Provides access to the raw AST nodes for metaprogramming."""
        return self.nodes


# =================================================================
# Core Runtime Types
# =================================================================

class Scope:
    """Represents a SLIP scope (object), with prototype parent and mixins.

    This is the core data structure for lexical scoping and the basis for
    SLIP's prototype-based object model. It supports:
      - lexical lookup via the enclosing scopes (handled by the evaluator),
      - object property lookup across instance, mixins, then parent,
      - explicit prototype inheritance (meta.parent),
      - capability composition via mixins (meta.mixins).
    """
    def __init__(self, parent: Optional['Scope'] = None):
        # User-visible bindings on this scope.
        self.bindings: Dict[str, Any] = {}
        # System metadata used by the object model and dispatch.
        # name/type_id may be populated during "christening" by set-path logic.
        self.meta: Dict[str, Any] = {
            "parent": parent,
            "mixins": []  # List[Scope]
        }

    def __setitem__(self, key: Any, value: Any):
        key = self._normalize_key(key)
        if key == "meta":
            raise KeyError("'.meta' is reserved and cannot be rebound.")
        if not isinstance(key, str):
            raise TypeError(f"Scope key must be a str, not {type(key)}")
        self.bindings[key] = value

    def __getitem__(self, key: Any) -> Any:
        key = self._normalize_key(key)
        if key == "meta":
            return self.meta
        if not isinstance(key, str):
            raise TypeError(f"Scope key must be a str, not {type(key)}")
        owner = self.find_owner(key)
        if owner:
            return owner.bindings[key]
        raise KeyError(f"'{key}'")

    def __delitem__(self, key: Any):
        key = self._normalize_key(key)
        if key == "meta":
            raise KeyError("'.meta' is reserved and cannot be deleted.")
        if not isinstance(key, str):
            raise TypeError(f"Scope key must be a str, not {type(key)}")
        if key not in self.bindings:
            raise KeyError(f"'{key}'")
        del self.bindings[key]

    def __contains__(self, key: Any) -> bool:
        """Checks if a key exists in this Scope or its prototypes."""
        key = self._normalize_key(key)
        if isinstance(key, str):
            return self.find_owner(key) is not None
        return False

    def find_owner(self, key: str) -> Optional['Scope']:
        """Finds the Scope in the lookup chain (self → mixins → parent) that owns key."""
        if key in self.bindings:
            return self
        # Check mixins in order; recurse into each mixin's own lookup chain.
        for mixin in self.meta.get("mixins", []):
            owner = mixin.find_owner(key)
            if owner is not None:
                return owner
        # Finally, walk the prototype chain.
        parent = self.meta.get("parent")
        if parent:
            return parent.find_owner(key)
        return None

    def get(self, key: Any, default: Any = None) -> Any:
        """Gets a value, returning a default if not found."""
        key = self._normalize_key(key)
        if not isinstance(key, str):
            return default
        owner = self.find_owner(key)
        if owner:
            return owner.bindings[key]
        return default

    def inherit(self, parent: 'Scope'):
        """Sets the prototype parent once. Raises if already set."""
        if self.meta.get("parent") is not None:
            raise ValueError("inherit can only be called once on a scope (parent already set).")
        self.meta["parent"] = parent

    def add_mixin(self, *sources: 'Scope'):
        """Adds one or more mixin scopes, preserving order and avoiding duplicates."""
        mixins: List['Scope'] = self.meta.setdefault("mixins", [])
        for src in sources:
            if src not in mixins:
                mixins.append(src)

    def _normalize_key(self, key):
        """Allow a single-name PathLiteral(GetPath(...)) or GetPath to be used as a key."""
        try:
            from slip.slip_datatypes import PathLiteral as _PL  # local import to avoid cycle during edits
            if isinstance(key, _PL):
                inner = getattr(key, 'inner', None)
                if isinstance(inner, GetPath):
                    segs = getattr(inner, 'segments', [])
                    if len(segs) == 1 and isinstance(segs[0], Name):
                        return segs[0].text
            if isinstance(key, GetPath):
                segs = getattr(key, 'segments', [])
                if len(segs) == 1 and isinstance(segs[0], Name):
                    return segs[0].text
        except Exception:
            pass
        return key

    @property
    def parent(self) -> Optional['Scope']:
        """Returns the prototype parent scope."""
        return self.meta.get("parent")

    @property
    def mixins(self) -> List['Scope']:
        """Returns the live list of mixin scopes for this object."""
        return self.meta.setdefault("mixins", [])

    def keys(self) -> collections.abc.KeysView[str]:
        """Returns a view of keys in the current scope only."""
        return self.bindings.keys()

    def __getattr__(self, key: str):
        """Attribute-style lookup fallback to support template engines."""
        if key == "meta":
            return self.meta
        owner = self.find_owner(key)
        if owner is not None and key in owner.bindings:
            return owner.bindings[key]
        raise AttributeError(key)

    def __repr__(self) -> str:
        keys = ', '.join(self.bindings.keys())
        parent_id = f", parent=#{id(self.parent)}" if self.parent else ""
        return f"<Scope bindings=[{keys}]{parent_id}>"


class Code(SlipBlock):
    """Represents an unevaluated block of SLIP code (`[...]`).

    This is a wrapper around a raw AST fragment, making "code" a
    first-class data type that can be passed to functions or manipulated.
    """
    def __init__(self, ast_nodes: List[Any]):
        super().__init__(ast_nodes)

    def __repr__(self) -> str:
        return f"Code({self.nodes!r})"

    def __eq__(self, other):
        return isinstance(other, Code) and self.nodes == other.nodes


class List(SlipBlock):
    """Represents a SLIP list literal (`#[...]`).

    This contains unevaluated AST nodes. At evaluation time, the
    expressions are run and their results collected into a new list of values.
    """
    def __init__(self, ast_nodes: List[Any]):
        super().__init__(ast_nodes)

    def __repr__(self) -> str:
        return f"List({self.nodes!r})"

    def __eq__(self, other):
        return isinstance(other, List) and self.nodes == other.nodes


class ByteStream(SlipBlock):
    """Represents a typed byte stream literal like 'u8#[...]', carrying unevaluated AST nodes."""
    def __init__(self, elem_type: str, ast_nodes: List[Any]):
        super().__init__(ast_nodes)
        self.elem_type = elem_type  # e.g., 'u8', 'i16', 'f32', 'b1'
    def __repr__(self):
        return f"ByteStream<{self.elem_type}>({self.nodes!r})"
    def __eq__(self, other):
        return isinstance(other, ByteStream) and self.elem_type == other.elem_type and self.nodes == other.nodes

class Sig:
    def __init__(self, positional: List[str], keywords: Dict[str, Any], rest: Optional[str] = None, return_annotation: Optional[Any] = None):
        self.positional = positional
        self.keywords = keywords
        self.rest = rest
        self.return_annotation = return_annotation
    def __repr__(self) -> str:
        return f"Sig(pos={self.positional!r}, kw={self.keywords!r}, rest={self.rest!r}, ret={self.return_annotation!r})"
    def __eq__(self, other):
        return isinstance(other, Sig) and (
            self.positional == other.positional and
            self.keywords == other.keywords and
            self.rest == other.rest and
            self.return_annotation == other.return_annotation
        )


class IString(str):
    """Represents a SLIP interpolated string (`"..."`).

    This is a distinct type from a raw string, signaling to the
    evaluator that it must be processed for `{{...}}` expressions.
    """
    def __repr__(self) -> str:
        return f'i"{self}"'


class SlipFunction(SlipCallable):
    """Represents a function defined in SLIP using `fn`.

    This is a closure, bundling the function's arguments, its code body,
    and the lexical scope in which it was defined.
    """
    def __init__(self, args: 'Code', body: 'Code', closure: 'Scope'):
        self.args = args
        self.body = body
        self.closure = closure
        self.meta: Dict[str, Any] = {}

    def __repr__(self) -> str:
        from slip.slip_printer import Printer
        p = Printer()
        # A simplified repr to avoid full formatting.
        return f"fn {p.pformat(self.args)} {p.pformat(self.body)}"

    def __eq__(self, other):
        if not isinstance(other, SlipFunction):
            return NotImplemented
        # NOTE: closure comparison is intentionally omitted.
        return self.args == other.args and self.body == other.body


class GenericFunction(SlipCallable):
    def __init__(self, name: Optional[str] = None):
        self.name = name
        self.methods: List[SlipFunction] = []
        self.meta: Dict[str, Any] = {}
    def add_method(self, fn: SlipFunction):
        self.methods.append(fn)
    def __repr__(self) -> str:
        return f"<GenericFunction name={self.name!r} methods={len(self.methods)}>"


class Response:
    """Represents a structured outcome from a function call (`response ...`)."""
    def __init__(self, status: 'PathLiteral', value: Any):
        self.status = status
        self.value = value

    def __repr__(self) -> str:
        from slip.slip_printer import Printer
        p = Printer()
        return f"response {p.pformat(self.status)} {p.pformat(self.value)}"

    def __eq__(self, other):
        if not isinstance(other, Response):
            return NotImplemented
        return self.status == other.status and self.value == other.value


class PipedPath(PathSegment):
    """Represents a SLIP piped-path (e.g., |map). Semantically identical
    to a GetPath but signals the evaluator to perform an implicit-pipe call
    when it appears in expression position #2."""
    def __init__(self, segments: List[PathSegment], meta: Optional['Group'] = None):
        if not segments:
            raise ValueError("PipedPath must have at least one segment.")
        self.segments = segments
        self.meta = meta
        self._str_repr: Optional[str] = None

    def __getitem__(self, key):
        return self.segments[key]

    def to_str_repr(self) -> str:
        from slip.slip_printer import Printer
        if self._str_repr is None:
            self._str_repr = Printer().pformat(self)
        return self._str_repr

    def __repr__(self):
        return f"<PipedPath segments={self.segments!r} meta={self.meta!r}>"

    def __eq__(self, other):
        if not isinstance(other, PipedPath):
            return NotImplemented
        return self.to_str_repr() == other.to_str_repr()

    def __hash__(self):
        return hash(self.to_str_repr())


class MultiSetPath(PathSegment):
    """Represents the left-hand pattern `[a, b.c]:` used for destructuring assignment."""
    def __init__(self, targets: List['SetPath']):
        if not targets:
            raise ValueError("MultiSetPath must contain at least one SetPath target.")
        self.targets = targets

    def __iter__(self):
        return iter(self.targets)

    def __repr__(self):
        return f"<MultiSetPath targets={self.targets!r}>"

    def __eq__(self, other):
        return isinstance(other, MultiSetPath) and self.targets == other.targets

    def __hash__(self):
        return hash(tuple(self.targets))


class GetPath:
    """Represents a SLIP get-path, an instruction to look up a value."""
    def __init__(self, segments: List[PathSegment], meta: Optional['Group'] = None):
        if not segments:
            raise ValueError("GetPath must have at least one segment.")
        self.segments = segments
        self.meta = meta
        self._str_repr: Optional[str] = None

    def __getitem__(self, key: Union[int, slice]) -> Union[PathSegment, List[PathSegment]]:
        return self.segments[key]

    def to_str_repr(self) -> str:
        from slip.slip_printer import Printer
        if self._str_repr is None:
            self._str_repr = Printer().pformat(self)
        return self._str_repr

    def __repr__(self) -> str:
        # Simple repr to avoid recursion with printer
        return f"<GetPath segments={self.segments!r} meta={self.meta!r}>"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, GetPath):
            return NotImplemented
        return self.to_str_repr() == other.to_str_repr()

    def __hash__(self) -> int:
        return hash(self.to_str_repr())


class PathLiteral:
    """Represents a quoted path value written with backticks. The inner may be any path-shaped object."""
    def __init__(self, inner: 'GetPath | SetPath | DelPath | PipedPath | MultiSetPath'):
        self.inner = inner
        self._str_repr: Optional[str] = None

    def to_str_repr(self) -> str:
        from slip.slip_printer import Printer
        if self._str_repr is None:
            self._str_repr = Printer().pformat(self)
        return self._str_repr

    def __repr__(self) -> str:
        return f"<PathLiteral {self.to_str_repr()}>"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, PathLiteral):
            return NotImplemented
        return self.to_str_repr() == other.to_str_repr()

    def __hash__(self) -> int:
        return hash(self.to_str_repr())






# -----------------------------------------------------------------
# New Literal Types (deprecated in favor of PathLiteral)
# -----------------------------------------------------------------


class DelPath:
    """Represents a SLIP del-path (~path), an instruction to delete a binding."""
    def __init__(self, path: 'GetPath'):
        self.path = path

    def __repr__(self) -> str:
        # Simple repr to avoid recursion with printer
        return f"<DelPath path={self.path!r}>"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, DelPath):
            return NotImplemented
        return self.path == other.path

    def __hash__(self) -> int:
        return hash(self.path)


class SetPath:
    """Represents a SLIP set-path, which is a sequence of segments ending with a colon.
    This is the data type representation for an assignment target.
    """
    def __init__(self, segments: List[PathSegment], meta: Optional['Group'] = None):
        if not segments:
            raise ValueError("SetPath must have at least one segment.")
        self.segments = segments
        self.meta = meta
        self._str_repr: Optional[str] = None

    def __getitem__(self, key: Union[int, slice]) -> Union[PathSegment, List[PathSegment]]:
        return self.segments[key]

    def to_str_repr(self) -> str:
        from slip.slip_printer import Printer
        if self._str_repr is None:
            self._str_repr = Printer().pformat(self)
        return self._str_repr

    def __repr__(self) -> str:
        # Simple repr to avoid recursion with printer
        return f"<SetPath segments={self.segments!r} meta={self.meta!r}>"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, SetPath):
            return NotImplemented
        return self.to_str_repr() == other.to_str_repr()

    def __hash__(self) -> int:
        return hash(self.to_str_repr())


class PostPath:
    """Represents a SLIP post-path, e.g., 'url<-', used as the head of a POST expression."""
    def __init__(self, segments: List[PathSegment], meta: Optional['Group'] = None):
        if not segments:
            raise ValueError("PostPath must have at least one segment.")
        self.segments = segments
        self.meta = meta
        self._str_repr: Optional[str] = None

    def __getitem__(self, key: Union[int, slice]) -> Union[PathSegment, List[PathSegment]]:
        return self.segments[key]

    def to_str_repr(self) -> str:
        from slip.slip_printer import Printer
        if self._str_repr is None:
            self._str_repr = Printer().pformat(self)
        return self._str_repr

    def __repr__(self) -> str:
        return f"<PostPath segments={self.segments!r} meta={self.meta!r}>"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, PostPath): return NotImplemented
        return self.to_str_repr() == other.to_str_repr()

    def __hash__(self) -> int:
        return hash(self.to_str_repr())


# =================================================================
# Path and Segment Types
# =================================================================

class Name(PathSegment):
    """A name segment in a path, e.g., 'user' in `user.name`."""
    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:
        return f"Name<{self.text!r}>"

    def __eq__(self, other):
        return isinstance(other, Name) and self.text == other.text

    def __hash__(self):
        # Hash by the underlying text so that segments with identical
        # names are treated as equal in hashed collections.
        return hash(self.text)


class Index(PathSegment):
    """An index segment in a path, e.g., `[0]`."""
    def __init__(self, expr_ast: List[Any]):
        self.expr_ast = expr_ast

    def __repr__(self) -> str:
        return f"Index({self.expr_ast!r})"

    def __eq__(self, other):
        return isinstance(other, Index) and self.expr_ast == other.expr_ast


class Slice(PathSegment):
    """A slice segment in a path, e.g., `[1:5]`."""
    def __init__(self, start_ast: Optional[List[Any]], end_ast: Optional[List[Any]]):
        self.start_ast = start_ast
        self.end_ast = end_ast

    def __repr__(self) -> str:
        return f"Slice(start={self.start_ast!r}, end={self.end_ast!r})"

    def __eq__(self, other):
        return isinstance(other, Slice) and self.start_ast == other.start_ast and self.end_ast == other.end_ast


class FilterQuery(PathSegment):
    """A filter query segment in a path, e.g., `[> 10]` or `[|dist < 10]` or `[* 10 - 20 > 5]`."""
    def __init__(self, operator: Optional[str], rhs_ast: Optional[List[Any]], predicate_ast: Optional[List[Any]] = None):
        self.operator = operator
        self.rhs_ast = rhs_ast
        self.predicate_ast = predicate_ast

    def __repr__(self) -> str:
        if self.predicate_ast is not None:
            return f"FilterQuery(pred={self.predicate_ast!r})"
        return f"FilterQuery(op={self.operator!r}, rhs={self.rhs_ast!r})"

    def __eq__(self, other):
        return (
            isinstance(other, FilterQuery) and
            self.operator == other.operator and
            self.rhs_ast == other.rhs_ast and
            self.predicate_ast == other.predicate_ast
        )


class Group(SlipBlock, PathSegment):
    """
    A dynamic group segment in a path, e.g., `(get-key)`.
    Also represents a group AST node that can be manipulated.
    """
    def __init__(self, ast_nodes: List[Any]):
        super().__init__(ast_nodes)

    def __repr__(self) -> str:
        return f"Group({self.nodes!r})"

    def __eq__(self, other):
        return isinstance(other, Group) and self.nodes == other.nodes


class _SingletonSegment(PathSegment):
    """Internal helper class for creating stateless singleton path segments."""
    def __init__(self, name):
        self._name = name
    def __repr__(self):
        return f"{self._name.capitalize()}<>"

# Singleton instances for stateless path segments
Root = _SingletonSegment("root")
Parent = _SingletonSegment("parent")
Pwd = _SingletonSegment("pwd")


