# Writing `api.py`

`api.py` is the only file that touches the upstream code. Motel imports it
inside the tool's own environment, reads each public function's signature and
docstring, and turns them into a JSON Schema that agents and the CLI use.

## A complete example

```python
"""CHGNet: relax structures and predict energies with a universal ML potential."""

from __future__ import annotations

import functools
from typing import Literal


@functools.lru_cache(maxsize=1)
def _model():
    from chgnet.model import CHGNet  # heavy import, done once

    return CHGNet.load()


def relax(
    structure: str,
    fmax: float = 0.05,
    steps: int = 500,
    relax_cell: bool = True,
    output: str = "relaxed.cif",
) -> dict:
    """Relax a crystal structure with the CHGNet universal potential.

    Args:
        structure: Path to the input structure (CIF, POSCAR, or extended XYZ).
        fmax: Force convergence threshold in eV/Å.
        steps: Maximum number of optimizer steps.
        relax_cell: Also relax the lattice, not only atomic positions.
        output: Where to write the relaxed structure (CIF).

    Returns:
        Final energy per atom (eV/atom), number of steps, convergence flag, and
        the path of the relaxed structure.
    """
    from chgnet.model import StructOptimizer
    from pymatgen.core import Structure

    initial = Structure.from_file(structure)
    result = StructOptimizer(model=_model()).relax(
        initial, fmax=fmax, steps=steps, relax_cell=relax_cell, verbose=False
    )
    final = result["final_structure"]
    final.to(filename=output)
    energies = result["trajectory"].energies
    return {
        "energy_ev_per_atom": float(energies[-1]) / len(final),
        "steps": len(energies),
        "converged": len(energies) < steps,
        "relaxed_structure": output,
    }
```

## Rules

**Signatures**
- Type-hint everything. Supported: `str`, `int`, `float`, `bool`, `list[...]`,
  `dict[str, ...]`, `Optional[...]`/`X | None`, `Literal[...]`, `Enum`,
  `pathlib.Path`, dataclasses, `TypedDict`.
- Use `Literal["pbe", "r2scan"]` for choices: agents see the allowed values.
- Give safe, sensible defaults; only truly essential inputs should be required.
- `Annotated[str, {"kind": "structure"}]` is an alternative to declaring kinds in
  `motel.yaml`.

**Docstrings** (Google style, or NumPy style)
- First line: what the function does, in plain words. Agents read it to choose.
- `Args:`: one line per parameter, **with units** and accepted formats.
- `Returns:`: what the keys mean, with units.

**Inputs and outputs**
- Files come in as path strings. Read them with the library's own readers
  (`Structure.from_file`, `ase.io.read`, `Chem.MolFromSmiles`).
- Return plain JSON values. Motel also converts NumPy values, dataclasses,
  paths, and objects with `as_dict()`/`todict()`, but explicit is clearer.
- Put units in key names: `band_gap_ev`, `lattice_a_angstrom`, `time_ps`.
- Write structures, trajectories, and large arrays to files in the **current
  directory** (each run has its own) and return their relative paths; Motel
  makes them absolute.

**Behaviour**
- Deterministic where possible: fix random seeds, or expose `seed: int = 0`.
  Default to the CPU when GPU results differ slightly (expose `device` as an
  option), so golden tests and cached results stay reproducible.
- No interactive input, GUI windows, or `plt.show()`; save figures as PNG.
- Raise `ValueError` with a helpful message for invalid input. The message
  reaches the agent.
- Load models once (`functools.lru_cache`); heavy imports may live inside
  functions so introspection stays fast.
- Printing is fine: output goes to the run's `stdout.log`.

**Repositories that are not pip-installable**
- Set `source.install: false`. At runtime the checkout's absolute path is in
  the environment variable `MOTEL_SOURCE_DIR`, so `api.py` can run its
  scripts (`subprocess.run([...], cwd=os.environ["MOTEL_SOURCE_DIR"])`), load
  its data files, or add it to `sys.path`.

**Long jobs**
- Mark slow functions `long_running: true` in `motel.yaml`.
- Write progress to stdout and intermediate results to files so a failed job
  still leaves something to inspect.
