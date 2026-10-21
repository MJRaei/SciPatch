"""Motel runtime shim: describes and calls tool functions inside a tool's environment.

This file is executed by the *tool's* interpreter, never imported by Motel's own
process at runtime. It therefore uses only the standard library and stays
compatible with Python 3.8+, so it works in any environment a tool needs.

Usage::

    python -I shim.py describe REQUEST.json
    python -I shim.py call REQUEST.json

``REQUEST.json`` is a JSON object (see ``motel.runtime.executor``). The response
is written atomically to ``request["response_path"]`` rather than to stdout, so
anything the tool prints cannot corrupt the protocol.

Annotations are never evaluated at runtime (``from __future__ import annotations``),
so modern typing syntax here stays compatible with Python 3.8.
"""

from __future__ import annotations

import asyncio
import collections.abc
import contextlib
import dataclasses
import enum
import importlib
import inspect
import json
import math
import os
import platform
import re
import sys
import time
import traceback
import types
import typing
from pathlib import PurePath
from typing import Any, Awaitable, Callable

if typing.TYPE_CHECKING:
    Schema = dict[str, Any]
    Function = Callable[..., Any]

PROTOCOL_VERSION = 1

_NONE_TYPE = type(None)
_UNION_TYPES: tuple[Any, ...] = (typing.Union,)
if sys.version_info >= (3, 10):
    _UNION_TYPES = (typing.Union, types.UnionType)

# Keys from ``Annotated[..., {...}]`` metadata copied into the schema unchanged.
_SCHEMA_KEYS = frozenset(
    {
        "description", "title", "default", "examples", "enum", "format", "pattern",
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength",
        "maxLength", "minItems", "maxItems",
    }
)  # fmt: skip
_TRACEBACK_LIMIT = 60
_MAX_DEPTH = 12


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("describe", "call"):
        sys.stderr.write("usage: shim.py {describe|call} REQUEST.json\n")
        return 2
    command, request_path = argv[1], argv[2]
    with open(request_path, encoding="utf-8") as handle:
        request = json.load(handle)
    wsl_root = os.environ.get("MOTEL_WSL_ROOT")
    if wsl_root:
        request = wsl_enter(request, command, wsl_root)
    # Output goes to log files; flush every line so progress is visible while running.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(line_buffering=True)

    started = time.time()
    payload: dict[str, Any]
    try:
        module = load_module(request["package_dir"], request["entrypoint"])
        functions = public_functions(module, request.get("functions"))
        if command == "describe":
            payload = {"ok": True, "functions": [describe_function(f) for f in functions]}
        else:
            payload = call_function(functions, request["function"], request.get("args") or {})
    except KeyboardInterrupt:
        payload = {"ok": False, "error": {"type": "Cancelled", "message": "Run was interrupted."}}
    except BaseException as exc:
        payload = {"ok": False, "error": format_error(exc)}

    if wsl_root and "value" in payload:
        distro = os.environ.get("WSL_DISTRO_NAME", "")
        payload["value"] = map_strings(
            payload["value"], lambda s: windows_path(s, wsl_root, distro)
        )
    payload["duration"] = round(time.time() - started, 6)
    payload["protocol"] = PROTOCOL_VERSION
    payload["python"] = platform.python_version()
    write_json_atomic(request["response_path"], payload)
    return 0 if payload["ok"] else 1


# --------------------------------------------------------------------------- #
# Running inside WSL for a Windows host
# --------------------------------------------------------------------------- #

_DRIVE_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$", re.DOTALL)
_WSL_UNC = re.compile(r"^[\\/]{2}wsl(?:\$|\.localhost)[\\/][^\\/]+(.*)$", re.IGNORECASE | re.DOTALL)
PROCESS_FILE = "linux-process.json"


def wsl_enter(request: dict[str, Any], command: str, root: str) -> dict[str, Any]:
    """Prepare a request from a Windows host: Linux paths, and a recorded process group."""
    prepend = os.environ.get("MOTEL_PREPEND_PATH")
    if prepend:
        os.environ["PATH"] = prepend + os.pathsep + os.environ.get("PATH", "")
    request = dict(request)
    for key in ("package_dir", "response_path"):
        request[key] = linux_path(request[key], root)
    request["args"] = map_strings(request.get("args") or {}, lambda s: linux_path(s, root))
    if command == "call":
        with contextlib.suppress(OSError):
            os.setsid()  # its own process group, so cancelling stops its children too
        info = {"distro": os.environ.get("WSL_DISTRO_NAME", ""), "pgid": os.getpgid(0)}
        folder = os.path.dirname(request["response_path"])
        write_json_atomic(os.path.join(folder, PROCESS_FILE), info)
    return request


