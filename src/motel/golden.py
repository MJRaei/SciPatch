"""Golden tests: declarative checks that a tool reproduces known results.

A golden test calls one function with fixed arguments and checks values in the
result. Ideally the expected value is a number from the paper, so a passing test
means "this installation reproduces the published work". In ``motel.yaml``::

    golden:
      - name: Cu lattice energy
        function: energy
        args: {structure: tests/data/Cu.cif}
        expect:
          energy_ev: {approx: -0.0057, abs: 0.001}
          n_atoms: 4
        reference: ASE documentation, EMT tutorial

Each key of ``expect`` is a dotted path into the result (``forces.0.2``; use
``.`` for the whole result). Each value is either a literal (numbers are
compared with a tiny tolerance) or a matcher:

=============  ==============================================================
``approx``     number within tolerance; ``rel`` (default 0.01) and/or ``abs``
``equals``     exactly equal
``min``/``max``  inclusive bounds
``contains``   substring of a string, or item of a list
``length``     ``len(value)`` equals this
``exists``     ``true``: the value is a path to an existing file
``type``       JSON type: number, integer, string, boolean, array, object, null
=============  ==============================================================
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

MATCHER_KEYS = frozenset(
    {"approx", "rel", "abs", "equals", "min", "max", "contains", "length", "exists", "type"}
)
DEFAULT_RELATIVE_TOLERANCE = 0.01

_MISSING = object()


def lookup(value: Any, path: str) -> Any:
    """Follow a dotted path (``a.b.0``) into nested dicts and lists."""
    if path in ("", "."):
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif (
            isinstance(current, list)
            and part.lstrip("-").isdigit()
            and -len(current) <= int(part) < len(current)
        ):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def check(expect: dict[str, Any], value: Any) -> list[str]:
    """Return human-readable failures; an empty list means the result matches."""
    failures = []
    for path, spec in expect.items():
        actual = lookup(value, path)
        if actual is _MISSING:
            failures.append(f"{path}: missing from the result")
            continue
        problem = _check_one(spec, actual)
        if problem:
            failures.append(f"{path}: {problem}")
    return failures


def _is_matcher(spec: Any) -> bool:
    return isinstance(spec, dict) and bool(spec) and set(spec) <= MATCHER_KEYS


def _check_one(spec: Any, actual: Any) -> str | None:
    if not _is_matcher(spec):
        if _is_number(spec) and _is_number(actual):
            ok = math.isclose(actual, spec, rel_tol=1e-9, abs_tol=1e-12)
        else:
            ok = actual == spec
        return None if ok else f"expected {spec!r}, got {actual!r}"

    if "approx" in spec:
        if not _is_number(actual):
            return f"expected a number near {spec['approx']}, got {actual!r}"
        absolute = float(spec.get("abs", 0.0))
        relative = float(spec.get("rel", 0.0 if "abs" in spec else DEFAULT_RELATIVE_TOLERANCE))
        if not math.isclose(actual, spec["approx"], rel_tol=relative, abs_tol=absolute):
            return f"expected {spec['approx']} (rel {relative:g}, abs {absolute:g}), got {actual!r}"
    if "equals" in spec and actual != spec["equals"]:
        return f"expected exactly {spec['equals']!r}, got {actual!r}"
    if "min" in spec and not (_is_number(actual) and actual >= spec["min"]):
        return f"expected at least {spec['min']}, got {actual!r}"
    if "max" in spec and not (_is_number(actual) and actual <= spec["max"]):
        return f"expected at most {spec['max']}, got {actual!r}"
    if "contains" in spec:
        try:
            found = spec["contains"] in actual
        except TypeError:
            found = False
        if not found:
            return f"expected to contain {spec['contains']!r}, got {actual!r}"
    if "length" in spec:
        try:
            length = len(actual)
        except TypeError:
            return f"expected something with length {spec['length']}, got {actual!r}"
        if length != spec["length"]:
            return f"expected length {spec['length']}, got {length}"
    if spec.get("exists") and not (isinstance(actual, str) and Path(actual).exists()):
        return f"expected a path to an existing file, got {actual!r}"
    if "type" in spec and _json_type(actual) not in _accepted_types(spec["type"]):
        return f"expected type {spec['type']}, got {_json_type(actual)}"
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _accepted_types(name: str) -> set[str]:
    # An integer is also a number, as in JSON Schema.
    return {"number", "integer"} if name == "number" else {name}


def resolve_paths(args: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Make relative paths in golden-test arguments (and in lists of them) absolute.

    Paths are relative to the package; values that are not existing files are kept.
    """
    return {key: _resolve(value, base_dir) for key, value in args.items()}


def _resolve(value: Any, base_dir: Path) -> Any:
    if isinstance(value, list):
        return [_resolve(item, base_dir) for item in value]
    if isinstance(value, str) and not Path(value).is_absolute() and (base_dir / value).exists():
        return str((base_dir / value).resolve())
    return value
