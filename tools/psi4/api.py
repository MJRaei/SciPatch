"""Intermolecular interaction energies with Psi4.

sapt splits the interaction between two molecules into electrostatics,
exchange (Pauli repulsion), induction (polarization and charge transfer), and
dispersion with symmetry-adapted perturbation theory. interaction_energy gives
the supermolecular interaction energy at any Psi4 method, including composite
complete-basis-set estimates, with counterpoise (Boys-Bernardi) correction of the
basis-set superposition error. benchmark_dimers gives the S22 and S66 benchmark
complexes and their reference CCSD(T)/CBS interaction energies.
"""

from __future__ import annotations

import atexit
import functools
import importlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Literal

import numpy as np

SaptLevel = Literal["sapt0", "sapt2", "sapt2+", "sapt2+(3)", "sapt2+3"]
Database = Literal["S22", "S66"]
COMPONENTS = ("ELST", "EXCH", "IND", "DISP")
NAMES = {"ELST": "electrostatics", "EXCH": "exchange", "IND": "induction", "DISP": "dispersion"}


@functools.cache
def _psi4():
    import psi4

    psi4.core.be_quiet()
    # Psi4 writes timer.dat into the working directory at exit; do that in a
    # temporary folder instead.
    atexit.unregister(psi4.core.finalize)
    atexit.register(_finalize, psi4)
    return psi4


def _finalize(psi4) -> None:
    here = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="psi4-") as folder:
        os.chdir(folder)
        try:
            psi4.core.finalize()
        finally:
            os.chdir(here)


def _database(name: str):
    psi4 = _psi4()
    from psi4.driver import qcdb

    sys.modules.setdefault("qcdb", qcdb)
    folder = str(Path(psi4.core.get_datadir()) / "databases")
    if folder not in sys.path:
        sys.path.append(folder)
    return importlib.import_module(name)


def _read_xyz(path: str) -> tuple[list[str], np.ndarray]:
    file = Path(path)
    if not file.is_file():
        raise ValueError(f"Geometry file {path!r} not found.")
    lines = file.read_text(encoding="utf-8").splitlines()
    try:
        count = int(lines[0].split()[0])
        rows = [line.split() for line in lines[2 : 2 + count]]
        symbols = [row[0].capitalize() for row in rows]
        coords = np.array([[float(v) for v in row[1:4]] for row in rows])
    except (IndexError, ValueError) as exc:
        raise ValueError(
            f"{file.name} is not an XYZ file (count, comment, atoms in Angstrom)."
        ) from exc
    if len(symbols) != count:
        raise ValueError(f"{file.name} lists {count} atoms but has {len(symbols)}.")
    return symbols, coords


def _fragments(symbols, coords, fragment_a_atoms: int | None) -> list[list[int]]:
    if fragment_a_atoms is not None:
        if not 0 < fragment_a_atoms < len(symbols):
            raise ValueError("fragment_a_atoms must leave at least one atom in each molecule.")
        return [list(range(fragment_a_atoms)), list(range(fragment_a_atoms, len(symbols)))]
    from psi4.driver.qcdb.bfs import BFS

    psi4 = _psi4()
    groups = BFS(coords / psi4.constants.bohr2angstroms, np.array(symbols), bond_threshold=1.2)
    if len(groups) != 2:
        raise ValueError(
            f"Found {len(groups)} separate molecules by connectivity; give fragment_a_atoms "
            "(the first N atoms form molecule A) to split the complex in two."
        )
    return sorted((sorted(int(i) for i in g) for g in groups), key=lambda g: g[0])


def _molecule(
    dimer: str | None,
    benchmark: str | None,
    fragment_a_atoms: int | None,
    charges: tuple[int, int],
    multiplicities: tuple[int, int],
):
    """Psi4 molecule string, a label, and the benchmark entry if any."""
    if (dimer is None) == (benchmark is None):
        raise ValueError("Give either dimer (an XYZ file) or benchmark (e.g. 'S22-2').")
    if benchmark is not None:
        entry = _benchmark_entry(benchmark)
        return entry["psi4_string"], entry["name"], entry
    symbols, coords = _read_xyz(dimer)
    groups = _fragments(symbols, coords, fragment_a_atoms)
    blocks = []
    for group, charge, multiplicity in zip(groups, charges, multiplicities, strict=True):
        atoms = "\n".join(
            f"{symbols[i]} {coords[i][0]:.10f} {coords[i][1]:.10f} {coords[i][2]:.10f}"
            for i in group
        )
        blocks.append(f"{charge} {multiplicity}\n{atoms}")
    text = "units angstrom\nno_com\nno_reorient\n" + "\n--\n".join(blocks)
    return text, Path(dimer).name, None