def linux_path(value: str, root: str) -> str:
    """``C:\\data\\x.cif`` -> ``/mnt/c/data/x.cif``; anything else unchanged."""
    unc = _WSL_UNC.match(value)
    if unc:
        return "/" + unc.group(1).replace("\\", "/").lstrip("/")
    drive = _DRIVE_PATH.match(value)
    if drive:
        return root + drive.group(1).lower() + "/" + drive.group(2).replace("\\", "/")
    return value


def windows_path(value: str, root: str, distro: str) -> str:
    """``/mnt/c/x/y.png`` -> ``C:\\x\\y.png``; other existing Linux paths as UNC paths."""
    drive = value[len(root) : len(root) + 2]
    if value.startswith(root) and len(drive) == 2 and drive[0].isalpha() and drive[1] == "/":
        rest = value[len(root) + 2 :].replace("/", "\\")
        return drive[0].upper() + ":\\" + rest
    if value.startswith("/") and distro and os.path.exists(value):
        return "\\\\wsl.localhost\\" + distro + value.replace("/", "\\")
    return value


def map_strings(value: Any, convert: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return convert(value)
    if isinstance(value, list):
        return [map_strings(item, convert) for item in value]
    if isinstance(value, dict):
        return {key: map_strings(item, convert) for key, item in value.items()}
    return value


def load_module(package_dir: str, entrypoint: str) -> types.ModuleType:
    """Import the tool's entry-point module from its package folder."""
    if package_dir not in sys.path:
        sys.path.insert(0, package_dir)
    return importlib.import_module(entrypoint)


def public_functions(module: types.ModuleType, names: list[str] | None = None) -> list[Function]:
    """Functions the tool exposes: ``names`` if given, else every public function."""
    if names:
        found: list[Function] = []
        for name in names:
            obj = getattr(module, name, None)
            if obj is None or not callable(obj):
                raise LookupError(
                    "Function '%s' is listed in motel.yaml but %s does not define it."
                    % (name, module.__name__)
                )
            found.append(obj)
        return found

    exported = getattr(module, "__all__", None)
    candidates: list[Function] = []
    for name, obj in vars(module).items():
        if name.startswith("_") or not inspect.isfunction(obj):
            continue
        if exported is not None:
            if name in exported:
                candidates.append(obj)
        elif obj.__module__ == module.__name__:
            candidates.append(obj)
    candidates.sort(key=lambda fn: getattr(fn.__code__, "co_firstlineno", 0))
    return candidates


# --------------------------------------------------------------------------- #
# Describe
# --------------------------------------------------------------------------- #


def describe_function(fn: Function) -> dict[str, Any]:
    """Describe ``fn`` as JSON: summary, docs, and a JSON Schema for its parameters."""
    doc = parse_docstring(inspect.getdoc(fn) or "")
    hints = _type_hints(fn)
    signature = inspect.signature(fn)
    warnings: list[str] = []
    if not doc["summary"]:
        warnings.append("has no docstring")

    properties: dict[str, Schema] = {}
    required: list[str] = []
    for name, param in signature.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        annotation = hints.get(name, param.annotation)
        schema: Schema
        if annotation is inspect.Parameter.empty:
            warnings.append("parameter '%s' has no type hint" % name)
            schema = {}
        else:
            schema = type_to_schema(annotation)
        if name in doc["params"] and "description" not in schema:
            schema["description"] = doc["params"][name]
        elif "description" not in schema:
            warnings.append("parameter '%s' is not described in the docstring" % name)
        if param.default is inspect.Parameter.empty:
            required.append(name)
        elif isinstance(param.default, PurePath):
            schema["default"] = str(param.default)  # keep relative: resolved at call time
        else:
            schema["default"] = to_jsonable(param.default)
        properties[name] = schema

    parameters: Schema = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    if not any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values()):
        parameters["additionalProperties"] = False

    returns_hint = hints.get("return", signature.return_annotation)
    returns: dict[str, Any] = {"description": doc["returns"]}
    if returns_hint is not inspect.Signature.empty:
        returns["schema"] = type_to_schema(returns_hint)

    return {
        "name": fn.__name__,
        "summary": doc["summary"],
        "description": doc["description"],
        "parameters": parameters,
        "returns": returns,
        "is_async": inspect.iscoroutinefunction(fn),
        "warnings": warnings,
    }


