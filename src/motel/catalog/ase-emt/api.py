"""ASE + EMT: fast, approximate energies and relaxations for simple metals.

Effective-medium theory (EMT) is a semi-empirical interatomic potential for the
fcc metals Al, Cu, Ag, Au, Ni, Pd and Pt. It runs in milliseconds, which makes
it ideal for teaching, for quick sanity checks, and for testing workflows before
spending time on DFT or machine-learned potentials.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

SUPPORTED_ELEMENTS = ("Al", "Cu", "Ag", "Au", "Ni", "Pd", "Pt")
EV_PER_ANGSTROM3_TO_GPA = 160.21766208

Crystal = Literal["fcc", "bcc", "sc", "hcp"]


def _check_elements(symbols: list[str]) -> None:
    unsupported = sorted(set(symbols) - set(SUPPORTED_ELEMENTS))
    if unsupported:
        raise ValueError(
            f"EMT has no reliable parameters for {', '.join(unsupported)}. "
            f"Supported elements: {', '.join(SUPPORTED_ELEMENTS)}."
        )


def _bulk(element: str, crystal: str, lattice_constant: float | None):
    from ase.build import bulk

    _check_elements([element])
    if lattice_constant is not None and lattice_constant <= 0:
        raise ValueError("lattice_constant must be positive (Å).")
    if lattice_constant is None:
        return bulk(element, crystal)
    return bulk(element, crystal, a=lattice_constant)


def _read(structure: str):
    from ase.io import read

    atoms = read(structure)
    _check_elements(atoms.get_chemical_symbols())
    return atoms


def build_bulk(
    element: str,
    crystal: Crystal = "fcc",
    lattice_constant: float | None = None,
    repeat: int = 1,
    output: str = "bulk.cif",
) -> dict:
    """Build a bulk crystal of one element and save it as a structure file.

    Args:
        element: Chemical symbol, e.g. "Cu".
        crystal: Crystal structure.
        lattice_constant: Lattice constant a in Å. Default: ASE's reference
            (experimental) value for the element.
        repeat: Repeat the primitive cell this many times along each axis.
        output: Structure file to write; the format follows the extension
            (.cif, .xyz/.extxyz, or POSCAR).

    Returns:
        Path of the written structure, its number of atoms, and its volume in Å³.
    """
    from ase.io import write

    if repeat < 1:
        raise ValueError("repeat must be at least 1.")
    atoms = _bulk(element, crystal, lattice_constant).repeat((repeat, repeat, repeat))
    write(output, atoms)
    return {
        "structure": output,
        "n_atoms": len(atoms),
        "volume_angstrom3": float(atoms.get_volume()),
    }


def energy(structure: str) -> dict:
    """Compute the EMT energy and forces of a structure, without relaxing it.

    Args:
        structure: Path to a structure file (CIF, extended XYZ, POSCAR, ...).

    Returns:
        Total energy (eV), energy per atom (eV/atom), the largest force on any
        atom (eV/Å), and the number of atoms.
    """
    from ase.calculators.emt import EMT

    atoms = _read(structure)
    atoms.calc = EMT()
    total = float(atoms.get_potential_energy())
    forces = atoms.get_forces()
    return {
        "energy_ev": total,
        "energy_ev_per_atom": total / len(atoms),
        "max_force_ev_per_angstrom": float(np.linalg.norm(forces, axis=1).max()),
        "n_atoms": len(atoms),
    }


def relax(
    structure: str,
    fmax: float = 0.05,
    steps: int = 300,
    relax_cell: bool = False,
    output: str = "relaxed.cif",
) -> dict:
    """Relax atomic positions (and optionally the cell) with EMT and the BFGS optimizer.

    Args:
        structure: Path to the starting structure file.
        fmax: Convergence threshold on the largest atomic force, in eV/Å.
        steps: Maximum number of optimizer steps.
        relax_cell: Also relax the cell shape and volume (zero pressure).
        output: File to write the relaxed structure to.

    Returns:
        Initial and final energies (eV), energy per atom (eV/atom), the final
        largest force (eV/Å), the number of steps, whether it converged, and the
        path of the relaxed structure.
    """
    from ase.calculators.emt import EMT
    from ase.filters import FrechetCellFilter
    from ase.io import write
    from ase.optimize import BFGS

    if fmax <= 0:
        raise ValueError("fmax must be positive (eV/Å).")
    atoms = _read(structure)
    atoms.calc = EMT()
    initial = float(atoms.get_potential_energy())
    target = FrechetCellFilter(atoms) if relax_cell else atoms
    optimizer = BFGS(target, logfile="-")  # progress goes to the run's stdout.log
    converged = bool(optimizer.run(fmax=fmax, steps=steps))
    final = float(atoms.get_potential_energy())
    write(output, atoms)
    return {
        "initial_energy_ev": initial,
        "final_energy_ev": final,
        "energy_ev_per_atom": final / len(atoms),
        "max_force_ev_per_angstrom": float(np.linalg.norm(atoms.get_forces(), axis=1).max()),
        "steps": int(optimizer.nsteps),
        "converged": converged,
        "relaxed_structure": output,
    }


def equation_of_state(
    element: str,
    crystal: Crystal = "fcc",
    points: int = 9,
    strain: float = 0.05,
) -> dict:
    """Find the equilibrium lattice constant and bulk modulus from an equation-of-state fit.

    The cell is scaled uniformly over ±strain in lattice constant, the energy is
    computed at each point, and a Birch-Murnaghan equation of state is fitted.

    Args:
        element: Chemical symbol, e.g. "Cu".
        crystal: Crystal structure.
        points: Number of volumes to sample (at least 5).
        strain: Largest relative change of the lattice constant (e.g. 0.05 = ±5%).

    Returns:
        Equilibrium lattice constant (Å), volume per atom (Å³), bulk modulus
        (GPa), and minimum energy per atom (eV/atom).
    """
    from ase.calculators.emt import EMT
    from ase.eos import EquationOfState

    if points < 5:
        raise ValueError("Use at least 5 points for a meaningful fit.")
    if not 0 < strain < 0.3:
        raise ValueError("strain must be between 0 and 0.3.")
    reference = _bulk(element, crystal, None)
    reference_a = float(reference.cell.cellpar()[0])
    if crystal == "fcc":
        reference_a *= np.sqrt(2)  # primitive fcc cell vector length is a/√2
    elif crystal == "bcc":
        reference_a *= 2 / np.sqrt(3)  # primitive bcc cell vector length is a·√3/2
    volumes, energies = [], []
    for scale in np.linspace(1 - strain, 1 + strain, points):
        atoms = reference.copy()
        atoms.set_cell(reference.cell * scale, scale_atoms=True)
        atoms.calc = EMT()
        volumes.append(atoms.get_volume())
        energies.append(atoms.get_potential_energy())
    volume, minimum, modulus = EquationOfState(volumes, energies, eos="birchmurnaghan").fit()
    n_atoms = len(reference)
    lattice_constant = reference_a * (volume / reference.get_volume()) ** (1 / 3)
    return {
        "lattice_constant_angstrom": float(lattice_constant),
        "volume_per_atom_angstrom3": float(volume / n_atoms),
        "bulk_modulus_gpa": float(modulus * EV_PER_ANGSTROM3_TO_GPA),
        "energy_ev_per_atom": float(minimum / n_atoms),
    }
