"""The runtime shim, tested in-process (it is a stdlib-only module)."""

from __future__ import annotations

import dataclasses
import enum
import json
import math
import sys
import types
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

import pytest

from scipatch.runtime import shim


class Functional(enum.Enum):
    PBE = "pbe"
    R2SCAN = "r2scan"


@dataclasses.dataclass
class Result:
    energy: float
    converged: bool


def documented(
    structure: Annotated[str, {"kind": "structure"}],
    fmax: float = 0.05,
    steps: int = 100,
    cell: bool = False,
    method: Literal["bfgs", "fire"] = "bfgs",
    functional: Functional = Functional.PBE,
    elements: list[str] | None = None,
    weights: dict[str, float] | None = None,
    output: Path = Path("out.cif"),
    label: Optional[str] = None,  # noqa: UP045 - checks typing.Optional support
) -> Result:
    """Relax a structure.

    Longer explanation of the method.

    Args:
        structure: Path to the structure.
        fmax: Force threshold in eV/Å,
            continued on a second line.
        steps: Maximum steps.
        cell: Relax the cell.
        method: Optimizer.
        functional: Exchange-correlation functional.
        elements: Elements to keep.
        weights: Per-element weights.
        output: Output file.
        label: Optional label.

    Returns:
        dict: Energy and convergence flag.
    """
    return Result(energy=-1.0, converged=True)


