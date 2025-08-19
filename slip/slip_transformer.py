"""
Transforms the raw parser AST into a semantic AST using slip_datatypes.
"""

from slip.slip_datatypes import (
    Code, List, IString,
    GetPathLiteral, SetPathLiteral, DelPathLiteral,
    GetPath, SetPath, DelPath, Name, Index, Slice, FilterQuery, Group,
    Root, Parent, Pwd, PipedPath,
    PipedPathLiteral, MultiSetPathLiteral,
    Sig, PostPath, ByteStream
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
                return self.transform(children)
            case 'code':
                return self._attach_loc(Code(self.transform(children)), node)
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
                if isinstance(inner, GetPath):
                    plit = GetPathLiteral(inner.segments, inner.meta)
                elif isinstance(inner, SetPath):
                    plit = SetPathLiteral(inner.segments, inner.meta)
                elif isinstance(inner, DelPath):
                    gp = inner.path
                    plit = DelPathLiteral(GetPathLiteral(gp.segments, gp.meta))
                elif isinstance(inner, PipedPath):
                    plit = PipedPathLiteral(inner.segments, inner.meta)
                elif isinstance(inner, tuple) and inner[0] == 'multi-set':
                    plit = MultiSetPathLiteral(inner[1])
                else:
                    raise TypeError(f"Unexpected path type in path literal: {type(inner)}")
                return self._attach_loc(plit, node)

            # Desugar literals
            case 'dict':
                # Note: #{...} is the 'dict' tag. It contains expressions to be evaluated.
                # The evaluator will handle creating a dict from these.
                return ('dict', self.transform(children))
            # Sig literal: construct a Sig object
            case 'sig':
                positional: list[str] = []
                keywords: dict[str, object] = {}
                rest: str | None = None
                return_annotation = None
                for ch in children:
                    ctag = ch.get('tag')
                    if ctag == 'sig-arg':
                        positional.append(self._extract_sig_name(ch))
                    elif ctag == 'sig-kwarg':
                        c = ch['children']
                        key = c['sig-key']['text'] if isinstance(c, dict) and 'sig-key' in c else None
                        # Robustly locate the value node irrespective of parser shape
                        val_node = None
                        if isinstance(c, dict):
                            # Prefer explicit 'value' key if present
                            val_node = c.get('value')
                            # Otherwise, pick the first dict child that is not 'sig-key'
                            if val_node is None:
                                for k, v in c.items():
                                    if k != 'sig-key' and isinstance(v, dict):
                                        val_node = v
                                        break
                        # Fallback: if children is a list, second element typically holds the value node
                        if val_node is None and isinstance(ch.get('children'), list) and len(ch['children']) > 1:
                            val_node = ch['children'][1]
                        keywords[key] = self._transform_sig_value(val_node)
                    elif ctag == 'sig-rest-arg':
                        rest = self._extract_sig_name(ch)
                    elif ctag == 'sig-return':
                        val_children = ch.get('children') or []
                        if val_children:
                            return_annotation = self._transform_sig_value(val_children[0])
                sig = Sig(positional, keywords, rest, return_annotation)
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
        # Koine sig_value is an expr leaf with a 'text' payload.
        if isinstance(val_node, dict) and val_node.get('tag') == 'expr' and 'text' in val_node:
            return self._parse_simple_literal(val_node['text'])
        return self.transform(val_node)

    def _parse_simple_literal(self, s: str):
        s = s.strip()
        # booleans/none
        if s == "true": return True
        if s == "false": return False
        if s == "none": return None
        # strings
        if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
            return s[1:-1]
        if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
            return IString(s[1:-1])
        # numbers
        try:
            if '.' in s:
                return float(s)
            return int(s)
        except ValueError:
            pass
        # fallback: treat as a simple path name
        return GetPath([Name(s)])

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

    def transform_path_literal(self, node):
        # The parser gives us a 'path-literal' node with a single child,
        # which is the AST for a get-path, set-path, or del-path.
        if not node.get('children'):
             # This can happen for an empty literal: ``
             raise ValueError("Path literal cannot be empty.")
        path_action_ast = node['children'][0]
        path_action_obj = self.transform(path_action_ast)

        if isinstance(path_action_obj, GetPath):
            return GetPathLiteral(path_action_obj.segments, path_action_obj.meta)
        if isinstance(path_action_obj, SetPath):
            return SetPathLiteral(path_action_obj.segments, path_action_obj.meta)
        if isinstance(path_action_obj, DelPath):
            get_path_action = path_action_obj.path
            return DelPathLiteral(GetPathLiteral(get_path_action.segments, get_path_action.meta))
        if isinstance(path_action_obj, PipedPath):
            return PipedPathLiteral(path_action_obj.segments, path_action_obj.meta)
        if isinstance(path_action_obj, tuple) and path_action_obj[0] == 'multi-set':
            return MultiSetPathLiteral(path_action_obj[1])

        raise TypeError(f"Unexpected path type in path literal: {type(path_action_obj)}")

    def transform_sig(self, node):
        # For this transformer, treat {...} as a dict literal and desugar to: (dict [...])
        assignments = []
        for child in node.get('children', []):
            if child.get('tag') == 'sig-kwarg':
                ch = child['children']
                key = ch['sig-key']['text']

                # Find the value node within the child mapping or fallback to second list child
                val_node = None
                for k, v in ch.items():
                    if k != 'sig-key' and isinstance(v, dict):
                        val_node = v
                        break
                if val_node is None and isinstance(child.get('children'), list) and len(child['children']) > 1:
                    val_node = child['children'][1]

                value = self.transform(val_node)
                assignments.append([SetPath([Name(key)]), value])

        dict_path = GetPath([Name('dict')])
        code_block = Code(assignments)
        return Group([[dict_path, code_block]])

