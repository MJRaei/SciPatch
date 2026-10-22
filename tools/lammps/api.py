"""Classical molecular dynamics and crystal properties with LAMMPS.

Interatomic potentials come from the LAMMPS distribution (a checked set is
installed with the tool; see list_potentials) or from your own files, e.g. from
the NIST Interatomic Potentials Repository. All functions use LAMMPS metal units:
Angstrom, eV, ps, bar (reported here in GPa where noted).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

POTENTIALS_DIR = Path(sys.prefix) / "share" / "lammps" / "potentials"
CATALOG = Path(__file__).with_name("potentials.json")
# LAMMPS looks here for potential files that are not in the working directory.
os.environ.setdefault("LAMMPS_POTENTIALS", str(POTENTIALS_DIR))

BAR_TO_GPA = 1e-4
#: Box edge (Angstrom) for isolated-atom energies; larger than any bundled cutoff.
_ISOLATED_BOX = 30.0
#: Minimum supercell edge for MD (Angstrom), so atoms do not see their own images.
MIN_MD_LENGTH = 15.0

# Pair styles by file suffix, longest first. "*" in pair_coeff takes element names.
_STYLES = [
    (".eam.alloy", "eam/alloy"),
    (".eam.fs", "eam/fs"),
    (".eam", "eam"),
    (".adp", "adp"),
    (".sw.mod", "sw/mod"),
    (".sw", "sw"),
    (".tersoff.mod", "tersoff/mod"),
    (".tersoff.modc", "tersoff/mod/c"),
    (".tersoff.zbl", "tersoff/zbl"),
    (".tersoff", "tersoff"),
    (".edip", "edip"),
    (".vashishta", "vashishta"),
    (".gw.zbl", "gw/zbl"),
    (".gw", "gw"),
    (".extep", "extep"),
    (".meam.spline", "meam/spline"),
    (".airebo-m", "airebo/morse 3.0"),
    (".airebo", "airebo 3.0 1 1"),
    (".rebo", "rebo"),
    (".ace", "pace"),
    (".snap", "snap"),
]
_ELEMENT = re.compile(r"^[A-Z][a-z]?$")


def _symbols() -> list[str]:
    from ase.data import chemical_symbols

    return chemical_symbols


@dataclass
class _Potential:
    """How to set up one potential: LAMMPS commands and the element of each atom type."""

    label: str
    commands: list[str]
    elements: list[str]
    files: list[Path] = field(default_factory=list)


def _style(path: Path) -> str:
    name = path.name.lower()
    if name.startswith("ffield.reax") or "reaxff" in name:
        raise ValueError(
            f"{path.name} is a ReaxFF force field, which needs LAMMPS 'real' units and charge "
            "equilibration (fix qeq/reaxff); run it with run_script and your own input script."
        )
    for suffix, style in _STYLES:
        if name.endswith(suffix):
            return style
    raise ValueError(
        f"Cannot tell the pair style of {path.name} from its name. Pass pair_style and "
        "pair_coeff, e.g. pair_style='eam/alloy', pair_coeff=['* * my.potential Cu Ni']."
    )


def _file_elements(path: Path, style: str) -> list[str]:
    """Elements a potential file covers, in the file's own order."""
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    if style == "eam":  # funcfl: line 2 starts with the atomic number
        return [_symbols()[int(lines[1].split()[0])]]
    if style in ("eam/alloy", "eam/fs", "adp"):  # setfl: line 4 is "N El1 El2 ..."
        tokens = lines[3].split()
        return tokens[1 : 1 + int(tokens[0])]
    if style == "pace":
        match = re.search(r"^elements:\s*\[?([^\]\n]*)", text, re.MULTILINE)
        return re.findall(r"[A-Z][a-z]?", match.group(1)) if match else []
    if style == "snap":
        coeff = [line.split() for line in lines if line.strip().startswith("pair_coeff * *")]
        return [token for token in coeff[-1] if _ELEMENT.match(token)] if coeff else []
    if style.startswith(("airebo", "rebo")):
        return ["C", "H"]
    if style == "meam/spline":
        header = next((line for line in lines if line.startswith("meam/spline")), "")
        return [token for token in header.split()[2:] if _ELEMENT.match(token)]
    found: list[str] = []  # sw, tersoff, edip, vashishta, ...: entries start with elements
    for line in lines:
        tokens = line.split("#", 1)[0].split()
        if len(tokens) >= 3 and all(_ELEMENT.match(token) for token in tokens[:3]):
            found.extend(token for token in tokens[:3] if token not in found)
    return found