def _benchmark_entry(label: str) -> dict:
    try:
        database, index = label.split("-", 1)
        database = database.upper()
        if database not in ("S22", "S66"):
            raise ValueError
        module = _database(database)
        key = f"{database}-{int(index)}"
        molecule = module.GEOS[f"{key}-dimer"]
    except (ValueError, KeyError) as exc:
        raise ValueError(
            f"Unknown benchmark {label!r}; use e.g. 'S22-2' (1-22) or 'S66-1' (1-66)."
        ) from exc
    reference = {
        "S22": ("S22B CCSD(T)/CBS, Marshall et al., J. Chem. Phys. 135, 194102 (2011)"),
        "S66": ("CCSD(T)/CBS, Rezac et al., J. Chem. Theory Comput. 7, 2427 (2011)"),
    }[database]
    return {
        "label": key,
        "name": module.TAGL[key],
        "reference_kcal_mol": float(module.BIND[key]),
        "reference": reference,
        "psi4_string": molecule.create_psi4_string_from_molecule(),
        "molecule": molecule,
    }


def _setup(memory_gb: float, threads: int | None, scratch: str) -> None:
    psi4 = _psi4()
    psi4.core.clean()
    psi4.core.clean_options()
    psi4.core.clean_variables()
    psi4.set_memory(int(memory_gb * 1e9))
    psi4.set_num_threads(threads or os.cpu_count() or 1)
    psi4.core.set_output_file(str(Path(scratch) / "psi4.out"), False)
    psi4.core.IOManager.shared_object().set_default_path(scratch)


def _energies(hartree: float) -> dict:
    psi4 = _psi4()
    return {
        "kcal_mol": round(hartree * psi4.constants.hartree2kcalmol, 5),
        "kj_mol": round(hartree * psi4.constants.hartree2kJmol, 5),
        "hartree": hartree,
    }