def _type_hints(fn: Any) -> dict[str, Any]:
    try:
        return typing.get_type_hints(fn, include_extras=True)
    except TypeError:  # Python 3.8: no include_extras
        try:
            return typing.get_type_hints(fn)
        except Exception:
            return {}
    except Exception:
        return {}


def type_to_schema(tp: Any, depth: int = 0) -> Schema:
    """Map a Python type annotation to a JSON Schema fragment (best effort)."""
    if depth > _MAX_DEPTH:
        return {}
    if tp is None or tp is _NONE_TYPE:
        return {"type": "null"}
    if tp is typing.Any or tp is object or tp is inspect.Parameter.empty:
        return {}
    if isinstance(tp, str):
        return {"x-python-type": tp}

    origin = typing.get_origin(tp) if hasattr(typing, "get_origin") else None
    args = typing.get_args(tp) if hasattr(typing, "get_args") else ()

    schema: Schema
    annotated = getattr(typing, "Annotated", None)
    if annotated is not None and origin is annotated:
        schema = type_to_schema(args[0], depth + 1)
        for extra in args[1:]:
            _merge_metadata(schema, extra)
        return schema
    if origin in _UNION_TYPES:
        options = [type_to_schema(arg, depth + 1) for arg in args]
        return {"anyOf": options}
    if origin is typing.Literal:
        values = [to_jsonable(arg) for arg in args]
        schema = {"enum": values}
        kinds = {_json_type(v) for v in values}
        if len(kinds) == 1:
            schema["type"] = kinds.pop()
        return schema
    if origin in (list, set, frozenset, collections.abc.Sequence, collections.abc.Iterable,
                  collections.abc.Set, collections.abc.MutableSequence):  # fmt: skip
        schema = {"type": "array"}
        if args:
            schema["items"] = type_to_schema(args[0], depth + 1)
        return schema
    if origin is tuple:
        schema = {"type": "array"}
        if len(args) == 2 and args[1] is Ellipsis:
            schema["items"] = type_to_schema(args[0], depth + 1)
        elif args:
            schema["prefixItems"] = [type_to_schema(arg, depth + 1) for arg in args]
            schema["minItems"] = schema["maxItems"] = len(args)
        return schema
    if origin in (dict, collections.abc.Mapping, collections.abc.MutableMapping):
        schema = {"type": "object"}
        if len(args) == 2:
            schema["additionalProperties"] = type_to_schema(args[1], depth + 1)
        return schema

    if isinstance(tp, type):
        if issubclass(tp, bool):
            return {"type": "boolean"}
        if issubclass(tp, enum.Enum):
            return {"enum": [to_jsonable(member.value) for member in tp]}
        if issubclass(tp, int):
            return {"type": "integer"}
        if issubclass(tp, float):
            return {"type": "number"}
        if issubclass(tp, str):
            return {"type": "string"}
        if issubclass(tp, (bytes, bytearray)):
            return {"type": "string", "contentEncoding": "base64"}
        if issubclass(tp, PurePath) or tp is os.PathLike:
            return {"type": "string", "format": "path"}
        if issubclass(tp, (list, tuple, set, frozenset)):
            return {"type": "array"}
        if issubclass(tp, dict):
            if _is_typeddict(tp):
                return _object_schema(
                    _type_hints(tp), depth, getattr(tp, "__required_keys__", None)
                )
            return {"type": "object"}
        if dataclasses.is_dataclass(tp):
            hints = _type_hints(tp)
            fields = {f.name: hints.get(f.name, f.type) for f in dataclasses.fields(tp)}
            return _object_schema(fields, depth, None)
    return {"x-python-type": getattr(tp, "__name__", None) or repr(tp)}


def _object_schema(fields: dict[str, Any], depth: int, required: Any) -> Schema:
    schema: Schema = {
        "type": "object",
        "properties": {name: type_to_schema(tp, depth + 1) for name, tp in fields.items()},
    }
    if required:
        schema["required"] = sorted(required)
    return schema


def _is_typeddict(tp: Any) -> bool:
    return isinstance(tp, type) and issubclass(tp, dict) and hasattr(tp, "__total__")


def _merge_metadata(schema: Schema, extra: Any) -> None:
    """Apply ``Annotated`` metadata: a string is a description, a dict adds schema keys."""
    if isinstance(extra, str):
        schema["description"] = extra
    elif isinstance(extra, dict):
        for raw_key, value in extra.items():
            key = str(raw_key)
            target = key if key in _SCHEMA_KEYS or key.startswith("x-") else "x-" + key
            schema[target] = to_jsonable(value)
    else:
        # pydantic.Field(...) and similar objects carry a ``description`` attribute.
        description = getattr(extra, "description", None)
        if isinstance(description, str):
            schema["description"] = description


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "null" if value is None else "object"