def _covered(path: Path, style: str) -> list[str]:
    """Elements a potential covers: from the catalog for installed files, else parsed."""
    if path.parent == POTENTIALS_DIR:
        for entry in _catalog():
            if entry["file"] == path.name and entry.get("elements"):
                return entry["elements"]
    return _file_elements(path, style)


def _resolve(name: str) -> Path:
    path = Path(name).expanduser()
    if path.is_file():
        return path.resolve()
    if (POTENTIALS_DIR / name).is_file():
        return POTENTIALS_DIR / name
    raise ValueError(
        f"No potential file {name!r}: give a path to your own file, or the name of an "
        "installed one (see list_potentials)."
    )


def _potential(
    potential: str | list[str] | None,
    pair_style: str | None,
    pair_coeff: list[str] | None,
    elements: list[str],
) -> _Potential:
    """The potential commands for a structure that contains these elements."""
    files = [_resolve(p) for p in ([potential] if isinstance(potential, str) else potential or [])]
    if pair_style:
        if not pair_coeff:
            if len(files) != 1:
                raise ValueError("With pair_style, pass pair_coeff (or one potential file).")
            pair_coeff = [f"* * {files[0]} {' '.join(elements)}"]
        commands = [f"pair_style {pair_style}", *(f"pair_coeff {c}" for c in pair_coeff)]
        return _Potential(f"pair_style {pair_style}", commands, elements, files)
    if not files:
        raise ValueError(
            "Choose a potential: the name of an installed file (see list_potentials), a path "
            "to your own file, or pair_style and pair_coeff."
        )
    styles = {_style(path) for path in files}
    if len(files) > 1 and styles != {"eam"}:
        raise ValueError(
            "Several files can be combined only for single-element EAM (.eam) files, one "
            "per element. Other potentials cover all their elements in one file."
        )
    style = styles.pop()
    if style == "eam":  # one funcfl file per element, coefficients per atom type
        by_element = {_covered(path, style)[0]: path for path in files}
        missing = [element for element in elements if element not in by_element]
        if missing:
            raise ValueError(
                f"No .eam file for {', '.join(missing)} (the files cover "
                f"{', '.join(by_element)}); pass one file per element."
            )
        coeffs = [f"pair_coeff {i} {i} {by_element[e]}" for i, e in enumerate(elements, 1)]
        label = ", ".join(path.name for path in files)
        return _Potential(label, ["pair_style eam", *coeffs], elements, files)
    path = files[0]
    covered = _covered(path, style)
    missing = [element for element in elements if element not in covered]
    if covered and missing:
        raise ValueError(
            f"{path.name} covers {', '.join(covered) or 'unknown elements'}; the structure "
            f"also has {', '.join(missing)}."
        )
    if style == "snap":
        # The .snap file sets up the pair style itself, for the types in its own order;
        # files it names are looked up next to it.
        text = path.read_text()
        for token in set(re.findall(r"\S+\.snap\w+", text)):
            if (path.parent / token).is_file():
                text = re.sub(rf"(?<!\S){re.escape(token)}(?!\S)", str(path.parent / token), text)
        return _Potential(path.name, [text], covered, files)
    coeff = f"pair_coeff * * {path} {' '.join(elements)}"
    return _Potential(path.name, [f"pair_style {style}", coeff], elements, files)


