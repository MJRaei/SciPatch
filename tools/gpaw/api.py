"""Density functional theory for crystals with GPAW (plane waves and PAW datasets).

Structures are read with ASE (CIF, POSCAR, extended XYZ, ...) and must be
periodic. Energies are in eV, lengths in Angstrom, stresses and moduli in GPa.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Literal

import numpy as np

Occupations = Literal["fermi-dirac", "tetrahedron"]

#: Starting magnetic moments (mu_B) for spin-polarized runs: a ferromagnetic guess.
_INITIAL_MOMENTS = {"Cr": 3.0, "Mn": 4.0, "Fe": 3.0, "Co": 2.0, "Ni": 1.0, "Gd": 7.0}


def _read(structure: str) -> Any:
    from ase.io import read

    atoms = read(structure)
    if not atoms.pbc.all() or atoms.cell.rank < 3:
        raise ValueError(
            f"{Path(structure).name} has no periodic cell: this tool computes crystals (and "
            "slabs in a periodic cell). For molecules, use the pyscf or xtb tool."
        )
    return atoms


def _setup(
    atoms: Any,
    xc: str,
    ecut_ev: float,
    kpoint_density: float,
    kpts: list[int] | None,
    spin_polarized: bool | None,
    occupations: Occupations,
    smearing_ev: float,
    gamma_centered: bool = True,
    txt: str = "-",
) -> dict[str, Any]:
    """Attach a GPAW plane-wave calculator; returns the settings actually used."""
    from gpaw import GPAW

    if ecut_ev < 150:
        raise ValueError("ecut_ev below 150 eV is far too low for PAW datasets; use 400-600.")
    if kpts is not None and (len(kpts) != 3 or any(int(n) != n or n < 1 for n in kpts)):
        raise ValueError("kpts must be three positive integers, e.g. [8, 8, 8].")
    magnetic = any(atoms.get_initial_magnetic_moments()) or any(
        s in _INITIAL_MOMENTS for s in atoms.get_chemical_symbols()
    )
    spin = magnetic if spin_polarized is None else spin_polarized
    if spin and not any(atoms.get_initial_magnetic_moments()):
        atoms.set_initial_magnetic_moments(
            [_INITIAL_MOMENTS.get(s, 0.0) for s in atoms.get_chemical_symbols()]
        )
    if not spin:
        atoms.set_initial_magnetic_moments(None)
    mesh = [int(n) for n in kpts] if kpts else _mesh(atoms, kpoint_density)
    occupation = (
        {"name": "tetrahedron-method"}
        if occupations == "tetrahedron"
        else {"name": "fermi-dirac", "width": smearing_ev}
    )
    atoms.calc = GPAW(
        mode={"name": "pw", "ecut": ecut_ev},
        xc=xc,
        kpts={"size": mesh, "gamma": gamma_centered},
        occupations=occupation,
        spinpol=spin,
        txt=txt,
    )
    return {
        "xc": xc,
        "ecut_ev": ecut_ev,
        "kpts": mesh,
        "gamma_centered": gamma_centered,
        "spin_polarized": bool(spin),
        "occupations": occupations,
        "smearing_ev": smearing_ev if occupations == "fermi-dirac" else None,
    }


def _mesh(atoms: Any, density: float) -> list[int]:
    """Monkhorst-Pack mesh with at least ``density`` points per reciprocal Angstrom."""
    reciprocal = 2 * np.pi * np.linalg.norm(atoms.cell.reciprocal(), axis=1)
    return [max(1, int(np.ceil(density * length))) for length in reciprocal]


def _electronic(atoms: Any) -> dict[str, Any]:
    from ase.dft.bandgap import bandgap

    calc = atoms.calc
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gap, valence, conduction = bandgap(calc, output=None)
        direct, _, _ = bandgap(calc, direct=True, output=None)
    spin = calc.get_number_of_spins() == 2
    moments = atoms.get_magnetic_moments() if spin else None
    return {
        "fermi_level_ev": float(calc.get_fermi_level()),
        "band_gap_ev": float(gap),
        "direct_band_gap_ev": float(direct),
        "is_metal": bool(gap == 0),
        "gap_is_direct": bool(gap > 0 and valence[1] == conduction[1]),
        "magnetic_moment_mu_b": float(atoms.get_magnetic_moment()) if spin else 0.0,
        "magnetic_moments_mu_b": None if moments is None else [float(m) for m in moments],
    }


def _stress_gpa(atoms: Any) -> list[float]:
    from ase.units import GPa

    return [float(s / GPa) for s in atoms.get_stress(voigt=True)]


def scf(
    structure: str,
    xc: str = "PBE",
    ecut_ev: float = 500.0,
    kpoint_density: float = 4.0,
    kpts: list[int] | None = None,
    spin_polarized: bool | None = None,
    occupations: Occupations = "fermi-dirac",
    smearing_ev: float = 0.05,
    gamma_centered: bool = True,
    output: str = "scf.gpw",
) -> dict:
    """Self-consistent DFT ground state of a crystal: energy, forces, stress, gap, magnetism.

    Args:
        structure: Crystal structure file (CIF, POSCAR, extended XYZ, ...).
        xc: Exchange-correlation functional: "PBE" (default), "LDA", "PBEsol",
            "RPBE", or other functionals GPAW supports.
        ecut_ev: Plane-wave cutoff in eV (400-600 is typical for converged results).
        kpoint_density: k-points per reciprocal Angstrom along each axis (4 is good
            for insulators, 6 or more for metals); ignored if kpts is given.
        kpts: Explicit Monkhorst-Pack mesh, e.g. [8, 8, 8].
        spin_polarized: Spin-polarized calculation. Default: yes if the structure
            has magnetic moments or contains Cr, Mn, Fe, Co, Ni, or Gd (started
            ferromagnetic).
        occupations: "fermi-dirac" smearing (default; needed for metals) or
            "tetrahedron" (accurate for insulators and densities of states).
        smearing_ev: Fermi-Dirac width in eV.
        gamma_centered: Center the k-point mesh on Gamma (default); False gives the
            standard Monkhorst-Pack mesh, which is shifted for even sizes.
        output: GPAW restart file (input for band_structure).

    Returns:
        Total energy and energy per atom (eV), the largest force (eV/Angstrom),
        stress (GPa, Voigt order xx yy zz yz xz xy), Fermi level, band gap (eV)
        and whether it is direct, magnetic moments (mu_B), the settings used,
        and the restart file path.
    """
    atoms = _read(structure)
    settings = _setup(
        atoms,
        xc,
        ecut_ev,
        kpoint_density,
        kpts,
        spin_polarized,
        occupations,
        smearing_ev,
        gamma_centered,
    )
    energy = float(atoms.get_potential_energy())
    forces = atoms.get_forces()
    result = {
        "formula": atoms.get_chemical_formula(mode="metal"),
        "n_atoms": len(atoms),
        "energy_ev": energy,
        "energy_per_atom_ev": energy / len(atoms),
        "max_force_ev_per_angstrom": float(np.linalg.norm(forces, axis=1).max()),
        "stress_gpa": _stress_gpa(atoms),
        **_electronic(atoms),
        "settings": settings,
        "restart_file": output,
    }
    atoms.calc.write(output)
    return result


def relax(
    structure: str,
    xc: str = "PBE",
    ecut_ev: float = 500.0,
    kpoint_density: float = 4.0,
    kpts: list[int] | None = None,
    spin_polarized: bool | None = None,
    smearing_ev: float = 0.05,
    relax_cell: bool = True,
    fmax: float = 0.02,
    max_steps: int = 100,
    output: str = "relaxed.cif",
) -> dict:
    """Relax atomic positions, and by default the cell, to the DFT minimum.

    Args:
        structure: Crystal structure file.
        xc: Exchange-correlation functional (see scf).
        ecut_ev: Plane-wave cutoff in eV; use at least 500 when the cell relaxes
            (stress converges more slowly than energy).
        kpoint_density: k-points per reciprocal Angstrom (see scf).
        kpts: Explicit Monkhorst-Pack mesh.
        spin_polarized: Spin-polarized calculation (default: automatic, see scf).
        smearing_ev: Fermi-Dirac width in eV.
        relax_cell: Also relax the cell shape and volume (zero pressure).
        fmax: Force convergence threshold in eV/Angstrom (applies to stress too).
        max_steps: Maximum number of optimizer steps.
        output: File for the relaxed structure (CIF, POSCAR, extended XYZ, ...).

    Returns:
        Whether it converged, steps taken, final energy and energy per atom (eV),
        lattice parameters (Angstrom, degrees), volume per atom (Angstrom^3), the
        remaining stress (GPa), magnetic moment, band gap, and the structure path.
    """
    from ase.filters import FrechetCellFilter
    from ase.io import write
    from ase.optimize import BFGS

    atoms = _read(structure)
    settings = _setup(
        atoms, xc, ecut_ev, kpoint_density, kpts, spin_polarized, "fermi-dirac", smearing_ev
    )
    target = FrechetCellFilter(atoms) if relax_cell else atoms
    optimizer = BFGS(target, logfile="-")
    converged = bool(optimizer.run(fmax=fmax, steps=max_steps))
    write(output, atoms)
    a, b, c, alpha, beta, gamma = atoms.cell.cellpar()
    energy = float(atoms.get_potential_energy())
    return {
        "formula": atoms.get_chemical_formula(mode="metal"),
        "converged": converged,
        "steps": int(optimizer.nsteps),
        "energy_ev": energy,
        "energy_per_atom_ev": energy / len(atoms),
        "lattice": {
            "a_angstrom": float(a),
            "b_angstrom": float(b),
            "c_angstrom": float(c),
            "alpha_deg": float(alpha),
            "beta_deg": float(beta),
            "gamma_deg": float(gamma),
        },
        "volume_per_atom_angstrom3": float(atoms.get_volume() / len(atoms)),
        "stress_gpa": _stress_gpa(atoms),
        **_electronic(atoms),
        "settings": settings,
        "relaxed_structure": output,
    }


def equation_of_state(
    structure: str,
    xc: str = "PBE",
    ecut_ev: float = 500.0,
    kpoint_density: float = 5.0,
    kpts: list[int] | None = None,
    spin_polarized: bool | None = None,
    smearing_ev: float = 0.05,
    volume_range: float = 0.06,
    n_points: int = 7,
    plot: str = "eos.png",
) -> dict:
    """Equilibrium volume, bulk modulus, and its pressure derivative from a Birch-Murnaghan fit.

    The cell is scaled uniformly (shape and fractional positions kept) over
    volumes from (1 - volume_range) to (1 + volume_range) times the input volume.

    Args:
        structure: Crystal structure file, ideally near equilibrium.
        xc: Exchange-correlation functional (see scf).
        ecut_ev: Plane-wave cutoff in eV.
        kpoint_density: k-points per reciprocal Angstrom (see scf); the mesh is fixed
            from the input cell for all volumes.
        kpts: Explicit Monkhorst-Pack mesh.
        spin_polarized: Spin-polarized calculation (default: automatic, see scf).
        smearing_ev: Fermi-Dirac width in eV.
        volume_range: Relative volume change on each side (0.06 = plus or minus 6%).
        n_points: Number of volumes.
        plot: PNG file of the fitted energy-volume curve.

    Returns:
        Equilibrium volume per atom (Angstrom^3) and the corresponding lattice
        scaling, energy per atom at the minimum (eV), bulk modulus (GPa) and its
        pressure derivative, the computed points, and the plot path.
    """
    from ase.eos import EquationOfState
    from ase.units import GPa

    if not 5 <= n_points <= 15 or not 0.01 <= volume_range <= 0.2:
        raise ValueError("Use 5 to 15 points and a volume_range between 0.01 and 0.2.")
    atoms = _read(structure)
    mesh = [int(n) for n in kpts] if kpts else _mesh(atoms, kpoint_density)
    settings = _setup(atoms, xc, ecut_ev, 0, mesh, spin_polarized, "fermi-dirac", smearing_ev)
    reference = atoms.get_cell()
    n = len(atoms)
    volumes, energies = [], []
    for scale in np.linspace(1 - volume_range, 1 + volume_range, n_points):
        atoms.set_cell(reference * scale ** (1 / 3), scale_atoms=True)
        energies.append(float(atoms.get_potential_energy()) / n)
        volumes.append(float(atoms.get_volume()) / n)
        print(f"V = {volumes[-1]:.4f} A^3/atom: E = {energies[-1]:.6f} eV/atom", flush=True)
    eos = EquationOfState(volumes, energies, eos="birchmurnaghan")
    v0, e0, bulk = eos.fit()
    derivative = float(eos.eos_parameters[2]) if hasattr(eos, "eos_parameters") else None
    _plot(eos, plot)
    return {
        "formula": atoms.get_chemical_formula(mode="metal"),
        "volume_per_atom_angstrom3": float(v0),
        "lattice_scale": float((v0 * n / abs(np.linalg.det(reference))) ** (1 / 3)),
        "energy_per_atom_ev": float(e0),
        "bulk_modulus_gpa": float(bulk / GPa),
        "bulk_modulus_derivative": derivative,
        "volumes_angstrom3": volumes,
        "energies_ev_per_atom": energies,
        "settings": settings,
        "plot": plot,
    }


def _plot(eos: Any, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    axes = eos.plot(show=False)
    axes.figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(axes.figure)


def band_structure(
    structure: str,
    path: str | None = None,
    n_points: int = 100,
    n_empty_bands: int = 8,
    xc: str = "PBE",
    ecut_ev: float = 500.0,
    kpoint_density: float = 4.0,
    spin_polarized: bool | None = None,
    plot: str = "bands.png",
) -> dict:
    """Electronic band structure along a high-symmetry path, and the band gap.

    Args:
        structure: A restart file from scf (.gpw; its settings are reused) or a
            crystal structure file (an scf calculation is run first).
        path: Special points, e.g. "GXWKGLUWLK" for fcc; default: the standard
            path for the lattice (Setyawan-Curtarolo).
        n_points: Number of k-points along the path.
        n_empty_bands: Conduction bands to converge above the gap.
        xc: Functional for a new scf calculation (ignored for .gpw input).
        ecut_ev: Plane-wave cutoff for a new scf calculation.
        kpoint_density: k-point density for a new scf calculation.
        spin_polarized: Spin polarization for a new scf calculation.
        plot: PNG file of the band structure.

    Returns:
        The band gap along the path and whether it is direct, the valence band
        maximum and conduction band minimum (eV) with their k-point labels, the
        path used, and the plot path.
    """
    from ase.dft.bandgap import bandgap
    from ase.spectrum.band_structure import BandStructure
    from gpaw import GPAW

    if Path(structure).suffix == ".gpw":
        ground_state = GPAW(structure, txt=None)
    else:
        scf(structure, xc, ecut_ev, kpoint_density, None, spin_polarized, output="scf.gpw")
        ground_state = GPAW("scf.gpw", txt=None)
    atoms = ground_state.get_atoms()
    lattice_path = atoms.cell.bandpath(path, npoints=n_points)
    occupied = int(np.ceil(ground_state.get_number_of_electrons() / 2))
    calc = ground_state.fixed_density(
        nbands=occupied + n_empty_bands + 4,
        symmetry="off",
        kpts=lattice_path,
        convergence={"bands": occupied + n_empty_bands},
        occupations={"name": "fermi-dirac", "width": 0.01},  # tetrahedra need a mesh
        txt="-",
    )
    fermi_level = float(ground_state.get_fermi_level())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gap, valence, conduction = bandgap(calc, efermi=fermi_level, output=None)
    vbm = None
    if gap > 0:
        vbm = float(calc.get_eigenvalues(kpt=valence[1], spin=valence[0])[valence[2]])
    # Zero of the plot: the valence band maximum for semiconductors, else the Fermi level.
    zero = vbm if vbm is not None else fermi_level
    energies = calc.band_structure().energies
    _plot_bands(BandStructure(lattice_path, energies, zero), "VBM" if vbm else "E_F", plot)
    return {
        "formula": atoms.get_chemical_formula(mode="metal"),
        "band_gap_ev": float(gap),
        "gap_is_direct": bool(gap > 0 and valence[1] == conduction[1]),
        "valence_band_maximum_ev": vbm,
        "valence_band_maximum_at": None if vbm is None else _location(lattice_path, valence[1]),
        "conduction_band_minimum_at": (
            None if vbm is None else _location(lattice_path, conduction[1])
        ),
        "fermi_level_ev": fermi_level,
        "path": lattice_path.path,
        "plot": plot,
    }


def _location(lattice_path: Any, index: int) -> str:
    """Where a k-point on the path is: a special point, or how far along a segment."""
    x, special_x, labels = lattice_path.get_linear_kpoint_axis()
    names = ["Γ" if label == "G" else label for label in labels]
    for position, name in zip(special_x, names, strict=True):
        if abs(x[index] - position) < 1e-6:
            return name
    segment = int(np.searchsorted(special_x, x[index])) - 1
    start, stop = special_x[segment], special_x[segment + 1]
    fraction = (x[index] - start) / (stop - start)
    return f"between {names[segment]} and {names[segment + 1]} ({fraction:.0%} of the way)"


def _plot_bands(structure_bands: Any, zero: str, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(6, 4.5))
    structure_bands.subtract_reference().plot(
        ax=axes, emin=-10, emax=8, ylabel=f"E - {zero} (eV)", show=False
    )
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
