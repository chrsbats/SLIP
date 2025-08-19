"""
The core SLIP interpreter, containing the Evaluator and PathResolver.
"""
import asyncio
import inspect
import sys
import os
import collections.abc
from typing import Any, List, Optional, Union, Tuple, Dict
from textwrap import dedent
import pystache

from slip.slip_datatypes import (
    Scope, Code, List as SlipList, IString, SlipFunction, GenericFunction, Response,
    GetPathLiteral, SetPathLiteral, DelPathLiteral, MultiSetPathLiteral, PathNotFound, PipedPathLiteral,
    GetPath, SetPath, DelPath, Name, Index, Slice, Group, FilterQuery,
    Root, Parent, Pwd, PipedPath, PathSegment, SlipCallable, Sig, PostPath, ByteStream
)

# Global registry for christening Scope types
TYPE_REGISTRY: Dict[str, int] = {}
_next_type_id = 1

def _tmpl_normalize_value(v):
    """Convert SLIP values into plain Python types for Mustache."""
    if isinstance(v, Scope):
        return _scope_to_dict(v)
    if isinstance(v, collections.abc.Mapping):
        # Convert mapping-like (including SlipObject/UserDict) to plain dict
        try:
            return {k: _tmpl_normalize_value(v[k]) for k in v.keys()}
        except Exception:
            try:
                return {k: _tmpl_normalize_value(val) for k, val in dict(v).items()}
            except Exception:
                return dict()
    if isinstance(v, list):
        return [_tmpl_normalize_value(x) for x in v]
    if isinstance(v, IString):
        # IString is a str subclass; ensure plain string for templates
        return str(v)
    return v

def _scope_to_dict(scope: Scope) -> dict:
    """Flatten the current scope and its parents into a single plain dict."""
    chain = []
    cur = scope
    while cur is not None:
        chain.append(cur)
        cur = cur.parent
    out: dict = {}
    # Populate from root to current so current bindings override parents
    for s in reversed(chain):
        for k, v in s.bindings.items():
            out[k] = _tmpl_normalize_value(v)
    return out

class View:
    """Simple placeholder for lazy query results (to be materialized later)."""
    def __init__(self, source, ops):
        self.source = source
        self.ops = ops
    def __repr__(self):
        return f"<View ops={self.ops!r} on {type(self.source).__name__}>"

