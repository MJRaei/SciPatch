"""Phonons and vibrational thermodynamics with phonopy, using CHGNet or EMT forces."""

from __future__ import annotations

import functools
import math
import warnings
from typing import Literal

import numpy as np

Calculator = Literal["chgnet", "emt"]
THZ_TO_CM1 = 33.35641
#: Frequencies above this (THz) count as numerical noise rather than instability.
IMAGINARY_TOLERANCE_THZ = -0.05
#: Default supercells make every lattice vector at least this long (Å).
MIN_SUPERCELL_LENGTH = 10.0


@functools.lru_cache(maxsize=2)
def _calculator(name: str, device: str):
    if name == "emt":
        from ase.calculators.emt import EMT

        return EMT()
    from chgnet.model import CHGNet
    from chgnet.model.dynamics import CHGNetCalculator

    warnings.filterwarnings("ignore")
    return CHGNetCalculator(model=CHGNet.load(verbose=False), use_device=device)


def _phonopy_atoms(atoms):
    from phonopy.structure.atoms import PhonopyAtoms

    return PhonopyAtoms(
        symbols=atoms.get_chemical_symbols(),
        cell=atoms.cell.array,
        scaled_positions=atoms.get_scaled_positions(),
    )


def _ase_atoms(cell):
    from ase import Atoms

    return Atoms(
        symbols=cell.symbols, cell=cell.cell, scaled_positions=cell.scaled_positions, pbc=True
    )


def _save_current_figure(path: str) -> None:
    import matplotlib.pyplot as plt

    plt.gcf().savefig(path, dpi=150, bbox_inches="tight")
    plt.close("all")


def phonons(
    structure: str,
    calculator: Calculator = "chgnet",
    supercell: list[int] | None = None,
    displacement_angstrom: float = 0.01,
    mesh: list[int] | None = None,
    temperatures_k: list[float] | None = None,
    device: Literal["cpu", "auto", "cuda", "mps"] = "cpu",
    band_plot: str = "phonon_bands.png",
    dos_plot: str = "phonon_dos.png",
    parameters: str = "phonopy_params.yaml",
) -> dict:
    """Compute phonons with finite displacements, and check dynamical stability.

    Forces come from the chosen interatomic potential. Use a structure relaxed with
    the same potential: phonons of an unrelaxed structure are not meaningful.

    Args:
        structure: Path to a relaxed crystal structure (CIF, POSCAR, extended XYZ).
        calculator: "chgnet" (universal ML potential, any inorganic crystal) or
            "emt" (fast, only Al, Cu, Ag, Au, Ni, Pd, Pt).
        supercell: Repetitions of the input cell along a, b, c. Default: the smallest
            that makes every direction at least 10 Å long.
        displacement_angstrom: Atomic displacement for finite differences in Å.
        mesh: q-point mesh for the density of states and thermal properties.
            Default [20, 20, 20].
        temperatures_k: Temperatures in K for thermal properties. Default [300].
        device: Device for CHGNet: "cpu" (reproducible), "auto", "cuda", or "mps".
        band_plot: PNG file for the band structure along a standard path.
        dos_plot: PNG file for the phonon density of states.
        parameters: phonopy file with the structure and force constants, for reuse.

    Returns:
        The supercell and number of displacements, Γ-point frequencies (THz and
        cm⁻¹), the lowest and highest frequencies (THz), whether the crystal is
        dynamically stable (no imaginary modes on the mesh or band path), the
        zero-point energy (kJ/mol), thermal properties per temperature (free energy
        in kJ/mol, entropy and heat capacity in J/K/mol, per mole of primitive cells
        and per atom), and the plot and parameter file paths.
    """
    import matplotlib

    matplotlib.use("Agg")
    from ase.io import read
    from phonopy import Phonopy

    atoms = read(structure)
    if not (atoms.pbc.all() and atoms.cell.rank == 3):
        raise ValueError("Phonons need a periodic crystal structure.")
    if displacement_angstrom <= 0:
        raise ValueError("displacement_angstrom must be positive.")
    if supercell is None:
        supercell = [
            max(1, math.ceil(MIN_SUPERCELL_LENGTH / length)) for length in atoms.cell.lengths()
        ]
    if len(supercell) != 3 or any(int(n) != n or n < 1 for n in supercell):
        raise ValueError("supercell must be three positive integers, e.g. [2, 2, 2].")

    phonon = Phonopy(
        _phonopy_atoms(atoms), supercell_matrix=np.diag(supercell), primitive_matrix="auto"
    )
    phonon.generate_displacements(distance=displacement_angstrom)
    displaced = phonon.supercells_with_displacements
    force_field = _calculator(calculator, device)
    forces = []
    for index, cell in enumerate(displaced, start=1):
        print(f"forces for displacement {index}/{len(displaced)}")
        supercell_atoms = _ase_atoms(cell)
        supercell_atoms.calc = force_field
        forces.append(supercell_atoms.get_forces())
    phonon.forces = np.array(forces)
    phonon.produce_force_constants()
    phonon.symmetrize_force_constants()

    gamma = np.sort(phonon.get_frequencies([0, 0, 0]))
    phonon.run_mesh(mesh or [20, 20, 20])
    mesh_frequencies = phonon.get_mesh_dict()["frequencies"]
    phonon.auto_band_structure(npoints=51)
    band_frequencies = np.concatenate(phonon.get_band_structure_dict()["frequencies"])
    phonon.plot_band_structure()
    _save_current_figure(band_plot)
    phonon.run_total_dos()
    phonon.plot_total_dos()
    _save_current_figure(dos_plot)

    temperatures = sorted({0.0, *(temperatures_k or [300.0])})
    phonon.run_thermal_properties(temperatures=temperatures)
    properties = phonon.get_thermal_properties_dict()
    n_primitive = len(phonon.primitive)
    thermal = [
        {
            "temperature_k": float(t),
            "free_energy_kj_mol": float(f),
            "entropy_j_k_mol": float(s),
            "heat_capacity_j_k_mol": float(c),
            "heat_capacity_per_atom_j_k_mol": float(c) / n_primitive,
        }
        for t, f, s, c in zip(
            properties["temperatures"],
            properties["free_energy"],
            properties["entropy"],
            properties["heat_capacity"],
            strict=True,
        )
    ]
    phonon.save(parameters, settings={"force_constants": True})

    lowest = float(min(mesh_frequencies.min(), band_frequencies.min()))
    return {
        "calculator": calculator,
        "supercell": [int(n) for n in supercell],
        "n_supercell_atoms": len(phonon.supercell),
        "n_displacements": len(displaced),
        "n_primitive_atoms": n_primitive,
        "gamma_frequencies_thz": [float(f) for f in gamma],
        "gamma_frequencies_cm1": [float(f) * THZ_TO_CM1 for f in gamma],
        "min_frequency_thz": lowest,
        "max_frequency_thz": float(max(mesh_frequencies.max(), band_frequencies.max())),
        "dynamically_stable": lowest > IMAGINARY_TOLERANCE_THZ,
        "imaginary_modes_on_mesh": int(np.sum(mesh_frequencies < IMAGINARY_TOLERANCE_THZ)),
        "zero_point_energy_kj_mol": thermal[0]["free_energy_kj_mol"],
        "thermal": [entry for entry in thermal if entry["temperature_k"] > 0] or thermal,
        "band_plot": band_plot,
        "dos_plot": dos_plot,
        "parameters": parameters,
    }
