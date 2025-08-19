"""
A pretty-printer for SLIP data structures.
"""
import collections.abc

from slip.slip_datatypes import (
    Code, List, IString, SlipFunction, Response,
    GetPathLiteral, SetPathLiteral, DelPathLiteral,
    PipedPathLiteral, MultiSetPathLiteral,
    GetPath, SetPath, DelPath, PipedPath, Name, Index, Slice, FilterQuery, Group,
    Root, Parent, Pwd, PathSegment, PostPath, ByteStream
)
from slip.slip_runtime import SlipDict


class Printer:
    """Formats SLIP objects into readable, valid SLIP source strings."""

    def __init__(self, indent_width=2):
        self._indent_char = " " * indent_width
        self._handlers = self._create_handlers()

    def pformat(self, obj, level=0):
        """Public entry point to format an object."""
        handler = self._get_handler(obj)
        return handler(obj, level)

    def _get_handler(self, obj):
        """Dispatcher to find the correct formatting method."""
        # Fast path for singletons
        if obj is Root: return self._pformat_root
        if obj is Parent: return self._pformat_parent
        if obj is Pwd: return self._pformat_pwd

        obj_type = type(obj)
        if obj_type in self._handlers:
            return self._handlers[obj_type]
        # Fallback for tuples and other types
        if isinstance(obj, tuple) and len(obj) > 0:
            if obj[0] == 'multi-set': return self._pformat_multi_set
        if isinstance(obj, collections.abc.Mapping): return self._pformat_dict
        if isinstance(obj, list): return self._pformat_expr
        # Default to Python's repr for unknown types
        return lambda o, l: repr(o)

    def _create_handlers(self):
        return {
            str: self._pformat_str,
            IString: self._pformat_istring,
            int: self._pformat_primitive,
            float: self._pformat_primitive,
            bool: self._pformat_bool,
            type(None): self._pformat_none,
            GetPath: self._pformat_get_path,
            SetPath: self._pformat_set_path,
            DelPath: self._pformat_del_path,
            PostPath: self._pformat_post_path,
            GetPathLiteral: self._pformat_get_path_literal,
            SetPathLiteral: self._pformat_set_path_literal,
            DelPathLiteral: self._pformat_del_path_literal,
            PipedPath: self._pformat_piped_path,
            PipedPathLiteral: self._pformat_piped_path_literal,
            MultiSetPathLiteral: self._pformat_multi_set_path_literal,
            Name: self._pformat_name,
            Index: self._pformat_index,
            Slice: self._pformat_slice,
            FilterQuery: self._pformat_filter_query,
            Group: self._pformat_group,
            Code: self._pformat_code,
            List: self._pformat_list_slip,
            ByteStream: self._pformat_byte_stream,
            Response: self._pformat_response,
            SlipFunction: self._pformat_slip_function,
            SlipDict: self._pformat_dict,
        }

    def _pformat_primitive(self, obj, level):
        return str(obj)

    def _pformat_str(self, obj, level):
        # Basic string formatting, does not handle complex escapes
        return f"'{obj}'"

    def _pformat_istring(self, obj, level):
        return f'i"{obj}"'

    def _pformat_bool(self, obj, level):
        return 'true' if obj else 'false'

    def _pformat_none(self, obj, level):
        return 'none'

    def _pformat_multi_set(self, obj, level):
        paths = [self._pformat_path_contents(p, level) for p in obj[1]]
        return f"[{','.join(paths)}]:"

    def _pformat_expr(self, obj, level):
        if len(obj) >= 2:
            lhs = obj[0]
            rhs_str = " ".join(self.pformat(term, level) for term in obj[1:])

            lhs_str = self.pformat(lhs, level) if isinstance(lhs, (SetPath, DelPath)) or \
                                                 (isinstance(lhs, tuple) and lhs[0] == 'multi-set') else None

            if lhs_str:
                if '\n' in rhs_str:
                    rhs_lines = rhs_str.splitlines()
                    first_line = f"{lhs_str} {rhs_lines[0]}"
                    indent = self._indent_char * (level + 1)
                    indented_rest = [f"{indent}{line}" for line in rhs_lines[1:]]
                    return "\n".join([first_line] + indented_rest)
                return f"{lhs_str} {rhs_str}"

        if obj and isinstance(obj[0], GetPath):
            path_obj = obj[0]
            if len(path_obj.segments) == 1 and isinstance(path_obj.segments[0], Name):
                func_name = path_obj.segments[0].text
                if func_name in ('if', 'when', 'while', 'foreach', 'for', 'cond', 'method'):
                    return self._pformat_lisp_style_call(obj, level)

        return " ".join(self.pformat(item, level) for item in obj)

    def _pformat_lisp_style_call(self, obj, level):
        """Formats a call with func+first_arg on one line and other args on subsequent lines."""
        if len(obj) < 2:  # Not a typical control-flow call, fallback
            return " ".join(self.pformat(item, level) for item in obj)

        # A heuristic to decide how many arguments belong on the "header" line.
        func_name = obj[0].segments[0].text
        num_head_args = 2 if func_name == 'foreach' and len(obj) > 3 else 1

        # Format header line (e.g., "if [condition]" or "foreach item list")
        head_parts = [self.pformat(p, level) for p in obj[:1 + num_head_args]]
        header_line = " ".join(head_parts)

        # Format subsequent arguments (typically code blocks) on new, indented lines
        body_args = obj[1 + num_head_args:]
        if not body_args:
            return header_line

        inner_level = level + 1

        body_lines = []
        for arg in body_args:
            # We format the body arguments at the same level as the 'if' call itself.
            # The block formatter will correctly indent the *contents* of the block
            # one level deeper. This prevents a double-indent when the entire
            # if-expression is indented by a parent construct (like an assignment).
            arg_str = self.pformat(arg, level)
            body_lines.append(arg_str)

        return f"{header_line}\n" + "\n".join(body_lines)

    def _is_simple_arg_list(self, nodes):
        if not nodes:
            return True
        if len(nodes) != 1 or not isinstance(nodes[0], list):
            return False  # Must be a single expression list
        
        expr = nodes[0]
        if not expr: # e.g., code block is `[[]]`
            return True

        for term in expr:
            if not isinstance(term, GetPath):
                return False
            path = term
            if not (len(path.segments) == 1 and isinstance(path.segments[0], Name)):
                return False
        return True

    def _pformat_block(self, nodes, level, open_char, close_char):
        if not nodes:
            return f"{open_char}{close_char}"
        
        outer_indent = self._indent_char * level
        inner_level = level + 1
        inner_indent = self._indent_char * inner_level
        
        lines = []
        for node in nodes:
            arg_str = self.pformat(node, inner_level)
            arg_lines = arg_str.splitlines()
            if not arg_lines:
                continue
            
            # Indent the first line of the argument. Subsequent lines are already
            # correctly indented by the recursive pformat call.
            first_line = inner_indent + arg_lines[0]
            rest_lines = arg_lines[1:]
            
            all_lines = [first_line] + rest_lines
            lines.append("\n".join(all_lines))
        
        return f"{open_char}\n" + "\n".join(lines) + f"\n{outer_indent}{close_char}"

    def _pformat_code(self, obj, level):
        if self._is_simple_arg_list(obj.nodes):
            if not obj.nodes or not obj.nodes[0]:
                return "[]"
            inner = " ".join(self.pformat(item, level) for item in obj.nodes[0])
            return f"[{inner}]"
        return self._pformat_block(obj.nodes, level, '[', ']')

    def _pformat_list_slip(self, obj, level):
        return self._pformat_block(obj.nodes, level, '#[', ']')

    def _pformat_byte_stream(self, obj, level):
        # obj.nodes is a list of expression nodes to print
        if not obj.nodes:
            return f"{obj.elem_type}#[]"
        outer_indent = self._indent_char * level
        inner_level = level + 1
        inner_indent = self._indent_char * inner_level
        lines = []
        for node in obj.nodes:
            arg_str = self.pformat(node, inner_level)
            arg_lines = arg_str.splitlines() or [""]
            first_line = inner_indent + arg_lines[0]
            rest_lines = arg_lines[1:]
            lines.append("\n".join([first_line] + rest_lines))
        return f"{obj.elem_type}#[\n" + "\n".join(lines) + f"\n{outer_indent}]"

    def _pformat_group(self, obj, level):
        if not obj.nodes:
            return "()"
        inner = self._pformat_expr(obj.nodes[0], level)
        return f"({inner})"

    def _pformat_dict(self, obj, level):
        if not obj:
            return "{}"

        # Create a list of set expressions to format
        set_exprs = []
        for key, value in obj.items():
            # Note: this isn't a perfect round-trip if key is not a valid name
            set_exprs.append([SetPath([Name(str(key))]), value])
        
        return self._pformat_block(set_exprs, level, '{', '}')

    def _pformat_get_path(self, obj, level):
        return self._pformat_path_contents(obj, level)

    def _pformat_set_path(self, obj, level):
        return f"{self._pformat_path_contents(obj, level)}:"

    def _pformat_del_path(self, obj, level):
        return f"~{self._pformat_path_contents(obj.path, level)}"

    def _pformat_post_path(self, obj, level):
        return f"{self._pformat_path_contents(obj, level)}<-"

    def _pformat_get_path_literal(self, path, level):
        return f"`{self._pformat_path_contents(path, level)}`"

    def _pformat_set_path_literal(self, path, level):
        return f"`{self._pformat_path_contents(path, level)}:`"

    def _pformat_del_path_literal(self, path, level):
        return f"`~{self._pformat_path_contents(path.path, level)}`"

    def _pformat_piped_path(self, obj, level):
        """Formats a runtime PipedPath value (e.g., produced by the transformer)."""
        return f"|{self._pformat_path_contents(obj, level)}"

    def _pformat_piped_path_literal(self, path, level):
        return f"`{self._pformat_path_contents(path, level)}`"

    def _pformat_multi_set_path_literal(self, path, level):
        inner = self._pformat_multi_set(('multi-set', path.targets), level)
        return f"`{inner}`"

    def _pformat_path_contents(self, path, level):
        parts = []
        segments = path.segments

        for i, seg in enumerate(segments):
            is_name_like = isinstance(seg, Name)
            prev_seg = segments[i-1] if i > 0 else None
            prev_is_name_like = isinstance(prev_seg, Name)

            if i > 0 and is_name_like and prev_is_name_like:
                parts.append('.')

            parts.append(self.pformat(seg, level))

        path_str = "".join(parts)
        if hasattr(path, 'meta') and path.meta is not None:
            meta_str = self.pformat(path.meta, level)
            return f"{path_str}#{meta_str}"
        return path_str

    def _pformat_name(self, obj, level):
        return obj.text

    def _pformat_index(self, obj, level):
        inner = self.pformat(obj.expr_ast, level)
        return f"[{inner}]"

    def _pformat_slice(self, obj, level):
        start = self.pformat(obj.start_ast, level) if obj.start_ast else ""
        end = self.pformat(obj.end_ast, level) if obj.end_ast else ""
        return f"[{start}:{end}]"

    def _pformat_filter_query(self, obj, level):
        # Prefer predicate form if present
        if getattr(obj, 'predicate_ast', None) is not None:
            pred_str = self.pformat(obj.predicate_ast, level)
            return f"[{pred_str}]"
        rhs = self.pformat(obj.rhs_ast, level) if obj.rhs_ast is not None else ""
        return f"[{obj.operator} {rhs}]"

    def _pformat_root(self, obj, level): return "/"
    def _pformat_parent(self, obj, level): return "../"
    def _pformat_pwd(self, obj, level): return "./"

    def _pformat_response(self, obj, level):
        status = self.pformat(obj.status, level)
        value = self.pformat(obj.value, level)
        return f"response {status} {value}"

    def _pformat_slip_function(self, obj, level):
        args = self.pformat(obj.args, level)
        body = self.pformat(obj.body, level)
        return f"fn {args} {body}"
