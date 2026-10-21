"""Materials properties from universal machine-learned potentials with matcalc.

Elastic constants, equations of state, quasi-harmonic thermal properties, and
formation energies, computed with MatGL's universal potentials trained on the
MatPES dataset (PBE or r2SCAN). Structures are read with pymatgen (CIF,
POSCAR, pymatgen JSON, ...). Moduli are in GPa, energies in eV.
"""

from __future__ import annotations

import functools
import warnings
from typing import Any, Literal

import numpy as np

Model = Literal[
    "TensorNet-MatPES-PBE-2025.2",
    "TensorNet-MatPES-r2SCAN-2025.2",
    "M3GNet-MatPES-PBE-2025.1",
    "CHGNet-MatPES-PBE-1M-2026.9",
    "CHGNet-MatPES-r2SCAN-1M-2026.9",
]
DEFAULT_MODEL = "TensorNet-MatPES-PBE-2025.2"
EV_PER_A3_TO_GPA = 160.21766208

warnings.filterwarnings("ignore")


@functools.cache
def _calculator(model: str) -> Any:
    import matcalc

    return matcalc.load_fp(model)


def _structure(path: str) -> Any:
    from pymatgen.core import Structure

    try:
        structure = Structure.from_file(path)
    except Exception as exc:
        raise ValueError(
            f"Could not read a periodic crystal structure from {path}: {exc}. Use CIF, POSCAR, "
            "or pymatgen JSON; for molecules, use the pyscf or xtb tool."
        ) from exc
    if not structure.is_ordered:
        raise ValueError(
            "The structure has partial occupancies, but a potential needs one atom per site. "
            "Order it first (e.g. enumerate orderings of a supercell) and compute each ordering."
        )
    return structure


def _lattice(structure: Any) -> dict[str, float]:
    a, b, c = structure.lattice.abc
    alpha, beta, gamma = structure.lattice.angles
    return {
        "a_angstrom": float(a),
        "b_angstrom": float(b),
        "c_angstrom": float(c),
        "alpha_deg": float(alpha),
        "beta_deg": float(beta),
        "gamma_deg": float(gamma),
        "volume_per_atom_angstrom3": float(structure.volume / len(structure)),
    }


def _strains(maximum: float) -> list[float]:
    if not 0 < maximum <= 0.1:
        raise ValueError("Strains must be between 0 and 0.1 (10%).")
    return [-maximum, -maximum / 2, maximum / 2, maximum]


def elastic_constants(
    structure: str,
    model: Model = DEFAULT_MODEL,
    relax: bool = True,
    fmax: float = 0.05,
    max_normal_strain: float = 0.01,
    max_shear_strain: float = 0.06,
) -> dict:
    """Full elastic tensor and moduli from stress-strain fits.

    Args:
        structure: Crystal structure file.
        model: Universal potential. TensorNet-MatPES-PBE (default) and the other
            "PBE" models reproduce PBE DFT; "r2SCAN" models reproduce the more
            accurate r2SCAN functional.
        relax: Relax the structure (atoms and cell) first; elastic constants are
            only meaningful at equilibrium.
        fmax: Force convergence for relaxations, eV/Angstrom.
        max_normal_strain: Largest normal strain (0.01 = 1%).
        max_shear_strain: Largest shear strain.

    Returns:
        The elastic tensor in Voigt notation (6x6, GPa), Voigt-Reuss-Hill bulk
        and shear moduli, Young's modulus (GPa), Poisson's ratio, whether the
        crystal is mechanically stable (all eigenvalues of the tensor positive),
        the fit quality, and the relaxed lattice.
    """
    import matcalc

    calc = matcalc.ElasticityCalc(
        _calculator(model),
        norm_strains=_strains(max_normal_strain),
        shear_strains=_strains(max_shear_strain),
        fmax=fmax,
        relax_structure=relax,
        use_equilibrium=True,
        units_GPa=True,
    )
    result = calc.calc(_structure(structure))
    voigt = np.asarray(result["elastic_tensor"].voigt, dtype=float)
    bulk = float(result["bulk_modulus_vrh"])
    shear = float(result["shear_modulus_vrh"])
    eigenvalues = np.linalg.eigvalsh((voigt + voigt.T) / 2)
    return {
        "model": model,
        "elastic_tensor_voigt_gpa": voigt.round(4).tolist(),
        "bulk_modulus_vrh_gpa": bulk,
        "shear_modulus_vrh_gpa": shear,
        "youngs_modulus_gpa": 9 * bulk * shear / (3 * bulk + shear),
        "poisson_ratio": (3 * bulk - 2 * shear) / (2 * (3 * bulk + shear)),
        "mechanically_stable": bool(eigenvalues.min() > 0),
        "fit_r2": float(result["r2_score_mean"]),
        "lattice": _lattice(result["final_structure"]),
    }


