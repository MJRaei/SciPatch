"""Lattice thermal conductivity from phonon-phonon scattering with phono3py.

Third-order force constants come either from DFT forces you already have (a
phono3py_disp.yaml or phono3py_params.yaml plus a FORCES_FC3 file) or from a
universal machine-learned potential computed here for a crystal structure.
Thermal conductivities are in W/(m K).
"""

from __future__ import annotations

import functools
import warnings
from pathlib import Path
from typing import Any, Literal

import numpy as np

Model = Literal[
    "TensorNet-MatPES-PBE-2025.2",
    "TensorNet-MatPES-r2SCAN-2025.2",
    "M3GNet-MatPES-PBE-2025.1",
    "CHGNet-MatPES-PBE-1M-2026.9",
]
DEFAULT_MODEL = "TensorNet-MatPES-PBE-2025.2"
#: Minimum supercell edge for third-order force constants, in Angstrom.
MIN_FC3_LENGTH = 9.0

warnings.filterwarnings("ignore")


@functools.cache
def _calculator(model: str) -> Any:
    import matcalc

    return matcalc.load_fp(model)


def _from_dft(yaml_file: str, forces: str | None) -> Any:
    import phono3py

    if forces is None and "params" not in Path(yaml_file).name:
        raise ValueError(
            "A phono3py displacement file needs its forces: pass forces (a FORCES_FC3 file), "
            "or give a phono3py_params.yaml that contains them."
        )
    return phono3py.load(yaml_file, forces_fc3_filename=forces, make_r0_average=True, log_level=0)


def _from_model(
    structure: str,
    model: str,
    supercell: list[int] | None,
    relax: bool,
    displacement: float,
    cutoff_pair_distance: float | None,
) -> tuple[Any, int]:
    from ase.filters import FrechetCellFilter
    from ase.optimize import BFGS
    from phono3py import Phono3py
    from phonopy.structure.atoms import PhonopyAtoms
    from pymatgen.core import Structure
    from pymatgen.io.ase import AseAtomsAdaptor
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    crystal = Structure.from_file(structure)
    if not crystal.is_ordered:
        raise ValueError("The structure has partial occupancies; order it first.")
    calc = _calculator(model)
    if relax:
        atoms = AseAtomsAdaptor.get_atoms(crystal)
        atoms.calc = calc
        BFGS(FrechetCellFilter(atoms), logfile=None).run(fmax=0.001, steps=500)
        crystal = AseAtomsAdaptor.get_structure(atoms)
    # Supercells of the symmetrized conventional cell are compact (cubic for cubic
    # crystals); diagonal supercells of a primitive cell can be badly shaped for fc3.
    crystal = SpacegroupAnalyzer(crystal, symprec=1e-3).get_conventional_standard_structure()
    atoms = AseAtomsAdaptor.get_atoms(crystal)
    if supercell is None:
        supercell = [max(1, int(np.ceil(MIN_FC3_LENGTH / a))) for a in atoms.cell.lengths()]
    unitcell = PhonopyAtoms(
        symbols=atoms.get_chemical_symbols(),
        cell=atoms.cell[:],
        scaled_positions=atoms.get_scaled_positions(),
    )
    ph3 = Phono3py(unitcell, supercell_matrix=np.diag(supercell), primitive_matrix="auto")
    ph3.generate_displacements(distance=displacement, cutoff_pair_distance=cutoff_pair_distance)
    from ase import Atoms

    cells = ph3.supercells_with_displacements
    forces = []
    for index, cell in enumerate(cells):
        if cell is None:  # pairs beyond the cutoff are skipped
            forces.append(np.zeros((len(ph3.supercell), 3)))
            continue
        displaced = Atoms(
            cell.symbols, cell=cell.cell, scaled_positions=cell.scaled_positions, pbc=True
        )
        displaced.calc = calc
        forces.append(displaced.get_forces())
        if index % 50 == 0:
            print(f"forces {index + 1}/{len(cells)}", flush=True)
    ph3.forces = np.array(forces)
    # Enforce translational invariance and symmetry: without it, tiny force noise
    # (single-precision ML models) leaves acoustic modes near Gamma slightly off and
    # makes kappa jump between runs.
    ph3.produce_fc3(symmetrize_fc3r=True)
    ph3.produce_fc2(symmetrize_fc2=True)
    return ph3, len(cells)