def _lammps(directory: Path, threads: int = 1):
    import lammps

    log = directory / "log.lammps"
    arguments = ["-screen", "none", "-log", str(log), "-nocite"]
    if threads > 1:  # OpenMP versions of the pair styles that have one
        arguments += ["-suffix", "omp", "-package", "omp", str(threads)]
    return lammps.lammps(cmdargs=arguments)


def _run(lmp, commands: str) -> None:
    try:
        lmp.commands_string(commands)
    except Exception as exc:
        message = str(exc).replace("ERROR on proc 0: ", "").replace("ERROR: ", "")
        raise ValueError(f"LAMMPS: {message}") from exc


def _setup(lmp, data: Path, pot: _Potential, extra: str = "") -> None:
    _run(
        lmp,
        f"""units metal
atom_style atomic
boundary p p p
read_data {data}
{chr(10).join(pot.commands)}
neighbor 2.0 bin
neigh_modify delay 0 every 1 check yes
thermo_style custom step pe press pxx pyy pzz pyz pxz pxy vol
thermo_modify norm no
{extra}""",
    )


def _write_data(path: Path, atoms, pot: _Potential) -> None:
    from ase.io.lammpsdata import write_lammps_data

    write_lammps_data(path, atoms, specorder=pot.elements, masses=True, force_skew=True)


def _read_structure(path: str):
    from ase.io import read

    try:
        atoms = read(path)
    except Exception as exc:
        raise ValueError(f"Could not read a structure from {path}: {exc}") from exc
    if not atoms.pbc.all() or atoms.cell.rank < 3:
        raise ValueError(f"{path} is not a periodic structure with a full cell.")
    return atoms


def _elements(atoms) -> list[str]:
    symbols = atoms.get_chemical_symbols()
    return sorted(set(symbols), key=symbols.index)


def _stress(lmp) -> np.ndarray:
    """Pressure tensor components in Voigt order (xx, yy, zz, yz, xz, xy), bar."""
    return np.array([lmp.get_thermo(name) for name in ("pxx", "pyy", "pzz", "pyz", "pxz", "pxy")])


def _box(lmp) -> tuple[np.ndarray, float, float, float]:
    """Cell vectors (rows) and the box lengths used as strain references."""
    low, high, xy, yz, xz, _, _ = lmp.extract_box()
    lx, ly, lz = (high[i] - low[i] for i in range(3))
    cell = np.array([[lx, 0, 0], [xy, ly, 0], [xz, yz, lz]])
    return cell, lx, ly, lz


def _atoms_from_lammps(lmp, pot: _Potential):
    from ase import Atoms

    cell, *_ = _box(lmp)
    low = np.array(lmp.extract_box()[0])
    n = lmp.extract_global("nlocal")  # the arrays also hold ghost atoms
    order = np.argsort(lmp.numpy.extract_atom("id")[:n])
    types = lmp.numpy.extract_atom("type")[:n][order]
    positions = lmp.numpy.extract_atom("x")[:n][order] - low
    atoms = Atoms([pot.elements[t - 1] for t in types], positions=positions, cell=cell, pbc=True)
    atoms.wrap()
    return atoms


def _isolated_energy(element: str, pot: _Potential, directory: Path) -> float:
    from ase import Atoms

    atoms = Atoms(element, positions=[[0, 0, 0]], cell=np.eye(3) * _ISOLATED_BOX, pbc=True)
    data = directory / f"isolated_{element}.data"
    _write_data(data, atoms, pot)
    lmp = _lammps(directory)
    try:
        _setup(lmp, data, pot, "run 0")
        return float(lmp.get_thermo("pe"))
    finally:
        lmp.close()


