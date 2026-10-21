"""Readable labels for the JSON Schema fragments that describe tool parameters."""

from __future__ import annotations

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