def test_describe_builds_a_json_schema() -> None:
    info = shim.describe_function(documented)
    params = info["parameters"]
    props = params["properties"]

    assert info["summary"] == "Relax a structure."
    assert info["description"] == "Longer explanation of the method."
    assert params["required"] == ["structure"]
    assert params["additionalProperties"] is False
    assert props["structure"] == {
        "type": "string",
        "x-kind": "structure",
        "description": "Path to the structure.",
    }
    assert props["fmax"] == {
        "type": "number",
        "description": "Force threshold in eV/Å, continued on a second line.",
        "default": 0.05,
    }
    assert props["steps"]["type"] == "integer"
    assert props["cell"]["type"] == "boolean"
    assert props["method"]["enum"] == ["bfgs", "fire"]
    assert props["method"]["type"] == "string"
    assert props["functional"]["enum"] == ["pbe", "r2scan"]
    assert props["functional"]["default"] == "pbe"
    assert props["elements"]["anyOf"] == [
        {"type": "array", "items": {"type": "string"}},
        {"type": "null"},
    ]
    assert props["weights"]["anyOf"][0] == {
        "type": "object",
        "additionalProperties": {"type": "number"},
    }
    assert props["output"]["format"] == "path"
    assert props["output"]["default"] == "out.cif"
    assert props["label"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert info["returns"]["description"] == "Energy and convergence flag."
    assert info["returns"]["schema"]["properties"] == {
        "energy": {"type": "number"},
        "converged": {"type": "boolean"},
    }
    assert info["warnings"] == []


def test_describe_warns_about_missing_docs_and_hints() -> None:
    def bare(x, y: int = 1):  # type: ignore[no-untyped-def]
        return x

    info = shim.describe_function(bare)
    assert "has no docstring" in info["warnings"]
    assert "parameter 'x' has no type hint" in info["warnings"]
    assert "parameter 'y' is not described in the docstring" in info["warnings"]


def test_numpy_style_docstrings_are_parsed() -> None:
    doc = """Compute a spectrum.

    Parameters
    ----------
    smiles : str
        Molecule as SMILES.
    width : float
        Line width in nm.

    Returns
    -------
    dict
        Wavelengths and intensities.
    """
    parsed = shim.parse_docstring(__import__("inspect").cleandoc(doc))
    assert parsed["summary"] == "Compute a spectrum."
    assert parsed["params"] == {"smiles": "Molecule as SMILES.", "width": "Line width in nm."}
    assert parsed["returns"] == "Wavelengths and intensities."


def test_google_return_description_without_type_is_kept() -> None:
    parsed = shim.parse_docstring("Do it.\n\nReturns:\n    A dict with keys: energy, forces.")
    assert parsed["returns"] == "A dict with keys: energy, forces."


def _module(source: str, name: str = "tool_api") -> types.ModuleType:
    module = types.ModuleType(name)
    exec(compile(source, f"<{name}>", "exec"), module.__dict__)  # noqa: S102 - test fixture
    return module


def test_public_functions_skip_private_and_imported() -> None:
    module = _module(
        "from os.path import join\n"
        "def second():\n    pass\n"
        "def _helper():\n    pass\n"
        "def first():\n    pass\n"
    )
    # Functions are ordered as defined in the source file.
    assert [f.__name__ for f in shim.public_functions(module)] == ["second", "first"]


def test_public_functions_respect_dunder_all_and_explicit_names() -> None:
    module = _module("__all__ = ['b']\ndef a():\n    pass\ndef b():\n    pass\n")
    assert [f.__name__ for f in shim.public_functions(module)] == ["b"]
    assert [f.__name__ for f in shim.public_functions(module, ["a"])] == ["a"]
    with pytest.raises(LookupError, match=r"'missing' is listed in scipatch\.yaml"):
        shim.public_functions(module, ["missing"])


def test_call_coerces_paths_enums_and_numbers() -> None:
    seen: dict[str, Any] = {}

    def target(path: Path, functional: Functional, scale: float) -> str:
        seen.update(path=path, functional=functional, scale=scale)
        return "ok"

    result = shim.call_function(
        [target], "target", {"path": "a.cif", "functional": "r2scan", "scale": 2}
    )
    assert result == {"ok": True, "value": "ok"}
    assert seen == {"path": Path("a.cif"), "functional": Functional.R2SCAN, "scale": 2.0}
    assert isinstance(seen["scale"], float)


def test_call_reports_argument_problems() -> None:
    def target(a: int, b: int = 0) -> int:
        return a + b

    with pytest.raises(TypeError) as caught:
        shim.call_function([target], "target", {"c": 1})
    assert getattr(caught.value, "scipatch_type", None) == "InvalidArguments"
    assert "unknown argument(s): c" in str(caught.value)
    assert "missing required argument(s): a" in str(caught.value)
    with pytest.raises(LookupError, match="Unknown function 'nope'"):
        shim.call_function([target], "nope", {})


def test_call_runs_async_functions() -> None:
    async def target(x: int) -> int:
        return x * 2

    assert shim.call_function([target], "target", {"x": 21})["value"] == 42


class FakeArray:
    def tolist(self) -> list[float]:
        return [1.0, 2.0]


class FakeStructure:
    def as_dict(self) -> dict[str, Any]:
        return {"lattice": FakeArray()}


def test_to_jsonable_handles_scientific_objects() -> None:
    value = shim.to_jsonable(
        {
            "array": FakeArray(),
            "structure": FakeStructure(),
            "nan": math.nan,
            "inf": -math.inf,
            "path": Path("x.cif"),
            "enum": Functional.PBE,
            "dataclass": Result(1.5, True),
            "set": {3},
            "bytes": b"abc",
            1: "int key",
        }
    )
    assert value["array"] == [1.0, 2.0]
    assert value["structure"] == {"lattice": [1.0, 2.0]}
    assert value["nan"] == "NaN"
    assert value["inf"] == "-Infinity"
    assert Path(value["path"]).is_absolute()
    assert value["enum"] == "pbe"
    assert value["dataclass"] == {"energy": 1.5, "converged": True}
    assert value["set"] == [3]
    assert value["bytes"] == "<3 bytes>"
    assert value["1"] == "int key"
    json.dumps(value)  # everything is serializable


def test_errors_hide_shim_frames() -> None:
    def target() -> None:
        raise RuntimeError("inside the tool")

    try:
        shim.call_function([target], "target", {})
    except RuntimeError as exc:
        error = shim.format_error(exc)
    assert error["type"] == "RuntimeError"
    assert error["message"] == "inside the tool"
    assert shim.__file__ not in error["traceback"]
    assert "in target" in error["traceback"]


def test_main_writes_response_file(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "my_api.py").write_text(
        "def double(x: int) -> int:\n    '''Double x.'''\n    return 2 * x\n"
    )
    response = tmp_path / "response.json"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "package_dir": str(package),
                "entrypoint": "my_api",
                "function": "double",
                "args": {"x": 4},
                "response_path": str(response),
            }
        )
    )
    try:
        assert shim.main(["shim.py", "call", str(request)]) == 0
    finally:
        sys.modules.pop("my_api", None)
        sys.path.remove(str(package))
    payload = json.loads(response.read_text())
    assert payload["ok"] is True
    assert payload["value"] == 8
    assert payload["protocol"] == shim.PROTOCOL_VERSION