def equation_of_state(
    structure: str,
    model: Model = DEFAULT_MODEL,
    relax: bool = True,
    fmax: float = 0.05,
    max_strain: float = 0.1,
    n_points: int = 11,
    plot: str = "eos.png",
) -> dict:
    """Bulk modulus and equilibrium volume from a Birch-Murnaghan equation of state.

    Args:
        structure: Crystal structure file.
        model: Universal potential (see elastic_constants).
        relax: Relax the structure first, and the atoms at each strained volume.
        fmax: Force convergence for relaxations, eV/Angstrom.
        max_strain: Largest linear strain (0.1 = 10%) on each side.
        n_points: Number of volumes.
        plot: PNG file of the energy-volume curve.

    Returns:
        Bulk modulus (GPa), equilibrium volume and energy per atom from the fit,
        the fit quality, the computed points, and the plot path.
    """
    import matcalc
    from ase.eos import EquationOfState
    from ase.units import GPa

    calc = matcalc.EOSCalc(
        _calculator(model),
        max_abs_strain=max_strain,
        n_points=n_points,
        fmax=fmax,
        relax_structure=relax,
    )
    crystal = _structure(structure)
    result = calc.calc(crystal)
    n = len(crystal)
    volumes = np.asarray(result["eos"]["volumes"], dtype=float) / n
    energies = np.asarray(result["eos"]["energies"], dtype=float) / n
    eos = EquationOfState(volumes, energies, eos="birchmurnaghan")
    v0, e0, bulk = eos.fit()
    _save_plot(eos.plot(show=False), plot)
    return {
        "model": model,
        "bulk_modulus_gpa": float(result["bulk_modulus_bm"]),
        "bulk_modulus_per_atom_fit_gpa": float(bulk / GPa),
        "volume_per_atom_angstrom3": float(v0),
        "energy_per_atom_ev": float(e0),
        "fit_r2": float(result["r2_score_bm"]),
        "volumes_angstrom3_per_atom": volumes.tolist(),
        "energies_ev_per_atom": energies.tolist(),
        "plot": plot,
    }


