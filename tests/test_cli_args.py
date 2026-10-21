from __future__ import annotations

from typing import Any

import pytest

from motel.cli.running import parse_assignments, parse_value
from motel.errors import MotelError
from motel.models import FunctionInfo


@pytest.mark.parametrize(
    ("raw", "schema", "expected"),
    [
        ("0.05", {"type": "number"}, 0.05),
        ("12", {"type": "integer"}, 12),
        ("true", {"type": "boolean"}, True),
        ('["Cu", "Au"]', {"type": "array"}, ["Cu", "Au"]),
        ('{"a": 1}', {"type": "object"}, {"a": 1}),
        # Strings stay strings, even when they look like JSON.
        ("123", {"type": "string"}, "123"),
        ("true", {"type": "string"}, "true"),
        ("Cu.cif", {"type": "string", "x-kind": "structure"}, "Cu.cif"),
        ("CCO", {"type": "string"}, "CCO"),
        # Optional values.
        ("null", {"anyOf": [{"type": "number"}, {"type": "null"}]}, None),
        ("3.5", {"anyOf": [{"type": "number"}, {"type": "null"}]}, 3.5),
        ("label", {"anyOf": [{"type": "string"}, {"type": "null"}]}, "label"),
        # A string-or-number parameter keeps numbers as numbers.
        ("7", {"anyOf": [{"type": "string"}, {"type": "number"}]}, 7),
        # Enums of strings.
        ("1", {"enum": ["1", "2"]}, "1"),
        # Unknown schema: best effort JSON, else string.
        ("[1, 2]", {}, [1, 2]),
        ("hello world", {}, "hello world"),
    ],
)
def test_parse_value(raw: str, schema: dict[str, Any], expected: Any) -> None:
    assert parse_value(raw, schema) == expected


def test_parse_assignments_uses_the_function_schema() -> None:
    function = FunctionInfo(
        name="relax",
        parameters={
            "type": "object",
            "properties": {"structure": {"type": "string"}, "fmax": {"type": "number"}},
        },
    )
    assert parse_assignments(["structure=1.cif", "fmax=0.01", "note=a=b"], function) == {
        "structure": "1.cif",
        "fmax": 0.01,
        "note": "a=b",
    }
    with pytest.raises(MotelError, match="key=value"):
        parse_assignments(["fmax"], function)
