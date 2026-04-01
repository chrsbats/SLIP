"""
Transforms the raw parser AST into a semantic AST using slip_datatypes.
"""


from slip.slip_datatypes import (
    Code, List, IString,
    PathLiteral,
    GetPath, SetPath, DelPath, Name, Index, Slice, FilterQuery, Group,
    Root, Parent, Pwd, PipedPath,
    Sig, PostPath, ByteStream, MultiSetPath, IdentityBoundary
)

class SlipTransformer:
    def _attach_loc(self, obj, node):
        line = node.get('line'); col = node.get('col')
        if line is not None and col is not None and hasattr(obj, '__dict__'):
            obj.loc = {'line': line, 'col': col, 'tag': node.get('tag'), 'text': node.get('text')}
        return obj

    def transform(self, node: object) -> object:
        # Lists: transform each item
        if isinstance(node, list):
            return [self.transform(n) for n in node]

        # Primitives already in final form
        if not isinstance(node, dict):
            return node

        # Koine subgrammar namespace wrappers (e.g., 'SlipPath_*'): unwrap
        tag = node.get('tag')
        if isinstance(tag, str) and tag.startswith('Slip'):
            children = node.get('children', [])
            if len(children) == 1:
                return self.transform(children[0])
            return self.transform(children)

        # Named-children dicts (no 'tag')
        if 'tag' not in node:
            return {k: self.transform(v) for k, v in node.items()}

        children = node.get('children', [])

        # Fast tag switch
        match tag:
            # Structural containers
            case 'expr':
                # Standalone comment line becomes an empty expression (no-op)
                if len(children) == 1 and isinstance(children[0], dict) and children[0].get('tag') in ('comment', 'line-comment', 'block-comment'):
                    return []

                terms = self.transform(children)

                # Write IR annotation (keep surface homoiconicity):
                # - Keep the surface form as an expression whose head is SetPath.
                # - Annotate the SetPath with an IR-only flag: sp.write_kind = 'value'|'commit'
                # - Validate write shapes here so the evaluator doesn't need to rescan.
                if isinstance(terms, list) and terms and isinstance(terms[0], SetPath):
                    sp: SetPath = terms[0]

                    # Reserve `this` as a normal assignment target (must not be `this:`).
                    if (
                        len(getattr(sp, "segments", []) or []) == 1
                        and isinstance(sp.segments[0], Name)
                        and sp.segments[0].text == "this"
                    ):
                        err = SyntaxError("`this` is reserved and cannot be assigned")
                        try:
                            err.slip_obj = sp
                        except Exception:
                            pass
                        raise err

                    segs = list(getattr(sp, "segments", []) or [])

                    # Enforce: write targets cannot cross identity boundaries (::)
                    if any(s is IdentityBoundary for s in segs):
                        err = PermissionError("Cannot write across an identity boundary (::)")
                        try:
                            err.slip_obj = sp
                        except Exception:
                            pass
                        raise err

                    kind = "commit" if (segs and isinstance(segs[0], Name) and segs[0].text == "this" and len(segs) > 1) else "value"
                    try:
                        sp.write_kind = kind
                    except Exception:
                        # Best-effort: do not fail transformation if annotation cannot be attached.
                        pass

                return terms
            case 'code':
                # Transform each child expr. If an expr consists solely of multiple PathLiterals,
                # split them into separate expressions to match expected AST shape.
                items = []
                for ch in children:
                    if isinstance(ch, dict) and ch.get('tag') == 'expr':
                        terms = self.transform(ch.get('children', []))
                        if isinstance(terms, list) and len(terms) > 1 and all(isinstance(t, PathLiteral) for t in terms):
                            items.extend([[t] for t in terms])
                        else:
                            items.append(terms)
                    else:
                        items.append(self.transform(ch))
                return self._attach_loc(Code(items), node)
            case 'list':
                return self._attach_loc(List(self.transform(children)), node)
            case 'typed-list':
                # children is a dict because we used ast: { name: ... } in the grammar
                tnode = (children or {}).get('t')
                items = (children or {}).get('items') or []
                tname = tnode.get('text') if isinstance(tnode, dict) else None
                bs = ByteStream(tname, self.transform(items))
                return self._attach_loc(bs, node)
            case 'group':
                return self._attach_loc(Group(self.transform(children)), node)

            # Atomics
            case 'number':
                # Ensure integers (no '.') are parsed as exact Python ints, avoiding float rounding for large values.
                txt = node.get('text')
                if isinstance(txt, str) and '.' not in txt:
                    try:
                        return int(txt)
                    except Exception:
                        pass
                return node['value']
            case 'boolean' | 'null':
                return node['value']
            case 'string':
                return node['text']
            case 'i-string':
                return IString(node['text'])

            # Path segments
            case 'name':
                return self._attach_loc(Name(node['text']), node)
            case 'root':
                return Root
            case 'parent':
                return Parent
            case 'pwd':
                return Pwd
            case 'identity':
                return IdentityBoundary

            # Query segment to Index/Slice
            case 'query-segment':
                return self._query_to_segment(node)

            # Full paths
            case 'get-path':
                segments, meta = self._segments_and_meta(children)
                obj = GetPath(segments, meta)
                return self._attach_loc(obj, node)
            case 'piped-path':
                segments, meta = self._segments_and_meta(children)
                return self._attach_loc(PipedPath(segments, meta), node)

            case 'quoted-set-path':
                # Leaf token text includes the trailing ':', e.g. "\"a\":"
                t = node.get('text') or ""
                if not isinstance(t, str) or not t.endswith(":") or len(t) < 3:
                    raise ValueError("quoted-set-path invalid key token")
                inner = t[:-1]  # strip trailing ':'
                if inner.startswith('"') and inner.endswith('"'):
                    body = inner[1:-1]
                    # Double-quoted keys are i-strings; evaluate at runtime via a Group segment.
                    # Represent the Group as a single expression [IString(...)] so Evaluator._eval
                    # will render the i-string to a concrete Python str.
                    seg = Group([[IString(body)]])
                    sp = SetPath([seg], None)
                    return self._attach_loc(sp, node)
                raise ValueError("quoted-set-path expected double quotes")

            case 'quoted-raw-set-path':
                # Leaf token text includes the trailing ':', e.g. "'a field':"
                t = node.get('text') or ""
                if not isinstance(t, str) or not t.endswith(":") or len(t) < 3:
                    raise ValueError("quoted-raw-set-path invalid key token")
                inner = t[:-1]
                if inner.startswith("'") and inner.endswith("'"):
                    body = inner[1:-1]
                    sp = SetPath([Name(body)], None)
                    return self._attach_loc(sp, node)
                raise ValueError("quoted-raw-set-path expected single quotes")

            case 'set-path':
                segments, meta = self._segments_and_meta(children)
                return self._attach_loc(SetPath(segments, meta), node)
            case 'post-path':
                segments, meta = self._segments_and_meta(children)
                return self._attach_loc(PostPath(segments, meta), node)
            case 'del-path':
                segments, meta = self._segments_and_meta(children)
                dp = DelPath(GetPath(segments, meta))
                return self._attach_loc(dp, node)
            case 'multi-set-path':
                return ('multi-set', [self.transform(c) for c in children])

            # Path literals -> literal datatypes
            case 'path-literal':
                if not children:
                    raise ValueError("Path literal cannot be empty.")
                inner = self.transform(children[0])
                if isinstance(inner, tuple) and inner[0] == 'multi-set':
                    inner = MultiSetPath(inner[1])
                if not isinstance(inner, (GetPath, SetPath, DelPath, PipedPath, MultiSetPath)):
                    raise TypeError(f"Unexpected path type in path literal: {type(inner)}")
                return self._attach_loc(PathLiteral(inner), node)

            # Desugar literals
            case 'dict':
                # Note: #{...} is the 'dict' tag. It contains expressions to be evaluated.
                # The evaluator will handle creating a dict from these.
                return ('dict', self.transform(children))
            case 'sig-conjunction' | 'sig-and':
                # Direct conjunction node from grammar: normalize to ('and', items)
                items = [self.transform(c) for c in children]
                return ('and', items)
            case 'sig-union':
                # Normalize union node to ('union', [...]) for use in annotations/values
                items = [self.transform(c) for c in children]
                return ('union', items)
            # Sig literal: construct a Sig object
            case 'sig':
                # Top-level union-only sig alias: { A or B or C }
                for ch in children:
                    if isinstance(ch, dict) and ch.get('tag') == 'sig-union':
                        items = [self.transform(c) for c in (ch.get('children') or [])]
                        sig = Sig(items, {}, None, None)
                        return self._attach_loc(sig, node)

                # Contract: if `this: ...` appears, it must be the first parameter in the sig.
                # Other typed kwargs may appear anywhere.
                #
                # IMPORTANT: enforce this based on the *transformed* Sig that this method
                # constructs (positional first, then typed keywords), because the slip_sig
                # grammar does not preserve a single unified parameter list ordering in a
                # way we can rely on here.

                positional: list[str] = []
                keywords: dict[str, object] = {}
                rest: str | None = None
                return_annotation = None
                where_block = None
                for ch in children:
                    ctag = ch.get('tag')
                    if ctag == 'sig-where':
                        if where_block is not None:
                            # Use a standard Python SyntaxError which ScriptRunner catches
                            raise SyntaxError("Only one |where clause is allowed per signature")

                        # Taste-aligned validation: keep the grammar structural and reject
                        # multiple where-clauses semantically.
                        try:
                            expr_node = (ch.get("children", {}) or {}).get("expression") or {}
                            expr_text = expr_node.get("text") if isinstance(expr_node, dict) else None
                            if isinstance(expr_text, str) and "|where" in expr_text:
                                raise SyntaxError("Only one |where clause is allowed per signature")
                        except SyntaxError:
                            raise
                        except Exception:
                            pass

                        expr_nodes = ch.get('children', {}).get('expression')
                        transformed = self.transform(expr_nodes)

                        # Normalize to Code(nodes): list of expressions (each expr is a list of terms).
                        if transformed is None:
                            transformed = []
                        elif isinstance(transformed, list) and (not transformed or not isinstance(transformed[0], list)):
                            transformed = [transformed]

                        where_block = self._attach_loc(Code(transformed), ch)
                    elif ctag == 'sig-arg':
                        positional.append(self._extract_sig_name(ch))
                    elif ctag == 'sig-kwarg':
                        c = ch['children']

                        # Extract key node from the slip_sig grammar shape:
                        # sig_kwarg children are a dict with keys 'sig-key' and 'value'.
                        key_node = c.get('sig-key') if isinstance(c, dict) else None
                        val_node = c.get('value') if isinstance(c, dict) else None

                        # Transform key node; it will typically become a Name(...)
                        key_obj = self.transform(key_node) if key_node is not None else None
                        key = None
                        if isinstance(key_obj, Name):
                            key = key_obj.text
                        elif isinstance(key_obj, str):
                            key = key_obj
                        elif isinstance(key_node, dict):
                            key = key_node.get('text')

                        if key is None:
                            raise ValueError("sig-kwarg missing key")

                        keywords[key] = self._transform_sig_value(val_node)
                    elif ctag == 'sig-rest-arg':
                        rest = self._extract_sig_name(ch)
                    elif ctag == 'sig-return':
                        val_children = ch.get('children') or []
                        if val_children:
                            return_annotation = self._transform_sig_value(val_children[0])

                sig = Sig(positional, keywords, rest, return_annotation, where_block)

                # Enforce `this: ...` must be the first declared parameter.
                #
                # We must enforce this using the same parameter stream we just used
                # to build `positional` and `keywords`, because `Sig(positional, keywords, ...)`
                # itself loses source ordering.
                #
                # Contract:
                #   - `{this: T, x}` is valid
                #   - `{x, this: T}` is invalid
                #
                # Implementation: if we see any positional param before encountering
                # `this: ...`, then `this` is not first.
                try:
                    seen_positional = False
                    for ch in children:
                        if not isinstance(ch, dict):
                            continue
                        ctag = ch.get('tag')
                        if ctag == 'sig-arg':
                            seen_positional = True
                            continue
                        if ctag == 'sig-kwarg':
                            c = ch.get('children')
                            key_node = c.get('sig-key') if isinstance(c, dict) else None
                            key_txt = key_node.get('text') if isinstance(key_node, dict) else None
                            if key_txt == 'this':
                                if seen_positional:
                                    err = SyntaxError("`this` is reserved and must be the first parameter when used (as `this: Type`)")
                                    try:
                                        err.slip_obj = sig
                                    except Exception:
                                        pass
                                    raise err
                                break
                            continue
                except SyntaxError:
                    raise
                except Exception:
                    pass

                return self._attach_loc(sig, node)

            case _:
                raise NotImplementedError(f"No transformer for tag '{tag}'")


    # --- Path Transformers ---

    def _segments_and_meta(self, raw_children):
        seg_nodes = []
        meta = None
        for ch in raw_children:
            if isinstance(ch, dict) and ch.get('tag') == 'meta':
                meta = Group(self.transform(ch.get('children', [])))
            else:
                seg_nodes.append(ch)
        segments = self.transform(seg_nodes)  # transforms query-segment to Index/Slice, names, groups, etc.
        return segments, meta

    def _query_to_segment(self, node):
        children = node.get('children', [])
        if not children:
            raise NotImplementedError("Empty query-segment")
        inner = children[0]
        itag = inner.get('tag')

        if itag == 'simple-query':
            expr_nodes = inner.get('children', [])
            terms = self.transform(expr_nodes[0]) if expr_nodes else []

            # Normalize ambiguous '/' token: a get-path consisting only of Root
            # inside a predicate chain is intended to be the '/' operator.
            def _normalize_division_operator(ts):
                if not isinstance(ts, list):
                    return ts
                out = []
                for t in ts:
                    if isinstance(t, GetPath) and len(t.segments) == 1 and t.segments[0] is Root:
                        out.append(GetPath([Name('/')]))
                    else:
                        out.append(t)
                return out

            terms = _normalize_division_operator(terms)

            # If this is a multi-term expression, treat it as a predicate chain.
            if isinstance(terms, list) and len(terms) >= 2:
                obj = FilterQuery(None, None, predicate_ast=terms)
                return self._attach_loc(obj, node)

            # Single-term PipedPath (e.g., |fn) is also a predicate chain.
            first = terms[0] if isinstance(terms, list) and terms else None
            if isinstance(first, PipedPath):
                obj = FilterQuery(None, None, predicate_ast=terms)
                return self._attach_loc(obj, node)

            # Otherwise, it's an index/key query
            obj = Index(terms)
            return self._attach_loc(obj, node)

        if itag == 'slice-query':
            start_ast = None
            end_ast = None
            for sub in inner.get('children', []):
                subtag = sub.get('tag')
                if subtag in ('start-expr', 'start'):
                    exprs = sub.get('children', [])
                    start_ast = self.transform(exprs[0]) if exprs else None
                elif subtag in ('end-expr', 'end'):
                    exprs = sub.get('children', [])
                    end_ast = self.transform(exprs[0]) if exprs else None
            obj = Slice(start_ast, end_ast)
            return self._attach_loc(obj, node)

        if itag == 'filter-query':
            op = None
            rhs_ast = []
            for sub in inner.get('children', []):
                subtag = sub.get('tag')
                if subtag == 'operator':
                    op = sub.get('text')
                elif subtag == 'rhs-expr':
                    exprs = sub.get('children', [])
                    rhs_ast = self.transform(exprs[0]) if exprs else []
            if op is None:
                raise ValueError("filter-query missing operator")
            # Legacy sugar: turn [> X] into a predicate chain [>, X]
            pred = [GetPath([Name(op)])] + (rhs_ast if isinstance(rhs_ast, list) else [rhs_ast])
            obj = FilterQuery(op, rhs_ast, pred)
            return self._attach_loc(obj, node)

        raise NotImplementedError("Unsupported query-segment type: " + str(itag))

    def _transform_sig_value(self, val_node):
        # Fast-path for structured nodes coming from the sig grammar (e.g., sig-union).
        if isinstance(val_node, dict) and val_node.get('tag') != 'expr':
            return self.transform(val_node)

        # The sig subgrammar encodes simple values as a leaf 'expr' with a 'text' payload.
        # Parse a minimal subset needed for typing/dispatch:
        #  - booleans/none
        #  - numbers
        #  - quoted strings (raw and i-string)
        #  - backticked names: `int`, `string`, etc -> GetPath(Name(...))
        #  - parenthesized conjunctions: (A and B and C) -> ('and', [GetPath(Name(A)), ...])
        #  - bare names: Foo -> GetPath(Name('Foo'))
        if isinstance(val_node, dict) and val_node.get('tag') == 'expr' and 'text' in val_node:
            s = val_node.get('text')
            if isinstance(s, str):
                t = s.strip()

                # booleans/none
                if t == "true":
                    return True
                if t == "false":
                    return False
                if t == "none":
                    return None

                # quoted strings
                if len(t) >= 2 and t[0] == "'" and t[-1] == "'":
                    return t[1:-1]
                if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
                    return IString(t[1:-1])

                # numbers
                try:
                    if any(ch in t for ch in ('.', 'e', 'E')):
                        return float(t)
                    return int(t)
                except ValueError:
                    pass

                # parenthesized conjunctions: (A and B and C)
                if len(t) >= 2 and t[0] == "(" and t[-1] == ")":
                    inner = t[1:-1].strip()
                    # Split on ' and ' (single spaces) which matches our test cases
                    parts = [p.strip() for p in inner.split(" and ") if p.strip()]
                    if len(parts) >= 2:
                        return ('and', [GetPath([Name(p)]) for p in parts])

                # backticked primitive/type names: `int`, `string`, etc.
                if len(t) >= 2 and t[0] == "`" and t[-1] == "`":
                    name = t[1:-1].strip()
                    return GetPath([Name(name)])

                # fallback: treat as a simple path name (support dotted paths like agents.Player)
                if "." in t:
                    parts = [p for p in t.split(".") if p]
                    return GetPath([Name(p) for p in parts])
                return GetPath([Name(t)])

        # Anything else: delegate to normal transform (e.g., unions already structured)
        return self.transform(val_node)


    def _extract_sig_name(self, node):
        # Accepts nodes that may be leaf with 'text' or a 'name' child
        if isinstance(node, dict):
            if 'text' in node and node.get('text'):
                return node['text']
            ch = node.get('children')
            if isinstance(ch, dict):
                if ch.get('tag') == 'name':
                    return ch.get('text')
            if isinstance(ch, list):
                for sub in ch:
                    if isinstance(sub, dict) and sub.get('tag') == 'name':
                        return sub.get('text')
        raise ValueError(f"Cannot extract signature name from node: {node!r}")