class PathResolver:
    """Handles all path traversal and resolution logic."""
    def __init__(self, evaluator: 'Evaluator'):
        self.evaluator = evaluator

    async def _get_segment_key(self, segment: PathSegment, scope: Scope) -> Any:
        """Evaluates a path segment to determine the key for a lookup."""
        match segment:
            case Name():
                return segment.text
            case Index():
                return await self.evaluator.eval(segment.expr_ast, scope)
            case Slice():
                start = await self.evaluator.eval(segment.start_ast, scope) if segment.start_ast else None
                end = await self.evaluator.eval(segment.end_ast, scope) if segment.end_ast else None
                return slice(start, end)
            case Group():
                return await self.evaluator.eval(segment.nodes, scope)
            case _:
                raise TypeError(f"Unsupported path segment for key extraction: {type(segment)}")

    def _extract_http_url(self, path: GetPath | SetPath) -> str | None:
        """
        Extract a full http(s) URL from a path.
        Priority:
          1) Use the raw token text if present.
          2) If the first segment is a Name that starts with http(s)://, return its text verbatim.
        """
        loc = getattr(path, 'loc', None) or {}
        txt = loc.get('text') if isinstance(loc, dict) else None
        if isinstance(txt, str) and (txt.startswith("http://") or txt.startswith("https://")):
            u = txt.rstrip()
            # Strip any inline metadata (e.g., "#(...)") that may be present in the token text
            # Be robust: cut at the first '#' to handle tokens like "...#:" as well.
            hash_idx = u.find("#")
            if hash_idx != -1:
                u = u[:hash_idx]
            if isinstance(path, SetPath) or u.endswith(":"):
                u = u.rstrip(":")
            if os.environ.get("SLIP_HTTP_DEBUG"):
                try:
                    print(f"[SLIP_HTTP_DEBUG] URL from loc.text: {u}", file=sys.stderr)
                except Exception:
                    pass
            return u
        segments = getattr(path, 'segments', None) or []
        if segments and isinstance(segments[0], Name):
            s0 = segments[0].text
            if isinstance(s0, str) and (s0.startswith("http://") or s0.startswith("https://")):
                u = s0
                # Trim any inline metadata fragment, e.g., "#(...)"
                hash_idx = u.find("#")
                if hash_idx != -1:
                    u = u[:hash_idx]
                if isinstance(path, SetPath) or u.endswith(":"):
                    u = u.rstrip(":")
                if os.environ.get("SLIP_HTTP_DEBUG"):
                    try:
                        print(f"[SLIP_HTTP_DEBUG] URL from first segment: {u}", file=sys.stderr)
                    except Exception:
                        pass
                return u
        return None

    def _extract_fs_locator(self, path: GetPath | SetPath) -> str | None:
        loc = getattr(path, 'loc', None) or {}
        txt = loc.get('text') if isinstance(loc, dict) else None
        if isinstance(txt, str) and txt.startswith("fs://"):
            u = txt.rstrip()
            # Strip any inline metadata (e.g., "#(...)") that may be present in the token text
            # Be robust: cut at the first '#' to handle tokens like "...#:" as well.
            hash_idx = u.find("#")
            if hash_idx != -1:
                u = u[:hash_idx]
            if isinstance(path, SetPath) or u.endswith(":"):
                u = u.rstrip(":")
            return u
        segments = getattr(path, 'segments', None) or []
        if segments and isinstance(segments[0], Name):
            s0 = segments[0].text
            if isinstance(s0, str) and s0.startswith("fs://"):
                u = s0
                # Trim any inline metadata fragment, e.g., "#(...)"
                hash_idx = u.find("#")
                if hash_idx != -1:
                    u = u[:hash_idx]
                if isinstance(path, SetPath) or u.endswith(":"):
                    u = u.rstrip(":")
                return u
        return None

    async def _meta_to_dict(self, meta_group: Group | None, scope: Scope) -> dict:
        if not isinstance(meta_group, Group):
            return {}
        ev_out = await self.evaluator._eval(('dict', meta_group.nodes), scope)
        try:
            return dict(ev_out)
        except Exception:
            # Fallback to iterating mapping-like
            return {k: ev_out[k] for k in getattr(ev_out, 'keys', lambda: [])()}

    async def _resolve(self, path: Union[GetPath, SetPath], scope: Scope) -> Tuple[Any, Any]:
        """
        Traverses a path to find the container object and the final key.
        Returns (container, key).
        """
        if path.segments[0] is Root:
            # Find the root scope
            container = scope
            while container.parent:
                container = container.parent
            segments = path.segments[1:]
        else:
            container = scope
            segments = path.segments

        if not segments:
            raise ValueError("Path resolution requires at least one segment after root.")

        for segment in segments[:-1]:
            if segment is Parent:
                if not isinstance(container, Scope) or not container.parent:
                    raise KeyError("Path traversal failed: cannot use parent segment ('../') on non-Scope or root Scope.")
                container = container.parent
                continue
            if segment is Pwd:
                # Pwd refers to the current scope, so it's a no-op in traversal
                continue

            key = await self._get_segment_key(segment, scope)
            if isinstance(container, Scope):
                try:
                    container = container[key]  # Standard __getitem__ handles prototype lookup
                except KeyError:
                    raise
            else:
                container = container[key]  # For lists, dicts, etc.

        final_key = await self._get_segment_key(segments[-1], scope)
        return container, final_key

    async def get(self, path: GetPath, scope: Scope) -> Any:
        """Resolves a GetPath to get a value."""
        # TODO: Handle path.meta for things like API timeouts
        url = self._extract_http_url(path)
        if url:
            from slip.slip_http import http_get  # local import to avoid hard dependency until needed
            cfg = await self._meta_to_dict(getattr(path, 'meta', None), scope)
            return await http_get(url, cfg)
        fs_loc = self._extract_fs_locator(path)
        if fs_loc:
            from slip.slip_fs import fs_get
            cfg = await self._meta_to_dict(getattr(path, 'meta', None), scope)
            base_dir = getattr(self.evaluator, 'source_dir', None)
            try:
                return await fs_get(fs_loc, cfg, base_dir=base_dir)
            except FileNotFoundError:
                raise PathNotFound(fs_loc)
        # Resolve the path normally
        val = await self._resolve_value(path, scope)
        # If the resolved value is itself a path (alias), try to dereference it safely.
        try:
            from slip.slip_datatypes import GetPath as _GP, GetPathLiteral as _GPL
            # Literal alias
            if isinstance(val, _GPL):
                # Self-alias like ok: `ok` should yield the literal, not recurse.
                if val.segments == path.segments and getattr(val, 'meta', None) == getattr(path, 'meta', None):
                    return val
                gp = _GP(val.segments, getattr(val, 'meta', None))
                try:
                    return await self.get(gp, scope)
                except Exception:
                    # On failure, keep the original literal (do not coerce to GetPath)
                    return val
            # Runtime path alias
            if isinstance(val, _GP):
                # Avoid immediate recursion when alias points to the same path.
                if val.segments == path.segments and getattr(val, 'meta', None) == getattr(path, 'meta', None):
                    from slip.slip_datatypes import GetPathLiteral as _GPLIT
                    return _GPLIT(val.segments, getattr(val, 'meta', None))
                try:
                    return await self.get(val, scope)
                except Exception:
                    # On failure, return a literal representation for stable equality
                    from slip.slip_datatypes import GetPathLiteral as _GPLIT
                    return _GPLIT(val.segments, getattr(val, 'meta', None))
        except Exception:
            pass
        return val

    async def set(self, path: SetPath, value: Any, scope: Scope):
        """Resolves a SetPath to set a value."""
        # TODO: Handle path.meta for generic function dispatch
        url = self._extract_http_url(path)
        if url:
            from slip.slip_http import http_put
            from slip.slip_serialize import serialize as _ser
            cfg = await self._meta_to_dict(getattr(path, 'meta', None), scope)
            # Promote content-type into headers and choose serialization
            ctype = (cfg.get('content-type') or cfg.get('content_type'))
            if ctype:
                headers = dict(cfg.get('headers', {}))
                headers['Content-Type'] = ctype
                cfg['headers'] = headers
            def _fmt_from_ctype(ct: str | None) -> str | None:
                if not isinstance(ct, str): return None
                ct_l = ct.lower()
                if 'json' in ct_l: return 'json'
                if 'yaml' in ct_l or 'x-yaml' in ct_l: return 'yaml'
                if 'toml' in ct_l: return 'toml'
                if 'xml' in ct_l or 'html' in ct_l or 'xhtml' in ct_l: return 'xml'
                return None
            fmt = _fmt_from_ctype(ctype)
            if fmt is not None:
                try:
                    payload = _ser(value, fmt=fmt, pretty=True)
                except Exception:
                    payload = str(value)
            else:
                payload = value if isinstance(value, (str, bytes, bytearray)) else str(value)
            await http_put(url, payload, cfg)
            return  # assignment expression will still return the RHS value upstream
        fs_loc = self._extract_fs_locator(path)
        if fs_loc:
            from slip.slip_fs import fs_put
            cfg = await self._meta_to_dict(getattr(path, 'meta', None), scope)
            await fs_put(fs_loc, value, cfg, base_dir=getattr(self.evaluator, 'source_dir', None))
            return
        container, key = await self._resolve(path, scope)

        # Scope christening: assign meta.name and meta.type_id on first assignment
        if isinstance(value, Scope) and 'type_id' not in value.meta:
            global _next_type_id
            name_str = str(key)
            value.meta['name'] = name_str
            value.meta['type_id'] = _next_type_id
            value.meta['type-id'] = _next_type_id  # also expose kebab-case for path lookups
            TYPE_REGISTRY[name_str] = _next_type_id
            _next_type_id += 1

        if isinstance(container, Scope):
            if getattr(self.evaluator, 'bind_locals_prefer_container', False):
                container[key] = value
            else:
                owner = container.find_owner(key) if hasattr(container, 'find_owner') else None
                (owner or container)[key] = value
        else:
            container[key] = value

    async def post(self, path: PostPath, value: Any, scope: Scope):
        url = self._extract_http_url(GetPath(path.segments, getattr(path, 'meta', None)))
        if url:
            from slip.slip_http import http_post
            from slip.slip_serialize import serialize as _ser
            cfg = await self._meta_to_dict(getattr(path, 'meta', None), scope)
            ctype = (cfg.get('content-type') or cfg.get('content_type'))
            if ctype:
                headers = dict(cfg.get('headers', {}))
                headers['Content-Type'] = ctype
                cfg['headers'] = headers
            def _fmt_from_ctype(ct: str | None) -> str | None:
                if not isinstance(ct, str): return None
                ct_l = ct.lower()
                if 'json' in ct_l: return 'json'
                if 'yaml' in ct_l or 'x-yaml' in ct_l: return 'yaml'
                if 'toml' in ct_l: return 'toml'
                if 'xml' in ct_l or 'html' in ct_l or 'xhtml' in ct_l: return 'xml'
                return None
            fmt = _fmt_from_ctype(ctype)
            if fmt is not None:
                try:
                    payload = _ser(value, fmt=fmt, pretty=True)
                except Exception:
                    payload = str(value)
            else:
                payload = value if isinstance(value, (str, bytes, bytearray)) else str(value)
            return await http_post(url, payload, cfg)
        # Non-HTTP post-paths are not supported
        raise TypeError("post-path expects an http(s) URL")

    async def delete(self, path: DelPath, scope: Scope):
        """Resolves a DelPath to delete a value."""
        # TODO: Handle path.path.meta for things like soft-delete
        url = self._extract_http_url(path.path)
        if url:
            from slip.slip_http import http_delete
            cfg = await self._meta_to_dict(getattr(path.path, 'meta', None), scope)
            await http_delete(url, cfg)
            return
        fs_loc = self._extract_fs_locator(path.path)
        if fs_loc:
            from slip.slip_fs import fs_delete
            cfg = await self._meta_to_dict(getattr(path.path, 'meta', None), scope)
            await fs_delete(fs_loc, cfg, base_dir=getattr(self.evaluator, 'source_dir', None))
            return
        container, key = await self._resolve(path.path, scope)
        del container[key]

    async def _resolve_value(self, path: GetPath, scope: Scope) -> Any:
        """Resolves a GetPath to a concrete value, handling filter queries inline."""
        from slip.slip_datatypes import FilterQuery, PathNotFound
        # Determine starting container based on the path and the passed-in scope.
        if path.segments and path.segments[0] is Root:
            container = scope
            while isinstance(container, Scope) and container.parent:
                container = container.parent
            segments = path.segments[1:]
        else:
            container = scope
            segments = path.segments

        if not segments:
            raise ValueError("Path resolution requires at least one segment after root.")

        for segment in segments:
            match segment:
                case _ if (segment is Parent):
                    if not isinstance(container, Scope) or not container.parent:
                        raise KeyError("Path traversal failed: cannot use parent segment ('../') on non-Scope or root Scope.")
                    container = container.parent
                    continue
                case _ if (segment is Pwd):
                    # Pwd refers to the current scope, so it's a no-op in traversal
                    continue
                case FilterQuery():
                    container = await self._apply_filter(container, segment, scope)
                    continue

            # Vectorized pluck: when container is a list and next segment is a Name,
            # pluck that field from each item to produce a new list.
            if isinstance(container, list) and isinstance(segment, Name):
                plucked = []
                for item in container:
                    if isinstance(item, Scope):
                        try:
                            val = item[segment.text]
                        except KeyError:
                            raise PathNotFound(segment.text)
                        plucked.append(val)
                    elif isinstance(item, collections.abc.Mapping):
                        try:
                            plucked.append(item[segment.text])
                        except KeyError:
                            raise PathNotFound(segment.text)
                    else:
                        # Best-effort: support attribute-style access on plain objects
                        try:
                            plucked.append(getattr(item, segment.text))
                        except Exception:
                            raise TypeError(f"Cannot pluck field {segment.text!r} from item of type {type(item).__name__}")
                container = plucked
                continue

            key = await self._get_segment_key(segment, scope)
            # Attribute fallback: allow name access on non-mapping objects (e.g., response.status)
            if isinstance(segment, Name) and not isinstance(container, (Scope, collections.abc.Mapping)):
                try:
                    container = getattr(container, key)
                    continue
                except AttributeError:
                    pass
            try:
                # Let the container handle the lookup. For a Scope, its __getitem__
                # will traverse the prototype and mixin chains correctly.
                container = container[key]
            except KeyError:
                # Re-raise as a PathNotFound error for better semantics.
                raise PathNotFound(str(key))
            except Exception:
                raise

        return container

    async def _apply_filter(self, container, segment, scope: Scope):
        """Applies a filter query to the current container. Supports predicate chains."""
        # Always evaluate via predicate_ast using the evaluator so operator rebinding/multimethods apply.
        pred = getattr(segment, 'predicate_ast', None)


        if pred is None:
            # Legacy shorthand like [> 10]: synthesize predicate_ast = [GetPath(Name(op))] + rhs_ast
            op = getattr(segment, 'operator', None)
            rhs_ast = getattr(segment, 'rhs_ast', None) or []
            if op is None:
                # No predicate and no operator → keep nothing by default
                return [] if isinstance(container, list) else View(container, [segment])
            pred = [GetPath([Name(op)])] + (rhs_ast if isinstance(rhs_ast, list) else [rhs_ast])

        if isinstance(container, list):
            out = []
            for item in container:
                try:
                    ok = await self.evaluator._eval_expr([item] + pred, scope)
                except Exception:
                    ok = False
                if ok:
                    out.append(item)
            return out
        # For non-list containers, return a simple View placeholder for future materialization.
        return View(container, [segment])

    async def set_vectorized_update(self, set_path: SetPath, update_expr_terms: list, scope: Scope):
        """
        Vectorized per-element update for patterns like: players.hp[< 50]: + 10
        Shape supported:
          - trailing FilterQuery
          - the segment before the filter is a Name (field),
          - the prefix resolves to a list container (e.g., players).
        Returns list of new values written.
        """
        segs = list(set_path.segments)
        if not segs or not isinstance(segs[-1], FilterQuery):
            raise NotImplementedError("vectorized update requires a trailing filter segment")
        filt = segs.pop()

        if not segs or not isinstance(segs[-1], Name):
            raise NotImplementedError("vectorized update expects a Name field before the filter")
        field_name = segs.pop().text

        # Resolve the base container (e.g., 'players')
        base_container = await self._resolve_value(GetPath(segs, getattr(set_path, 'meta', None)), scope)
        if not isinstance(base_container, list):
            raise TypeError("vectorized update base must be a list")

        # Build match list: (owner, old_val) for items passing the filter
        matches = []
        for item in base_container:
            # read field
            try:
                if isinstance(item, Scope):
                    val = item[field_name]
                elif isinstance(item, collections.abc.Mapping):
                    if field_name not in item:
                        continue
                    val = item[field_name]
                else:
                    val = getattr(item, field_name)
            except Exception:
                continue

            # predicate
            keep = True
            if getattr(filt, 'predicate_ast', None) is not None:
                try:
                    keep = await self.evaluator._eval_expr([val] + filt.predicate_ast, scope)
                except Exception:
                    keep = False
            else:
                # Legacy shorthand like [> 10]: synthesize predicate and evaluate via evaluator
                op = getattr(filt, 'operator', None)
                rhs_ast = getattr(filt, 'rhs_ast', None) or []
                pred = [GetPath([Name(op)])] + (rhs_ast if isinstance(rhs_ast, list) else [rhs_ast])
                try:
                    keep = await self.evaluator._eval_expr([val] + pred, scope)
                except Exception:
                    keep = False

            if keep:
                matches.append((item, val))

        # Apply update expression per match: new = f(old)
        out_vals = []
        for owner, old_val in matches:
            new_val = await self.evaluator._eval_expr([old_val] + update_expr_terms, scope)
            # write back
            try:
                if isinstance(owner, Scope) or hasattr(owner, '__getitem__') and hasattr(owner, '__setitem__'):
                    # Scope and mapping-like
                    if isinstance(owner, Scope):
                        owner[field_name] = new_val
                    else:
                        owner[field_name] = new_val
                else:
                    setattr(owner, field_name, new_val)
            except Exception as e:
                raise e
            out_vals.append(new_val)

        return out_vals

    async def set_vectorized_assign(self, set_path: SetPath, value_expr_terms: list, scope: Scope):
        """
        Vectorized assignment for patterns like:
          - players.hp[< 50]: 50         (broadcast)
          - players.hp[< 50]: #[51, 52]  (elementwise when lengths match)
        Same shape constraints as set_vectorized_update.
        Returns list of new values written.
        """
        segs = list(set_path.segments)
        if not segs or not isinstance(segs[-1], FilterQuery):
            raise NotImplementedError("vectorized assign requires a trailing filter segment")
        filt = segs.pop()

        if not segs or not isinstance(segs[-1], Name):
            raise NotImplementedError("vectorized assign expects a Name field before the filter")
        field_name = segs.pop().text

        base_container = await self._resolve_value(GetPath(segs, getattr(set_path, 'meta', None)), scope)
        if not isinstance(base_container, list):
            raise TypeError("vectorized assign base must be a list")

        # Collect owners that satisfy the filter
        owners = []
        for item in base_container:
            # read field for predicate
            try:
                if isinstance(item, Scope):
                    val = item[field_name]
                elif isinstance(item, collections.abc.Mapping):
                    if field_name not in item:
                        continue
                    val = item[field_name]
                else:
                    val = getattr(item, field_name)
            except Exception:
                continue

            keep = True
            if getattr(filt, 'predicate_ast', None) is not None:
                try:
                    keep = await self.evaluator._eval_expr([val] + filt.predicate_ast, scope)
                except Exception:
                    keep = False
            else:
                # Legacy shorthand like [> 10]: synthesize predicate and evaluate via evaluator
                op = getattr(filt, 'operator', None)
                rhs_ast = getattr(filt, 'rhs_ast', None) or []
                pred = [GetPath([Name(op)])] + (rhs_ast if isinstance(rhs_ast, list) else [rhs_ast])
                try:
                    keep = await self.evaluator._eval_expr([val] + pred, scope)
                except Exception:
                    keep = False

            if keep:
                owners.append(item)

        # Evaluate RHS once
        rhs_val = await self.evaluator._eval_expr(value_expr_terms, scope)

        new_values = []
        if isinstance(rhs_val, list):
            if len(rhs_val) != len(owners):
                raise TypeError(f"Vectorized assign length mismatch: {len(owners)} targets, {len(rhs_val)} values")
            pairs = zip(owners, rhs_val)
        else:
            pairs = ((o, rhs_val) for o in owners)

        for owner, new_val in pairs:
            try:
                if isinstance(owner, Scope) or hasattr(owner, '__getitem__') and hasattr(owner, '__setitem__'):
                    if isinstance(owner, Scope):
                        owner[field_name] = new_val
                    else:
                        owner[field_name] = new_val
                else:
                    setattr(owner, field_name, new_val)
            except Exception as e:
                raise e
            new_values.append(new_val)

        return new_values

