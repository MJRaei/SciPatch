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
- Printing is fine: output goes to the run's `stdout.log`, and is shown live for
  long jobs.

**Repositories that are not pip-installable**
- Set `source.install: false`. At runtime the checkout's absolute path is in
  the environment variable `MOTEL_SOURCE_DIR`, so `api.py` can run its
  scripts (`subprocess.run([...], cwd=os.environ["MOTEL_SOURCE_DIR"])`), load
  its data files, or add it to `sys.path`.

**Repositories with a user interface**
- Expose what the interface computes, not the interface. Find the handler
  behind each control (Gradio `fn=`, Streamlit script body, Dash or Flask
  callbacks and routes, Qt slots) and call the computation it reaches. Never
  launch the app, start a server, or drive widgets.
- Import the library module behind the app, not the app module: app modules
  often build the interface or start a server when imported (`demo.launch()`,
  top-level `st.title(...)`).
- Map the controls to parameters, keeping the interface's defaults: text and
  number fields → `str`/`float` (units in the docstring); dropdowns and radio
  buttons → `Literal[...]`; sliders → numbers whose range the docstring states
  and a `ValueError` enforces; file uploads → path strings.
- Map the displays to outputs: plots → PNG files; tables → JSON values, or CSV
  when long; 3D molecule or structure viewers → structure or molecule files
  (declare their `kind`); downloads → files in the current directory.
- Computation written inside a callback (common in Streamlit scripts): move it
  into a function in `source/` and save that as a patch, or into a helper in
  `api.py` if it is a few lines. A golden test then checks it against the
  repository's documented example.
- Desktop programs: use their Python module, command line, or batch mode (OVITO
  through its `ovito` module, not the desktop app; a CLI through `subprocess`).
- A web front end for a hosted service: call the service's API, with its key
  declared under `environment.secrets`.
- Example inputs the interface ships with make good golden-test inputs. The
  expected values still need a named source (paper, README, test suite); a
  number you only got by running the app must say exactly that.

```python
# source/app.py (the interface)
def run(smiles, temperature):
    result = model.predict(load(smiles), T=temperature)
    return plot(result), result.table


gr.Interface(
    run, [gr.Textbox(), gr.Slider(200, 1000, value=300)], [gr.Plot(), gr.Dataframe()]
).launch()


# api.py (the tool): same computation, no gradio
def predict(smiles: str, temperature_k: float = 300.0, plot: str = "result.png") -> dict:
    """Predict the model's property table for a molecule at a temperature.

    Args:
        smiles: Molecule as SMILES.
        temperature_k: Temperature in K, from 200 to 1000.
        plot: Where to save the plot (PNG).

    Returns:
        The table the app displays, one dict per row, and the plot's path.
    """
    if not 200 <= temperature_k <= 1000:
        raise ValueError("temperature_k must be between 200 and 1000 K.")
    from mypackage import load, model, plot_result  # not `app`

    result = model.predict(load(smiles), T=temperature_k)
    plot_result(result).savefig(plot)
    return {"rows": result.table.to_dict("records"), "plot": plot}
```

**Long jobs**
- Mark slow functions `long_running: true` in `motel.yaml`.
- Print progress (e.g. `step 120/5000, T = 598 K`): the latest lines are shown
  to agents and users while the job runs. If the wrapped code logs to a file
  instead, attach a callback that prints a short line every few hundred steps.
- Write intermediate results to files, so a failed job still leaves something
  to inspect.
