"""Plane-wave density functional theory for crystals with Quantum ESPRESSO (pw.x).

By default the verified SSSP 1.3 PBE efficiency pseudopotentials are used, with
their recommended cutoffs. Structures are read with ASE (CIF, POSCAR, extended
XYZ, ...) and must be periodic. Energies in eV, lengths in Angstrom, stresses
and moduli in GPa; plane-wave cutoffs in Rydberg, as in Quantum ESPRESSO.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any, Literal

import numpy as np

Occupations = Literal["smearing", "fixed"]

SSSP_DIR = Path(sys.prefix) / "share" / "sssp"
SSSP_JSON = SSSP_DIR / "SSSP_1.3.0_PBE_efficiency.json"
#: Starting magnetization (fraction of valence electrons) for spin-polarized runs.
_MAGNETIC = {"Cr": 0.5, "Mn": 0.5, "Fe": 0.5, "Co": 0.5, "Ni": 0.5, "Gd": 0.5}


def _read(structure: str) -> Any:
    from ase.io import read

    atoms = read(structure)
    if not atoms.pbc.all() or atoms.cell.rank < 3:
        raise ValueError(
            f"{Path(structure).name} has no periodic cell: this tool computes crystals (and "
            "slabs in a periodic cell). For molecules, use the pyscf or xtb tool."
        )
    return atoms


def _upf_element(path: Path) -> str:
    """The element of a UPF pseudopotential, from its header (UPF v1 or v2)."""
    head = path.read_text(errors="replace")[:20000]
    match = re.search(r'element\s*=\s*"\s*([A-Za-z]{1,2})\s*"', head) or re.search(
        r"^\s*([A-Z][a-z]?)\s+Element", head, re.MULTILINE
    )
    if match is None:
        raise ValueError(f"Could not find the element in the header of {path.name}.")
    return match.group(1).capitalize()


def _pseudopotentials(
    symbols: list[str], custom: list[str] | None
) -> tuple[dict[str, str], float | None, float | None, str]:
    """Pseudopotential files in ./pseudo, and SSSP's recommended cutoffs (Ry)."""
    folder = Path("pseudo")
    folder.mkdir(exist_ok=True)
    chosen: dict[str, str] = {}
    if custom:
        for path in map(Path, custom):
            shutil.copy(path, folder / path.name)
            chosen[_upf_element(path)] = path.name
        missing = sorted(set(symbols) - set(chosen))
        if missing:
            raise ValueError(f"No pseudopotential given for {', '.join(missing)}.")
        return chosen, None, None, "custom"
    if not SSSP_JSON.exists():
        raise RuntimeError("The SSSP library is missing; rebuild the tool to download it.")
    table = json.loads(SSSP_JSON.read_text())
    wfc = rho = 0.0
    for element in sorted(set(symbols)):
        if element not in table:
            raise ValueError(f"SSSP has no pseudopotential for {element}.")
        entry = table[element]
        chosen[element] = entry["filename"]
        shutil.copy(SSSP_DIR / "pseudos" / entry["filename"], folder / entry["filename"])
        wfc, rho = max(wfc, entry["cutoff_wfc"]), max(rho, entry["cutoff_rho"])
    return chosen, wfc, rho, "SSSP 1.3.0 PBE efficiency"


def _mesh(atoms: Any, density: float) -> list[int]:
    reciprocal = 2 * np.pi * np.linalg.norm(atoms.cell.reciprocal(), axis=1)
    return [max(1, int(np.ceil(density * length))) for length in reciprocal]