def _relax(lmp, cell_relax: bool) -> None:
    if cell_relax:
        _run(lmp, "fix relax all box/relax tri 0.0 vmax 0.001")
    for _ in range(6):  # box/relax converges best in a few restarts
        _run(lmp, "minimize 0.0 1.0e-10 10000 100000")
        if not cell_relax or np.abs(_stress(lmp)).max() < 0.01:
            break
    if cell_relax:
        _run(lmp, "unfix relax")


# Box change for each Voigt strain (as in the LAMMPS ELASTIC example): the strained
# length, and the box length the strain is relative to.
_DEFORM = {
    1: ("x delta 0 {d} xy delta {dxy} xz delta {dxz}", 1),
    2: ("y delta 0 {d} yz delta {dyz}", 2),
    3: ("z delta 0 {d}", 3),
    4: ("yz delta {d}", 3),
    5: ("xz delta {d}", 3),
    6: ("xy delta {d}", 2),
}


def _elastic(data: Path, pot: _Potential, stress0: np.ndarray, strain: float, directory: Path):
    """Elastic stiffness tensor (GPa) from central differences of stress with strain."""
    stiffness = np.zeros((6, 6))
    for voigt, (template, axis) in _DEFORM.items():
        rows = []
        for sign in (-1, 1):
            lmp = _lammps(directory)
            try:
                _setup(lmp, data, pot)
                _, lx, ly, lz = _box(lmp)
                _, _, xy, yz, xz, _, _ = lmp.extract_box()
                length = (lx, ly, lz)[axis - 1]
                change = template.format(
                    d=sign * strain * length,
                    dxy=sign * strain * xy,
                    dxz=sign * strain * xz,
                    dyz=sign * strain * yz,
                )
                _run(lmp, f"change_box all {change} remap units box")
                _run(lmp, "minimize 0.0 1.0e-10 1000 10000")
                rows.append(-(_stress(lmp) - stress0) / (sign * strain) * BAR_TO_GPA)
            finally:
                lmp.close()
        stiffness[:, voigt - 1] = 0.5 * (rows[0] + rows[1])
    return 0.5 * (stiffness + stiffness.T)


def _moduli(c: np.ndarray) -> dict:
    s = np.linalg.inv(c)
    bulk_voigt = (c[0, 0] + c[1, 1] + c[2, 2] + 2 * (c[0, 1] + c[0, 2] + c[1, 2])) / 9
    bulk_reuss = 1 / (s[0, 0] + s[1, 1] + s[2, 2] + 2 * (s[0, 1] + s[0, 2] + s[1, 2]))
    shear_voigt = (
        c[0, 0]
        + c[1, 1]
        + c[2, 2]
        - (c[0, 1] + c[0, 2] + c[1, 2])
        + 3 * (c[3, 3] + c[4, 4] + c[5, 5])
    ) / 15
    shear_reuss = 15 / (
        4 * (s[0, 0] + s[1, 1] + s[2, 2])
        - 4 * (s[0, 1] + s[0, 2] + s[1, 2])
        + 3 * (s[3, 3] + s[4, 4] + s[5, 5])
    )
    return {
        "bulk_modulus_gpa": float((bulk_voigt + bulk_reuss) / 2),
        "shear_modulus_gpa": float((shear_voigt + shear_reuss) / 2),
        "bulk_modulus_voigt_gpa": float(bulk_voigt),
        "bulk_modulus_reuss_gpa": float(bulk_reuss),
        "shear_modulus_voigt_gpa": float(shear_voigt),
        "shear_modulus_reuss_gpa": float(shear_reuss),
        "mechanically_stable": bool(np.linalg.eigvalsh(c).min() > 0),
    }


def _lattice(atoms) -> dict:
    a, b, c, alpha, beta, gamma = atoms.cell.cellpar()
    return {
        "a_angstrom": float(a),
        "b_angstrom": float(b),
        "c_angstrom": float(c),
        "alpha_deg": float(alpha),
        "beta_deg": float(beta),
        "gamma_deg": float(gamma),
        "volume_per_atom_angstrom3": float(atoms.get_volume() / len(atoms)),
    }


