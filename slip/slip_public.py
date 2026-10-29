"""Public command schemas and direct calls over module exports."""

import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .slip_core import (
    Code, Collection, Generic, IString, Lambda, Path, PathLiteral, Sig,
    Template, invoke,
)
from .slip_syntax import parse


def json_type(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, Sig) and value.logic:
        parts = [json_type(item) for item in value.types]
        if any(part is None for part in parts):
            return None
        return {"anyOf" if value.logic == "or" else "allOf": parts}
    if not isinstance(value, PathLiteral) or len(value.path.keys) != 1:
        return None
    name = value.path.keys[0]
    if name == "id":
        return {"type": "string", "pattern": "^id:.+"}
    types = {"int": "integer", "float": "number", "number": "number",
             "string": "string", "i-string": "string", "boolean": "boolean",
             "none": "null", "list": "array", "dict": "object"}
    return {"type": types[name]} if name in types else None


def literal(value):
    if isinstance(value, Template):
        if any(isinstance(part, Code) for part in value.parts):
            raise ValueError("Public source calls require literals")
        return "".join(value.parts)
    if isinstance(value, Collection) and value.kind in ("list", "dict"):
        if value.kind == "list":
            if any(len(expression) != 1 for expression in value.code):
                raise ValueError("Public source calls require literals")
            return [literal(expression[0]) for expression in value.code]
        output = {}
        for expression in value.code:
            if (len(expression) != 2 or not isinstance(expression[0], Path)
                    or expression[0].mode != "set"
                    or len(expression[0].keys) != 1
                    or not isinstance(expression[0].keys[0], str)):
                raise ValueError(
                    "Public source calls require literal mappings",
                )
            output[expression[0].keys[0]] = literal(expression[1])
        return output
    if value is None or type(value) in (str, IString, int, float, bool):
        return value
    raise ValueError("Public source calls require literals")


class PublicModule:
    def __init__(self, runner, exports):
        self.runner, self.exports = runner, exports
        self.public_exports = {
            name: exports[name] for name in exports.parent
            if isinstance(exports[name], (Lambda, Generic))
            and exports[name].meta.get("public") is True
        }

    def public_names(self):
        return sorted(self.public_exports)

    def _forms(self, function, host_parameters):
        methods = function.methods if isinstance(function, Generic) \
            else [function]
        forms = []
        for method in methods:
            properties = {}
            for parameter in method.sig.parameters:
                if parameter.name in host_parameters:
                    continue
                description = json_type(parameter.annotation) \
                    if parameter.is_typed else {"type": "string"}
                if description is None:
                    break
                properties[parameter.name] = description
            else:
                description = {
                    "type": "object", "required": list(properties),
                    "properties": properties, "additionalProperties": False,
                }
                if method.sig.rest and method.sig.rest not in host_parameters:
                    properties[method.sig.rest] = {"type": "array"}
                if description not in forms:
                    forms.append(description)
        return forms

    def json_schema(self, *, host_parameters=()):
        branches = []
        for name in self.public_names():
            forms = self._forms(self.public_exports[name], host_parameters)
            if not forms:
                raise ValueError(f"no JSON-compatible signatures: {name}")
            branches.append({
                "type": "object", "required": ["function", "arguments"],
                "properties": {
                    "function": {"const": name},
                    "arguments": forms[0] if len(forms) == 1
                    else {"anyOf": forms},
                },
                "additionalProperties": False,
            })
        return {"anyOf": branches} if branches else {"not": {}}

    def commands_schema(self, *, host_parameters=()):
        return {"type": "array", "items": self.json_schema(
            host_parameters=host_parameters,
        )}

    def validate_json_command(self, command, *, host_parameters=()):
        validator = Draft202012Validator(self.json_schema(
            host_parameters=host_parameters,
        ))
        validator.validate(command)

    def run_json_command(self, command, *, host_arguments=None):
        host_arguments = {} if host_arguments is None else host_arguments

        def execute(frame):
            payload = command
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError as error:
                    raise ValueError(
                        f"invalid command JSON: {error}",
                    ) from error
            try:
                self.validate_json_command(
                    payload, host_parameters=host_arguments,
                )
            except (ValueError, ValidationError) as error:
                raise ValueError(f"invalid public command: {error}") from error
            function = self.public_exports[payload["function"]]
            supplied = {**payload["arguments"], **host_arguments}
            methods = function.methods if isinstance(function, Generic) \
                else [function]
            for method in methods:
                names = [p.name for p in method.sig.parameters]
                accepted = set(names)
                if method.sig.rest:
                    accepted.add(method.sig.rest)
                if (all(name in supplied for name in names)
                        and set(payload["arguments"]) <= accepted):
                    args = [supplied[name] for name in names]
                    if method.sig.rest:
                        args.extend(supplied.get(method.sig.rest, []))
                    return invoke(function, args, frame)
            raise TypeError("No matching method")

        return self.runner._run(execute)

    def run_json_commands(self, commands, *, host_arguments=None):
        if isinstance(commands, str):
            commands = json.loads(commands)
        return [self.run_json_command(command, host_arguments=host_arguments)
                for command in commands]

    def json_command_from_source(self, source, *, host_parameters=()):
        code = parse(source)
        if len(code) != 1 or not code[0]:
            raise ValueError("Expected one expression")
        head, *arguments = code[0]
        if (not isinstance(head, Path) or head.mode != "get"
                or len(head.keys) != 1
                or head.keys[0] not in self.public_exports):
            raise ValueError("unknown public command")
        values = [literal(value) for value in arguments]
        function = self.public_exports[head.keys[0]]
        methods = function.methods if isinstance(function, Generic) \
            else [function]
        for method in methods:
            parameters = [p for p in method.sig.parameters
                          if p.name not in host_parameters]
            if len(values) < len(parameters) or (
                not method.sig.rest and len(parameters) != len(values)
            ):
                continue
            command = {"function": head.keys[0], "arguments": {
                p.name: value for p, value in zip(parameters, values)
            }}
            if method.sig.rest and method.sig.rest not in host_parameters:
                command["arguments"][method.sig.rest] = values[
                    len(parameters):
                ]
            try:
                self.validate_json_command(
                    command, host_parameters=host_parameters,
                )
            except ValidationError:
                continue
            return command
        raise ValueError("No matching public call with literal arguments")