def sapt(
    dimer: str | None = None,
    benchmark: str | None = None,
    level: SaptLevel = "sapt0",
    basis: str = "jun-cc-pVDZ",
    fragment_a_atoms: int | None = None,
    charge_a: int = 0,
    multiplicity_a: int = 1,
    charge_b: int = 0,
    multiplicity_b: int = 1,
    freeze_core: bool = True,
    options: dict | None = None,
    memory_gb: float = 2.0,
    threads: int | None = None,
) -> dict:
    """Energy decomposition of the interaction between two molecules (SAPT).

    Args:
        dimer: XYZ file (Angstrom) of the complex. It is split into the two
            molecules by connectivity unless fragment_a_atoms is given.
        benchmark: Instead of dimer, a benchmark complex: "S22-1" to "S22-22" or
            "S66-1" to "S66-66" (see benchmark_dimers).
        level: "sapt0" (fast, with sSAPT0 also reported), "sapt2", "sapt2+",
            "sapt2+(3)", or "sapt2+3" (more accurate, much slower).
        basis: Orbital basis. Recommended: jun-cc-pVDZ for SAPT0 (Parker et al.
            2014), aug-cc-pVDZ or larger for SAPT2+ levels.
        fragment_a_atoms: The first N atoms form molecule A, the rest B.
        charge_a: Charge of molecule A.
        multiplicity_a: Spin multiplicity of molecule A (open shell: sapt0 only).
        charge_b: Charge of molecule B.
        multiplicity_b: Spin multiplicity of molecule B.
        freeze_core: Exclude core electrons from correlation (dispersion).
        options: Extra Psi4 options, e.g. {"df_basis_elst": "jun-cc-pVDZ-RI"}.
        memory_gb: Memory for Psi4 in GB.
        threads: CPU threads (default: all).

    Returns:
        Electrostatics, exchange, induction, dispersion, and total interaction
        energy (kcal/mol, kJ/mol, hartree; negative is attractive); the share of
        each attractive term; sSAPT0 values for sapt0; and, for a benchmark
        complex, its reference CCSD(T)/CBS interaction energy.
    """
    psi4 = _psi4()
    open_shell = multiplicity_a > 1 or multiplicity_b > 1
    if open_shell and level != "sapt0":
        raise ValueError("Open-shell molecules are supported at level sapt0 only.")
    text, name, entry = _molecule(
        dimer, benchmark, fragment_a_atoms, (charge_a, charge_b), (multiplicity_a, multiplicity_b)
    )
    with tempfile.TemporaryDirectory(prefix="psi4-") as scratch:
        _setup(memory_gb, threads, scratch)
        molecule = psi4.geometry(text)
        if molecule.nfragments() != 2:
            raise ValueError("SAPT needs exactly two molecules.")
        settings = {"basis": basis, "freeze_core": freeze_core, "scf_type": "df"}
        if open_shell:
            settings["reference"] = "uhf"
        settings.update(options or {})
        psi4.set_options(settings)
        try:
            psi4.energy(level, molecule=molecule)
        except Exception as exc:
            raise RuntimeError(f"Psi4 {level} failed: {exc}") from exc
        values = {key: float(psi4.variable(f"SAPT {key} ENERGY")) for key in COMPONENTS}
        total = float(psi4.variable("SAPT TOTAL ENERGY"))
        scaled = None
        if level == "sapt0" and psi4.core.has_variable("SSAPT0 TOTAL ENERGY"):
            scaled = {
                NAMES[key]: _energies(float(psi4.variable(f"SSAPT0 {key} ENERGY")))
                for key in COMPONENTS
            } | {"total": _energies(float(psi4.variable("SSAPT0 TOTAL ENERGY")))}
        psi4.core.clean()
        psi4.core.be_quiet()
    attractive = {k: -v for k, v in values.items() if k != "EXCH" and v < 0}
    share = {NAMES[k]: round(v / sum(attractive.values()), 4) for k, v in attractive.items()}
    result = {
        "system": name,
        "level": level,
        "basis": basis,
        "components": {NAMES[k]: _energies(v) for k, v in values.items()},
        "total": _energies(total),
        "attractive_share": share,
        "dominant_attraction": max(share, key=share.get) if share else None,
    }
    if scaled:
        result["ssapt0"] = scaled
    if entry:
        result["benchmark"] = {
            "label": entry["label"],
            "reference_kcal_mol": entry["reference_kcal_mol"],
            "reference": entry["reference"],
        }
    return result