# --------------------------------------------------------------------------- #
# Docstrings (Google and NumPy styles)
# --------------------------------------------------------------------------- #

_SECTION_NAMES = {
    "args": "params", "arguments": "params", "parameters": "params", "params": "params",
    "keyword args": "params", "keyword arguments": "params", "other parameters": "params",
    "returns": "returns", "return": "returns", "yields": "returns",
}  # fmt: skip
_ANY_SECTION = re.compile(
    r"^(args|arguments|parameters|params|keyword args|keyword arguments|other parameters|"
    r"returns?|yields|raises|examples?|notes?|references|see also|warnings?|todo|attributes)"
    r"\s*:?\s*$",
    re.IGNORECASE,
)
_ENTRY = re.compile(r"^\*{0,2}(\w+)\s*(?:\(([^)]*)\))?\s*:\s*(.*)$")


def parse_docstring(doc: str) -> dict[str, Any]:
    """Split a docstring into summary, description, parameter docs, and return docs."""
    lines = doc.expandtabs().splitlines()
    result: dict[str, Any] = {"summary": "", "description": "", "params": {}, "returns": ""}
    if not lines:
        return result

    # Summary: the first paragraph.
    index = 0
    summary: list[str] = []
    while index < len(lines) and lines[index].strip():
        if _is_section_header(lines, index):
            break
        summary.append(lines[index].strip())
        index += 1
    result["summary"] = " ".join(summary)

    description: list[str] = []
    section: str | None = None
    numpy_style = False
    body: list[str] = []

    def flush() -> None:
        if section == "params":
            result["params"].update(_parse_entries(body, numpy_style))
        elif section == "returns":
            result["returns"] = _join_paragraph(body, numpy_style)

    while index < len(lines):
        line = lines[index]
        if _is_section_header(lines, index):
            flush()
            header = line.strip().rstrip(":").lower()
            section = _SECTION_NAMES.get(header, "other")
            numpy_style = _is_underline(lines, index + 1)
            body = []
            index += 2 if numpy_style else 1
            continue
        if section is None:
            description.append(line)
        else:
            body.append(line)
        index += 1
    flush()
    result["description"] = "\n".join(description).strip()
    return result


def _is_underline(lines: list[str], index: int) -> bool:
    return index < len(lines) and bool(re.match(r"^\s*-{3,}\s*$", lines[index]))


def _is_section_header(lines: list[str], index: int) -> bool:
    line = lines[index]
    if not _ANY_SECTION.match(line.strip()):
        return False
    return line.strip().endswith(":") or _is_underline(lines, index + 1)


def _parse_entries(body: list[str], numpy_style: bool) -> dict[str, str]:
    entries: dict[str, list[str]] = {}
    base_indent: int | None = None
    current: str | None = None
    for line in body:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if base_indent is None:
            base_indent = indent
        match = _ENTRY.match(line.strip())
        if indent <= base_indent and match:
            current = match.group(1)
            # NumPy puts the type after the colon; Google puts the description there.
            entries[current] = [] if numpy_style else [match.group(3).strip()]
        elif current is not None:
            entries[current].append(line.strip())
    return {name: " ".join(part for part in parts if part) for name, parts in entries.items()}


def _join_paragraph(body: list[str], numpy_style: bool) -> str:
    text = [line.strip() for line in body if line.strip()]
    if numpy_style and text and _ENTRY.match(text[0]) is None and len(text) > 1:
        text = text[1:]  # NumPy: first line is the return type
    if not numpy_style and text:
        match = _RETURN_TYPE_PREFIX.match(text[0])
        if match:  # Google: "dict[str, float]: The results." -> "The results."
            text[0] = match.group(1)
    return " ".join(text)


# A type expression such as ``dict``, ``list[float]`` or ``str | None``, then a colon.
_RETURN_TYPE_PREFIX = re.compile(
    r"^[\w.]+(?:\[[^\]]*\])?(?:\s*\|\s*[\w.]+(?:\[[^\]]*\])?)*:\s+(.*)$"
)


# --------------------------------------------------------------------------- #
# Call
# --------------------------------------------------------------------------- #


class InvalidArgumentsError(TypeError):
    """The arguments do not match the function's signature."""

    motel_type = "InvalidArguments"