def thermal_properties(
    structure: str,
    model: Model = DEFAULT_MODEL,
    t_max: float = 1000.0,
    t_step: float = 50.0,
    report_temperatures: list[float] | None = None,
    supercell: list[int] | None = None,
    scale_range: float = 0.03,
    n_volumes: int = 7,
    relax: bool = True,
    fmax: float = 0.05,
    table: str = "thermal_properties.csv",
    plot: str = "thermal_properties.png",
) -> dict:
    """Thermal expansion, heat capacity, and free energy vs temperature (quasi-harmonic).

    Phonons are computed at several volumes, and the free energy is minimized
    over volume at each temperature (quasi-harmonic approximation).

    Args:
        structure: Crystal structure file.
        model: Universal potential (see elastic_constants).
        t_max: Highest temperature, K.
        t_step: Temperature step, K.
        report_temperatures: Temperatures to report in the result (K); the full
            curves are in the table. Default: 300 K and t_max.
        supercell: Phonon supercell, e.g. [2, 2, 2]. Default: automatic.
        scale_range: Largest relative change of the lattice parameters (0.03 = 3%).
        n_volumes: Number of volumes (odd numbers include the input volume).
        relax: Relax the structure first.
        fmax: Force convergence for relaxations, eV/Angstrom.
        table: CSV file with all properties at every temperature.
        plot: PNG file with thermal expansion and heat capacity vs temperature.

    Returns:
        At each reported temperature: the equilibrium cell volume (Angstrom^3),
        volumetric thermal expansion coefficient (1/K; the linear coefficient of a
        cubic crystal is a third of it), heat capacity at constant pressure (J/K
        per mole of input cells, and per mole of atoms), bulk modulus (GPa),
        Gruneisen parameter, and Gibbs free energy (eV per cell); plus the table
        and plot.
    """
    import matcalc

    if not 3 <= n_volumes <= 15 or not 0.005 <= scale_range <= 0.1:
        raise ValueError("Use 3 to 15 volumes and a scale_range between 0.005 and 0.1.")
    temperatures = report_temperatures or [300.0, t_max]
    phonon_kwargs = {}
    if supercell is not None:
        if len(supercell) != 3 or any(int(n) != n or n < 1 for n in supercell):
            raise ValueError("supercell must be three positive integers, e.g. [2, 2, 2].")
        phonon_kwargs["supercell_matrix"] = np.diag([int(n) for n in supercell]).tolist()
    calc = matcalc.QHACalc(
        calculator=_calculator(model),
        t_step=t_step,
        t_max=t_max,
        scale_factors=np.linspace(1 - scale_range, 1 + scale_range, n_volumes).tolist(),
        fmax=fmax,
        relax_structure=relax,
        phonon_calc_kwargs=phonon_kwargs or None,
    )
    crystal = _structure(structure)
    result = calc.calc(crystal)
    grid = np.asarray(result["temperatures"], dtype=float)
    columns = {
        "temperature_k": grid,
        "volume_angstrom3": result["qha"].volume_temperature,
        "thermal_expansion_per_k": result["thermal_expansion_coefficients"],
        "heat_capacity_p_j_per_k_mol": result["heat_capacity_P"],
        "bulk_modulus_gpa": result["bulk_modulus_P"],
        "gruneisen_parameter": result["gruneisen_parameters"],
        "gibbs_free_energy_ev": result["gibbs_free_energies"],
    }
    columns = {k: np.asarray(v, dtype=float)[: len(grid)] for k, v in columns.items()}
    _write_table(columns, table)
    _plot_thermal(columns, plot)
    n = len(crystal)
    report = []
    for temperature in temperatures:
        i = int(np.argmin(abs(grid - temperature)))
        row = {k: float(v[i]) for k, v in columns.items()}
        row["heat_capacity_p_j_per_k_per_mol_atoms"] = row["heat_capacity_p_j_per_k_mol"] / n
        report.append(row)
    return {"model": model, "n_atoms_in_cell": n, "at": report, "table": table, "plot": plot}


def formation_energy(structure: str, model: Model = DEFAULT_MODEL, relax: bool = True) -> dict:
    """Formation energy (from the elements) and cohesive energy per atom.

    Args:
        structure: Crystal structure file.
        model: Universal potential (see elastic_constants); elemental reference
            energies are taken from the matching MatPES dataset (PBE or r2SCAN).
        relax: Relax the structure first.

    Returns:
        Formation energy per atom relative to the elemental ground states (eV/atom),
        cohesive energy per atom relative to isolated atoms (eV/atom), the total
        energy, and the relaxed lattice.
    """
    import matcalc

    references = "MatPES-r2SCAN" if "r2SCAN" in model else "MatPES-PBE"
    calc = matcalc.EnergeticsCalc(
        _calculator(model), elemental_refs=references, relax_structure=relax
    )
    result = calc.calc(_structure(structure))
    return {
        "model": model,
        "elemental_references": references,
        "formation_energy_per_atom_ev": float(result["formation_energy_per_atom"]),
        "cohesive_energy_per_atom_ev": float(result["cohesive_energy_per_atom"]),
        "energy_ev": float(result["energy"]),
        "lattice": _lattice(result["final_structure"]),
    }


def _write_table(columns: dict[str, np.ndarray], path: str) -> None:
    data = np.column_stack(list(columns.values()))
    np.savetxt(path, data, delimiter=",", header=",".join(columns), comments="")


def _save_plot(axes: Any, path: str) -> None:
    import matplotlib.pyplot as plt

    axes.figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(axes.figure)


def _plot_thermal(columns: dict[str, np.ndarray], path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, (left, right) = plt.subplots(1, 2, figsize=(9, 3.5))
    left.plot(columns["temperature_k"], columns["thermal_expansion_per_k"] * 1e6)
    left.set(xlabel="T (K)", ylabel="volumetric thermal expansion (10⁻⁶/K)")
    right.plot(columns["temperature_k"], columns["heat_capacity_p_j_per_k_mol"])
    right.set(xlabel="T (K)", ylabel="C_p (J/K/mol of cell)")
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
