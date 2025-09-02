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
    PathLiteral, PathNotFound,
    GetPath, SetPath, DelPath, Name, Index, Slice, Group, FilterQuery,
    Root, Parent, Pwd, PipedPath, PathSegment, SlipCallable, Sig, PostPath, ByteStream, MultiSetPath
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

    def _build_item_overlay_scope(self, item, parent: Scope) -> Scope:
        s = Scope(parent=parent)
        try:
            # Scope-like
            from slip.slip_datatypes import Scope as _Scope
            if isinstance(item, _Scope):
                for k, v in item.bindings.items():
                    s[k] = v
            # Mapping-like
            elif isinstance(item, collections.abc.Mapping):
                for k in item.keys():
                    try:
                        key = str(k)
                        s[key] = item[k]
                    except Exception:
                        continue
            else:
                # Plain object: expose public attributes (non-callables, no _ prefix)
                for name in dir(item):
                    if name.startswith('_'):
                        continue
                    try:
                        v = getattr(item, name)
                        if callable(v):
                            continue
                        s[name] = v
                    except Exception:
                        continue
        except Exception:
            pass
        return s

    def _normalize_relative_predicate_terms(self, terms):
        # Strip a leading '.' in single-name GetPath nodes to support .hp syntax.
        from slip.slip_datatypes import GetPath as _GP, Name as _Name, Group as _Group, List as _List, Parent as _Parent
        def norm_term(t):
            if isinstance(t, _GP) and t.segments and isinstance(t.segments[0], _Name):
                txt = t.segments[0].text
                if isinstance(txt, str):
                    if txt.startswith('.') and len(txt) > 1:
                        # .field -> field (item-relative; evaluate in overlay)
                        new_first = _Name(txt[1:])
                        segs = [new_first] + list(t.segments[1:])
                        return _GP(segs, getattr(t, 'meta', None))
                    else:
                        # Bare name -> force lexical: rewrite to ../name so overlay cannot shadow it
                        segs = [_Parent, _Name(txt)] + list(t.segments[1:])
                        return _GP(segs, getattr(t, 'meta', None))
                return t
            if isinstance(t, _Group):
                # Recurse into nested expression lists
                inner = []
                for expr in t.nodes:
                    inner.append([norm_term(x) for x in expr])
                g = _Group(inner)
                try:
                    g.loc = getattr(t, 'loc', None)
                except Exception:
                    pass
                return g
            if isinstance(t, _List):
                # Recurse into list literal expressions
                inner = []
                for expr in t.nodes:
                    inner.append([norm_term(x) for x in expr])
                l = _List(inner)
                try:
                    l.loc = getattr(t, 'loc', None)
                except Exception:
                    pass
                return l
            return t
        return [norm_term(x) for x in terms]

    def _split_top_level_and(self, terms):
        from slip.slip_datatypes import GetPath as _GP, Name as _Name, Parent as _Parent
        if not isinstance(terms, list):
            return None
        for i, t in enumerate(terms):
            if isinstance(t, _GP):
                segs = getattr(t, 'segments', [])
                if len(segs) == 1 and isinstance(segs[0], _Name) and segs[0].text in ('and', 'logical-and'):
                    left = terms[:i]
                    right = terms[i+1:]
                    return left, right
                if len(segs) == 2 and segs[0] is _Parent and isinstance(segs[1], _Name) and segs[1].text in ('and', 'logical-and'):
                    left = terms[:i]
                    right = terms[i+1:]
                    return left, right
        return None

    async def _get_segment_key(self, segment: PathSegment, scope: Scope) -> Any:
        """Evaluates a path segment to determine the key for a lookup."""
        match segment:
            case Name():
                txt = segment.text
                # Normalize leading-dot names like ".outcome" after groups into "outcome"
                if isinstance(txt, str) and txt.startswith('.') and len(txt) > 1:
                    return txt[1:]
                return txt
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
            # Cut at the first occurrence of known SLIP suffix markers
            cut_at = len(u)
            for ch in ("#", "["):
                idx = u.find(ch)
                if idx != -1:
                    cut_at = min(cut_at, idx)
            u = u[:cut_at]
            # If a dot-chained SLIP name follows the URL path (after the first '/'),
            # treat it as a SLIP segment, not part of the URL.
            scheme_i = u.find("://")
            if scheme_i != -1:
                slash_i = u.find("/", scheme_i + 3)
                if slash_i != -1:
                    # Only strip dots occurring in the path portion (not in the host)
                    dot_i = u.find(".", slash_i + 1)
                    if dot_i != -1:
                        u = u[:dot_i]
            # Trailing colon from set-path tokens
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
                # Cut at the first occurrence of known SLIP suffix markers
                cut_at = len(u)
                for ch in ("#", "["):
                    idx = u.find(ch)
                    if idx != -1:
                        cut_at = min(cut_at, idx)
                u = u[:cut_at]
                # If a dot-chained SLIP name follows the URL path (after the first '/'),
                # treat it as a SLIP segment, not part of the URL.
                scheme_i = u.find("://")
                if scheme_i != -1:
                    slash_i = u.find("/", scheme_i + 3)
                    if slash_i != -1:
                        dot_i = u.find(".", slash_i + 1)
                        if dot_i != -1:
                            u = u[:dot_i]
                if isinstance(path, SetPath) or u.endswith(":"):
                    u = u.rstrip(":")
                if os.environ.get("SLIP_HTTP_DEBUG"):
                    try:
                        print(f"[SLIP_HTTP_DEBUG] URL from first segment: {u}", file=sys.stderr)
                    except Exception:
                        pass
                return u
        return None

    def _extract_file_locator(self, path: GetPath | SetPath) -> str | None:
        loc = getattr(path, 'loc', None) or {}
        txt = loc.get('text') if isinstance(loc, dict) else None
        if isinstance(txt, str) and txt.startswith("file://"):
            u = txt.rstrip()
            # Strip any inline metadata (e.g., "#(...)") that may be present in the token text
            # Be robust: cut at the first '#' to handle tokens like "...#:" as well.
            hash_idx = u.find("#")
            if hash_idx != -1:
                u = u[:hash_idx]
            br_idx = u.find("[")
            if br_idx != -1:
                u = u[:br_idx]
            if isinstance(path, SetPath) or u.endswith(":"):
                u = u.rstrip(":")
            # Canonicalize bare and relative forms
            try:
                tail = u[len("file://"):]
                if tail in ("", "/", ".", "./"):
                    return "file://./"
                if tail in ("..", "../"):
                    return "file://../"
            except Exception:
                pass
            return u
        segments = getattr(path, 'segments', None) or []
        if segments and isinstance(segments[0], Name):
            s0 = segments[0].text
            if isinstance(s0, str) and s0.startswith("file://"):
                u = s0
                # Trim any inline metadata fragment, e.g., "#(...)"
                hash_idx = u.find("#")
                if hash_idx != -1:
                    u = u[:hash_idx]
                if isinstance(path, SetPath) or u.endswith(":"):
                    u = u.rstrip(":")
                # Canonicalize bare and relative forms
                try:
                    tail = u[len("file://"):]
                    if tail in ("", "/", ".", "./"):
                        return "file://./"
                    if tail in ("..", "../"):
                        return "file://../"
                except Exception:
                    pass
                return u
        return None

    def _has_http_trailing_segments(self, path: GetPath | SetPath | PostPath) -> bool:
        """
        Returns True if the original token text indicates trailing SLIP segments
        (dot-chained names or bracketed queries) after an http(s) URL.
        This catches cases where the parser kept those in the first segment.
        """
        segments = getattr(path, 'segments', None) or []
        if len(segments) > 1:
            return True
        loc = getattr(path, 'loc', None) or {}
        txt = loc.get('text') if isinstance(loc, dict) else None
        if isinstance(txt, str) and (txt.startswith("http://") or txt.startswith("https://")):
            scheme_i = txt.find("://")
            if scheme_i != -1:
                slash_i = txt.find("/", scheme_i + 3)
                if slash_i != -1:
                    # Any bracket after the first slash indicates trailing query segments
                    if txt.find("[", slash_i + 1) != -1:
                        return True
                    # A dot after the first slash (before any '#') indicates dot-chained SLIP name
                    stop = txt.find("#", slash_i + 1)
                    if stop == -1:
                        stop = len(txt)
                    if txt.find(".", slash_i + 1, stop) != -1:
                        return True
        # Fallback: inspect the first Name segment text when loc.text is unavailable or incomplete
        segments = getattr(path, 'segments', None) or []
        if segments and isinstance(segments[0], Name):
            s0 = segments[0].text
            if isinstance(s0, str) and (s0.startswith("http://") or s0.startswith("https://")):
                scheme_i = s0.find("://")
                if scheme_i != -1:
                    slash_i = s0.find("/", scheme_i + 3)
                    if slash_i != -1:
                        # Any bracket after the first slash indicates trailing query segments
                        if s0.find("[", slash_i + 1) != -1:
                            return True
                        # A dot after the first slash (before any '#') indicates dot-chained SLIP name
                        stop = s0.find("#", slash_i + 1)
                        if stop == -1:
                            stop = len(s0)
                        if s0.find(".", slash_i + 1, stop) != -1:
                            return True
        return False

    def _has_file_trailing_segments(self, path: GetPath | SetPath | PostPath) -> bool:
        """
        Returns True if a file:// path includes any trailing SLIP segments.
        Treats bracketed queries as trailing; dot detection is avoided to not
        confuse filename extensions.
        """
        segments = getattr(path, 'segments', None) or []
        if len(segments) > 1:
            return True
        loc = getattr(path, 'loc', None) or {}
        txt = loc.get('text') if isinstance(loc, dict) else None
        if isinstance(txt, str) and txt.startswith("file://"):
            # Any bracket after the scheme indicates a query segment in source
            if "[" in txt:
                return True
        return False

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
            # Enforce two-step policy: no trailing segments on HTTP GET
            if self._has_http_trailing_segments(path):
                raise TypeError("http get does not support trailing path segments; bind the response then filter")
            from slip.slip_http import http_get  # local import to avoid hard dependency until needed
            cfg = await self._meta_to_dict(getattr(path, 'meta', None), scope)

            def _resp_mode(c: dict) -> str | None:
                m = c.get('response-mode')
                # Legacy flags
                try:
                    if m is None:
                        if c.get('lite') is True:
                            return 'lite'
                        if c.get('full') is True:
                            return 'full'
                except Exception:
                    pass
                try:
                    from slip.slip_datatypes import PathLiteral as _PL, GetPath as _GP, Name as _Name, IString as _IStr
                    if isinstance(m, (str, _IStr)):
                        s = str(m).strip().strip('`').lower()
                        return s if s in ('lite', 'full', 'none') else None
                    if isinstance(m, _PL):
                        inner = getattr(m, 'inner', None)
                        if isinstance(inner, _GP) and len(inner.segments) == 1 and isinstance(inner.segments[0], _Name):
                            s = inner.segments[0].text
                            if isinstance(s, str):
                                s = s.strip().strip('`').lower()
                                return s if s in ('lite', 'full', 'none') else None
                    if isinstance(m, _GP) and len(m.segments) == 1 and isinstance(m.segments[0], _Name):
                        s = m.segments[0].text
                        if isinstance(s, str):
                            s = s.strip().strip('`').lower()
                            return s if s in ('lite', 'full', 'none') else None
                except Exception:
                    pass
                return None

            mode = _resp_mode(cfg)
            raw = await http_get(url, cfg)
            if mode == 'lite' and isinstance(raw, tuple) and len(raw) == 3:
                status, value, headers = raw
                return [status, value]
            if mode == 'full' and isinstance(raw, tuple) and len(raw) == 3:
                status, value, headers = raw
                return {'status': status, 'value': value, 'meta': {'headers': headers}}
            return raw
        file_loc = self._extract_file_locator(path)
        if file_loc:
            # Enforce two-step policy: no trailing segments on file GET
            if self._has_file_trailing_segments(path):
                raise TypeError("file get does not support trailing path segments; bind the response then filter")
            from slip.slip_file import file_get
            cfg = await self._meta_to_dict(getattr(path, 'meta', None), scope)
            base_dir = getattr(self.evaluator, 'source_dir', None)
            try:
                data = await file_get(file_loc, cfg, base_dir=base_dir)
                return data
            except FileNotFoundError:
                raise PathNotFound(file_loc)
        # Resolve the path normally
        val = await self._resolve_value(path, scope)
        # If the resolved value is itself a path (alias), try to dereference it safely.
        try:
            from slip.slip_datatypes import GetPath as _GP, PathLiteral as _PL
            # Literal alias: return as-is. Callers that need a path object can use call.
            if isinstance(val, _PL):
                return val
            # Runtime path alias
            if isinstance(val, _GP):
                # Avoid immediate recursion when alias points to the same path.
                if val.segments == path.segments and getattr(val, 'meta', None) == getattr(path, 'meta', None):
                    from slip.slip_datatypes import PathLiteral as _PLIT
                    return _PLIT(val)
                try:
                    return await self.get(val, scope)
                except Exception:
                    # On failure, return a literal representation for stable equality
                    from slip.slip_datatypes import PathLiteral as _PLIT
                    return _PLIT(val)
        except Exception:
            pass
        return val

    async def set(self, path: SetPath, value: Any, scope: Scope):
        """Resolves a SetPath to set a value."""
        # TODO: Handle path.meta for generic function dispatch
        url = self._extract_http_url(path)
        if url:
            if self._has_http_trailing_segments(path):
                raise TypeError("http write does not support trailing path segments")
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
        file_loc = self._extract_file_locator(path)
        if file_loc:
            if len(getattr(path, 'segments', []) or []) > 1:
                raise TypeError("file write does not support trailing path segments")
            from slip.slip_file import file_put
            cfg = await self._meta_to_dict(getattr(path, 'meta', None), scope)
            await file_put(file_loc, value, cfg, base_dir=getattr(self.evaluator, 'source_dir', None))
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
            if self._has_http_trailing_segments(path):
                raise TypeError("http post does not support trailing path segments")
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
            raw = await http_post(url, payload, cfg)
            # Package per response-mode if requested
            def _resp_mode(c: dict) -> str | None:
                m = c.get('response-mode')
                # Legacy flags
                try:
                    if m is None:
                        if c.get('lite') is True:
                            return 'lite'
                        if c.get('full') is True:
                            return 'full'
                except Exception:
                    pass
                try:
                    from slip.slip_datatypes import PathLiteral as _PL, GetPath as _GP, Name as _Name, IString as _IStr
                    if isinstance(m, (str, _IStr)):
                        s = str(m).strip().strip('`').lower()
                        return s if s in ('lite', 'full', 'none') else None
                    if isinstance(m, _PL):
                        inner = getattr(m, 'inner', None)
                        if isinstance(inner, _GP) and len(inner.segments) == 1 and isinstance(inner.segments[0], _Name):
                            s = inner.segments[0].text
                            if isinstance(s, str):
                                s = s.strip().strip('`').lower()
                                return s if s in ('lite', 'full', 'none') else None
                    if isinstance(m, _GP) and len(m.segments) == 1 and isinstance(m.segments[0], _Name):
                        s = m.segments[0].text
                        if isinstance(s, str):
                            s = s.strip().strip('`').lower()
                            return s if s in ('lite', 'full', 'none') else None
                except Exception:
                    pass
                return None
            mode = _resp_mode(cfg)
            if mode == 'lite' and isinstance(raw, tuple) and len(raw) == 3:
                status, value, headers = raw
                return [status, value]
            if mode == 'full' and isinstance(raw, tuple) and len(raw) == 3:
                status, value, headers = raw
                return {'status': status, 'value': value, 'meta': {'headers': headers}}
            return raw
        # Non-HTTP post-paths are not supported
        raise TypeError("post-path expects an http(s) URL")

    async def delete(self, path: DelPath, scope: Scope):
        """Resolves a DelPath to delete a value."""
        # TODO: Handle path.path.meta for things like soft-delete
        url = self._extract_http_url(path.path)
        if url:
            if self._has_http_trailing_segments(path.path):
                raise TypeError("http delete does not support trailing path segments")
            from slip.slip_http import http_delete
            cfg = await self._meta_to_dict(getattr(path.path, 'meta', None), scope)

            def _resp_mode(c: dict) -> str | None:
                m = c.get('response-mode')
                # Legacy flags
                try:
                    if m is None:
                        if c.get('lite') is True:
                            return 'lite'
                        if c.get('full') is True:
                            return 'full'
                except Exception:
                    pass
                try:
                    from slip.slip_datatypes import PathLiteral as _PL, GetPath as _GP, Name as _Name, IString as _IStr
                    if isinstance(m, (str, _IStr)):
                        s = str(m).strip().strip('`').lower()
                        return s if s in ('lite', 'full', 'none') else None
                    if isinstance(m, _PL):
                        inner = getattr(m, 'inner', None)
                        if isinstance(inner, _GP) and len(inner.segments) == 1 and isinstance(inner.segments[0], _Name):
                            s = inner.segments[0].text
                            if isinstance(s, str):
                                s = s.strip().strip('`').lower()
                                return s if s in ('lite', 'full', 'none') else None
                    if isinstance(m, _GP) and len(m.segments) == 1 and isinstance(m.segments[0], _Name):
                        s = m.segments[0].text
                        if isinstance(s, str):
                            s = s.strip().strip('`').lower()
                            return s if s in ('lite', 'full', 'none') else None
                except Exception:
                    pass
                return None

            raw = await http_delete(url, cfg)
            mode = _resp_mode(cfg)
            if mode == 'lite' and isinstance(raw, tuple) and len(raw) == 3:
                status, value, headers = raw
                return [status, value]
            if mode == 'full' and isinstance(raw, tuple) and len(raw) == 3:
                status, value, headers = raw
                return {'status': status, 'value': value, 'meta': {'headers': headers}}
            return raw
        file_loc = self._extract_file_locator(path.path)
        if file_loc:
            if len(getattr(path.path, 'segments', []) or []) > 1:
                raise TypeError("file delete does not support trailing path segments")
            from slip.slip_file import file_delete
            cfg = await self._meta_to_dict(getattr(path.path, 'meta', None), scope)
            await file_delete(file_loc, cfg, base_dir=getattr(self.evaluator, 'source_dir', None))
            return
        # Build a breadcrumb chain to support post-delete pruning
        target = path.path
        # Determine starting container and segments (mirror _resolve)
        if target.segments and target.segments[0] is Root:
            container = scope
            while isinstance(container, Scope) and container.parent:
                container = container.parent
            segments = target.segments[1:]
        else:
            container = scope
            segments = target.segments

        # Walk to the leaf, tracking (owner, key, child) steps for pruning
        chain = []
        for seg in segments[:-1]:
            if seg is Parent:
                if not isinstance(container, Scope) or not container.parent:
                    raise KeyError("Path traversal failed: cannot use parent segment ('../') on non-Scope or root Scope.")
                container = container.parent
                continue
            if seg is Pwd:
                continue
            key = await self._get_segment_key(seg, scope)
            next_container = container[key] if not isinstance(container, Scope) else container[key]
            chain.append((container, key, next_container))
            container = next_container

        # Perform the deletion at the leaf
        final_key = await self._get_segment_key(segments[-1], scope)
        del container[final_key]

        # Cascade prune: if a Scope becomes empty, remove it from its owner; repeat upward
        try:
            dbg = bool(os.environ.get("SLIP_PRUNE_DEBUG"))
            cur = container
            i = len(chain) - 1
            if dbg:
                try:
                    print(f"[PRUNE] start: chain_len={len(chain)} leaf_empty={isinstance(cur, Scope) and len(cur.bindings)==0}", file=sys.stderr)
                except Exception:
                    pass
            while isinstance(cur, Scope) and len(cur.bindings) == 0 and i >= 0:
                owner, owner_key, child = chain[i]
                if not isinstance(owner, Scope) or not isinstance(owner_key, str):
                    if dbg:
                        try:
                            otype = type(owner).__name__
                            print(f"[PRUNE] stop: owner_type={otype} owner_key_type={type(owner_key).__name__}", file=sys.stderr)
                        except Exception:
                            pass
                    break
                try:
                    if dbg:
                        try:
                            print(f"[PRUNE] del owner[{owner_key!r}] (owner_bindings_before={list(owner.bindings.keys())})", file=sys.stderr)
                        except Exception:
                            pass
                    del owner[owner_key]
                except Exception:
                    if dbg:
                        try:
                            print(f"[PRUNE] stop: failed to delete key {owner_key!r} from owner", file=sys.stderr)
                        except Exception:
                            pass
                    break
                cur = owner
                i -= 1
                if dbg:
                    try:
                        print(f"[PRUNE] ascended: now_empty={len(cur.bindings)==0} next_i={i}", file=sys.stderr)
                    except Exception:
                        pass
        except Exception:
            # Pruning is best-effort; never fail the delete if pruning encounters an issue
            pass
        return

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
                ok = False
                try:
                    # New: object-relative predicate in overlay scope
                    pred_terms = self._normalize_relative_predicate_terms(pred)
                    overlay = self._build_item_overlay_scope(item, scope)
                    # Try structured AND split first to ensure grouped RHS is truth-evaluated as a whole.
                    split = self._split_top_level_and(pred_terms)
                    if split:
                        left_terms, right_terms = split
                        try:
                            lval = await self.evaluator._eval_expr(left_terms, overlay)
                            if isinstance(lval, Response):
                                st = lval.status
                                if (
                                    isinstance(st, PathLiteral)
                                    and isinstance(getattr(st, "inner", None), GetPath)
                                    and len(st.inner.segments) == 1
                                    and isinstance(st.inner.segments[0], Name)
                                    and st.inner.segments[0].text == "return"
                                ):
                                    lval = lval.value
                            if not lval:
                                ok = False
                            else:
                                rval = await self.evaluator._eval_expr(right_terms, overlay)
                                if isinstance(rval, Response):
                                    st = rval.status
                                    if (
                                        isinstance(st, PathLiteral)
                                        and isinstance(getattr(st, "inner", None), GetPath)
                                        and len(st.inner.segments) == 1
                                        and isinstance(st.inner.segments[0], Name)
                                        and st.inner.segments[0].text == "return"
                                    ):
                                        rval = rval.value
                                ok = bool(rval)
                            # short-circuit: skip generic path when split succeeded
                            if ok:
                                out.append(item)
                            continue
                        except Exception:
                            # Fall through to generic single-expression eval below
                            pass
                    # Generic single-expression evaluation in overlay
                    ok_eval = await self.evaluator._eval_expr(pred_terms, overlay)
                    if isinstance(ok_eval, Response):
                        st = ok_eval.status
                        if (
                            isinstance(st, PathLiteral)
                            and isinstance(getattr(st, "inner", None), GetPath)
                            and len(st.inner.segments) == 1
                            and isinstance(st.inner.segments[0], Name)
                            and ok_eval.status.inner.segments[0].text == "return"
                        ):
                            ok_eval = ok_eval.value
                    ok = bool(ok_eval)
                except Exception:
                    # Back-compat: old pipeline style using the item as LHS
                    try:
                        ok = bool(await self.evaluator._eval_expr([item] + pred, scope))
                    except Exception:
                        ok = False
                if ok:
                    out.append(item)
            return out
        # For non-list containers, return a simple View placeholder for future materialization.
        return View(container, [segment])

    async def _apply_segments(self, container, segments, scope: Scope):
        """Apply SLIP path segments to an already-fetched container (list/dict/scope/etc.)."""
        cur = container
        for segment in segments:
            match segment:
                case _ if (segment is Parent):
                    if not isinstance(cur, Scope) or not cur.parent:
                        raise KeyError("Path traversal failed: cannot use parent segment ('../') on non-Scope or root Scope.")
                    cur = cur.parent
                    continue
                case _ if (segment is Pwd):
                    continue
                case FilterQuery():
                    cur = await self._apply_filter(cur, segment, scope)
                    continue
            if isinstance(cur, list) and isinstance(segment, Name):
                plucked = []
                for item in cur:
                    if isinstance(item, Scope):
                        try:
                            plucked.append(item[segment.text])
                        except KeyError:
                            raise PathNotFound(segment.text)
                    elif isinstance(item, collections.abc.Mapping):
                        try:
                            plucked.append(item[segment.text])
                        except KeyError:
                            raise PathNotFound(segment.text)
                    else:
                        try:
                            plucked.append(getattr(item, segment.text))
                        except Exception:
                            raise TypeError(f"Cannot pluck field {segment.text!r} from item of type {type(item).__name__}")
                cur = plucked
                continue
            key = await self._get_segment_key(segment, scope)
            if isinstance(segment, Name) and not isinstance(cur, (Scope, collections.abc.Mapping)):
                try:
                    cur = getattr(cur, key)
                    continue
                except AttributeError:
                    pass
            try:
                cur = cur[key]
            except KeyError:
                raise PathNotFound(str(key))
        return cur

    def _parse_vectorized_target(self, set_path: SetPath):
        """
        Recognize vectorized write targets in either order:
          A) ... Name, FilterQuery      (e.g., players.hp[< 50]: ...)
          B) ... FilterQuery, Name      (e.g., players[.hp < 50].hp: ...)
        Returns (base_segments, field_name, filter_query, meta) or None.
        """
        segs = list(getattr(set_path, 'segments', []) or [])
        if len(segs) < 2:
            return None
        last = segs[-1]
        prev = segs[-2]
        meta = getattr(set_path, 'meta', None)
        from slip.slip_datatypes import Name as _Name, FilterQuery as _FQ
        if isinstance(last, _FQ) and isinstance(prev, _Name):
            return segs[:-2], prev.text, last, meta
        if isinstance(last, _Name) and isinstance(prev, _FQ):
            return segs[:-2], last.text, prev, meta
        return None

    async def set_vectorized_update(self, set_path: SetPath, update_expr_terms: list, scope: Scope):
        """
        Vectorized per-element update for patterns like: players.hp[< 50]: + 10
        Supports both:
          - ... Name, FilterQuery
          - ... FilterQuery, Name
        Returns list of new values written.
        """
        parsed = self._parse_vectorized_target(set_path)
        if not parsed:
            raise NotImplementedError("vectorized update requires a trailing name/filter pair")
        base_segs, field_name, filt, meta = parsed

        # Resolve the base container (e.g., 'players')
        base_container = await self._resolve_value(GetPath(base_segs, meta), scope)
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
                    pred_terms = self._normalize_relative_predicate_terms(filt.predicate_ast)
                    overlay = self._build_item_overlay_scope(item, scope)
                    split = self._split_top_level_and(pred_terms)
                    if split:
                        try:
                            left_terms, right_terms = split
                            lval = await self.evaluator._eval_expr(left_terms, overlay)
                            if isinstance(lval, Response):
                                st = lval.status
                                if (
                                    isinstance(st, PathLiteral)
                                    and isinstance(getattr(st, "inner", None), GetPath)
                                    and len(st.inner.segments) == 1
                                    and isinstance(st.inner.segments[0], Name)
                                    and st.inner.segments[0].text == "return"
                                ):
                                    lval = lval.value
                            if not lval:
                                keep = False
                            else:
                                rval = await self.evaluator._eval_expr(right_terms, overlay)
                                if isinstance(rval, Response):
                                    st = rval.status
                                    if (
                                        isinstance(st, PathLiteral)
                                        and isinstance(getattr(st, "inner", None), GetPath)
                                        and len(st.inner.segments) == 1
                                        and isinstance(st.inner.segments[0], Name)
                                        and st.inner.segments[0].text == "return"
                                    ):
                                        rval = rval.value
                                keep = bool(rval)
                        except Exception:
                            # fallback to generic eval below
                            keep = bool(await self.evaluator._eval_expr(pred_terms, overlay))
                    else:
                        keep = bool(await self.evaluator._eval_expr(pred_terms, overlay))
                except Exception:
                    try:
                        keep = bool(await self.evaluator._eval_expr([val] + filt.predicate_ast, scope))
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
          - players.hp[< 50]: 50
          - players[.hp < 50].hp: * 1.1
        Supports both:
          - ... Name, FilterQuery
          - ... FilterQuery, Name
        Returns list of new values written.
        """
        parsed = self._parse_vectorized_target(set_path)
        if not parsed:
            raise NotImplementedError("vectorized assign requires a trailing name/filter pair")
        base_segs, field_name, filt, meta = parsed

        base_container = await self._resolve_value(GetPath(base_segs, meta), scope)
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
                    pred_terms = self._normalize_relative_predicate_terms(filt.predicate_ast)
                    overlay = self._build_item_overlay_scope(item, scope)
                    split = self._split_top_level_and(pred_terms)
                    if split:
                        try:
                            left_terms, right_terms = split
                            lval = await self.evaluator._eval_expr(left_terms, overlay)
                            if isinstance(lval, Response):
                                st = lval.status
                                if (
                                    isinstance(st, PathLiteral)
                                    and isinstance(getattr(st, "inner", None), GetPath)
                                    and len(st.inner.segments) == 1
                                    and isinstance(st.inner.segments[0], Name)
                                    and st.inner.segments[0].text == "return"
                                ):
                                    lval = lval.value
                            if not lval:
                                keep = False
                            else:
                                rval = await self.evaluator._eval_expr(right_terms, overlay)
                                if isinstance(rval, Response):
                                    st = rval.status
                                    if (
                                        isinstance(st, PathLiteral)
                                        and isinstance(getattr(st, "inner", None), GetPath)
                                        and len(st.inner.segments) == 1
                                        and isinstance(st.inner.segments[0], Name)
                                        and st.inner.segments[0].text == "return"
                                    ):
                                        rval = rval.value
                                keep = bool(rval)
                        except Exception:
                            # fallback to generic eval below
                            keep = bool(await self.evaluator._eval_expr(pred_terms, overlay))
                    else:
                        keep = bool(await self.evaluator._eval_expr(pred_terms, overlay))
                except Exception:
                    try:
                        keep = bool(await self.evaluator._eval_expr([val] + filt.predicate_ast, scope))
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
        # Cache of loaded modules keyed by PathLiteral string
        self.module_cache: Dict[str, Any] = {}
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
        if isinstance(result, Response) and isinstance(result.status, PathLiteral) and isinstance(result.status.inner, GetPath) and len(result.status.inner.segments) == 1 and isinstance(result.status.inner.segments[0], Name) and result.status.inner.segments[0].text == "return":
            return result.value
        return result

    async def _expand_code_literal(self, code: Code, scope: Scope) -> list[list]:
        """
        Perform definition-time template expansion on a Code literal:
        - (inject X): evaluate X now in the current lexical scope and substitute the value verbatim
        - (splice X):
            * inside an expression: X must evaluate to a list; splice elements into the arg list
            * as a standalone expression: X may evaluate to a list or a Code; splice contents as sibling expressions
        Returns a new list-of-expressions suitable for Code(nodes).
        """
        async def preprocess_expr(terms: list) -> list:
            out: list = []
            for term in terms:
                # Detect (inject ...) or (splice ...) forms: a Group with a single inner expression
                if isinstance(term, Group) and term.nodes and len(term.nodes) == 1:
                    inner_expr = term.nodes[0]
                    if inner_expr and isinstance(inner_expr[0], GetPath):
                        head = inner_expr[0]
                        if len(head.segments) == 1 and isinstance(head.segments[0], Name):
                            fname = head.segments[0].text
                            args = inner_expr[1:]
                            if fname == 'inject':
                                if len(args) != 1:
                                    raise TypeError("inject expects 1 argument")
                                val = await self._eval(args[0], scope)
                                out.append(val)
                                continue
                            if fname == 'splice':
                                if len(args) != 1:
                                    raise TypeError("splice expects 1 argument")
                                val = await self._eval(args[0], scope)
                                if isinstance(val, list):
                                    out.extend(val)
                                    continue
                                raise TypeError("splice in expression requires a list")
                # Recurse into nested Group (non-inject/splice)
                if isinstance(term, Group):
                    new_inner = []
                    for expr in term.nodes:
                        new_inner.append(await preprocess_expr(expr))
                    new_group = Group(new_inner)
                    if hasattr(term, 'loc'):
                        try: new_group.loc = term.loc
                        except Exception: pass
                    out.append(new_group)
                    continue
                # Recurse into list literal elements
                if isinstance(term, SlipList):
                    new_items = []
                    for expr in term.nodes:
                        new_items.append(await preprocess_expr(expr))
                    new_list = SlipList(new_items)
                    if hasattr(term, 'loc'):
                        try: new_list.loc = term.loc
                        except Exception: pass
                    out.append(new_list)
                    continue
                # Recurse into dict constructor tuple ('dict', [exprs])
                match term:
                    case ('dict', exprs):
                        new_exprs = [await preprocess_expr(expr) for expr in exprs]
                        out.append(('dict', new_exprs))
                        continue
                # Default: keep term as-is
                out.append(term)
            return out

        out_exprs: list[list] = []
        for expr in code.ast:
            # Whole-expression splice: [(splice ...)]
            if len(expr) == 1:
                t = expr[0]
                if isinstance(t, Group) and t.nodes and len(t.nodes) == 1:
                    inner = t.nodes[0]
                    if inner and isinstance(inner[0], GetPath):
                        head = inner[0]
                        if len(head.segments) == 1 and isinstance(head.segments[0], Name) and head.segments[0].text == 'splice':
                            args = inner[1:]
                            if len(args) != 1:
                                raise TypeError("splice expects 1 argument")
                            val = await self._eval(args[0], scope)
                            if isinstance(val, Code):
                                nested = await self._expand_code_literal(val, scope)
                                out_exprs.extend(nested)
                                continue
                            if isinstance(val, list):
                                for item in val:
                                    out_exprs.append([item])
                                continue
                            raise TypeError("splice in statement requires code or list")
            # Normal expression: recursively preprocess all nested terms
            out_exprs.append(await preprocess_expr(expr))
        return out_exprs

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
                    if isinstance(result, Response) and isinstance(result.status, PathLiteral) and isinstance(result.status.inner, GetPath) and len(result.status.inner.segments) == 1 and isinstance(result.status.inner.segments[0], Name) and result.status.inner.segments[0].text == "return":
                        return result
                return result
            else: # It's a single expression (list of terms)
                return await self._eval_expr(node, scope)

        match node:
            case GetPath():
                self.current_node = node
                return await self.path_resolver.get(node, scope)

            # Path literals evaluate to themselves (do not resolve)
            case PathLiteral():
                return node

            case Group():
                self.current_node = node
                return await self._eval(node.nodes, scope)

            case SlipList():
                results = []
                for expr in node.nodes:
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
                            rhs_terms = expr[1:]
                            # Normalize i-string sugar inside dict values:
                            # allow "key: i\"...\"" syntax by treating [GetPath('i'), IString(...)] as a single IString value
                            if (
                                len(rhs_terms) == 2
                                and isinstance(rhs_terms[0], GetPath)
                                and len(rhs_terms[0].segments) == 1
                                and isinstance(rhs_terms[0].segments[0], Name)
                                and rhs_terms[0].segments[0].text == 'i'
                                and isinstance(rhs_terms[1], IString)
                            ):
                                val = rhs_terms[1]
                            else:
                                val = await self._eval_expr(rhs_terms, temp_scope)
                            temp_scope[key] = val
                            continue
                    # Fallback: evaluate any other expressions for their value/side-effects
                    await self._eval_expr(expr, temp_scope)
                out = SlipDict()
                for k, v in temp_scope.bindings.items():
                    out[k] = v
                return out

            case Code() as code:
                # Definition-time expansion of inject/splice to produce a pure Code value
                exprs = await self._expand_code_literal(code, scope)
                new_code = Code(exprs)
                try:
                    new_code._expanded = True  # marker for run/run-with fast-path
                except Exception:
                    pass
                return new_code

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
                        update_style = isinstance(resolved, PipedPath)
                    except Exception:
                        update_style = False

                # Vectorized write: LHS ending with a filter on a plucked field
                is_vectorized_target = self.path_resolver._parse_vectorized_target(head_uneval) is not None
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
                        if isinstance(cur_val, PipedPath):
                            update_style = False
                    except PathNotFound:
                        update_style = False

                if update_style:
                    # Seed the RHS chain with the current value, evaluate, set, and return the new value.
                    new_value = await self._eval_expr([cur_val] + value_expr, scope)
                    if isinstance(new_value, Response) and isinstance(new_value.status, PathLiteral) and isinstance(new_value.status.inner, GetPath) and len(new_value.status.inner.segments) == 1 and isinstance(new_value.status.inner.segments[0], Name) and new_value.status.inner.segments[0].text == "return":
                        new_value = new_value.value
                    self.current_node = head_uneval
                    await self.path_resolver.set(head_uneval, new_value, scope)
                    return new_value

                # Normal assignment: evaluate RHS as a value, set, return the assigned value (or merged GF)
                self.current_node = head_uneval
                value = await self._eval_expr(value_expr, scope)
                if isinstance(value, Response) and isinstance(value.status, PathLiteral) and isinstance(value.status.inner, GetPath) and len(value.status.inner.segments) == 1 and isinstance(value.status.inner.segments[0], Name) and value.status.inner.segments[0].text == "return":
                    value = value.value

                # Alias write: if LHS is a simple name bound to a path, write to that path instead of rebinding
                if len(head_uneval.segments) == 1 and isinstance(head_uneval.segments[0], Name):
                    tname = head_uneval.segments[0].text
                    try:
                        existing = scope[tname]
                    except KeyError:
                        existing = None
                    from slip.slip_datatypes import GetPath as _GP, PathLiteral as _PL
                    if isinstance(existing, _PL) and isinstance(getattr(existing, 'inner', None), _GP):
                        existing = existing.inner
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
                            PathLiteral as _PL, MultiSetPath as _MSP
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
                        if isinstance(val, (_GP, _SP, _DP, _PP, _PL, _MSP)):
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
                            # Merge by signature: add new methods and merge examples for duplicates
                            sig_map = {}
                            for m in existing.methods:
                                s = getattr(m, 'meta', {}).get('type')
                                if s is not None:
                                    sig_map[repr(s)] = m
                            to_add = []
                            for m in methods_to_add:
                                s = getattr(m, 'meta', {}).get('type')
                                key = repr(s) if s is not None else None
                                if key is not None and key in sig_map:
                                    # Merge examples into existing method
                                    try:
                                        dst_ex = sig_map[key].meta.setdefault('examples', [])
                                        src_ex = getattr(m, 'meta', {}).get('examples') or []
                                        dst_ex.extend(x for x in src_ex if x not in dst_ex)
                                    except Exception:
                                        pass
                                    continue
                                to_add.append(m)
                                if key is not None:
                                    sig_map[key] = m
                            for m in to_add:
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
                            # Merge duplicates by signature and keep all examples
                            sig_map = {}
                            for m in methods_to_add:
                                s = getattr(m, 'meta', {}).get('type')
                                key = repr(s) if s is not None else None
                                if key is None or key not in sig_map:
                                    sig_map[key] = m
                                else:
                                    try:
                                        dst_ex = sig_map[key].meta.setdefault('examples', [])
                                        src_ex = getattr(m, 'meta', {}).get('examples') or []
                                        dst_ex.extend(x for x in src_ex if x not in dst_ex)
                                    except Exception:
                                        pass
                            for m in sig_map.values():
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
                    if isinstance(value, Response) and isinstance(value.status, PathLiteral) and isinstance(value.status.inner, GetPath) and len(value.status.inner.segments) == 1 and isinstance(value.status.inner.segments[0], Name) and value.status.inner.segments[0].text == "return":
                        value = value.value
                    await self.path_resolver.set(SetPath(head_uneval.segments, getattr(head_uneval, 'meta', None)), value, scope)
                    return value
                # Convenience: allow FS PUT using get-path + value, e.g.:
                #   file://path/to/file "body"
                # Treat as a SetPath to the same locator and perform PUT.
                try:
                    file_loc = self.path_resolver._extract_file_locator(head_uneval)
                except Exception:
                    file_loc = None
                if file_loc is not None and len(terms) >= 2:
                    value = await self._eval_expr(terms[1:], scope)
                    if isinstance(value, Response) and isinstance(value.status, PathLiteral) and isinstance(value.status.inner, GetPath) and len(value.status.inner.segments) == 1 and isinstance(value.status.inner.segments[0], Name) and value.status.inner.segments[0].text == "return":
                        value = value.value
                    await self.path_resolver.set(SetPath(head_uneval.segments, getattr(head_uneval, 'meta', None)), value, scope)
                    return value

            case PostPath():
                value_expr = terms[1:]
                if not value_expr:
                    raise SyntaxError("PostPath must be followed by a value.")
                value = await self._eval_expr(value_expr, scope)
                if isinstance(value, Response) and isinstance(value.status, PathLiteral) and isinstance(value.status.inner, GetPath) and len(value.status.inner.segments) == 1 and isinstance(value.status.inner.segments[0], Name) and value.status.inner.segments[0].text == "return":
                    value = value.value
                self.current_node = head_uneval
                result = await self.path_resolver.post(head_uneval, value, scope)
                return result

            case DelPath():
                if len(terms) > 1:
                    raise SyntaxError("del-path cannot be part of a larger expression.")
                self.current_node = head_uneval
                result = await self.path_resolver.delete(head_uneval, scope)
                return result

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

        # Dynamic assignment: if the head evaluates to a SetPath or MultiSetPath, treat it as an assignment target
        from slip.slip_datatypes import SetPath as _SP, MultiSetPath as _MSP
        if isinstance(head_val, _SP):
            value = await self._eval_expr(remaining_terms[1:], scope)
            if isinstance(value, Response) and isinstance(value.status, PathLiteral) and isinstance(value.status.inner, GetPath) and len(value.status.inner.segments) == 1 and isinstance(value.status.inner.segments[0], Name) and value.status.inner.segments[0].text == "return":
                value = value.value
            self.current_node = remaining_terms[0]
            await self.path_resolver.set(head_val, value, scope)
            return value
        if isinstance(head_val, _MSP) or (isinstance(head_val, tuple) and len(head_val) > 0 and head_val[0] == 'multi-set'):
            # Normalize targets list from runtime MultiSetPath or literal tuple form
            targets = head_val.targets if isinstance(head_val, _MSP) else head_val[1]
            values = await self._eval_expr(remaining_terms[1:], scope)
            if not isinstance(values, list) or len(values) != len(targets):
                raise TypeError(f"Multi-set mismatch: pattern requires {len(targets)} values")
            for path, v in zip(targets, values):
                self.current_node = remaining_terms[0]
                await self.path_resolver.set(path, v, scope)
            return None

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

            # ADD: debug prep for prefix call
            self._dbg(
                "CALL prefix prepare",
                "head_type", getattr(head_val, "__class__", type(head_val)).__name__,
                "split_at", split_at,
                "arg_end", arg_end,
                "argc_terms", len(arg_terms),
                "arg_term_types", [type(t).__name__ for t in arg_terms],
            )

            # Zero‑arity handling:
            # - If a piped operator follows, do not invoke; let the pipe consume the head as LHS.
            # - Otherwise, auto‑invoke only if the callee has an exact zero‑arity (non‑variadic) method,
            #   or is a Python callable with no required positional args.
            if arg_end == 1:
                if split_at is not None:
                    k = 1  # defer to the pipe
                else:
                    def _should_autocall_zero_arity(v):
                        try:
                            from slip.slip_datatypes import GenericFunction as _GF, SlipFunction as _SF, Sig as _Sig, Code as _Code
                            if isinstance(v, _GF):
                                for m in v.methods:
                                    s = getattr(m, 'meta', {}).get('type')
                                    if isinstance(s, _Sig):
                                        base = len(s.positional) + len(s.keywords)
                                        if base == 0 and s.rest is None:
                                            return True
                                    else:
                                        if isinstance(m.args, _Code) and len(m.args.nodes) == 0:
                                            return True
                                return False
                            if isinstance(v, _SF):
                                s = getattr(v, 'meta', {}).get('type')
                                if isinstance(s, _Sig):
                                    base = len(s.positional) + len(s.keywords)
                                    return base == 0 and s.rest is None
                                if isinstance(v.args, _Code) and len(v.args.nodes) == 0:
                                    return True
                                return False
                        except Exception:
                            pass
                        # Python callable fallback
                        try:
                            import inspect
                            sig = inspect.signature(v)
                            req = [
                                p for p in sig.parameters.values()
                                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                                and p.default is inspect._empty
                            ]
                            # keyword-only params (e.g., scope) are ignored here
                            return len(req) == 0
                        except Exception:
                            return False

                    if _should_autocall_zero_arity(head_val):
                        name = None
                        if isinstance(remaining_terms[0], GetPath) and len(remaining_terms[0].segments) == 1 and isinstance(remaining_terms[0].segments[0], Name):
                            name = remaining_terms[0].segments[0].text
                        evaluated_args = []
                        self._dbg(
                            "CALL prefix",
                            getattr(head_val, "__class__", type(head_val)).__name__,
                            "split_at", split_at,
                            "argc_terms", 0,
                            "argc", 0,
                            "arg_term_types", [],
                            "arg_types", [],
                        )
                        self._push_frame(name or '<call>', head_val, evaluated_args, remaining_terms[0])
                        _ok = False
                        try:
                            result = await self.call(head_val, evaluated_args, scope)
                            _ok = True
                        finally:
                            if _ok:
                                self._pop_frame()
                        k = 1
                    else:
                        k = 1  # leave result=head_val (function value)
            else:
                # existing evaluated-args call path remains unchanged
                # Determine display name for stack frame
                name = None
                if isinstance(remaining_terms[0], GetPath) and len(remaining_terms[0].segments) == 1 and isinstance(remaining_terms[0].segments[0], Name):
                    name = remaining_terms[0].segments[0].text

                from slip.slip_datatypes import GetPath as _GP, Name as _Name, Code as _Code
                evaluated_args = []
                i = 0

                async def _apply_chain(base_val, segs):
                    cur = base_val
                    applied = 0
                    for seg in segs:
                        try:
                            cur = await self.path_resolver._apply_segments(cur, [seg], scope)
                            applied += 1
                        except Exception:
                            break
                    return cur, applied

                while i < len(arg_terms):
                    base_term = arg_terms[i]
                    base_val = await self._eval(base_term, scope)

                    # Collect consecutive single-name get-paths that could form a property chain.
                    segs = []
                    j = i + 1
                    allow_bare = isinstance(base_term, (Group, _Code))
                    term_seg_counts = []
                    while j < len(arg_terms):
                        t = arg_terms[j]
                        if not isinstance(t, _GP):
                            break
                        segs_list = list(getattr(t, 'segments', []) or [])
                        if not segs_list:
                            break

                        # Case 1: single-name get-path
                        if len(segs_list) == 1 and isinstance(segs_list[0], _Name):
                            name_txt = segs_list[0].text
                            if isinstance(name_txt, str) and name_txt.startswith('.') and len(name_txt) > 1:
                                # .field after any base
                                segs.append(_Name(name_txt[1:]))
                                term_seg_counts.append(1)
                                j += 1
                                continue
                            if allow_bare:
                                # Bare name allowed after Group/Code base: ( ... ).field
                                segs.append(_Name(name_txt))
                                term_seg_counts.append(1)
                                j += 1
                                continue
                            break

                        # Case 2: multi-name get-path in the immediate next term; fold contiguous name segments
                        if j == i + 1 and all(isinstance(s, _Name) for s in segs_list):
                            first_txt = segs_list[0].text
                            if (isinstance(first_txt, str) and first_txt.startswith('.') and len(first_txt) > 1) or allow_bare:
                                # Normalize each name (strip leading '.' if present)
                                added = 0
                                for s in segs_list:
                                    txt = s.text
                                    if isinstance(txt, str) and txt.startswith('.') and len(txt) > 1:
                                        segs.append(_Name(txt[1:]))
                                    else:
                                        segs.append(_Name(txt))
                                    added += 1
                                term_seg_counts.append(added)
                                j += 1
                                continue

                        break

                    if segs:
                        # Optional debug: show collected segments per arg term
                        self._dbg("FOLD collect",
                                  "base_type", type(base_term).__name__,
                                  "segs", [getattr(s, "text", None) for s in segs],
                                  "term_counts", term_seg_counts)
                        cur, applied = await _apply_chain(base_val, segs)
                        if applied > 0:
                            # Determine how many arg terms were fully consumed by the applied segments
                            terms_used = 0
                            remaining = applied
                            for c in term_seg_counts:
                                if remaining >= c:
                                    terms_used += 1
                                    remaining -= c
                                else:
                                    break
                            self._dbg("FOLD apply", "applied", applied, "terms_used", terms_used)
                            evaluated_args.append(cur)
                            i = i + 1 + terms_used
                            continue

                    # No usable chain → keep base as-is and don’t consume the next term
                    evaluated_args.append(base_val)
                    i += 1
                # Auto‑invoke zero‑arity callables when they appear as arguments (e.g., 'keys current-scope')
                async def _autocall_if_zero_arity(v):
                    def _should_autocall_zero_arity(v):
                        try:
                            from slip.slip_datatypes import GenericFunction as _GF, SlipFunction as _SF, Sig as _Sig, Code as _Code
                            if isinstance(v, _GF):
                                for m in v.methods:
                                    s = getattr(m, 'meta', {}).get('type')
                                    if isinstance(s, _Sig):
                                        base = len(s.positional) + len(s.keywords)
                                        if base == 0 and s.rest is None:
                                            return True
                                    else:
                                        if isinstance(m.args, _Code) and len(m.args.nodes) == 0:
                                            return True
                                return False
                            if isinstance(v, _SF):
                                s = getattr(v, 'meta', {}).get('type')
                                if isinstance(s, _Sig):
                                    base = len(s.positional) + len(s.keywords)
                                    return base == 0 and s.rest is None
                                if isinstance(v.args, _Code) and len(v.args.nodes) == 0:
                                    return True
                                return False
                        except Exception:
                            pass
                        # Python callable fallback
                        try:
                            import inspect
                            sig = inspect.signature(v)
                            req = [
                                p for p in sig.parameters.values()
                                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                                and p.default is inspect._empty
                            ]
                            return len(req) == 0
                        except Exception:
                            return False
                    if _should_autocall_zero_arity(v):
                        return await self.call(v, [], scope)
                    return v
                def _is_call_primitive(fn):
                    try:
                        import inspect as _inspect
                        if _inspect.ismethod(fn):
                            self_obj = getattr(fn, "__self__", None)
                            if getattr(self_obj, "__class__", None).__name__ == "StdLib" and getattr(fn, "__name__", "") == "_call":
                                return True
                    except Exception:
                        pass
                    return False
                if evaluated_args and not _is_call_primitive(head_val):
                    evaluated_args = [await _autocall_if_zero_arity(a) for a in evaluated_args]
                self._dbg(
                    "CALL prefix",
                    getattr(head_val, "__class__", type(head_val)).__name__,
                    "split_at", split_at,
                    "argc_terms", len(arg_terms),
                    "argc", len(evaluated_args),
                    "arg_term_types", [type(t).__name__ for t in arg_terms],
                    "arg_types", [type(a).__name__ for a in evaluated_args],
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
        async def _rhs_span_for_logical(terms, op_index, scope):
            """
            Determine how many terms constitute the RHS operand for a logical op.
            Recognize simple infix patterns by resolving the middle term to any piped operator:
              <term> <operator> <term>  -> span 3
            Also recognize unary piped operator form when only two terms are present:
              <term> <operator>         -> span 2
            Otherwise, treat RHS as a single term (span 1).
            """
            start = op_index + 1
            # Try binary form: [term, op, term]
            if start + 2 < len(terms):
                mid = terms[start + 1]
                try:
                    # PipedPath literal counts as an operator
                    if isinstance(mid, PipedPath):
                        return 3
                    # Resolve mid; if it resolves to a PipedPath, treat as operator
                    resolved = await self._eval(mid, scope)
                    if isinstance(resolved, PipedPath):
                        return 3
                except Exception:
                    pass
            # Try unary piped op form: [term, op]
            if start + 1 < len(terms):
                mid = terms[start + 1]
                try:
                    if isinstance(mid, PipedPath):
                        return 2
                    resolved = await self._eval(mid, scope)
                    if isinstance(resolved, PipedPath):
                        return 2
                except Exception:
                    pass
            return 1

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
            visited_ops = set()
            steps = 0
            while not isinstance(op_val, PipedPath):
                steps += 1
                if steps > 50:
                    err = RecursionError("maximum operator resolution depth exceeded")
                    try:
                        err.slip_obj = raw_op_term
                    except Exception:
                        pass
                    raise err
                # Detect simple self-referential loops on get-path objects
                try:
                    key = getattr(op_val, "to_str_repr", lambda: repr(op_val))()
                    if key in visited_ops:
                        err = RecursionError("operator resolution cycle detected")
                        try:
                            err.slip_obj = raw_op_term
                        except Exception:
                            pass
                        raise err
                    visited_ops.add(key)
                except Exception:
                    # best-effort; ignore if op_val has no stable repr
                    pass

                # Normalize ambiguous '/' token parsed as Root into operator name '/'
                if isinstance(op_val, GetPath) and len(op_val.segments) == 1 and op_val.segments[0] is Root:
                    op_val = GetPath([Name('/')], op_val.meta)
                    continue
                # Convert path literals to runtime path types first
                if isinstance(op_val, PathLiteral):
                    inner = op_val.inner
                    if isinstance(inner, PipedPath):
                        op_val = inner
                        continue
                    # Non-piped path-literal (e.g., `ok`) is not an operator; stop resolving
                    break
                # Resolve GetPath references from scope (e.g., '+' -> '|add')
                if isinstance(op_val, GetPath):
                    next_val = await self._eval(op_val, scope)
                    # Guard against pathological self-aliases that re-yield the same get-path
                    if isinstance(next_val, GetPath) and getattr(next_val, "to_str_repr", lambda: None)() == getattr(op_val, "to_str_repr", lambda: None)():
                        err = RecursionError("operator resolution cycle detected")
                        try:
                            err.slip_obj = raw_op_term
                        except Exception:
                            pass
                        raise err
                    op_val = next_val
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
                        if isinstance(pv, PathLiteral):
                            inner = pv.inner
                            if isinstance(inner, PipedPath):
                                unary_mode = True
                            # Either way, stop unwrapping to avoid toggling PathLiteral <-> GetPath
                            break
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
                span = await _rhs_span_for_logical(remaining_terms, k, scope)
                if not result:
                    # Skip operator and the entire RHS operand
                    k += 1 + span
                    continue
                rhs_start = k + 1
                if span >= 2:
                    # Evaluate the RHS slice (operator-inclusive) as a single sub-expression
                    rhs_arg = await self._eval_expr(remaining_terms[rhs_start:rhs_start + span], scope)
                else:
                    self.current_node = remaining_terms[rhs_start]
                    rhs_arg = await self._eval(remaining_terms[rhs_start], scope)
                result = rhs_arg
                k += 1 + span
                continue

            if func_name == 'logical-or':
                # Short-circuit: only evaluate RHS if LHS is falsey
                span = await _rhs_span_for_logical(remaining_terms, k, scope)
                if result:
                    # Skip operator and the entire RHS operand
                    k += 1 + span
                    continue
                rhs_start = k + 1
                if span >= 2:
                    # Evaluate the RHS slice (operator-inclusive) as a single sub-expression
                    rhs_arg = await self._eval_expr(remaining_terms[rhs_start:rhs_start + span], scope)
                else:
                    self.current_node = remaining_terms[rhs_start]
                    rhs_arg = await self._eval(remaining_terms[rhs_start], scope)
                result = rhs_arg
                k += 1 + span
                continue



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
            if isinstance(val, (GetPath, SetPath, DelPath, PipedPath, PathLiteral, MultiSetPath)):
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

        async def _spec_ok(spec, val) -> bool:
            # Unwrap path-literals
            if isinstance(spec, PathLiteral):
                spec = spec.inner
            # Recursive forms
            if isinstance(spec, tuple) and len(spec) > 0:
                tag = spec[0]
                parts = list(spec[1] or [])
                if tag == 'and':
                    for p in parts:
                        if not await _spec_ok(p, val):
                            return False
                    return True
                if tag == 'union':
                    for p in parts:
                        if await _spec_ok(p, val):
                            return True
                    return False
            # Resolve to Scope or primitive name
            resolved = None
            target_scope = None
            if isinstance(spec, GetPath):
                # Normalize backticked single-name to plain name for primitive check
                if len(spec.segments) == 1 and isinstance(spec.segments[0], Name):
                    ntext = spec.segments[0].text
                    if isinstance(ntext, str) and len(ntext) >= 2 and ntext[0] == '`' and ntext[-1] == '`':
                        spec = GetPath([Name(ntext[1:-1])], getattr(spec, 'meta', None))
                try:
                    resolved = await self.path_resolver.get(spec, method.closure)
                except Exception:
                    try:
                        resolved = await self.path_resolver.get(spec, scope)
                    except Exception:
                        resolved = None
            elif isinstance(spec, Scope):
                target_scope = spec
            # Scope requirement
            if isinstance(resolved, Scope) or isinstance(target_scope, Scope):
                target = resolved if isinstance(resolved, Scope) else target_scope
                return isinstance(val, Scope) and _scope_matches(val, target)
            # Primitive requirement via single-name annotation
            ann_name = None
            if isinstance(spec, GetPath) and len(spec.segments) == 1 and isinstance(spec.segments[0], Name):
                ann_name = spec.segments[0].text
            if ann_name in PRIMITIVES:
                return _type_name(val) == ann_name
            # Sig alias (union of primitives/scopes)
            if isinstance(resolved, Sig):
                allowed = set()
                for item in getattr(resolved, 'positional', []) or []:
                    n = item if isinstance(item, str) else (
                        item.segments[0].text if isinstance(item, GetPath) and len(item.segments) == 1 and isinstance(item.segments[0], Name) else None
                    )
                    if isinstance(n, str) and len(n) >= 2 and n[0] == '`' and n[-1] == '`':
                        n = n[1:-1]
                    if isinstance(n, str):
                        allowed.add(n)
                return bool(allowed) and (_type_name(val) in allowed)
            # Unknown/unsupported element
            return False

        offset = len(sig.positional)
        idx = 0
        for _, type_spec in sig.keywords.items():
            arg_i = offset + idx
            if arg_i >= len(args):
                return False
            val = args[arg_i]
            # Unified recursive matcher handles primitives, scopes, Sig aliases,
            # and nested ('and', ...)/('union', ...) combinations.
            if not await _spec_ok(type_spec, val):
                return False
            idx += 1

        return True

    def _primitive_type_name(self, val) -> str:
        from slip.slip_datatypes import (
            Scope, Code, IString, SlipFunction, GenericFunction,
            GetPath, SetPath, DelPath, PipedPath, PathLiteral, MultiSetPath
        )
        if val is None: return 'none'
        if isinstance(val, bool): return 'boolean'
        if isinstance(val, int) and not isinstance(val, bool): return 'int'
        if isinstance(val, float): return 'float'
        if isinstance(val, IString): return 'i-string'
        if isinstance(val, str): return 'string'
        if isinstance(val, list): return 'list'
        if isinstance(val, (dict, collections.abc.Mapping)): return 'dict'
        if isinstance(val, Scope): return 'scope'
        if isinstance(val, (GetPath, SetPath, DelPath, PipedPath, PathLiteral, MultiSetPath)): return 'path'
        if isinstance(val, (SlipFunction, GenericFunction)) or callable(val): return 'function'
        if isinstance(val, Code): return 'code'
        return 'string'

    def _scope_family(self, scope_obj) -> set:
        from slip.slip_datatypes import Scope as _Scope
        if not isinstance(scope_obj, _Scope):
            return set()
        # cache on the scope itself
        try:
            fam = scope_obj.meta.get('_family')
            if fam:
                return fam
        except Exception:
            pass
        seen = set()
        stack = [scope_obj]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            # parent
            p = cur.meta.get('parent')
            if isinstance(p, _Scope):
                stack.append(p)
            # mixins
            for m in cur.meta.get('mixins', []) or []:
                if isinstance(m, _Scope):
                    stack.append(m)
        try:
            scope_obj.meta['_family'] = seen
        except Exception:
            pass
        return seen

    def _value_family(self, val) -> tuple[set, int]:
        # Returns (family_set, size) where size is used as denominator in coverage
        from slip.slip_datatypes import Scope as _Scope
        if isinstance(val, _Scope):
            fam = self._scope_family(val)
            return fam, len(fam) if fam else 1
        # primitives → singleton size
        return {self._primitive_type_name(val)}, 1

    def _compile_annotation_item(self, item, method_closure, current_scope):
        # Normalize a single annotation element into a compiled form
        from slip.slip_datatypes import GetPath as _GP, PathLiteral as _PL, Name as _Name, Sig as _Sig, Scope as _Scope
        # Path literal -> inner
        if isinstance(item, _PL):
            item = item.inner
        # Single-name get-path → may resolve to scope or primitive name
        if isinstance(item, _GP) and len(item.segments) == 1 and isinstance(item.segments[0], _Name):
            n = item.segments[0].text
            # strip backticks
            if isinstance(n, str) and len(n) >= 2 and n[0] == '`' and n[-1] == '`':
                n = n[1:-1]
            # Try resolve to Scope at definition time (closure first, then current scope)
            try:
                v = method_closure[n]
            except Exception:
                try:
                    v = current_scope[n]
                except Exception:
                    v = None
            from slip.slip_datatypes import Scope as _Scope2
            if isinstance(v, _Scope2):
                return {'kind': 'scope', 'scope': v}
            # else treat as primitive name
            return {'kind': 'prim', 'name': n}
        # Already a Scope
        if isinstance(item, _Scope):
            return {'kind': 'scope', 'scope': item}
        # Nested union (Sig) in annotation → union
        if isinstance(item, _Sig):
            # compile each positional child
            compiled = []
            for pos in getattr(item, 'positional', []) or []:
                compiled.append(self._compile_annotation_item(pos, method_closure, current_scope))
            return {'kind': 'union', 'items': compiled}
        # Tuple ('and', [...])
        if isinstance(item, tuple) and len(item) > 0 and item[0] == 'and':
            compiled = [self._compile_annotation_item(x, method_closure, current_scope) for x in item[1]]
            # flatten and dedupe by identity
            flat = []
            for it in compiled:
                if it.get('kind') == 'and':
                    flat.extend(it['items'])
                else:
                    flat.append(it)
            return {'kind': 'and', 'items': flat}
        # Tuple ('union', [...])
        if isinstance(item, tuple) and len(item) > 0 and item[0] == 'union':
            compiled = [self._compile_annotation_item(x, method_closure, current_scope) for x in item[1]]
            return {'kind': 'union', 'items': compiled}
        # Fallback: re-run through GP normalization
        return self._compile_annotation_item(self._to_getpath_like(item), method_closure, current_scope)

    def _to_getpath_like(self, value):
        # Minimal helper to convert strings to GetPath(Name(...)) for annotation compilation
        from slip.slip_datatypes import GetPath as _GP, Name as _Name, PathLiteral as _PL
        if isinstance(value, _GP):
            return value
        if isinstance(value, _PL):
            return value.inner
        if isinstance(value, str):
            return _GP([_Name(value)])
        return value

    def _compile_method_signature(self, method, current_scope):
        # Early-bound compilation; cache on method.meta['_compiled_sig']
        from slip.slip_datatypes import Sig as _Sig, Code as _Code
        meta = getattr(method, 'meta', {}) or {}
        sig = meta.get('type')
        if not isinstance(sig, _Sig):
            return None
        cache = meta.get('_compiled_sig')
        if cache:
            return cache
        # Build positional count and typed keywords in declaration order
        pos_count = len(sig.positional or [])
        compiled_kws = []
        for name, ann in (sig.keywords or {}).items():
            compiled_kws.append((
                name if isinstance(name, str) else getattr(name, 'text', str(name)),
                self._compile_annotation_item(ann, method.closure, current_scope)
            ))
        out = {'positional': pos_count, 'keywords': compiled_kws, 'rest': sig.rest is not None}
        meta['_compiled_sig'] = out
        return out

    def _annotation_applicability_and_coverage(self, compiled_ann, arg_val) -> tuple[bool, float, int, int]:
        """
        Returns (applicable, coverage_score, detail_count, signature_family_size)
        - coverage_score in [0,1]
        - detail_count used for tie-breaker 2 (total required types count)
        """
        kind = compiled_ann.get('kind')
        arg_fam, arg_size = self._value_family(arg_val)

        def scope_ok(scope_t):
            return scope_t in arg_fam

        def scope_family(scope_t):
            fam = self._scope_family(scope_t)
            return fam if fam else {scope_t}

        if kind == 'prim':
            name = compiled_ann['name']
            # First, handle real primitives
            if self._primitive_type_name(arg_val) == name:
                return True, 1.0, 1, 1
            # If name is not a real primitive, attempt scope-name matching against the argument's family.
            try:
                from slip.slip_datatypes import Scope as _Scope
            except Exception:
                _Scope = None
            if _Scope and isinstance(arg_val, _Scope):
                arg_fam, arg_size = self._value_family(arg_val)
                # Match by meta.name of any scope in the argument's family
                for s in arg_fam:
                    try:
                        sname = s.meta.get('name')
                    except Exception:
                        sname = None
                    if sname == name:
                        # Treat this like a scope match; use the signature side family size for coverage
                        fam = self._scope_family(s)
                        fam_size = len(fam) if fam else 1
                        cov = fam_size / max(1, arg_size)
                        return True, cov, 1, fam_size
            # No match
            return False, 0.0, 0, 0
        if kind == 'scope':
            fam = scope_family(compiled_ann['scope'])
            applicable = compiled_ann['scope'] in arg_fam
            cov = (len(fam) / max(1, arg_size)) if applicable else 0.0
            return applicable, cov, 1, len(fam)
        if kind == 'and':
            # all members must be applicable; accumulate signature family size
            scope_union = set()
            prim_count = 0
            union_fam_sum = 0
            detail = 0
            for it in compiled_ann['items']:
                ok, _cov, dcnt, fam_sz = self._annotation_branch_applicable(it, arg_val)
                if not ok:
                    return False, 0.0, 0, 0
                if it['kind'] == 'scope':
                    scope_union |= self._scope_family(it['scope'])
                    detail += 1
                elif it['kind'] == 'prim':
                    prim_count += 1
                    detail += 1
                elif it['kind'] in ('and', 'union'):
                    # Include the chosen branch’s family size and detail
                    union_fam_sum += fam_sz
                    detail += dcnt
                else:
                    detail += 1
            fam_size = len(scope_union) + prim_count + union_fam_sum
            cov = fam_size / max(1, arg_size)
            return True, cov, detail, fam_size
        if kind == 'union':
            # pick the best matching branch
            best = (False, 0.0, 0, 0)
            for it in compiled_ann['items']:
                ok, cov, dcnt, fam_sz = self._annotation_applicability_and_coverage(it, arg_val)
                if ok and (cov > best[1]):
                    best = (ok, cov, dcnt, fam_sz)
            return best
        # Fallback: treat as non-applicable
        return False, 0.0, 0, 0

    # small helper used by _annotation_applicability_and_coverage for 'and' branches
    def _annotation_branch_applicable(self, compiled_ann, arg_val):
        return self._annotation_applicability_and_coverage(compiled_ann, arg_val)

    async def _legacy_dispatch_generic(self, func: GenericFunction, args: list, scope: Scope):
        # This is the logic from the older 'match func: GenericFunction()' branch.
        def _build_guard_scope(method: SlipFunction):
            call_scope = Scope(parent=method.closure)
            s = getattr(method, 'meta', {}).get('type')
            if isinstance(s, Sig):
                for param_name, arg_val in zip(s.positional, args):
                    name = param_name if isinstance(param_name, str) else getattr(param_name, 'text', str(param_name))
                    call_scope[name] = arg_val
                offset = len(s.positional)
                for i, param_name in enumerate(s.keywords.keys()):
                    if offset + i < len(args):
                        name = param_name if isinstance(param_name, str) else getattr(param_name, 'text', str(param_name))
                        call_scope[name] = args[offset + i]
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

        guarded_exact: list[SlipFunction] = []
        plain_exact: list[SlipFunction] = []
        for m in reversed(func.methods):
            s = getattr(m, 'meta', {}).get('type')
            if not isinstance(s, Sig):
                continue
            base = len(s.positional) + len(s.keywords)
            if s.rest is not None or len(args) != base:
                continue
            if not await self._sig_types_match(s, m, args, scope):
                continue
            guards = getattr(m, 'meta', {}).get('guards') or []
            if guards:
                guard_scope = _build_guard_scope(m)
                ok = True
                for g in guards:
                    val = await self._eval(g.ast, guard_scope) if isinstance(g, Code) else await self._eval(g, guard_scope)
                    if isinstance(val, Response) and isinstance(val.status, PathLiteral) and isinstance(val.status.inner, GetPath) and len(val.status.inner.segments) == 1 and isinstance(val.status.inner.segments[0], Name) and val.status.inner.segments[0].text == "return":
                        val = val.value
                    if not val:
                        ok = False
                        break
                if ok:
                    guarded_exact.append(m)
            else:
                plain_exact.append(m)
        if guarded_exact:
            return await self.call(guarded_exact[0], args, scope)
        if plain_exact:
            return await self.call(plain_exact[0], args, scope)

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
            if isinstance(s, Sig):
                base = len(s.positional) + len(s.keywords)
                types_ok = await self._sig_types_match(s, m, args, scope)
            guard_ok = True
            if guards:
                guard_scope = _build_guard_scope(m)
                for g in guards:
                    val = await self._eval(g.ast, guard_scope) if isinstance(g, Code) else await self._eval(g, guard_scope)
                    if isinstance(val, Response) and isinstance(val.status, PathLiteral) and isinstance(val.status.inner, GetPath) and len(val.status.inner.segments) == 1 and isinstance(val.status.inner.segments[0], Name) and val.status.inner.segments[0].text == "return":
                        val = val.value
                    if not val:
                        guard_ok = False
                        break
            if not guard_ok:
                continue
            if isinstance(s, Sig):
                if s.rest is None and len(args) == base and types_ok:
                    (exact_nonvar_guarded if guards else exact_nonvar_plain).append(m)
                elif s.rest is not None and len(args) >= base and types_ok:
                    (variadic_ok_guarded if guards else variadic_ok_plain).append((base, m))
            else:
                (no_sig_guarded if guards else no_sig_plain).append(m)

        if exact_nonvar_guarded:
            return await self.call(exact_nonvar_guarded[-1], args, scope)
        if exact_nonvar_plain:
            return await self.call(exact_nonvar_plain[-1], args, scope)
        if variadic_ok_guarded:
            max_base = max(b for b, _ in variadic_ok_guarded)
            options = [m for b, m in variadic_ok_guarded if b == max_base]
            return await self.call(options[-1], args, scope)
        if variadic_ok_plain:
            max_base = max(b for b, _ in variadic_ok_plain)
            options = [m for b, m in variadic_ok_plain if b == max_base]
            return await self.call(options[-1], args, scope)
        if no_sig_guarded:
            return await self.call(no_sig_guarded[-1], args, scope)
        # Fallback: try core- prefixed builtin (e.g., has-key? -> core-has-key?)
        try:
            name = getattr(func, "name", None)
            if isinstance(name, str):
                from slip.slip_datatypes import GetPath as _GP, Name as _Name
                core_path = _GP([_Name(f"core-{name}")])
                alt = await self.path_resolver.get(core_path, scope)
                return await self.call(alt, args, scope)
        except Exception:
            pass
        err = TypeError("No matching method")
        try:
            err.slip_detail = "No matching method"
        except Exception:
            pass
        raise err

    async def call(self, func: Any, args: List[Any], scope: Scope):
        """Calls a callable (SlipFunction or Python function)."""
        self._dbg("Evaluator.call", type(func).__name__, "argc", len(args))
        # Normalize arguments: unwrap 'return' responses so nested calls receive values.
        if isinstance(args, list):
            args = [
                (a.value if isinstance(a, Response) and isinstance(a.status, PathLiteral) and isinstance(a.status.inner, GetPath) and len(a.status.inner.segments) == 1 and isinstance(a.status.inner.segments[0], Name) and a.status.inner.segments[0].text == "return" else a)
                for a in args
            ]

        if isinstance(func, GenericFunction):
            self._dbg("GF call", func.name, "argc", len(args), "methods", len(func.methods))

            def _build_guard_scope(method: SlipFunction):
                call_scope = Scope(parent=method.closure)
                s = getattr(method, 'meta', {}).get('type')
                if isinstance(s, Sig):
                    for param_name, arg_val in zip(s.positional, args):
                        name = param_name if isinstance(param_name, str) else getattr(param_name, 'text', str(param_name))
                        call_scope[name] = arg_val
                    offset = len(s.positional)
                    for i, param_name in enumerate(s.keywords.keys()):
                        if offset + i < len(args):
                            name = param_name if isinstance(param_name, str) else getattr(param_name, 'text', str(param_name))
                            call_scope[name] = args[offset + i]
                    if s.rest is not None:
                        name = s.rest if isinstance(s.rest, str) else getattr(s.rest, 'text', str(s.rest))
                        base = len(s.positional) + len(s.keywords)
                        call_scope[name] = args[base:] if len(args) > base else []
                return call_scope

            exact, variadic, untyped = [], [], []
            for m in func.methods:
                s = getattr(m, 'meta', {}).get('type')
                if isinstance(s, Sig):
                    base = len(s.positional) + len(s.keywords)
                    if s.rest is None and len(args) == base:
                        exact.append(m)
                    elif s.rest is not None and len(args) >= base:
                        variadic.append(m)
                else:
                    untyped.append(m)

            if exact:
                tier = exact
            elif variadic:
                tier = variadic
            else:
                tier = untyped

            guarded = []
            plain = []
            for m in tier:
                guards = getattr(m, 'meta', {}).get('guards') or []
                if not guards:
                    plain.append(m)
                    continue
                call_scope = _build_guard_scope(m)
                ok = True
                for g in guards:
                    val = await self._eval(g.ast, call_scope) if hasattr(g, 'ast') else await self._eval(g, call_scope)
                    if isinstance(val, Response):
                        st = val.status
                        if (
                            isinstance(st, PathLiteral)
                            and isinstance(getattr(st, "inner", None), GetPath)
                            and len(st.inner.segments) == 1
                            and isinstance(st.inner.segments[0], Name)
                            and st.inner.segments[0].text == "return"
                        ):
                            val = val.value
                    if not val:
                        ok = False
                        break
                if ok:
                    guarded.append(m)

            candidates = guarded + plain

            if not candidates:
                # Lenient fallback: If no candidates in the primary tier, try exact-arity
                # methods by truncating extra arguments from the right.
                exact_guarded = []
                exact_plain = []
                for m in func.methods:
                    s = getattr(m, 'meta', {}).get('type')
                    if not isinstance(s, Sig):
                        continue
                    base = len(s.positional) + len(s.keywords)
                    if s.rest is not None:
                        continue
                    if len(args) < base:
                        continue
                    # Check types/guards against truncated args
                    trunc_args = args[:base]
                    types_ok = await self._sig_types_match(s, m, trunc_args, scope)
                    if not types_ok:
                        continue
                    guards = getattr(m, 'meta', {}).get('guards') or []
                    if guards:
                        call_scope = _build_guard_scope(m)
                        ok = True
                        for g in guards:
                            val = await self._eval(g.ast, call_scope) if hasattr(g, 'ast') else await self._eval(g, call_scope)
                            if isinstance(val, Response):
                                st = val.status
                                if (
                                    isinstance(st, PathLiteral)
                                    and isinstance(getattr(st, "inner", None), GetPath)
                                    and len(st.inner.segments) == 1
                                    and isinstance(st.inner.segments[0], Name)
                                    and st.inner.segments[0].text == "return"
                                ):
                                    val = val.value
                            if not val:
                                ok = False
                                break
                        if ok:
                            exact_guarded.append((m, trunc_args))
                    else:
                        exact_plain.append((m, trunc_args))
                # Prefer most recently defined guarded, then plain
                if exact_guarded:
                    m, trunc_args = exact_guarded[-1]
                    return await self.call(m, trunc_args, scope)
                if exact_plain:
                    m, trunc_args = exact_plain[-1]
                    return await self.call(m, trunc_args, scope)
                # Fallback to legacy dispatcher if lenient mode also found nothing
                return await self._legacy_dispatch_generic(func, args, scope)

            def score_method(m):
                s = getattr(m, 'meta', {}).get('type')
                if not isinstance(s, Sig):
                    return (0.0, 0, 0, bool(getattr(m, 'meta', {}).get('guards') or []))
                comp = self._compile_method_signature(m, scope)
                pos_n = comp['positional']
                typed = comp['keywords']
                total = 0.0
                detail = 0
                fam_sum = 0
                for idx, (_nm, ann) in enumerate(typed):
                    arg_i = pos_n + idx
                    if arg_i >= len(args):
                        return (-1.0, 0, 0, False)
                    ok, cov, dcnt, fam_sz = self._annotation_applicability_and_coverage(ann, args[arg_i])
                    if not ok:
                        return (-1.0, 0, 0, False)
                    total += cov
                    detail += dcnt
                    fam_sum += fam_sz
                has_guard = bool(getattr(m, 'meta', {}).get('guards') or [])
                return (total, detail, fam_sum, has_guard)

            scored = []
            for m in candidates:
                sc, det, famsz, has_guard = score_method(m)
                if sc >= 0.0:
                    scored.append((sc, det, famsz, has_guard, m))

            if not scored:
                # Fallback to legacy dispatcher
                return await self._legacy_dispatch_generic(func, args, scope)

            max_score = max(s for s, *_ in scored)
            best = [t for t in scored if t[0] == max_score]
            if len(best) > 1:
                guarded_best = [t for t in best if t[3]]
                if guarded_best:
                    best = guarded_best
            if len(best) > 1:
                max_detail = max(t[1] for t in best)
                best = [t for t in best if t[1] == max_detail]
            if len(best) > 1:
                max_fam = max(t[2] for t in best)
                best = [t for t in best if t[2] == max_fam]
            if len(best) != 1:
                err = TypeError("Ambiguous method call")
                try:
                    err.slip_detail = "Ambiguous method call: candidates have tied scores."
                except Exception:
                    pass
                raise err

            chosen = best[0][4]
            return await self.call(chosen, args, scope)

        match func:
            case GenericFunction():
                # ADD: entry debug
                self._dbg("GF call", func.name, "argc", len(args), "methods", len(func.methods))
                # Helper to build a scope for evaluating guards with parameters bound
                def _build_guard_scope(method: SlipFunction):
                    call_scope = Scope(parent=method.closure)
                    s = getattr(method, 'meta', {}).get('type')
                    if isinstance(s, Sig):
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

                # Hard preference: exact-arity, non-variadic match (guarded outranks plain)
                guarded_exact: list[SlipFunction] = []
                plain_exact: list[SlipFunction] = []

                for m in reversed(func.methods):  # most recent first
                    s = getattr(m, 'meta', {}).get('type')
                    if not isinstance(s, Sig):
                        continue
                    base = len(s.positional) + len(s.keywords)
                    if s.rest is not None or len(args) != base:
                        continue
                    # Type match
                    if not await self._sig_types_match(s, m, args, scope):
                        continue
                    guards = getattr(m, 'meta', {}).get('guards') or []
                    if guards:
                        guard_scope = _build_guard_scope(m)
                        ok = True
                        for g in guards:
                            val = await self._eval(g.ast, guard_scope) if isinstance(g, Code) else await self._eval(g, guard_scope)
                            if isinstance(val, Response) and isinstance(val.status, PathLiteral) and isinstance(val.status.inner, GetPath) and len(val.status.inner.segments) == 1 and isinstance(val.status.inner.segments[0], Name) and val.status.inner.segments[0].text == "return":
                                val = val.value
                            if not val:
                                ok = False
                                break
                        if ok:
                            guarded_exact.append(m)
                            # ADD: log candidate
                            self._dbg("GF exact candidate guarded", getattr(m, "meta", {}).get("type"))
                    else:
                        plain_exact.append(m)
                        # ADD: log candidate
                        self._dbg("GF exact candidate plain", getattr(m, "meta", {}).get("type"))

                if guarded_exact:
                    # ADD: log pick
                    self._dbg("GF pick exact_guarded", getattr(guarded_exact[0], "meta", {}).get("type"))
                    return await self.call(guarded_exact[0], args, scope)  # most recent guarded
                if plain_exact:
                    # ADD: log pick
                    self._dbg("GF pick exact_plain", getattr(plain_exact[0], "meta", {}).get("type"))
                    return await self.call(plain_exact[0], args, scope)    # most recent plain

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
                    if isinstance(s, Sig):
                        base = len(s.positional) + len(s.keywords)
                        types_ok = await self._sig_types_match(s, m, args, scope)
                        self._dbg("GF method", getattr(m, 'name', None) or repr(m), "base", base, "rest", bool(s.rest), "types_ok", types_ok)
                    # Evaluate guards if present
                    guard_ok = True
                    if guards:
                        guard_scope = _build_guard_scope(m)
                        for g in guards:
                            val = await self._eval(g.ast, guard_scope) if isinstance(g, Code) else await self._eval(g, guard_scope)
                            if isinstance(val, Response) and isinstance(val.status, PathLiteral) and isinstance(val.status.inner, GetPath) and len(val.status.inner.segments) == 1 and isinstance(val.status.inner.segments[0], Name) and val.status.inner.segments[0].text == "return":
                                val = val.value
                            if not val:
                                guard_ok = False
                                break
                    if not guard_ok:
                        continue  # skip this method entirely

                    if isinstance(s, Sig):
                        if s.rest is None and len(args) == base and types_ok:
                            (exact_nonvar_guarded if guards else exact_nonvar_plain).append(m)
                        elif s.rest is not None and len(args) >= base and types_ok:
                            (variadic_ok_guarded if guards else variadic_ok_plain).append((base, m))
                    else:
                        (no_sig_guarded if guards else no_sig_plain).append(m)

                # If any exact-arity candidates exist, ignore variadic ones entirely to ensure exact wins.
                if exact_nonvar_guarded or exact_nonvar_plain:
                    variadic_ok_guarded = []
                    variadic_ok_plain = []

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
                    if isinstance(mt, Sig):
                        sig_obj = mt
                # Extra safety: if meta.type wasn't set for some reason, but args holds a Sig, use it.
                if sig_obj is None and isinstance(func.args, Sig):
                    sig_obj = func.args

                self._dbg("SlipFunction call", repr(func), "argc", len(args), "has_sig", bool(sig_obj))
                if isinstance(sig_obj, Sig):
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
                    if isinstance(result.status, PathLiteral) and isinstance(result.status.inner, GetPath) and len(result.status.inner.segments) == 1 and isinstance(result.status.inner.segments[0], Name) and result.status.inner.segments[0].text == "return":
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

