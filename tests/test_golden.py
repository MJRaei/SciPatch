from __future__ import annotations

from pathlib import Path

import pytest

from motel import golden

RESULT = {
    "energy_ev": -3.7412,
    "converged": True,
    "formula": "C9H8O4",
    "forces": [[0.0, 0.1, -0.2], [0.0, 0.0, 0.3]],
    "steps": 12,
    "tags": ["relaxed", "fcc"],
}


@pytest.mark.parametrize(
    ("expect", "failures"),
    [
        ({"energy_ev": {"approx": -3.74, "abs": 0.01}}, 0),
        ({"energy_ev": {"approx": -3.74, "abs": 0.0001}}, 1),
        ({"energy_ev": {"approx": -3.71}}, 0),  # default 1% relative tolerance
        ({"energy_ev": {"approx": -3.60}}, 1),
        ({"converged": True, "formula": "C9H8O4"}, 0),
        ({"formula": "C9H8O3"}, 1),
        ({"steps": {"min": 1, "max": 50}}, 0),
        ({"steps": {"max": 10}}, 1),
        ({"forces.1.2": {"approx": 0.3, "abs": 1e-9}}, 0),
        ({"forces.-1.2": 0.3}, 0),
        ({"forces": {"length": 2}}, 0),
        ({"tags": {"contains": "fcc"}}, 0),
        ({"formula": {"contains": "O4"}}, 0),
        ({"steps": {"type": "number"}}, 0),  # integers are numbers
        ({"steps": {"type": "string"}}, 1),
        ({".": {"type": "object"}}, 0),
        ({"missing.key": 1}, 1),
        ({"forces.5.0": 1}, 1),
    ],
)
def test_matchers(expect: dict[str, object], failures: int) -> None:
    assert len(golden.check(expect, RESULT)) == failures


def test_failure_messages_are_readable() -> None:
    [message] = golden.check({"energy_ev": {"approx": -3.0, "abs": 0.1}}, RESULT)
    assert message == "energy_ev: expected -3.0 (rel 0, abs 0.1), got -3.7412"
    [message] = golden.check({"nothing": 1}, RESULT)
    assert message == "nothing: missing from the result"


def test_exists_checks_files(tmp_path: Path) -> None:
    present = tmp_path / "out.cif"
    present.write_text("data")
    assert golden.check({"path": {"exists": True}}, {"path": str(present)}) == []
    assert golden.check({"path": {"exists": True}}, {"path": str(tmp_path / "no")}) != []


def test_resolve_paths_only_touches_existing_relative_files(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "Cu.cif").write_text("x")
    args = {"structure": "data/Cu.cif", "element": "Cu", "n": 3, "files": ["data/Cu.cif", "CO"]}
    resolved = golden.resolve_paths(args, tmp_path)
    cif = str((tmp_path / "data" / "Cu.cif").resolve())
    assert resolved == {"structure": cif, "element": "Cu", "n": 3, "files": [cif, "CO"]}


def test_resolve_paths_finds_source_files_wherever_the_checkout_is(tmp_path: Path) -> None:
    package, checkout = tmp_path / "package", tmp_path / "elsewhere"
    package.mkdir()
    (checkout / "data").mkdir(parents=True)
    (checkout / "data" / "MgF2.cif").write_text("x")
    resolved = golden.resolve_paths({"structure": "source/data/MgF2.cif"}, package, checkout)
    assert resolved == {"structure": str((checkout / "data" / "MgF2.cif").resolve())}
    assert golden.resolve_paths({"structure": "source/data/MgF2.cif"}, package) == {
        "structure": "source/data/MgF2.cif"
    }