class Evaluator:
    """The SLIP execution engine."""
    def __init__(self):
        self.path_resolver = PathResolver(self)
        self.side_effects: List[Any] = []
        self.is_in_task_context: bool = False
        self.host_object: Optional[Any] = None
        self.current_node = None
        # Count of active task contexts running on this evaluator (supports concurrency)
        self.task_context_count: int = 0
        self.call_stack = []
        self.current_source = None
        self.current_local_scope = None
        # When True, prefer binding into the current container scope even if a parent owns the key.
        # Used by run-with to avoid leaking writes into the caller's scope.
        self.bind_locals_prefer_container: bool = True

    def _push_frame(self, name, func, args, call_site_node):
        loc = getattr(call_site_node, 'loc', None)
        self.call_stack.append({
            'name': name,
            'func': func,
            'args': args,
            'call_site': loc,
            'source_kind': self.current_source,
        })

    def _pop_frame(self):
        if self.call_stack:
            self.call_stack.pop()

    def _dbg(self, *parts):
        import os, sys
        if os.environ.get("SLIP_DEBUG"):
            try:
                print("[DBG]", *parts, file=sys.stderr)
            except Exception:
                pass

    async def eval(self, node: Any, scope: Scope) -> Any:
        """Public entry point for evaluation. Unwraps 'return' responses."""
        self.current_node = node
        result = await self._eval(node, scope)
        if isinstance(result, Response) and result.status == GetPathLiteral([Name("return")]):
            return result.value
        return result

    async def _eval(self, node: Any, scope: Scope) -> Any:
        """Recursive dispatcher for evaluating any AST node."""
        self.current_node = node
        if isinstance(node, list):
            # An expression list from a code block `[...]` or group `(...)`
            if not node:
                return None
            
            # Heuristic to check if it's a list of expressions or one expression.
            # An expression's terms are never lists themselves (except for nested
            # structures like Group, which are handled before this).
            is_expression_list = isinstance(node[0], list)

            if is_expression_list:
                result = None
                for expr in node:
                    result = await self._eval_expr(expr, scope)
                    # Only propagate 'return' control-flow responses; other responses are data.
                    if isinstance(result, Response) and result.status == GetPathLiteral([Name("return")]):
                        return result
                return result
            else: # It's a single expression (list of terms)
                return await self._eval_expr(node, scope)

        match node:
            case GetPath():
                self.current_node = node
                return await self.path_resolver.get(node, scope)

            # Path literals evaluate to themselves (do not resolve)
            case GetPathLiteral() | SetPathLiteral() | DelPathLiteral() | MultiSetPathLiteral() | PipedPathLiteral():
                return node

            case Group():
                self.current_node = node
                return await self._eval(node.nodes, scope)

            case SlipList():
                results = []
                for expr in node.nodes:
                    # Special handling for list elements that are a single term which may be callable:
                    # auto-call only when there is an exact zero-arity (non-variadic) method.
                    if isinstance(expr, list) and len(expr) == 1:
                        term = expr[0]
                        val = await self._eval(term, scope)
                        should_auto_call = False

                        # GenericFunction: auto-call only if it has an exact 0-arity, non-variadic method.
                        if isinstance(val, GenericFunction):
                            for m in val.methods:
                                s = getattr(m, 'meta', {}).get('type')
                                if isinstance(s, Sig):
                                    base = len(s.positional) + len(s.keywords)
                                    if base == 0 and s.rest is None:
                                        should_auto_call = True
                                        break
                                elif isinstance(m.args, Code):
                                    # Legacy Code-args function with zero parameters
                                    if len(m.args.nodes) == 0:
                                        should_auto_call = True
                                        break

                        # SlipFunction: check its signature (or legacy Code args) for zero arity.
                        elif isinstance(val, SlipFunction):
                            s = getattr(val, 'meta', {}).get('type')
                            if isinstance(s, Sig):
                                base = len(s.positional) + len(s.keywords)
                                if base == 0 and s.rest is None:
                                    should_auto_call = True
                            elif isinstance(val.args, Code) and len(val.args.nodes) == 0:
                                should_auto_call = True

                        if should_auto_call:
                            results.append(await self.call(val, [], scope))
                        else:
                            results.append(val)
                    else:
                        results.append(await self._eval_expr(expr, scope))
                return results

            case ByteStream() as bs:
                # Evaluate items
                vals = []
                for expr in bs.nodes:
                    v = await self._eval_expr(expr, scope)
                    vals.append(v)
                # Pack to bytes according to elem_type
                import struct
                t = (bs.elem_type or '').lower()
                try:
                    if t == 'u8':
                        out = bytes(int(x) & 0xFF for x in vals)
                    elif t == 'i8':
                        out = bytes((int(x) + 256) % 256 for x in vals)
                    elif t == 'u16':
                        out = b''.join(struct.pack('<H', int(x) & 0xFFFF) for x in vals)
                    elif t == 'i16':
                        out = b''.join(struct.pack('<h', int(x)) for x in vals)
                    elif t == 'u32':
                        out = b''.join(struct.pack('<I', int(x) & 0xFFFFFFFF) for x in vals)
                    elif t == 'i32':
                        out = b''.join(struct.pack('<i', int(x)) for x in vals)
                    elif t == 'u64':
                        out = b''.join(struct.pack('<Q', int(x) & 0xFFFFFFFFFFFFFFFF) for x in vals)
                    elif t == 'i64':
                        out = b''.join(struct.pack('<q', int(x)) for x in vals)
                    elif t == 'f32':
                        out = b''.join(struct.pack('<f', float(x)) for x in vals)
                    elif t == 'f64':
                        out = b''.join(struct.pack('<d', float(x)) for x in vals)
                    elif t == 'b1':
                        # Pack bits MSB-first within each byte
                        b = 0
                        count = 0
                        chunks = []
                        for x in vals:
                            bit = 1 if bool(x) else 0
                            b = ((b << 1) | bit) & 0xFF
                            count += 1
                            if count == 8:
                                chunks.append(b.to_bytes(1, 'little'))
                                b = 0
                                count = 0
                        if count > 0:
                            # pad remaining bits to the left (MSB side)
                            b = (b << (8 - count)) & 0xFF
                            chunks.append(b.to_bytes(1, 'little'))
                        out = b''.join(chunks)
                    else:
                        raise TypeError(f"Unknown byte-stream type: {t!r}")
                except Exception as e:
                    raise TypeError(f"Invalid value for {t} byte stream: {e}")
                return out

            case tuple() as t if len(t) > 0 and t[0] == 'dict':
                from slip.slip_runtime import SlipDict
                # Use a child scope so lookups (e.g., +, names) resolve via the parent chain,
                # but ensure assignments inside the dict literal NEVER leak into the parent scope.
                temp_scope = Scope(parent=scope)
                for expr in node[1]:
                    # Fast path: simple "name: value" assignments write directly to the temp scope
                    if isinstance(expr, list) and expr and isinstance(expr[0], SetPath):
                        sp = expr[0]
                        if len(sp.segments) == 1 and isinstance(sp.segments[0], Name):
                            key = sp.segments[0].text
                            val = await self._eval_expr(expr[1:], temp_scope)
                            temp_scope[key] = val
                            continue
                    # Fallback: evaluate any other expressions for their value/side-effects
                    await self._eval_expr(expr, temp_scope)
                out = SlipDict()
                for k, v in temp_scope.bindings.items():
                    out[k] = v
                return out

            case Code():
                # Code is an unevaluated literal. It should be executed only by
                # primitives like run/run-with, if/while/foreach, list, dict, or fn.
                return node

            case IString():
                # Auto‑dedent and render with Mustache using the current lexical scope as context.
                raw = str(node)
                text = dedent(raw)
                if text.startswith("\n"):
                    text = text[1:]
                if text.endswith("\n"):
                    text = text[:-1]
                renderer = pystache.Renderer(escape=lambda u: u)
                try:
                    rendered = renderer.render(text, scope)
                except Exception:
                    rendered = text
                return IString(rendered)

            case _:
                # It's a literal (int, str, bool, None, etc.)
                return node

    async def _eval_expr(self, terms: List[Any], scope: Scope) -> Any:
        """Evaluates a single expression (a list of terms)."""
        if not terms:
            return None

        head_uneval = terms[0]

        # Handle assignment/deletion forms first, as they consume the whole expression.
        match head_uneval:
            case SetPath():
                value_expr = terms[1:]
                if not value_expr:
                    raise SyntaxError("SetPath must be followed by a value.")

                # Detect update-style RHS (seed with current value): "+ 1", "|heal", "|add 5", etc.
                # Determine if RHS starts with a pipe operator (literal or alias to a PipedPath)
                update_style = False
                first = value_expr[0] if value_expr else None
                if isinstance(first, PipedPath):
                    update_style = True
                elif isinstance(first, GetPath):
                    try:
                        resolved = await self._eval(first, scope)
                        update_style = isinstance(resolved, (PipedPath, PipedPathLiteral))
                    except Exception:
                        update_style = False

                # Vectorized write: LHS ending with a filter on a plucked field
                is_vectorized_target = (
                    len(head_uneval.segments) >= 2
                    and isinstance(head_uneval.segments[-1], FilterQuery)
                    and isinstance(head_uneval.segments[-2], Name)
                )
                if is_vectorized_target:
                    if update_style:
                        # Apply RHS as per-element update seeded with each old value
                        return await self.path_resolver.set_vectorized_update(head_uneval, value_expr, scope)
                    else:
                        # Plain assignment: broadcast or elementwise if RHS is list of matching length
                        return await self.path_resolver.set_vectorized_assign(head_uneval, value_expr, scope)

                if update_style:
                    # Try to read current value; if not found, or if the existing binding is itself a piped-path alias,
                    # treat as a normal assignment (e.g., "+: |add" or rebind "/+: |sub") rather than an update.
                    try:
                        cur_val = await self.path_resolver.get(GetPath(head_uneval.segments, head_uneval.meta), scope)
                        if isinstance(cur_val, (PipedPath, PipedPathLiteral)):
                            update_style = False
                    except PathNotFound:
                        update_style = False

                if update_style:
                    # Seed the RHS chain with the current value, evaluate, set, and return the new value.
                    new_value = await self._eval_expr([cur_val] + value_expr, scope)
                    if isinstance(new_value, Response) and new_value.status == GetPathLiteral([Name("return")]):
                        new_value = new_value.value
                    self.current_node = head_uneval
                    await self.path_resolver.set(head_uneval, new_value, scope)
                    return new_value

                # Normal assignment: evaluate RHS as a value, set, return the assigned value (or merged GF)
                self.current_node = head_uneval
                value = await self._eval_expr(value_expr, scope)
                if isinstance(value, Response) and value.status == GetPathLiteral([Name("return")]):
                    value = value.value

                # Alias write: if LHS is a simple name bound to a path, write to that path instead of rebinding
                if len(head_uneval.segments) == 1 and isinstance(head_uneval.segments[0], Name):
                    tname = head_uneval.segments[0].text
                    try:
                        existing = scope[tname]
                    except KeyError:
                        existing = None
                    from slip.slip_datatypes import GetPath as _GP, GetPathLiteral as _GPL
                    if isinstance(existing, _GPL):
                        existing = _GP(existing.segments, getattr(existing, 'meta', None))
                    if isinstance(existing, _GP):
                        await self.path_resolver.set(SetPath(existing.segments, getattr(existing, 'meta', None)), value, scope)
                        return value

                if isinstance(value, SlipFunction):
                    # Begin replacement: synthesize typed methods from examples when untyped
                    sig_obj = None
                    if hasattr(value, 'meta'):
                        mt = value.meta.get('type')
                        if isinstance(mt, Sig):
                            sig_obj = mt

                    def _pname(n):
                        return n if isinstance(n, str) else getattr(n, 'text', str(n))

                    async def _resolve_value(node_obj):
                        # Try in function closure first, then current scope
                        try:
                            return await self._eval(node_obj, value.closure)
                        except Exception:
                            return await self._eval(node_obj, scope)

                    def _infer_type_name(val: object) -> str:
                        from slip.slip_datatypes import (
                            Scope, Code, IString, SlipFunction as _SF, GenericFunction as _GF,
                            GetPath as _GP, SetPath as _SP, DelPath as _DP, PipedPath as _PP,
                            GetPathLiteral as _GPL, SetPathLiteral as _SPL, DelPathLiteral as _DPL,
                            PipedPathLiteral as _PPL, MultiSetPathLiteral as _MSPL
                        )
                        if val is None:
                            return 'none'
                        if isinstance(val, bool):
                            return 'boolean'
                        if isinstance(val, int) and not isinstance(val, bool):
                            return 'int'
                        if isinstance(val, float):
                            return 'float'
                        if isinstance(val, IString):
                            return 'i-string'
                        if isinstance(val, str):
                            return 'string'
                        if isinstance(val, list):
                            return 'list'
                        if isinstance(val, (dict, collections.abc.Mapping)):
                            return 'dict'
                        if isinstance(val, Scope):
                            return 'scope'
                        if isinstance(val, (_GP, _SP, _DP, _PP, _GPL, _SPL, _DPL, _PPL, _MSPL)):
                            return 'path'
                        if isinstance(val, (_SF, _GF)) or callable(val):
                            return 'function'
                        if isinstance(val, Code):
                            return 'code'
                        return 'string'

                    # Decide if function is already explicitly typed
                    has_explicit_types = isinstance(sig_obj, Sig) and bool(getattr(sig_obj, 'keywords', {}))

                    # Gather parameter names (for untyped functions)
                    param_names: list[str] = []
                    if isinstance(sig_obj, Sig) and not has_explicit_types:
                        param_names = [_pname(n) for n in (sig_obj.positional or [])]
                    elif sig_obj is None and isinstance(value.args, Code):
                        params = value.args.nodes
                        for param_expr in params:
                            pn = param_expr
                            if isinstance(pn, list) and len(pn) == 1:
                                pn = pn[0]
                            if isinstance(pn, GetPath) and len(pn.segments) == 1 and isinstance(pn.segments[0], Name):
                                param_names.append(pn.segments[0].text)

                    methods_to_add = []

                    if (not has_explicit_types) and getattr(value, 'meta', None):
                        examples = value.meta.get('examples') or []
                        for ex in examples:
                            if not isinstance(ex, Sig):
                                continue
                            # Only use keyworded examples for synthesis
                            ex_kws = getattr(ex, 'keywords', {}) or {}
                            if not ex_kws or not param_names:
                                continue
                            typed_kw = {}
                            ok = True
                            for pname in param_names:
                                if pname not in ex_kws:
                                    ok = False
                                    break
                                sample_spec = ex_kws[pname]
                                try:
                                    sample_val = await _resolve_value(sample_spec)
                                except Exception:
                                    ok = False
                                    break
                                tname = _infer_type_name(sample_val)
                                typed_kw[pname] = GetPath([Name(tname)])
                            if not ok or len(typed_kw) != len(param_names):
                                continue
                            typed_sig = Sig([], typed_kw, None, None)
                            clone = SlipFunction(value.args, value.body, value.closure)
                            clone.meta['type'] = typed_sig
                            clone.meta['examples'] = [ex]
                            if 'guards' in value.meta:
                                # Preserve any guards attached before synthesis
                                clone.meta['guards'] = list(value.meta['guards'])
                            methods_to_add.append(clone)

                    # Merge into a GenericFunction (existing or new)
                    # Local-only merge: do not pull an existing container from parent scopes.
                    lhs_name = head_uneval.segments[0].text if len(head_uneval.segments) == 1 and isinstance(head_uneval.segments[0], Name) else None
                    existing = scope.bindings.get(lhs_name) if (lhs_name is not None and isinstance(scope, Scope)) else None

                    if isinstance(existing, GenericFunction):
                        if methods_to_add:
                            for m in methods_to_add:
                                existing.add_method(m)
                            await self.path_resolver.set(head_uneval, existing, scope)
                            return existing
                        else:
                            existing.add_method(value)
                            await self.path_resolver.set(head_uneval, existing, scope)
                            return existing
                    else:
                        name = None
                        if isinstance(head_uneval.segments[-1], Name):
                            name = head_uneval.segments[-1].text
                        gf = GenericFunction(name)
                        if methods_to_add:
                            for m in methods_to_add:
                                gf.add_method(m)
                        else:
                            gf.add_method(value)
                        await self.path_resolver.set(head_uneval, gf, scope)
                        return gf
                    # End replacement
                else:
                    def _rhs_mentions_name(terms, target):
                        for t in terms:
                            if isinstance(t, GetPath) and len(t.segments) == 1 and isinstance(t.segments[0], Name) and t.segments[0].text == target:
                                return True
                            if isinstance(t, Group):
                                for expr in t.nodes:
                                    if _rhs_mentions_name(expr, target):
                                        return True
                            if isinstance(t, SlipList):
                                for expr in t.nodes:
                                    if _rhs_mentions_name(expr, target):
                                        return True
                            if isinstance(t, list):
                                if _rhs_mentions_name(t, target):
                                    return True
                        return False

                    prev_bind = getattr(self, 'bind_locals_prefer_container', False)
                    try:
                        # Default local-by-default
                        prefer_local = True
                        # If assigning to a simple local name and RHS references that name, and a parent owns it, prefer owner write
                        if len(head_uneval.segments) == 1 and isinstance(head_uneval.segments[0], Name):
                            tname = head_uneval.segments[0].text
                            has_local = isinstance(scope, Scope) and (tname in scope.bindings)
                            owner = scope.find_owner(tname) if isinstance(scope, Scope) else None
                            if (not has_local) and (owner is not None) and (owner is not scope):
                                if _rhs_mentions_name(value_expr, tname):
                                    prefer_local = False
                        self.bind_locals_prefer_container = prefer_local
                        await self.path_resolver.set(head_uneval, value, scope)
                    finally:
                        self.bind_locals_prefer_container = prev_bind
                    return value

            case tuple() as t if len(t) > 0 and t[0] == 'multi-set':
                set_paths = head_uneval[1]
                value_expr = terms[1:]
                if not value_expr:
                    raise SyntaxError("multi-set must be followed by a value.")
                values = await self._eval_expr(value_expr, scope)

                if not isinstance(values, list) or len(set_paths) != len(values):
                    raise TypeError(f"Multi-set mismatch: pattern requires {len(set_paths)} values, got {len(values)}")
                for path, value in zip(set_paths, values):
                    self.current_node = path
                    await self.path_resolver.set(path, value, scope)
                return None

            # Convenience: allow HTTP PUT using get-path + value, e.g.:
            #   http://host/path "body"
            # Treat as a SetPath to the same URL and perform PUT.
            case GetPath():
                try:
                    url = self.path_resolver._extract_http_url(head_uneval)
                except Exception:
                    url = None
                if url is not None and len(terms) >= 2:
                    # Evaluate RHS to a value, then write via PathResolver.set
                    value = await self._eval_expr(terms[1:], scope)
                    if isinstance(value, Response) and value.status == GetPathLiteral([Name("return")]):
                        value = value.value
                    await self.path_resolver.set(SetPath(head_uneval.segments, getattr(head_uneval, 'meta', None)), value, scope)
                    return value
                # Convenience: allow FS PUT using get-path + value, e.g.:
                #   fs://path/to/file "body"
                # Treat as a SetPath to the same locator and perform PUT.
                try:
                    fs_loc = self.path_resolver._extract_fs_locator(head_uneval)
                except Exception:
                    fs_loc = None
                if fs_loc is not None and len(terms) >= 2:
                    value = await self._eval_expr(terms[1:], scope)
                    if isinstance(value, Response) and value.status == GetPathLiteral([Name("return")]):
                        value = value.value
                    await self.path_resolver.set(SetPath(head_uneval.segments, getattr(head_uneval, 'meta', None)), value, scope)
                    return value

            case PostPath():
                value_expr = terms[1:]
                if not value_expr:
                    raise SyntaxError("PostPath must be followed by a value.")
                value = await self._eval_expr(value_expr, scope)
                if isinstance(value, Response) and value.status == GetPathLiteral([Name("return")]):
                    value = value.value
                self.current_node = head_uneval
                result = await self.path_resolver.post(head_uneval, value, scope)
                return result

            case DelPath():
                if len(terms) > 1:
                    raise SyntaxError("del-path cannot be part of a larger expression.")
                self.current_node = head_uneval
                await self.path_resolver.delete(head_uneval, scope)
                return None

        # If not assignment, it's a value/call expression.
        remaining_terms = terms
        # Check for special form (macro) call
        head_term = remaining_terms[0]
        if isinstance(head_term, GetPath):
            if len(head_term.segments) == 1 and isinstance(head_term.segments[0], Name):
                func_name = head_term.segments[0].text
                # Short-circuiting logical forms are treated as special forms (macros)
                if func_name in ('logical-and', 'logical-or'):
                    if len(remaining_terms) != 3:
                        raise TypeError(f"{func_name} expects exactly 2 arguments")
                    left = await self._eval(remaining_terms[1], scope)
                    if func_name == 'logical-and':
                        if not left:
                            return left
                        return await self._eval(remaining_terms[2], scope)
                    else:  # logical-or
                        if left:
                            return left
                        return await self._eval(remaining_terms[2], scope)
                if func_name in ('if', 'fn', 'while', 'foreach'):
                    self.current_node = head_term
                    func = await self.path_resolver.get(head_term, scope)

                    # Only consume args up to the first piped operator so chaining like:
                    #   fn {...} [...] |example {...}
                    # works by letting the pipe consume the function value.
                    split_at = None
                    for idx in range(1, len(remaining_terms)):
                        if isinstance(remaining_terms[idx], PipedPath):
                            split_at = idx
                            break
                    arg_end = split_at if split_at is not None else len(remaining_terms)
                    args_raw = remaining_terms[1:arg_end]

                    self._dbg("SPECIAL", func_name, "args_raw_types", [type(a).__name__ for a in args_raw])
                    self._push_frame(func_name, func, args_raw, head_term)
                    _ok = False
                    try:
                        if inspect.iscoroutinefunction(func):
                            result = await func(args_raw, scope=scope)
                        else:
                            result = func(args_raw, scope=scope)
                        _ok = True
                    finally:
                        if _ok:
                            self._pop_frame()

                    # If there is a trailing pipe/infix chain, continue evaluation with the result as LHS.
                    if split_at is not None:
                        return await self._eval_expr([result] + remaining_terms[arg_end:], scope)
                    return result

        # Evaluate the rest of the expression as a call chain
        self.current_node = remaining_terms[0]
        head_val = await self._eval(remaining_terms[0], scope)

        # Support mixing prefix-call followed by piped infix operators.
        # If a PipedPath appears, only consume args up to it for the prefix call.
        result = head_val
        k = 1
        if isinstance(head_val, SlipCallable) or callable(head_val):
            # Find first piped operator position (if any)
            split_at = None
            for idx in range(1, len(remaining_terms)):
                # Only actual PipedPath terms start an infix chain. A PipedPathLiteral is a value.
                if isinstance(remaining_terms[idx], PipedPath):
                    split_at = idx
                    break
            arg_end = split_at if split_at is not None else len(remaining_terms)
            arg_terms = remaining_terms[1:arg_end]

            # If a piped operator appears immediately after the head (e.g., "f |example ..."),
            # do NOT perform a zero-arity prefix call. Treat the head as a value and let
            # the pipe consume it as the left-hand argument.
            if split_at is not None and arg_end == 1:
                k = 1  # start processing at the piped operator
            else:
                # Determine display name for stack frame
                name = None
                if isinstance(remaining_terms[0], GetPath) and len(remaining_terms[0].segments) == 1 and isinstance(remaining_terms[0].segments[0], Name):
                    name = remaining_terms[0].segments[0].text

                evaluated_args = [await self._eval(arg, scope) for arg in arg_terms] if arg_terms else []
                self._dbg(
                    "CALL prefix",
                    getattr(head_val, "__class__", type(head_val)).__name__,
                    "argc", len(evaluated_args),
                    "arg_types", [type(a).__name__ for a in evaluated_args]
                )
                self._push_frame(name or '<call>', head_val, evaluated_args, remaining_terms[0])
                _ok = False
                try:
                    result = await self.call(head_val, evaluated_args, scope)
                    _ok = True
                finally:
                    if _ok:
                        self._pop_frame()
                k = arg_end
        while k < len(remaining_terms):
            op_term = remaining_terms[k]
            raw_op_term = op_term # Preserve original term for error reporting
            func_path = None

            # Resolve operator term, potentially through multiple aliases, until we find a PipedPath.
            self.current_node = raw_op_term
            # Pre-normalize ambiguous '/' token parsed as Root into operator name '/'
            if isinstance(raw_op_term, GetPath) and len(raw_op_term.segments) == 1 and raw_op_term.segments[0] is Root:
                raw_op_term = GetPath([Name('/')], raw_op_term.meta)
            op_val = await self._eval(raw_op_term, scope)

            # Keep resolving/unwrapping aliases until we find a PipedPath.
            while not isinstance(op_val, PipedPath):
                # Normalize ambiguous '/' token parsed as Root into operator name '/'
                if isinstance(op_val, GetPath) and len(op_val.segments) == 1 and op_val.segments[0] is Root:
                    op_val = GetPath([Name('/')], op_val.meta)
                    continue
                # Convert path literals to runtime path types first
                if isinstance(op_val, GetPathLiteral):
                    op_val = GetPath(op_val.segments, op_val.meta)
                    continue
                if isinstance(op_val, PipedPathLiteral):
                    op_val = PipedPath(op_val.segments, op_val.meta)
                    continue
                # Resolve GetPath references from scope (e.g., '+' -> '|add')
                if isinstance(op_val, GetPath):
                    op_val = await self._eval(op_val, scope)
                    continue
                # Unwrap simple Group/Code wrappers
                if isinstance(op_val, Group) and op_val.nodes and isinstance(op_val.nodes[0], list) and op_val.nodes[0]:
                    op_val = op_val.nodes[0][0]
                    continue
                if isinstance(op_val, Code) and len(op_val.nodes) == 1 and op_val.nodes[0]:
                    op_val = op_val.nodes[0][0]
                    continue

                # If we're here, we couldn't resolve/unwrap it further.
                err = TypeError("Unexpected term in expression - expected a piped-path for infix operation")
                try:
                    err.slip_obj = raw_op_term
                except Exception:
                    pass
                raise err

            # We have a PipedPath, so create the GetPath for the call.
            func_path = GetPath(op_val.segments, op_val.meta)

            # Preserve source location from the operator token for error reporting
            if hasattr(raw_op_term, 'loc'):
                try:
                    func_path.loc = raw_op_term.loc
                except Exception:
                    pass

            # Identify function name (for special short-circuit ops)
            func_name = None
            if func_path.segments and isinstance(func_path.segments[-1], Name):
                func_name = func_path.segments[-1].text

            # Decide whether to treat current piped op as unary
            unary_mode = False
            if k + 1 >= len(remaining_terms):
                unary_mode = True
            else:
                # Peek next term: if it resolves to a PipedPath (an operator), this op is unary
                try:
                    peek_raw = remaining_terms[k + 1]
                    self.current_node = peek_raw
                    peek_val = await self._eval(peek_raw, scope)
                    pv = peek_val
                    while True:
                        if isinstance(pv, PipedPath):
                            unary_mode = True
                            break
                        if isinstance(pv, GetPathLiteral):
                            pv = GetPath(pv.segments, pv.meta); continue
                        if isinstance(pv, PipedPathLiteral):
                            pv = PipedPath(pv.segments, pv.meta); continue
                        if isinstance(pv, GetPath):
                            pv = await self._eval(pv, scope); continue
                        if isinstance(pv, Group) and pv.nodes and isinstance(pv.nodes[0], list) and pv.nodes[0]:
                            pv = pv.nodes[0][0]; continue
                        if isinstance(pv, Code) and len(pv.nodes) == 1 and pv.nodes[0]:
                            pv = pv.nodes[0][0]; continue
                        break
                except Exception:
                    unary_mode = False

            if unary_mode:
                # Support unary piped ops: treat "|fn" as a unary call with only the LHS.
                if func_name in ('logical-and', 'logical-or'):
                    raise SyntaxError("Infix operator missing right-hand side")
                self.current_node = func_path
                func = await self.path_resolver.get(func_path, scope)
                self._push_frame(func_name or '<pipe>', func, [result], func_path)
                _ok = False
                try:
                    result = await self.call(func, [result], scope)
                    _ok = True
                finally:
                    if _ok:
                        self._pop_frame()
                k += 1
                continue

            if func_name == 'logical-and':
                # Short-circuit: only evaluate RHS if LHS is truthy
                if not result:
                    k += 2
                    continue
                self.current_node = remaining_terms[k + 1]
                self.current_node = remaining_terms[k + 1]
                rhs_arg = await self._eval(remaining_terms[k + 1], scope)
                result = rhs_arg
                k += 2
                continue

            if func_name == 'logical-or':
                # Short-circuit: only evaluate RHS if LHS is falsey
                if result:
                    k += 2
                    continue
                rhs_arg = await self._eval(remaining_terms[k + 1], scope)
                result = rhs_arg
                k += 2
                continue

            # Special-case: attach examples without calling into StdLib for Sig RHS
            if not unary_mode and func_name == 'example':
                rhs_term = remaining_terms[k + 1]
                if isinstance(rhs_term, Sig):
                    from slip.slip_datatypes import SlipFunction as _SF, GenericFunction as _GF
                    target = result
                    if isinstance(target, (_SF, _GF)):
                        # Attach example to target.meta.examples
                        meta = getattr(target, 'meta', None)
                        if meta is None:
                            try:
                                target.meta = {}
                                meta = target.meta
                            except Exception:
                                pass
                        if isinstance(meta, dict):
                            examples = meta.setdefault('examples', [])
                            examples.append(rhs_term)
                            result = target
                            k += 2
                            continue
                # If target isn’t a function/generic, fall through to normal call

            # Special-case: attach guards without calling into StdLib when RHS is a Code block
            if not unary_mode and func_name == 'guard':
                rhs_term = remaining_terms[k + 1]
                # Accept a literal Code block or a variable that evaluates to Code
                cond_code = rhs_term if isinstance(rhs_term, Code) else None
                if cond_code is None:
                    try:
                        maybe = await self._eval(rhs_term, scope)
                        if isinstance(maybe, Code):
                            cond_code = maybe
                    except Exception:
                        cond_code = None
                if cond_code is not None:
                    target = result
                    from slip.slip_datatypes import SlipFunction as _SF, GenericFunction as _GF
                    if isinstance(target, (_SF, _GF)):
                        meta = getattr(target, 'meta', None)
                        if meta is None:
                            try:
                                target.meta = {}
                                meta = target.meta
                            except Exception:
                                meta = None
                        if isinstance(meta, dict):
                            guards_list = meta.setdefault('guards', [])
                            guards_list.append(cond_code)
                            result = target
                            k += 2
                            continue
                # If not a Code block, fall through to normal call

            # Normal infix: evaluate RHS and call the function
            self.current_node = remaining_terms[k + 1]
            rhs_term = remaining_terms[k + 1]
            if isinstance(rhs_term, Sig):
                rhs_arg = rhs_term
            else:
                rhs_arg = await self._eval(rhs_term, scope)
            self.current_node = func_path
            func = await self.path_resolver.get(func_path, scope)
            self._dbg("PIPE", func_name, "lhs_type", type(result).__name__, "rhs_type", type(rhs_arg).__name__)
            self._push_frame(func_name or '<pipe>', func, [result, rhs_arg], func_path)
            _ok = False
            try:
                result = await self.call(func, [result, rhs_arg], scope)
                _ok = True
            finally:
                if _ok:
                    self._pop_frame()
            k += 2

        return result


    async def _sig_types_match(self, sig, method, args, scope) -> bool:
        # No typed constraints -> always matches
        if not getattr(sig, "keywords", None):
            return True

        # Primitive type names we recognize in annotations
        PRIMITIVES = {
            'int', 'float', 'string', 'i-string',
            'list', 'dict', 'scope', 'function',
            'code', 'path', 'boolean', 'none'
        }

        # Helper: compute primitive type name for a value (mirrors StdLib._type_of)
        def _type_name(val: object) -> str:
            if val is None:
                return 'none'
            if isinstance(val, bool):
                return 'boolean'
            if isinstance(val, int) and not isinstance(val, bool):
                return 'int'
            if isinstance(val, float):
                return 'float'
            if isinstance(val, IString):
                return 'i-string'
            if isinstance(val, str):
                return 'string'
            if isinstance(val, list):
                return 'list'
            if isinstance(val, (dict, collections.abc.Mapping)):
                return 'dict'
            if isinstance(val, Scope):
                return 'scope'
            if isinstance(val, (GetPath, SetPath, DelPath, PipedPath,
                                GetPathLiteral, SetPathLiteral, DelPathLiteral, PipedPathLiteral, MultiSetPathLiteral)):
                return 'path'
            if isinstance(val, (SlipFunction, GenericFunction)) or callable(val):
                return 'function'
            if isinstance(val, Code):
                return 'code'
            # Fallback: treat unknowns as string-like for typing purposes
            return 'string'

        def _scope_matches(val_scope: Scope, target: Scope) -> bool:
            if not isinstance(val_scope, Scope):
                return False
            if val_scope is target:
                return True
            # Recurse into mixins (and their own parents/mixins)
            try:
                for mix in val_scope.meta.get("mixins", []):
                    if _scope_matches(mix, target):
                        return True
            except Exception:
                pass
            # Walk prototype chain
            cur = val_scope.parent
            while isinstance(cur, Scope):
                if cur is target:
                    return True
                cur = cur.parent
            return False

        offset = len(sig.positional)
        idx = 0
        for _, type_spec in sig.keywords.items():
            # Normalize path-literal annotations to runtime get-path form
            if isinstance(type_spec, GetPathLiteral):
                type_spec = GetPath(type_spec.segments, type_spec.meta)

            arg_i = offset + idx
            if arg_i >= len(args):
                return False
            val = args[arg_i]

            # Try to resolve a scope annotation first (prototype/type dispatch)
            target_scope = None
            resolved_val = None
            # Normalize backticked single-name annotations like `list-like` to plain name for resolution
            if isinstance(type_spec, GetPath) and len(type_spec.segments) == 1 and isinstance(type_spec.segments[0], Name):
                ntext = type_spec.segments[0].text
                if isinstance(ntext, str) and len(ntext) >= 2 and ntext[0] == '`' and ntext[-1] == '`':
                    type_spec = GetPath([Name(ntext[1:-1])], getattr(type_spec, 'meta', None))
            if isinstance(type_spec, GetPath):
                # Resolve in method closure first, then in current scope
                try:
                    resolved_val = await self.path_resolver.get(type_spec, method.closure)
                except Exception:
                    try:
                        resolved_val = await self.path_resolver.get(type_spec, scope)
                    except Exception:
                        resolved_val = None
            elif isinstance(type_spec, Scope):
                target_scope = type_spec

            # If the resolved value is a Scope (prototype or mixin), enforce capability match
            if isinstance(resolved_val, Scope) or isinstance(target_scope, Scope):
                target = resolved_val if isinstance(resolved_val, Scope) else target_scope
                if not isinstance(val, Scope):
                    return False
                if not _scope_matches(val, target):
                    return False
                idx += 1
                continue

            # Union alias: if the resolved annotation is a Sig, treat its positional names as a set of allowed primitive types
            if isinstance(resolved_val, Sig):
                allowed: set[str] = set()
                for item in getattr(resolved_val, 'positional', []) or []:
                    n = None
                    if isinstance(item, str):
                        n = item
                    else:
                        try:
                            # Accept simple GetPath names as well
                            if isinstance(item, GetPath) and len(item.segments) == 1 and isinstance(item.segments[0], Name):
                                n = item.segments[0].text
                        except Exception:
                            n = None
                    if isinstance(n, str) and len(n) >= 2 and n[0] == '`' and n[-1] == '`':
                        n = n[1:-1]
                    if isinstance(n, str):
                        allowed.add(n)
                if allowed and _type_name(val) not in allowed:
                    return False
                idx += 1
                continue

            # If not a Scope annotation, check for primitive type path annotation like `string`, `int`, `path`, ...
            ann_name = None
            if isinstance(type_spec, GetPath) and len(type_spec.segments) == 1 and isinstance(type_spec.segments[0], Name):
                ann_name = type_spec.segments[0].text
                # Signature annotations often come from backticked path literals in sigs: `string`, `int`, etc.
                # Normalize by stripping surrounding backticks so we can match primitive names.
                if isinstance(ann_name, str) and len(ann_name) >= 2 and ann_name[0] == '`' and ann_name[-1] == '`':
                    ann_name = ann_name[1:-1]

            if ann_name in PRIMITIVES:
                if _type_name(val) != ann_name:
                    return False
                idx += 1
                continue

            # Unknown/unsupported annotation form -> ignore constraint
            idx += 1

        return True

    async def call(self, func: Any, args: List[Any], scope: Scope):
        """Calls a callable (SlipFunction or Python function)."""
        from slip.slip_datatypes import GenericFunction, Sig as SigType
        self._dbg("Evaluator.call", type(func).__name__, "argc", len(args))
        # Normalize arguments: unwrap 'return' responses so nested calls receive values.
        if isinstance(args, list):
            args = [
                (a.value if isinstance(a, Response) and a.status == GetPathLiteral([Name("return")]) else a)
                for a in args
            ]

        match func:
            case GenericFunction():
                # Helper to build a scope for evaluating guards with parameters bound
                def _build_guard_scope(method: SlipFunction):
                    call_scope = Scope(parent=method.closure)
                    s = getattr(method, 'meta', {}).get('type')
                    if isinstance(s, SigType):
                        # Bind positional
                        for param_name, arg_val in zip(s.positional, args):
                            name = param_name if isinstance(param_name, str) else getattr(param_name, 'text', str(param_name))
                            call_scope[name] = arg_val
                        # Bind keyword (treated positionally by declaration order)
                        offset = len(s.positional)
                        for i, param_name in enumerate(s.keywords.keys()):
                            if offset + i < len(args):
                                name = param_name if isinstance(param_name, str) else getattr(param_name, 'text', str(param_name))
                                call_scope[name] = args[offset + i]
                        # Bind rest if present
                        if s.rest is not None:
                            name = s.rest if isinstance(s.rest, str) else getattr(s.rest, 'text', str(s.rest))
                            base = len(s.positional) + len(s.keywords)
                            call_scope[name] = args[base:] if len(args) > base else []
                    elif isinstance(method.args, Code):
                        params = method.args.nodes
                        for param_expr, arg_val in zip(params, args):
                            pn = param_expr
                            if isinstance(pn, list) and len(pn) == 1:
                                pn = pn[0]
                            if isinstance(pn, GetPath) and len(pn.segments) == 1 and isinstance(pn.segments[0], Name):
                                call_scope[pn.segments[0].text] = arg_val
                    return call_scope

                exact_nonvar_guarded: list[SlipFunction] = []
                exact_nonvar_plain: list[SlipFunction] = []
                variadic_ok_guarded: list[tuple[int, SlipFunction]] = []
                variadic_ok_plain: list[tuple[int, SlipFunction]] = []
                no_sig_guarded: list[SlipFunction] = []
                no_sig_plain: list[SlipFunction] = []

                for m in func.methods:
                    s = getattr(m, 'meta', {}).get('type')
                    guards = getattr(m, 'meta', {}).get('guards') or []
                    types_ok = True
                    base = 0
                    if isinstance(s, SigType):
                        base = len(s.positional) + len(s.keywords)
                        types_ok = await self._sig_types_match(s, m, args, scope)
                        self._dbg("GF method", getattr(m, 'name', None) or repr(m), "base", base, "rest", bool(s.rest), "types_ok", types_ok)
                    # Evaluate guards if present
                    guard_ok = True
                    if guards:
                        guard_scope = _build_guard_scope(m)
                        for g in guards:
                            val = await self._eval(g.ast, guard_scope) if isinstance(g, Code) else await self._eval(g, guard_scope)
                            if isinstance(val, Response) and val.status == GetPathLiteral([Name("return")]):
                                val = val.value
                            if not val:
                                guard_ok = False
                                break
                    if not guard_ok:
                        continue  # skip this method entirely

                    if isinstance(s, SigType):
                        if s.rest is None and len(args) == base and types_ok:
                            (exact_nonvar_guarded if guards else exact_nonvar_plain).append(m)
                        elif s.rest is not None and len(args) >= base and types_ok:
                            (variadic_ok_guarded if guards else variadic_ok_plain).append((base, m))
                    else:
                        (no_sig_guarded if guards else no_sig_plain).append(m)

                # 1) Prefer exact-arity, non-variadic; guarded methods outrank plain
                if exact_nonvar_guarded:
                    self._dbg("GF pick exact_guarded", repr(exact_nonvar_guarded[-1]))
                    return await self.call(exact_nonvar_guarded[-1], args, scope)
                if exact_nonvar_plain:
                    self._dbg("GF pick exact_plain", repr(exact_nonvar_plain[-1]))
                    return await self.call(exact_nonvar_plain[-1], args, scope)

                # 2) Prefer variadic with the largest base arity; guarded outrank plain
                if variadic_ok_guarded:
                    max_base = max(b for b, _ in variadic_ok_guarded)
                    options = [m for b, m in variadic_ok_guarded if b == max_base]
                    self._dbg("GF pick variadic_guarded_base", max_base, "chosen", repr(options[-1]))
                    return await self.call(options[-1], args, scope)
                if variadic_ok_plain:
                    max_base = max(b for b, _ in variadic_ok_plain)
                    options = [m for b, m in variadic_ok_plain if b == max_base]
                    self._dbg("GF pick variadic_plain_base", max_base, "chosen", repr(options[-1]))
                    return await self.call(options[-1], args, scope)

                # 3) Fallbacks: prefer most recently defined; guarded outrank plain
                if no_sig_guarded:
                    self._dbg("GF pick no_sig_guarded", repr(no_sig_guarded[-1]))
                    return await self.call(no_sig_guarded[-1], args, scope)
                if func.methods:
                    self._dbg("GF pick fallback", repr(func.methods[-1]))
                    return await self.call(func.methods[-1], args, scope)

                raise TypeError(f"No methods defined for generic function {func.name!r}")

            case SlipFunction():
                # A function call creates a new scope. The parent of this scope for
                # variable lookup is the scope where the function was defined (its closure).
                call_scope = Scope(parent=func.closure)
                # Prefer signature-based binding when available. Fall back to legacy Code arg lists.
                sig_obj = None
                if hasattr(func, 'meta'):
                    mt = func.meta.get('type')
                    if isinstance(mt, SigType):
                        sig_obj = mt
                # Extra safety: if meta.type wasn't set for some reason, but args holds a Sig, use it.
                if sig_obj is None and isinstance(func.args, SigType):
                    sig_obj = func.args

                self._dbg("SlipFunction call", repr(func), "argc", len(args), "has_sig", bool(sig_obj))
                if isinstance(sig_obj, SigType):
                    sig = sig_obj
                    # Normalize parameter name to a plain string
                    def _pname(n):
                        return n if isinstance(n, str) else getattr(n, 'text', str(n))
                    # Bind positional names
                    for param_name, arg_val in zip(sig.positional, args):
                        call_scope[_pname(param_name)] = arg_val
                    self._dbg("Bind positional", [((n if isinstance(n, str) else getattr(n, 'text', str(n))), type(v).__name__) for n, v in zip(sig.positional, args)])
                    # Bind typed keyword parameters (treated as positional in order of declaration)
                    offset = len(sig.positional)
                    for i, param_name in enumerate(sig.keywords.keys()):
                        if offset + i < len(args):
                            call_scope[_pname(param_name)] = args[offset + i]
                    self._dbg("Bind keywords", list(sig.keywords.keys()))
                    # Handle rest parameter
                    base_arity = len(sig.positional) + len(sig.keywords)
                    if sig.rest is not None:
                        call_scope[_pname(sig.rest)] = args[base_arity:] if len(args) > base_arity else []
                        self._dbg("Bind rest", (sig.rest if isinstance(sig.rest, str) else getattr(sig.rest, 'text', str(sig.rest))), "count", max(0, len(args) - base_arity))

                elif isinstance(func.args, Code):
                    self._dbg("Legacy arg binding", "param_count", len(func.args.nodes), "argc", len(args))
                    # The AST for parameters like `[x]` from parser is `[[GetPath('x')]]`.
                    # Manually constructed test ASTs may incorrectly be `[GetPath('x')]`.
                    params = func.args.nodes
                    if len(params) > len(args):
                        raise TypeError(f"Function requires at least {len(params)} arguments, got {len(args)}")

                    for param_expr, arg_val in zip(params, args):
                        param_node = param_expr
                        if isinstance(param_node, list) and len(param_node) == 1:
                            param_node = param_node[0]
                        if isinstance(param_node, GetPath) and len(param_node.segments) == 1 and isinstance(param_node.segments[0], Name):
                            call_scope[param_node.segments[0].text] = arg_val
                        else:
                            raise NotImplementedError(f"Unsupported parameter expression: {param_expr}")
                else:
                    # No parameters to bind or unsupported type
                    pass

                # Evaluate the function body in the new call scope, and mark it as active
                prev_local = self.current_local_scope
                self.current_local_scope = call_scope
                try:
                    try:
                        self._dbg("Call-scope bindings", list(call_scope.keys()))
                    except Exception:
                        pass
                    result = await self._eval(func.body.nodes, call_scope)
                finally:
                    self.current_local_scope = prev_local
                if isinstance(result, Response):
                    # Unwrap 'return' control-flow when leaving a SLIP function call.
                    if result.status == GetPathLiteral([Name("return")]):
                        return result.value
                    return result
                return result

            case _ if callable(func):
                # Prepare kwargs for Python functions that need `scope`
                kwargs = {}
                try:
                    sig = inspect.signature(func)
                    if 'scope' in sig.parameters and sig.parameters['scope'].kind == inspect.Parameter.KEYWORD_ONLY:
                        kwargs['scope'] = scope
                except (ValueError, TypeError): # some builtins can't be inspected
                    pass

                if inspect.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                result = func(*args, **kwargs)
                if inspect.isawaitable(result):
                    # Do not await asyncio.Task; return handle so background tasks remain concurrent
                    if isinstance(result, asyncio.Task):
                        return result
                    return await result
                return result

            case _:
                raise TypeError(f"Object is not callable: {repr(func)}")