def interaction_energy(
    dimer: str | None = None,
    benchmark: str | None = None,
    method: str = "mp2",
    basis: str = "aug-cc-pVDZ",
    counterpoise: bool = True,
    fragment_a_atoms: int | None = None,
    charge_a: int = 0,
    multiplicity_a: int = 1,
    charge_b: int = 0,
    multiplicity_b: int = 1,
    freeze_core: bool = True,
    options: dict | None = None,
    memory_gb: float = 2.0,
    threads: int | None = None,
) -> dict:
    """Supermolecular interaction energy E(AB) - E(A) - E(B) of two molecules.

    Args:
        dimer: XYZ file (Angstrom) of the complex, split by connectivity unless
            fragment_a_atoms is given.
        benchmark: Instead of dimer, "S22-n" or "S66-n" (see benchmark_dimers).
        method: Any Psi4 energy method: "hf", "mp2", "ccsd(t)", "b3lyp-d3bj",
            "wb97x-d", "pbe0-d3bj", ...; or a complete-basis-set recipe with its
            own bases, e.g. "mp2/aug-cc-pv[tq]z + D:ccsd(t)/aug-cc-pvdz" (then
            basis is ignored).
        basis: Orbital basis when method has none.
        counterpoise: Correct the basis-set superposition error (monomers in the
            dimer basis); the uncorrected value is reported too.
        fragment_a_atoms: The first N atoms form molecule A, the rest B.
        charge_a: Charge of molecule A.
        multiplicity_a: Spin multiplicity of molecule A.
        charge_b: Charge of molecule B.
        multiplicity_b: Spin multiplicity of molecule B.
        freeze_core: Exclude core electrons from correlation.
        options: Extra Psi4 options.
        memory_gb: Memory for Psi4 in GB.
        threads: CPU threads (default: all).

    Returns:
        Counterpoise-corrected and uncorrected interaction energies (kcal/mol,
        kJ/mol, hartree; negative is attractive), the basis-set superposition
        error, and, for a benchmark complex, its reference value and the
        deviation from it.
    """
    psi4 = _psi4()
    text, name, entry = _molecule(
        dimer, benchmark, fragment_a_atoms, (charge_a, charge_b), (multiplicity_a, multiplicity_b)
    )
    recipe = method if "/" in method else f"{method}/{basis}"
    with tempfile.TemporaryDirectory(prefix="psi4-") as scratch:
        _setup(memory_gb, threads, scratch)
        molecule = psi4.geometry(text)
        if molecule.nfragments() != 2:
            raise ValueError("The complex must consist of exactly two molecules.")
        settings = {"freeze_core": freeze_core, "scf_type": "df"}
        if multiplicity_a > 1 or multiplicity_b > 1:
            settings["reference"] = "uhf"
        settings.update(options or {})
        psi4.set_options(settings)
        kinds = ["cp", "nocp"] if counterpoise else ["nocp"]
        try:
            psi4.energy(recipe, molecule=molecule, bsse_type=kinds)
        except Exception as exc:
            raise RuntimeError(f"Psi4 {recipe} failed: {exc}") from exc
        nocp = float(psi4.variable("NOCP-CORRECTED INTERACTION ENERGY"))
        cp = float(psi4.variable("CP-CORRECTED INTERACTION ENERGY")) if counterpoise else None
        psi4.core.clean()
        psi4.core.be_quiet()
    best = cp if cp is not None else nocp
    result = {
        "system": name,
        "method": recipe,
        "interaction_energy": _energies(best),
        "counterpoise_corrected": cp is not None,
        "uncorrected": _energies(nocp),
    }
    if cp is not None:
        result["bsse"] = _energies(nocp - cp)
    if entry:
        reference = entry["reference_kcal_mol"]
        result["benchmark"] = {
            "label": entry["label"],
            "reference_kcal_mol": reference,
            "reference": entry["reference"],
            "deviation_kcal_mol": round(result["interaction_energy"]["kcal_mol"] - reference, 4),
        }
    return result


def benchmark_dimers(
    database: Database = "S22", index: int | None = None, output: str | None = None
) -> dict:
    """The S22 or S66 benchmark complexes and their reference interaction energies.

    Args:
        database: "S22" (Jurecka et al. 2006; S22B energies of Marshall et al.
            2011) or "S66" (Rezac et al. 2011).
        index: One complex (1-22 or 1-66); omit to list them all.
        output: With index, write that complex as an XYZ file here.

    Returns:
        For each complex its label (use as benchmark= in sapt and
        interaction_energy), name, and reference CCSD(T)/CBS interaction energy
        in kcal/mol; with index and output, the XYZ file and the number of atoms
        in molecule A.
    """
    module = _database(database)
    if index is None:
        rows = [
            {
                "label": f"{database}-{i}",
                "name": module.TAGL[f"{database}-{i}"],
                "reference_kcal_mol": float(module.BIND[f"{database}-{i}"]),
            }
            for i in module.HRXN
        ]
        return {
            "database": database,
            "reference": _benchmark_entry(f"{database}-1")["reference"],
            "complexes": rows,
        }
    entry = _benchmark_entry(f"{database}-{index}")
    result = {key: entry[key] for key in ("label", "name", "reference_kcal_mol", "reference")}
    if output:
        molecule = entry["molecule"]
        molecule.update_geometry()
        geometry = np.asarray(molecule.geometry()) * _psi4().constants.bohr2angstroms
        symbols = [molecule.symbol(i).capitalize() for i in range(molecule.natom())]
        lines = [str(len(symbols)), f"{entry['label']} {entry['name']}"]
        lines += [
            f"{s} {x:.6f} {y:.6f} {z:.6f}" for s, (x, y, z) in zip(symbols, geometry, strict=True)
        ]
        Path(output).write_text("\n".join(lines) + "\n", encoding="utf-8")
        first = molecule.fragments[0]
        result["xyz"] = output
        result["fragment_a_atoms"] = int(first[1] - first[0] + 1)
    return result
