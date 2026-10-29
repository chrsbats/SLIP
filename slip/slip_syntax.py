"""Translate the Koine language grammar into editable symbolic values."""

import re
import textwrap
from collections.abc import Mapping
from decimal import Decimal
from functools import lru_cache
from dataclasses import fields, is_dataclass

from koine import Parser
from safer_yaml import load

from .grammar import GRAMMAR_PATH
from .slip_core import (
    Code, Collection, Group, IString, Locator, MultiPath, Navigation,
    Parameter, Path, PathLiteral, Query, Sig, Slice, Template,
)


@lru_cache(maxsize=1)
def parser():
    return Parser(load(GRAMMAR_PATH), base_path=GRAMMAR_PATH.parent)


def parse(source):
    result = parser().parse(source)
    if result["status"] != "success":
        error = SyntaxError(
            "ParseError: " + result.get("message", str(result)),
        )
        match = re.search(r"L(\d+):C(\d+)", str(error))
        if match:
            error.error_token = {"line": int(match[1]),
                                 "col": int(match[2]), "text": ""}
        raise error
    code = transform(result["ast"])

    attach_source(code, source)
    return code


def attach_source(value, source, path=None):
    if isinstance(value, Code):
        value.source_text = source
        value.source_path = path
    if isinstance(value, list):
        for item in value:
            attach_source(item, source, path)
    elif is_dataclass(value):
        for description in fields(value):
            attach_source(getattr(value, description.name), source, path)


def to_path(value):
    if isinstance(value, PathLiteral):
        return value
    if isinstance(value, Path):
        return PathLiteral(value)
    code = parse(str(value))
    if len(code) != 1 or len(code[0]) != 1 or not isinstance(code[0][0], Path):
        raise ValueError("Expected one path")
    return PathLiteral(code[0][0])


def code_from(node):
    value = transform(node)
    return value if isinstance(value, Code) else Code([value])


def unescape(text):
    escapes = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", "'": "'", '"': '"'}
    return re.sub(r"\\([nrt\\'\"])", lambda m: escapes[m[1]], text)