def thermal_conductivity(
    structure: str,
    forces: str | None = None,
    model: Model = DEFAULT_MODEL,
    temperatures_k: list[float] | None = None,
    mesh: list[int] | None = None,
    method: Literal["RTA", "LBTE"] = "RTA",
    isotope: bool = False,
    supercell: list[int] | None = None,
    relax: bool = True,
    displacement: float = 0.03,
    cutoff_pair_distance: float | None = None,
    plot: str = "kappa.png",
) -> dict:
    """Lattice thermal conductivity from third-order anharmonic force constants.

    Args:
        structure: A crystal structure file (forces from the ML potential), or a
            phono3py_disp.yaml / phono3py_params.yaml from your own DFT calculations.
        forces: FORCES_FC3 file of DFT forces for a phono3py_disp.yaml.
        model: Universal potential for structure input (ignored with DFT forces).
        temperatures_k: Temperatures in K. Default: 100 to 1000 K in steps of 100.
        mesh: q-point mesh for the phonon Brillouin zone sum, e.g. [19, 19, 19];
            default: chosen from the cell size (density of about 40 points per
            reciprocal Angstrom). Converge it: kappa usually rises with the mesh.
        method: "RTA" (relaxation-time approximation; default, fast) or "LBTE"
            (full linearized Boltzmann equation; more accurate for high-kappa
            materials like diamond, much slower).
        isotope: Include scattering by natural isotope mixtures.
        supercell: Supercell for third-order force constants (structure input),
            e.g. [2, 2, 2]; default: at least 9 Angstrom along each axis.
        relax: Relax the structure with the model first (structure input).
        displacement: Atomic displacement in Angstrom (structure input).
        cutoff_pair_distance: Skip displacement pairs farther apart than this
            (Angstrom), to save time for larger cells.
        plot: PNG of kappa vs temperature.

    Returns:
        For each temperature: kappa tensor components (xx, yy, zz, yz, xz, xy)
        and the average (trace / 3) in W/(m K); the mesh, method, number of
        supercell force calculations, the source of the forces, and the plot path.
    """
    temperatures = temperatures_k or [float(t) for t in range(100, 1001, 100)]
    if any(t <= 0 for t in temperatures):
        raise ValueError("Temperatures must be positive.")
    path = Path(structure)
    if path.suffix.lower() in (".yaml", ".yml"):
        ph3 = _from_dft(structure, forces)
        n_forces = len(ph3.supercells_with_displacements or [])
        source = "DFT forces (phono3py file)"
    else:
        ph3, n_forces = _from_model(
            structure, model, supercell, relax, displacement, cutoff_pair_distance
        )
        source = f"ML potential {model}"
    if mesh is None:
        reciprocal = np.linalg.norm(np.linalg.inv(ph3.primitive.cell), axis=0)
        mesh = [max(3, int(np.ceil(40 * length))) | 1 for length in reciprocal]
    if len(mesh) != 3 or any(int(n) != n or n < 1 for n in mesh):
        raise ValueError("mesh must be three positive integers, e.g. [19, 19, 19].")
    ph3.mesh_numbers = [int(n) for n in mesh]
    print(f"Phonon-phonon interactions on a {mesh} mesh...", flush=True)
    ph3.init_phph_interaction()
    ph3.run_thermal_conductivity(
        temperatures=temperatures, is_isotope=isotope, is_LBTE=(method == "LBTE")
    )
    kappa = np.asarray(ph3.thermal_conductivity.kappa)[0]  # (temperatures, 6)
    rows = [
        {
            "temperature_k": float(t),
            "kappa_w_mk": [float(v) for v in k],
            "kappa_average_w_mk": float(np.mean(k[:3])),
        }
        for t, k in zip(temperatures, kappa, strict=True)
    ]
    _plot(temperatures, [r["kappa_average_w_mk"] for r in rows], plot)
    return {
        "source": source,
        "method": method,
        "isotope_scattering": isotope,
        "mesh": [int(n) for n in mesh],
        "n_force_calculations": int(n_forces),
        "kappa": rows,
        "plot": plot,
    }


def _plot(temperatures: list[float], kappa: list[float], path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(5.5, 3.8))
    axes.plot(temperatures, kappa, marker="o")
    axes.set(xlabel="T (K)", ylabel="lattice thermal conductivity (W/m/K)")
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