def _density(atoms) -> float:
    return float(atoms.get_masses().sum() / atoms.get_volume() * 1.66053906660)


def _describe(pot: _Potential) -> dict:
    catalog = {entry["file"]: entry for entry in _catalog()}
    citations = [
        catalog[path.name]["citation"]
        for path in pot.files
        if path.parent == POTENTIALS_DIR and path.name in catalog
    ]
    return {"name": pot.label, "citation": "; ".join(dict.fromkeys(citations)) or None}


def list_potentials(elements: list[str] | None = None) -> dict:
    """Interatomic potentials installed with the tool, optionally only those for given elements.

    Args:
        elements: Element symbols the potential must cover, e.g. ["Cu"] or ["Si", "C"].

    Returns:
        For each potential file: its name (pass it as potential), pair style,
        elements, the paper to cite, and notes. More potentials: the NIST
        Interatomic Potentials Repository (ctcms.nist.gov/potentials) and OpenKIM;
        pass their files by path.
    """
    wanted = set(elements or [])
    unknown = [e for e in wanted if e not in _symbols()[1:]]
    if unknown:
        raise ValueError(f"Unknown element symbol(s): {', '.join(unknown)}.")
    rows = [
        {
            key: entry[key]
            for key in ("file", "pair_style", "elements", "citation", "notes")
            if key in entry
        }
        for entry in _catalog()
        if entry.get("pair_style") and wanted <= set(entry["elements"])
    ]
    return {"potentials": rows, "n_potentials": len(rows), "directory": str(POTENTIALS_DIR)}


def _catalog() -> list[dict]:
    return json.loads(CATALOG.read_text())["potentials"]


def crystal_properties(
    structure: str,
    potential: str | list[str] | None = None,
    pair_style: str | None = None,
    pair_coeff: list[str] | None = None,
    relax: bool = True,
    elastic: bool = True,
    strain: float = 1e-5,
    relaxed_structure: str = "relaxed.cif",
) -> dict:
    """Relaxed lattice, cohesive energy, and elastic constants of a crystal at 0 K.

    Args:
        structure: Crystal structure file (CIF, POSCAR, extended XYZ). Use the
            conventional cell to get elastic constants along the crystal axes.
        potential: Installed potential file name (see list_potentials), a path to
            your own file, or a list of single-element .eam files (one per element).
            The pair style comes from the file name (.eam, .eam.alloy, .eam.fs,
            .sw, .tersoff, .snap, .ace, ...).
        pair_style: LAMMPS pair_style for any other potential, e.g. "lj/cut 10.0".
        pair_coeff: pair_coeff arguments with pair_style, e.g. ["* * 0.0104 3.40"].
            Atom types are numbered by the order in which elements first appear.
        relax: Relax atoms and cell (all six components) to zero stress first.
        elastic: Compute the elastic constants (12 strained relaxations).
        strain: Strain for the finite differences.
        relaxed_structure: CIF file for the relaxed structure.

    Returns:
        Lattice parameters, energy and cohesive energy per atom (eV, cohesive =
        isolated atoms minus crystal, positive when bound), density, the 6x6
        elastic stiffness tensor in GPa (Voigt order xx, yy, zz, yz, xz, xy, in
        the LAMMPS frame: a along x, b in the xy plane) with the named
        components (C11, C12, ...), Voigt-Reuss-Hill bulk and shear moduli, and
        whether the crystal is mechanically stable.
    """
    if not 0 < strain <= 0.01:
        raise ValueError("strain must be between 0 and 0.01.")
    atoms = _read_structure(structure)
    pot = _potential(potential, pair_style, pair_coeff, _elements(atoms))
    with tempfile.TemporaryDirectory(prefix="scipatch-lammps-") as tmp:
        directory = Path(tmp)
        data = directory / "start.data"
        _write_data(data, atoms, pot)
        lmp = _lammps(directory)
        try:
            _setup(lmp, data, pot)
            if relax:
                _relax(lmp, cell_relax=True)
            else:
                _run(lmp, "run 0")
            energy = float(lmp.get_thermo("pe"))
            stress = _stress(lmp)
            relaxed = _atoms_from_lammps(lmp, pot)
            reference = directory / "relaxed.data"
            _run(lmp, f"write_data {reference} nocoeff")
        finally:
            lmp.close()
        n = len(relaxed)
        symbols = relaxed.get_chemical_symbols()
        isolated = sum(symbols.count(e) * _isolated_energy(e, pot, directory) for e in set(symbols))
        result: dict = {
            "potential": _describe(pot),
            "formula": relaxed.get_chemical_formula(mode="metal"),
            "n_atoms": n,
            "energy_per_atom_ev": energy / n,
            "cohesive_energy_ev_per_atom": (isolated - energy) / n,
            "lattice": _lattice(relaxed),
            "density_g_cm3": _density(relaxed),
            "max_residual_stress_gpa": float(np.abs(stress).max() * BAR_TO_GPA),
        }
        if elastic:
            c = _elastic(reference, pot, stress, strain, directory)
            names = {
                f"C{i + 1}{j + 1}": float(round(c[i, j], 6)) for i in range(6) for j in range(i, 6)
            }
            result["elastic_constants_gpa"] = names
            result["elastic_tensor_gpa"] = [[float(round(v, 6)) for v in row] for row in c]
            result.update(_moduli(c))
    relaxed.write(relaxed_structure)
    result["relaxed_structure"] = relaxed_structure
    return result