def call_function(functions: list[Function], name: str, args: Any) -> dict[str, Any]:
    by_name = {fn.__name__: fn for fn in functions}
    fn = by_name.get(name)
    if fn is None:
        raise LookupError(
            "Unknown function '%s'. Available: %s" % (name, ", ".join(sorted(by_name)) or "none")
        )
    if not isinstance(args, dict):
        raise TypeError("Arguments must be a JSON object of name/value pairs.")

    signature = inspect.signature(fn)
    _check_arguments(signature, args)
    hints = _type_hints(fn)
    kwargs = {key: _coerce(value, hints.get(key)) for key, value in args.items()}

    value = fn(**kwargs)
    if inspect.isawaitable(value):
        value = asyncio.run(_await(value))
    return {"ok": True, "value": to_jsonable(value)}


async def _await(awaitable: Awaitable[Any]) -> Any:
    return await awaitable


def _check_arguments(signature: inspect.Signature, args: dict[str, Any]) -> None:
    params = signature.parameters
    accepts_any = any(p.kind == p.VAR_KEYWORD for p in params.values())
    named = {name for name, p in params.items() if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)}
    unknown = sorted(set(args) - named) if not accepts_any else []
    missing = sorted(
        name
        for name, p in params.items()
        if name in named and p.default is p.empty and name not in args
    )
    problems: list[str] = []
    if unknown:
        problems.append("unknown argument(s): %s" % ", ".join(unknown))
    if missing:
        problems.append("missing required argument(s): %s" % ", ".join(missing))
    if problems:
        raise InvalidArgumentsError(
            "; ".join(problems) + ". Expected: %s" % ", ".join(sorted(named))
        )


def _coerce(value: Any, hint: Any) -> Any:
    """Convert JSON values into the annotated type where that is unambiguous."""
    if hint is None or value is None:
        return value
    annotated = getattr(typing, "Annotated", None)
    origin = typing.get_origin(hint) if hasattr(typing, "get_origin") else None
    if annotated is not None and origin is annotated:
        return _coerce(value, typing.get_args(hint)[0])
    if origin in _UNION_TYPES:
        non_null = [arg for arg in typing.get_args(hint) if arg is not _NONE_TYPE]
        return _coerce(value, non_null[0]) if len(non_null) == 1 else value
    if isinstance(hint, type):
        if issubclass(hint, PurePath) and isinstance(value, str):
            return hint(value)
        if issubclass(hint, enum.Enum) and not isinstance(value, hint):
            return hint(value)
        if hint is float and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        if hint is tuple and isinstance(value, list):
            return tuple(value)
    return value


def to_jsonable(obj: Any, depth: int = 0) -> Any:
    """Convert results (numpy, pymatgen, dataclasses, paths, ...) into JSON values."""
    if depth > _MAX_DEPTH:
        return repr(obj)
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        if math.isnan(obj):
            return "NaN"
        if math.isinf(obj):
            return "Infinity" if obj > 0 else "-Infinity"
        return float(obj)
    if isinstance(obj, enum.Enum):
        return to_jsonable(obj.value, depth + 1)
    if isinstance(obj, PurePath):
        return os.path.abspath(str(obj))
    if isinstance(obj, dict):
        return {str(key): to_jsonable(value, depth + 1) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(item, depth + 1) for item in obj]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return to_jsonable(dataclasses.asdict(obj), depth + 1)
    if isinstance(obj, (bytes, bytearray)):
        return "<%d bytes>" % len(obj)
    # numpy arrays/scalars, torch tensors (after .tolist()), pymatgen/ASE objects, pandas.
    for method in ("tolist", "item", "as_dict", "todict", "to_dict"):
        converter = getattr(obj, method, None)
        if callable(converter):
            try:
                return to_jsonable(converter(), depth + 1)
            except Exception:
                continue
    return repr(obj)


def format_error(exc: BaseException) -> dict[str, str]:
    # Hide the shim's own frames: users care about their tool's code.
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename != __file__]
    lines = ["Traceback (most recent call last):\n"] if frames else []
    lines += traceback.format_list(frames) + traceback.format_exception_only(type(exc), exc)
    text = "".join(lines).splitlines()
    return {
        "type": getattr(exc, "motel_type", None) or type(exc).__name__,
        "message": str(exc) or type(exc).__name__,
        "traceback": "\n".join(text[-_TRACEBACK_LIMIT:]),
    }


def write_json_atomic(path: str, payload: dict[str, Any]) -> None:
    temporary = "%s.%d.tmp" % (path, os.getpid())
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, default=repr)
    os.replace(temporary, path)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
