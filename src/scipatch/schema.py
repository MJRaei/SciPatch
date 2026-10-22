"""Readable labels for the JSON Schema fragments that describe tool parameters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def type_label(schema: dict[str, Any]) -> str:
    """Short label such as ``number [eV/Å]``, ``structure``, ``fcc|bcc``, or ``list of string``."""
    if "x-kind" in schema:
        label = str(schema["x-kind"])
    elif "enum" in schema:
        label = "|".join(str(value) for value in schema["enum"])
    elif "anyOf" in schema:
        options = [type_label(option) for option in schema["anyOf"] if option.get("type") != "null"]
        label = " or ".join(dict.fromkeys(options)) or "any"
    elif schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        label = f"list of {type_label(schema['items'])}"
    else:
        label = str(schema.get("type", "any"))
    if "x-unit" in schema:
        label += f" [{schema['x-unit']}]"
    return label


_JSON_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def matches(value: Any, schema: dict[str, Any]) -> bool:
    """Whether ``value`` fits a parameter's schema (types, enums, unions, list items)."""
    if "enum" in schema:
        return value in schema["enum"]
    if "anyOf" in schema:
        return any(matches(value, option) for option in schema["anyOf"])
    declared = schema.get("type")
    if declared is None:
        return True
    types = declared if isinstance(declared, list) else [declared]
    if not any(_JSON_TYPES.get(name, lambda _: True)(value) for name in types):
        return False
    items = schema.get("items")
    if isinstance(value, list) and isinstance(items, dict):
        return all(matches(item, items) for item in value)
    return True


def normalize(value: Any, schema: dict[str, Any]) -> Any:
    """Turn whole-number floats (``500.0``) into integers where an integer is expected."""
    integer_expected = schema.get("type") == "integer" or any(
        option.get("type") == "integer" for option in schema.get("anyOf", [])
    )
    if integer_expected and isinstance(value, float) and value.is_integer():
        return int(value)
    return value