def simulate(
    structure: str,
    potential: str | list[str] | None = None,
    pair_style: str | None = None,
    pair_coeff: list[str] | None = None,
    ensemble: Literal["nvt", "npt", "nve"] = "nvt",
    temperature_k: float = 300.0,
    pressure_gpa: float = 0.0,
    barostat: Literal["iso", "aniso", "tri"] = "aniso",
    steps: int = 20000,
    equilibration_steps: int | None = None,
    timestep_fs: float = 1.0,
    supercell: list[int] | None = None,
    seed: int = 12345,
    threads: int | None = None,
    frame_interval: int = 100,
    trajectory: str = "md.extxyz",
    final_structure: str = "final.cif",
) -> dict:
    """Molecular dynamics of a crystal, liquid, or amorphous solid with a classical potential.

    Temperature and pressure are held with Nose-Hoover thermostats and barostats.
    Averages are taken after equilibration.

    Args:
        structure: Structure file (CIF, POSCAR, extended XYZ, LAMMPS data).
        potential: Installed potential name, a path, or single-element .eam files
            (as in crystal_properties).
        pair_style: LAMMPS pair_style for any other potential.
        pair_coeff: pair_coeff arguments with pair_style.
        ensemble: "nvt" (default), "npt" (constant pressure, e.g. for thermal
            expansion or liquid density), or "nve".
        temperature_k: Temperature in K (also the starting velocities).
        pressure_gpa: Pressure for npt, in GPa.
        barostat: "iso" (liquids, cubic crystals), "aniso" (orthogonal cells), or
            "tri" (all cell components).
        steps: MD steps after equilibration (production).
        equilibration_steps: Steps before averaging; default steps / 4.
        timestep_fs: Time step in fs (1 fs for most solids; 0.5 fs with hydrogen).
        supercell: Repetitions of the cell, e.g. [4, 4, 4]; default: at least
            15 Angstrom along each axis.
        seed: Random seed for the starting velocities.
        threads: OpenMP threads; default: the number of CPU cores, up to 8.
        frame_interval: Steps between saved trajectory frames.
        trajectory: Extended XYZ trajectory of the production run (readable by ASE,
            OVITO, and the diffusion tools).
        final_structure: CIF of the last frame.

    Returns:
        Averages and standard deviations of temperature (K), pressure (GPa),
        potential energy (eV/atom), volume per atom, density (g/cm3), and the
        mean cell lengths per repeated cell; the trajectory, number of frames,
        frame interval (fs), simulated time (ps), and the number of atoms.
    """
    if steps < 1 or timestep_fs <= 0 or temperature_k <= 0 or frame_interval < 1:
        raise ValueError("steps, timestep_fs, temperature_k, and frame_interval must be positive.")
    equilibration = steps // 4 if equilibration_steps is None else equilibration_steps
    if equilibration < 0:
        raise ValueError("equilibration_steps cannot be negative.")
    atoms = _read_structure(structure)
    if supercell is None:
        supercell = [max(1, int(np.ceil(MIN_MD_LENGTH / h))) for h in _heights(atoms)]
    if len(supercell) != 3 or any(int(n) != n or n < 1 for n in supercell):
        raise ValueError("supercell must be three positive integers, e.g. [4, 4, 4].")
    atoms = atoms.repeat([int(n) for n in supercell])
    pot = _potential(potential, pair_style, pair_coeff, _elements(atoms))
    dt = timestep_fs / 1000
    pressure_bar = pressure_gpa / BAR_TO_GPA
    integrator = {
        "nvt": f"nvt temp {temperature_k} {temperature_k} {100 * dt}",
        "npt": f"npt temp {temperature_k} {temperature_k} {100 * dt} "
        f"{barostat} {pressure_bar} {pressure_bar} {1000 * dt}",
        "nve": "nve",
    }[ensemble]
    with tempfile.TemporaryDirectory(prefix="scipatch-lammps-") as tmp:
        directory = Path(tmp)
        data = directory / "start.data"
        _write_data(data, atoms, pot)
        dump = directory / "md.dump"
        lmp = _lammps(directory, threads or min(8, os.cpu_count() or 1))
        try:
            _setup(lmp, data, pot)
            _run(
                lmp,
                f"""timestep {dt}
velocity all create {temperature_k} {seed} mom yes rot yes dist gaussian
fix md all {integrator}
thermo_style custom step temp press pe vol density lx ly lz
thermo_modify norm no
thermo {max(1, (equilibration + steps) // 100)}
run {equilibration}
reset_timestep 0
thermo {max(1, min(frame_interval, steps // 200 or 1))}
dump traj all custom {frame_interval} {dump} id element x y z
dump_modify traj element {" ".join(pot.elements)} sort id
run {steps}""",
            )
            final = _atoms_from_lammps(lmp, pot)
        finally:
            lmp.close()
        from lammps.formats import LogFile

        production = LogFile(str(directory / "log.lammps")).runs[-1]
        frames = _convert_dump(dump, trajectory)
    n = len(final)
    columns = {key: np.asarray(values, dtype=float) for key, values in production.items()}
    reps = np.array(supercell, dtype=float)

    def stats(values: np.ndarray, scale: float = 1.0) -> tuple[float, float]:
        return float(values.mean() * scale), float(values.std() * scale)

    temperature = stats(columns["Temp"])
    pressure = stats(columns["Press"], BAR_TO_GPA)
    energy = stats(columns["PotEng"], 1 / n)
    volume = stats(columns["Volume"], 1 / n)
    density = stats(columns["Density"])
    final.write(final_structure)
    return {
        "potential": _describe(pot),
        "ensemble": ensemble,
        "n_atoms": n,
        "supercell": [int(r) for r in reps],
        "average_temperature_k": temperature[0],
        "std_temperature_k": temperature[1],
        "average_pressure_gpa": pressure[0],
        "std_pressure_gpa": pressure[1],
        "average_potential_energy_ev_per_atom": energy[0],
        "std_potential_energy_ev_per_atom": energy[1],
        "average_volume_per_atom_angstrom3": volume[0],
        "average_density_g_cm3": density[0],
        "average_cell_lengths_angstrom": [
            float(columns[k].mean() / r) for k, r in zip(("Lx", "Ly", "Lz"), reps, strict=True)
        ],
        "simulated_time_ps": steps * dt,
        "trajectory": trajectory,
        "n_frames": frames,
        "frame_interval_fs": frame_interval * timestep_fs,
        "final_structure": final_structure,
    }