def string_content(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in text:
        text = textwrap.dedent(text).removeprefix("\n").removesuffix("\n")
    return unescape(text)


def interpolated(text):
    parts = re.split(r"\{\{(.*?)\}\}", string_content(text), flags=re.S)
    return Template([
        parse(part) if index % 2 else part for index, part in enumerate(parts)
    ])


def quote(text, delimiter="'"):
    text = text.replace("\\", "\\\\").replace(delimiter, "\\" + delimiter)
    for character, escape in (("\n", r"\n"), ("\r", r"\r"), ("\t", r"\t")):
        text = text.replace(character, escape)
    return delimiter + text + delimiter


def format_expression(expression):
    return " ".join(format_source(term) for term in expression)


def inline_code(code):
    return "; ".join(format_expression(expression) for expression in code)


def format_block(opening, items, closing, separator=","):
    if len(items) <= 1 and not any("\n" in item for item in items):
        return opening + "".join(items) + closing
    body = textwrap.indent((separator + "\n").join(items), "    ")
    return opening + "\n" + body + "\n" + closing


def format_path(path):
    parts = []
    for index, key in enumerate(path.keys):
        if isinstance(key, Navigation):
            if key is Navigation.PARENT:
                if parts and not parts[-1].endswith(("/", "::")):
                    parts.append("/")
                parts.append("../")
            else:
                parts.append(key.value)
            continue
        if isinstance(key, str):
            if parts and not parts[-1].endswith(("/", "::")):
                parts.append(".")
            if (len(path.keys) == 1 and path.mode == "set"
                    and not isinstance(key, Locator)
                    and re.fullmatch(r"[A-Za-z_-][A-Za-z0-9_-]*\??", key)
                    is None):
                parts.append(quote(key))
            else:
                parts.append(key)
        elif isinstance(key, Query):
            code = key.code
            # Filter shorthand has an implicit current-item operand.
            if (len(code) == 1 and code[0]
                    and code[0][0] == Path(["."])):
                parts.append("[" + format_expression(code[0][1:]) + "]")
            else:
                parts.append("[" + inline_code(code) + "]")
        elif isinstance(key, Slice):
            start = inline_code(key.start) if key.start is not None else ""
            end = inline_code(key.end) if key.end is not None else ""
            parts.append(f"[{start}:{end}]")
        elif isinstance(key, Group):
            parts.append("(" + inline_code(key) + ")")
        else:
            parts.append("[" + format_source(key) + "]")
    if path.options is not None:
        parts.append("#(" + inline_code(path.options) + ")")
    prefix = {"get": "", "set": "", "pipe": "|", "del": "~", "post": ""}
    suffix = {"get": "", "set": ":", "pipe": "", "del": "", "post": "<-"}
    return prefix[path.mode] + "".join(parts) + suffix[path.mode]


def format_logic(value):
    return (" " + value.logic + " ").join(
        "(" + format_logic(item) + ")" if isinstance(item, Sig) and item.logic
        else format_source(item) for item in value.types
    )


def format_source(value):
    """Render symbolic values and data without inspecting executable lists."""
    match value:
        case MultiPath():
            return "[" + ", ".join(
                format_path(path).removesuffix(":") for path in value.paths
            ) + "]:"
        case Group():
            return "(" + inline_code(value) + ")"
        case Code():
            return format_block(
                "[", [format_expression(e) for e in value], "]", ";",
            )
        case Collection():
            opening, closing = ("#{", "}") if value.kind == "dict" else (
                "#[" if value.kind == "list" else value.kind + "#[", "]",
            )
            return format_block(
                opening, [format_expression(e) for e in value.code], closing,
            )
        case PathLiteral():
            return "`" + format_path(value.path) + "`"
        case Path():
            return format_path(value)
        case Sig():
            if value.logic:
                return "{" + format_logic(value) + "}"
            parts = [
                p.name + (": " + (
                    format_logic(p.annotation)
                    if isinstance(p.annotation, Sig) and p.annotation.logic
                    else format_source(p.annotation)
                ) if p.is_typed else "")
                for p in value.parameters
            ]
            if value.rest is not None:
                parts.append(value.rest + "...")
            content = ", ".join(parts)
            if value.where is not None:
                content += " |where " + inline_code(value.where)
            if value.return_annotation is not None:
                content += " -> " + format_source(value.return_annotation)
            return "{" + content + "}"
        case Template():
            parts = ["{{" + quote(inline_code(part), '"')[1:-1] + "}}"
                     if isinstance(part, Code) else quote(part, '"')[1:-1]
                     for part in value.parts]
            return '"' + "".join(parts) + '"'
        case IString():
            return quote(value, '"')
        case str():
            return quote(value)
        case bytes() | bytearray():
            return format_block("u8#[", [str(v) for v in value], "]")
        case None:
            return "none"
        case bool():
            return "true" if value else "false"
        case int():
            return str(value)
        case float():
            decimal = Decimal(str(value))
            if not decimal.is_finite():
                raise ValueError(
                    "Non-finite numbers have no SLIP source literal",
                )
            text = format(decimal, "f")
            return text if "." in text else text + ".0"
        case Mapping():
            return format_block("#{", [
                (quote(key) if isinstance(key, str)
                 else "(" + format_source(key) + ")")
                + ": " + format_source(item) for key, item in value.items()
            ], "}")
        case list() | tuple():
            return format_block("#[", [format_source(v) for v in value], "]")
        case _:
            name = type(value).__name__
            raise TypeError(f"No SLIP source literal for {name}")


def transform(node):
    tag = node["tag"]
    children = node.get("children", [])
    if tag.startswith("SlipPath_"):
        return transform(children[0])
    match tag:
        case "number" | "boolean" | "null":
            return node["value"]
        case "string":
            return string_content(node["text"])
        case "i-string":
            return interpolated(node["text"])
        case "name" | "operator":
            text = node["text"]
            return Locator(text) if "://" in text else text
        case "expr":
            if "children" not in node:
                return parse(node["text"])[0]
            return [
                transform(child) for child in children
                if child["tag"] != "comment"
            ]
        case "code" | "group":
            kind = Group if tag == "group" else Code
            statements = [
                child for child in children
                if child["tag"] == "expr" and child.get("children")
            ]
            code = kind()
            for statement in statements:
                expression = transform(statement)
                if expression:
                    code.append(expression)
                    first = statement["children"][0]
                    code.locations.append({"line": statement.get("line", 1),
                                           "col": statement.get("col", 1),
                                           "text": first.get("text", "")})
            return code
        case "list" | "dict":
            expressions = Code([transform(child) for child in children])
            return Collection(tag, expressions)
        case "typed-list":
            items = children["items"]
            if isinstance(items, dict):
                items = [items]
            return Collection(children["t"]["text"], Code([
                transform(child) for child in items
            ]))
        case "get-path" | "set-path" | "piped-path" | "del-path" | "post-path":
            modes = {
                "get-path": "get", "set-path": "set",
                "piped-path": "pipe", "del-path": "del", "post-path": "post",
            }
            keys = [transform(child) for child in children
                    if child["tag"] != "meta"]
            options = next((code_from(child) for child in children
                            if child["tag"] == "meta"), None)
            return Path(keys, modes[tag], options)
        case "meta":
            return Code([transform(child) for child in children])
        case "root":
            return "/"
        case "parent":
            return Navigation.PARENT
        case "pwd":
            return Navigation.CURRENT
        case "identity":
            return Navigation.IDENTITY
        case "multi-set-path":
            return MultiPath([transform(child) for child in children])
        case "path-literal":
            return PathLiteral(transform(children[0]))
        case "quoted-set-path":
            value = interpolated(node["text"][1:-2])
            if any(isinstance(part, Code) for part in value.parts):
                return Path([Navigation.CURRENT, Group([[value]])], "set")
            return Path(["".join(value.parts)], "set")
        case "quoted-raw-set-path":
            return Path([unescape(node["text"][1:-2])], "set")
        case "query-segment":
            return transform(children[0])
        case "simple-query":
            code = Code([transform(child) for child in children])
            predicate = any(
                len(expression) > 1 or any(
                    isinstance(term, Path) and isinstance(term.keys[0], str)
                    and term.keys[0].startswith('.')
                    for term in expression
                )
                for expression in code
            )
            return Query(code, predicate)
        case "filter-query":
            operation = Path([transform(children[0])])
            rhs = code_from(children[1])
            return Query(Code([[Path(["."]), operation, *rhs[0]]]), True)
        case "rhs-expr" | "start-expr" | "end-expr":
            return Code([transform(child) for child in children])
        case "slice-query":
            ends = {child["tag"]: code_from(child) for child in children}
            return Slice(ends.get("start-expr"), ends.get("end-expr"))
        case "sig-union" | "sig-and":
            return Sig(logic="or" if tag == "sig-union" else "and",
                       types=[transform(child) for child in children])
        case "sig":
            parameters, rest, where, returned = [], None, None, None
            for child in children:
                match child["tag"]:
                    case "sig-arg":
                        name = child["children"][0]["text"]
                        parameters.append(Parameter(name))
                    case "sig-kwarg":
                        fields = child["children"]
                        annotation = transform(fields["value"])
                        if isinstance(annotation, list):
                            if len(annotation) != 1:
                                raise SyntaxError("Expected one annotation")
                            annotation = annotation[0]
                        parameters.append(Parameter(
                            fields["sig-key"]["text"], annotation, True,
                        ))
                    case "sig-rest-arg":
                        rest = child["text"]
                    case "sig-where":
                        where = code_from(child["children"]["expression"])
                        if any(isinstance(term, Path) and term.mode == "pipe"
                               and term.keys == ["where"]
                               for expression in where for term in expression):
                            raise SyntaxError(
                                "Only one |where clause is allowed in a sig",
                            )
                    case "sig-return":
                        values = transform(child["children"][0])
                        returned = values[0] if len(values) == 1 \
                            else Code([values])
                    case "sig-union" | "sig-and":
                        return transform(child)
                    case _:
                        raise NotImplementedError(child["tag"])
            return Sig(parameters, rest, where, returned)
        case _:
            raise NotImplementedError(tag)