def _run_pw(
    atoms: Any,
    calculation: str,
    ecutwfc_ry: float | None,
    ecutrho_ry: float | None,
    kpoint_density: float,
    kpts: list[int] | None,
    gamma_centered: bool,
    occupations: Occupations,
    smearing_ry: float,
    spin_polarized: bool | None,
    pseudopotentials: list[str] | None,
    extra: dict[str, dict[str, Any]] | None = None,
) -> tuple[Any, str, dict[str, Any]]:
    """Write pw.in, run pw.x, and return (final atoms with results, output text, settings)."""
    from ase.io import read
    from ase.io.espresso import write_espresso_in

    symbols = atoms.get_chemical_symbols()
    pseudos, sssp_wfc, sssp_rho, library = _pseudopotentials(symbols, pseudopotentials)
    wfc = ecutwfc_ry or sssp_wfc
    if wfc is None:
        raise ValueError("Give ecutwfc_ry for custom pseudopotentials.")
    rho = ecutrho_ry or (sssp_rho if ecutwfc_ry is None else None) or 4 * wfc
    if kpts is not None and (len(kpts) != 3 or any(int(n) != n or n < 1 for n in kpts)):
        raise ValueError("kpts must be three positive integers, e.g. [8, 8, 8].")
    mesh = [int(n) for n in kpts] if kpts else _mesh(atoms, kpoint_density)
    atoms = atoms.copy()
    given = any(atoms.get_initial_magnetic_moments())
    magnetic = given or any(s in _MAGNETIC for s in symbols)
    spin = magnetic if spin_polarized is None else spin_polarized
    system: dict[str, Any] = {"ecutwfc": wfc, "ecutrho": rho, "occupations": occupations}
    if occupations == "smearing":
        system |= {"smearing": "mv", "degauss": smearing_ry}
    # ASE's writer derives starting_magnetization from the atoms' initial moments
    # (moments from the structure file, e.g. for antiferromagnets, are kept).
    if spin:
        system["nspin"] = 2
        if not given:
            atoms.set_initial_magnetic_moments([_MAGNETIC.get(s, 0.0) for s in symbols])
    else:
        atoms.set_initial_magnetic_moments(None)
    # Wave functions are large and never kept: write them to the system's temporary
    # folder (on the Linux file system even when the run folder is on Windows, in WSL).
    scratch = tempfile.mkdtemp(prefix="motel-qe-")
    input_data = {
        "control": {
            "calculation": calculation,
            "tprnfor": True,
            "tstress": True,
            "pseudo_dir": "pseudo",
            "outdir": scratch,
        },
        "system": system,
        "electrons": {"conv_thr": 1e-9 * len(atoms), "mixing_beta": 0.4},
    }
    for section, values in (extra or {}).items():
        input_data.setdefault(section, {}).update(values)
    with open("pw.in", "w") as handle:
        write_espresso_in(
            handle,
            atoms,
            input_data=input_data,
            pseudopotentials=pseudos,
            kpts=mesh,
            koffset=(0, 0, 0) if gamma_centered else (1, 1, 1),
        )
    command = _pw_command(mesh)
    print(f"Running pw.x ({calculation}, {mesh} k-points, {wfc} Ry)...", flush=True)
    environment = {**os.environ, "OMP_NUM_THREADS": "1"} if command[0] == "mpirun" else None
    try:
        completed = subprocess.run(command, capture_output=True, text=True, env=environment)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    output = completed.stdout + completed.stderr
    Path("pw.out").write_text(output)
    if "JOB DONE" not in output:
        tail = "\n".join(output.splitlines()[-20:])
        raise RuntimeError(f"pw.x failed (exit code {completed.returncode}):\n{tail}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = read("pw.out", format="espresso-out", index=-1)
    settings = {
        "pseudopotentials": library,
        "ecutwfc_ry": wfc,
        "ecutrho_ry": rho,
        "kpts": mesh,
        "gamma_centered": gamma_centered,
        "spin_polarized": bool(spin),
        "occupations": occupations,
        "smearing_ry": smearing_ry if occupations == "smearing" else None,
    }
    return result, output, settings


def _pw_command(mesh: list[int]) -> list[str]:
    """pw.x on all cores with MPI (one thread per process), or serial without mpirun."""
    processes = os.cpu_count() or 1
    if processes == 1 or shutil.which("mpirun") is None:
        return ["pw.x", "-in", "pw.in"]
    # Split k-points over processes only when there are clearly enough of them.
    pools = processes if int(np.prod(mesh)) >= 4 * processes else 1
    return [
        "mpirun", "--oversubscribe", "-np", str(processes),
        "pw.x", "-nk", str(pools), "-in", "pw.in",
    ]  # fmt: skip


def _electronic(atoms: Any, output: str) -> dict[str, Any]:
    from ase.dft.bandgap import bandgap

    calc = atoms.calc
    gap = direct = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gap, valence, conduction = bandgap(calc, output=None)
            direct, _, _ = bandgap(calc, direct=True, output=None)
    except Exception:  # fixed occupations without empty bands give no gap
        valence = conduction = None
    magnetization = re.findall(r"total magnetization\s+=\s+(-?\d+\.\d+)", output)
    fermi = re.findall(r"the Fermi energy is\s+(-?\d+\.\d+)", output)
    highest = re.findall(
        r"highest occupied(?:, lowest unoccupied)? level \(ev\):\s+(-?\d+\.\d+)", output
    )
    return {
        "fermi_level_ev": float(fermi[-1]) if fermi else None,
        "highest_occupied_level_ev": float(highest[-1]) if highest else None,
        "band_gap_ev": None if gap is None else float(gap),
        "direct_band_gap_ev": None if direct is None else float(direct),
        "is_metal": None if gap is None else bool(gap == 0),
        "gap_is_direct": None
        if gap is None or valence is None or conduction is None
        else bool(gap > 0 and valence[1] == conduction[1]),
        "magnetic_moment_mu_b": float(magnetization[-1]) if magnetization else 0.0,
    }


def scf(
    structure: str,
    ecutwfc_ry: float | None = None,
    ecutrho_ry: float | None = None,
    kpoint_density: float = 4.0,
    kpts: list[int] | None = None,
    gamma_centered: bool = True,
    occupations: Occupations = "smearing",
    smearing_ry: float = 0.01,
    spin_polarized: bool | None = None,
    pseudopotentials: list[str] | None = None,
) -> dict:
    """Self-consistent DFT ground state of a crystal: energy, forces, stress, gap, magnetism.

    Args:
        structure: Crystal structure file (CIF, POSCAR, extended XYZ, ...).
        ecutwfc_ry: Wave-function cutoff in Ry. Default: the SSSP recommendation
            (the largest over the elements present).
        ecutrho_ry: Charge-density cutoff in Ry. Default: the SSSP recommendation,
            or 4 x ecutwfc_ry when ecutwfc_ry is given.
        kpoint_density: k-points per reciprocal Angstrom along each axis (4 is good
            for insulators, 6 or more for metals); ignored if kpts is given.
        kpts: Explicit Monkhorst-Pack mesh, e.g. [8, 8, 8].
        gamma_centered: Center the mesh on Gamma (default); False shifts it by half
            a step (the "1 1 1" offset of pw.x).
        occupations: "smearing" (Marzari-Vanderbilt; default, needed for metals) or
            "fixed" (insulators only).
        smearing_ry: Smearing width in Ry.
        spin_polarized: Default: yes if the structure contains Cr, Mn, Fe, Co, Ni, or
            Gd (started ferromagnetic).
        pseudopotentials: Your own pseudopotential files (UPF), one per element, e.g.
            ["Si.pbe-n-rrkjus_psl.1.0.0.UPF"]; then give ecutwfc_ry. Default: SSSP
            1.3 PBE efficiency.

    Returns:
        Total energy and energy per atom (eV), the largest force (eV/Angstrom),
        stress (GPa, Voigt order), Fermi level or highest occupied level, band gap
        (eV; when empty bands are computed), magnetization (mu_B per cell), and
        the settings used. The pw.x input and output are kept as pw.in and pw.out.
    """
    from ase.units import GPa

    atoms = _read(structure)
    result, output, settings = _run_pw(
        atoms, "scf", ecutwfc_ry, ecutrho_ry, kpoint_density, kpts, gamma_centered,
        occupations, smearing_ry, spin_polarized, pseudopotentials,
    )  # fmt: skip
    energy = float(result.get_potential_energy())
    return {
        "formula": atoms.get_chemical_formula(mode="metal"),
        "n_atoms": len(atoms),
        "energy_ev": energy,
        "energy_per_atom_ev": energy / len(atoms),
        "max_force_ev_per_angstrom": float(np.linalg.norm(result.get_forces(), axis=1).max()),
        "stress_gpa": [float(s / GPa) for s in result.get_stress(voigt=True)],
        **_electronic(result, output),
        "settings": settings,
        "input_file": "pw.in",
        "output_file": "pw.out",
    }


def relax(
    structure: str,
    relax_cell: bool = True,
    ecutwfc_ry: float | None = None,
    ecutrho_ry: float | None = None,
    kpoint_density: float = 4.0,
    kpts: list[int] | None = None,
    smearing_ry: float = 0.01,
    spin_polarized: bool | None = None,
    pseudopotentials: list[str] | None = None,
    output: str = "relaxed.cif",
) -> dict:
    """Relax atomic positions, and by default the cell (pw.x 'vc-relax'), at zero pressure.

    Args:
        structure: Crystal structure file.
        relax_cell: Also relax the cell shape and volume.
        ecutwfc_ry: Wave-function cutoff in Ry (default: SSSP recommendation; the
            cell relaxation uses it as is, so raise it for accurate stresses).
        ecutrho_ry: Charge-density cutoff in Ry (default: SSSP recommendation).
        kpoint_density: k-points per reciprocal Angstrom (see scf).
        kpts: Explicit Monkhorst-Pack mesh.
        smearing_ry: Smearing width in Ry.
        spin_polarized: Spin polarization (default: automatic, see scf).
        pseudopotentials: Your own pseudopotentials (see scf).
        output: File for the relaxed structure.

    Returns:
        Whether it converged, the final energy and energy per atom (eV), lattice
        parameters (Angstrom, degrees), volume per atom, remaining stress (GPa),
        magnetization, settings, and the relaxed structure path.
    """
    from ase.io import write
    from ase.units import GPa

    atoms = _read(structure)
    extra = {"ions": {"ion_dynamics": "bfgs"}}
    if relax_cell:
        extra["cell"] = {"cell_dynamics": "bfgs", "press_conv_thr": 0.5}
    result, text, settings = _run_pw(
        atoms, "vc-relax" if relax_cell else "relax", ecutwfc_ry, ecutrho_ry, kpoint_density,
        kpts, True, "smearing", smearing_ry, spin_polarized, pseudopotentials, extra,
    )  # fmt: skip
    write(output, result)
    a, b, c, alpha, beta, gamma = result.cell.cellpar()
    energy = float(result.get_potential_energy())
    return {
        "formula": result.get_chemical_formula(mode="metal"),
        "converged": "bfgs converged" in text or "End of BFGS" in text,
        "energy_ev": energy,
        "energy_per_atom_ev": energy / len(result),
        "lattice": {
            "a_angstrom": float(a),
            "b_angstrom": float(b),
            "c_angstrom": float(c),
            "alpha_deg": float(alpha),
            "beta_deg": float(beta),
            "gamma_deg": float(gamma),
        },
        "volume_per_atom_angstrom3": float(result.get_volume() / len(result)),
        "stress_gpa": [float(s / GPa) for s in result.get_stress(voigt=True)],
        **_electronic(result, text),
        "settings": settings,
        "relaxed_structure": output,
    }


def equation_of_state(
    structure: str,
    ecutwfc_ry: float | None = None,
    ecutrho_ry: float | None = None,
    kpoint_density: float = 5.0,
    kpts: list[int] | None = None,
    smearing_ry: float = 0.01,
    spin_polarized: bool | None = None,
    pseudopotentials: list[str] | None = None,
    volume_range: float = 0.06,
    n_points: int = 7,
    plot: str = "eos.png",
) -> dict:
    """Equilibrium volume, bulk modulus, and its pressure derivative (Birch-Murnaghan fit).

    The cell is scaled uniformly over volumes from (1 - volume_range) to
    (1 + volume_range) times the input volume; the k-point mesh is fixed from
    the input cell.

    Args:
        structure: Crystal structure file, ideally near equilibrium.
        ecutwfc_ry: Wave-function cutoff in Ry (default: SSSP recommendation).
        ecutrho_ry: Charge-density cutoff in Ry (default: SSSP recommendation).
        kpoint_density: k-points per reciprocal Angstrom (see scf).
        kpts: Explicit Monkhorst-Pack mesh.
        smearing_ry: Smearing width in Ry.
        spin_polarized: Spin polarization (default: automatic, see scf).
        pseudopotentials: Your own pseudopotentials (see scf).
        volume_range: Relative volume change on each side (0.06 = plus or minus 6%).
        n_points: Number of volumes.
        plot: PNG file of the fitted energy-volume curve.

    Returns:
        Equilibrium volume per atom (Angstrom^3), energy per atom at the minimum
        (eV), bulk modulus (GPa) and its pressure derivative, the computed points,
        settings, and the plot path.
    """
    from ase.eos import EquationOfState
    from ase.units import GPa

    if not 5 <= n_points <= 15 or not 0.01 <= volume_range <= 0.2:
        raise ValueError("Use 5 to 15 points and a volume_range between 0.01 and 0.2.")
    atoms = _read(structure)
    mesh = [int(n) for n in kpts] if kpts else _mesh(atoms, kpoint_density)
    reference = atoms.get_cell()
    n = len(atoms)
    volumes, energies, settings = [], [], {}
    for scale in np.linspace(1 - volume_range, 1 + volume_range, n_points):
        atoms.set_cell(reference * scale ** (1 / 3), scale_atoms=True)
        result, _, settings = _run_pw(
            atoms, "scf", ecutwfc_ry, ecutrho_ry, 0, mesh, True, "smearing", smearing_ry,
            spin_polarized, pseudopotentials,
        )  # fmt: skip
        volumes.append(float(atoms.get_volume()) / n)
        energies.append(float(result.get_potential_energy()) / n)
        print(f"V = {volumes[-1]:.4f} A^3/atom: E = {energies[-1]:.6f} eV/atom", flush=True)
    eos = EquationOfState(volumes, energies, eos="birchmurnaghan")
    v0, e0, bulk = eos.fit()
    _plot(eos, plot)
    return {
        "formula": atoms.get_chemical_formula(mode="metal"),
        "volume_per_atom_angstrom3": float(v0),
        "energy_per_atom_ev": float(e0),
        "bulk_modulus_gpa": float(bulk / GPa),
        "bulk_modulus_derivative": float(eos.eos_parameters[2]),
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