def _heights(atoms) -> np.ndarray:
    """Distances between opposite cell faces."""
    reciprocal = np.linalg.inv(atoms.cell[:]).T
    return 1 / np.linalg.norm(reciprocal, axis=1)


def _convert_dump(dump: Path, trajectory: str) -> int:
    from ase.io import read, write

    frames = read(dump, index=":", format="lammps-dump-text")
    for frame in frames:
        frame.calc = None
        frame.pbc = True
    write(trajectory, frames, format="extxyz")
    return len(frames)


def run_script(
    script: str,
    files: list[str] | None = None,
    variables: dict[str, str] | None = None,
    processes: int = 1,
    log: str = "log.lammps",
) -> dict:
    """Run your own LAMMPS input script, like `lmp -in script`.

    The script and the files it reads are copied into the working folder and run
    there, so everything it writes (dumps, restart and data files) ends up next to
    the log. Installed potential files can be named without a path (see
    list_potentials).

    Args:
        script: LAMMPS input script.
        files: Other files the script reads (data files, potential files,
            included scripts), copied next to it.
        variables: Index variables as with `lmp -var name value`, e.g. {"T": "300"}.
        processes: MPI processes (1 = serial).
        log: Log file name.

    Returns:
        Thermo output of each run (columns, the first and last rows, and the
        number of rows), warnings, the LAMMPS version, wall time, and the log path.
    """
    if processes < 1:
        raise ValueError("processes must be at least 1.")
    here = Path.cwd()
    copied = []
    for item in [script, *(files or [])]:
        source = Path(item).expanduser()
        if not source.is_file():
            raise ValueError(f"No such file: {item}")
        target = here / source.name
        if source.resolve() != target.resolve():
            shutil.copy(source, target)
        copied.append(target)
    command = [str(Path(sys.prefix) / "bin" / "lmp"), "-in", copied[0].name, "-log", log]
    command += ["-nocite", "-screen", "none"]
    for name, value in (variables or {}).items():
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise ValueError(f"Invalid variable name {name!r}.")
        command += ["-var", name, str(value)]
    environment = dict(os.environ)
    if processes > 1:
        command = [str(Path(sys.prefix) / "bin" / "mpiexec"), "-n", str(processes), *command]
        environment["OMP_NUM_THREADS"] = "1"
    completed = subprocess.run(command, capture_output=True, text=True, env=environment)
    text = Path(log).read_text(errors="replace") if Path(log).exists() else ""
    errors = [
        line
        for line in (text + completed.stdout + completed.stderr).splitlines()
        if line.startswith("ERROR")
    ]
    if completed.returncode != 0 or errors:
        detail = errors[0] if errors else (completed.stderr or completed.stdout).strip()[-2000:]
        raise ValueError(f"LAMMPS stopped: {detail}")
    from lammps.formats import LogFile

    runs = []
    for run in LogFile(log).runs:
        columns = list(run)
        n_rows = len(run[columns[0]]) if columns else 0
        runs.append(
            {
                "columns": columns,
                "n_rows": n_rows,
                "first": {key: float(run[key][0]) for key in columns} if n_rows else {},
                "last": {key: float(run[key][-1]) for key in columns} if n_rows else {},
            }
        )
    version = re.search(r"LAMMPS \(([^)]*)\)", text)
    wall = re.search(r"Total wall time: (\S+)", text)
    return {
        "runs": runs,
        "n_runs": len(runs),
        "warnings": sorted({line for line in text.splitlines() if line.startswith("WARNING")})[:20],
        "lammps_version": version.group(1) if version else None,
        "wall_time": wall.group(1) if wall else None,
        "log": log,
    }
