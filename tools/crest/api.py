"""Conformer, protomer, and tautomer searches with CREST and GFN-xTB.

Molecules can be given as SMILES (a 3D starting structure is generated with
RDKit) or as an XYZ file. Energies are GFN2-xTB (or GFN-FF) energies; relative
energies are in kcal/mol.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Literal

import numpy as np

Method = Literal["gfn2", "gfnff", "gfn2//gfnff"]
Mode = Literal["normal", "quick", "squick", "mquick"]

HARTREE_TO_KCAL = 627.509474
KT_KCAL_298 = 0.0019872043 * 298.15


def _prepare(molecule: str, seed: int = 42) -> tuple[Path, int | None, int | None]:
    """An XYZ start structure, plus the charge and radical count from a SMILES."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem

    RDLogger.DisableLog("rdApp.*")
    path = Path(molecule)
    if path.is_file():
        if path.suffix.lower() != ".xyz":
            raise ValueError("Give a SMILES string or an XYZ file.")
        target = Path("input.xyz")
        target.write_text(path.read_text())
        return target, None, None
    rdmol = Chem.MolFromSmiles(molecule)
    if rdmol is None:
        raise ValueError(f"'{molecule}' is neither an XYZ file nor a valid SMILES string.")
    rdmol = Chem.AddHs(rdmol)
    parameters = AllChem.ETKDGv3()
    parameters.randomSeed = seed
    if AllChem.EmbedMolecule(rdmol, parameters) != 0:
        raise ValueError("Could not generate 3D coordinates for this molecule.")
    if AllChem.MMFFHasAllMoleculeParams(rdmol):
        AllChem.MMFFOptimizeMolecule(rdmol, maxIters=2000)
    target = Path("input.xyz")
    Chem.MolToXYZFile(rdmol, str(target))
    radicals = sum(atom.GetNumRadicalElectrons() for atom in rdmol.GetAtoms())
    return target, Chem.GetFormalCharge(rdmol), radicals


def _run_crest(arguments: list[str]) -> str:
    threads = str(os.cpu_count() or 1)
    completed = subprocess.run(
        ["crest", *arguments, "-T", threads], capture_output=True, text=True, check=False
    )
    output = completed.stdout + completed.stderr
    Path("crest.out").write_text(output, encoding="utf-8")
    if completed.returncode != 0 or "CREST terminated normally" not in output:
        tail = "\n".join(output.splitlines()[-15:])
        raise RuntimeError(f"CREST failed (exit code {completed.returncode}):\n{tail}")
    return output


def _common(
    method: Method,
    charge: int,
    unpaired: int,
    solvent: str | None,
    window: float,
) -> list[str]:
    args = {"gfn2": ["--gfn2"], "gfnff": ["--gfnff"], "gfn2//gfnff": ["--gfn2//gfnff"]}[method]
    args += ["--chrg", str(charge), "--uhf", str(unpaired), "--ewin", f"{window:.4f}"]
    if solvent:
        args += ["--alpb", solvent]
    return args


def _read_ensemble(path: str) -> list[tuple[float, list[str], np.ndarray]]:
    """(energy in Hartree, element symbols, coordinates) for each structure in an XYZ file."""
    lines = Path(path).read_text().splitlines()
    structures = []
    i = 0
    while i < len(lines) and lines[i].strip():
        n = int(lines[i])
        energy = float(lines[i + 1].split()[0])
        rows = [line.split() for line in lines[i + 2 : i + 2 + n]]
        symbols = [row[0].capitalize() for row in rows]
        coordinates = np.array([[float(v) for v in row[1:4]] for row in rows])
        structures.append((energy, symbols, coordinates))
        i += n + 2
    return structures


def _relative(energies: list[float]) -> tuple[list[float], list[float]]:
    """Relative energies (kcal/mol) and Boltzmann populations at 298.15 K."""
    lowest = min(energies)
    relative = [(e - lowest) * HARTREE_TO_KCAL for e in energies]
    weights = np.exp(-np.array(relative) / KT_KCAL_298)
    return relative, (weights / weights.sum()).tolist()


def _smiles(symbols: list[str], coordinates: np.ndarray, charge: int) -> str | None:
    """SMILES perceived from 3D coordinates (None if the bonding is ambiguous)."""
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds

    block = f"{len(symbols)}\n\n" + "\n".join(
        f"{s} {x:.6f} {y:.6f} {z:.6f}" for s, (x, y, z) in zip(symbols, coordinates, strict=True)
    )
    try:
        mol = Chem.MolFromXYZBlock(block)
        rdDetermineBonds.DetermineBonds(mol, charge=charge)
        return Chem.MolToSmiles(Chem.RemoveHs(mol))
    except Exception:  # bond perception can fail for unusual structures
        return None


def conformer_search(
    molecule: str,
    method: Method = "gfn2",
    charge: int | None = None,
    unpaired_electrons: int | None = None,
    solvent: str | None = None,
    energy_window_kcal_mol: float = 6.0,
    mode: Mode = "normal",
) -> dict:
    """Find the low-energy conformers of a molecule (CREST iMTD-GC metadynamics search).

    Args:
        molecule: SMILES (a 3D start structure is generated) or an XYZ file.
        method: "gfn2" (GFN2-xTB; default), "gfnff" (force field; fast, for large
            molecules), or "gfn2//gfnff" (sampling with GFN-FF, energies with GFN2).
        charge: Total charge. Default: from the SMILES, or 0 for files.
        unpaired_electrons: Number of unpaired electrons. Default: radicals in the
            SMILES, or 0.
        solvent: Implicit solvent (ALPB) such as "water", "methanol", "dmso",
            "toluene"; None for the gas phase.
        energy_window_kcal_mol: Keep conformers up to this energy above the lowest.
        mode: Thoroughness: "normal" (default), "quick", "squick", or "mquick"
            (fastest, roughest).

    Returns:
        The number of conformers, their relative energies (kcal/mol) and Boltzmann
        populations at 298.15 K (rotamer degeneracy not counted), the lowest
        energy (Hartree), and the ensemble and best-structure XYZ files.
    """
    start, smiles_charge, smiles_unpaired = _prepare(molecule)
    charge = (smiles_charge or 0) if charge is None else charge
    unpaired = (smiles_unpaired or 0) if unpaired_electrons is None else unpaired_electrons
    args = [str(start), *_common(method, charge, unpaired, solvent, energy_window_kcal_mol)]
    if mode != "normal":
        args.append(f"--{mode}")
    _run_crest(args)
    ensemble = _read_ensemble("crest_conformers.xyz")
    relative, populations = _relative([energy for energy, _, _ in ensemble])
    return {
        "method": method,
        "charge": charge,
        "solvent": solvent,
        "n_conformers": len(ensemble),
        "relative_energies_kcal_mol": relative,
        "populations": populations,
        "lowest_energy_hartree": min(energy for energy, _, _ in ensemble),
        "conformers_file": "crest_conformers.xyz",
        "best_structure": "crest_best.xyz",
    }


def _site_search(
    molecule: str,
    flag: str,
    output: str,
    method: Method,
    charge: int | None,
    solvent: str | None,
    window: float,
    charge_change: int,
) -> dict:
    start, smiles_charge, _ = _prepare(molecule)
    charge = (smiles_charge or 0) if charge is None else charge
    _run_crest([str(start), flag, *_common(method, charge, 0, solvent, window)])
    reference = _read_ensemble_input(start)
    structures = _read_ensemble(output)
    relative, populations = _relative([energy for energy, _, _ in structures])
    new_charge = charge + charge_change
    items = []
    for (energy, symbols, coordinates), rel, population in zip(
        structures, relative, populations, strict=True
    ):
        item: dict[str, Any] = {
            "relative_energy_kcal_mol": rel,
            "population": population,
            "energy_hartree": energy,
            "smiles": _smiles(symbols, coordinates, new_charge),
        }
        if charge_change:
            item["site"] = _site(reference, symbols, coordinates, charge_change)
        items.append(item)
    return {"charge": new_charge, "n_structures": len(items), "structures": items, "file": output}


def _read_ensemble_input(path: Path) -> tuple[list[str], np.ndarray]:
    lines = path.read_text().splitlines()
    n = int(lines[0])
    rows = [line.split() for line in lines[2 : 2 + n]]
    return [r[0].capitalize() for r in rows], np.array([[float(v) for v in r[1:4]] for r in rows])


def _site(
    reference: tuple[list[str], np.ndarray],
    symbols: list[str],
    coordinates: np.ndarray,
    change: int,
) -> str | None:
    """The heavy atom that gained (or lost) a proton, as e.g. "N4" (1-based index)."""
    ref_symbols, ref_xyz = reference
    if change > 0:
        hydrogen = len(symbols) - 1  # CREST appends the added proton
        heavy = [i for i, s in enumerate(symbols) if s != "H"]
        nearest = min(heavy, key=lambda i: np.linalg.norm(coordinates[i] - coordinates[hydrogen]))
        return f"{symbols[nearest]}{nearest + 1}"

    # Deprotonation: the input heavy atom that now has one hydrogen fewer nearby.
    def hydrogens(sym: list[str], xyz: np.ndarray, atom: int) -> int:
        return sum(
            1 for j, s in enumerate(sym) if s == "H" and np.linalg.norm(xyz[j] - xyz[atom]) < 1.25
        )

    for i, s in enumerate(ref_symbols):
        if (
            s != "H"
            and i < len(symbols)
            and hydrogens(symbols, coordinates, i) < hydrogens(ref_symbols, ref_xyz, i)
        ):
            return f"{s}{i + 1}"
    return None


def protonation_sites(
    molecule: str,
    method: Method = "gfn2",
    charge: int | None = None,
    solvent: str | None = None,
    energy_window_kcal_mol: float = 30.0,
) -> dict:
    """Where a molecule is most likely protonated: protomers ranked by energy.

    Args:
        molecule: SMILES or an XYZ file of the neutral (or given-charge) molecule.
        method: "gfn2" (default) or "gfnff".
        charge: Charge before protonation. Default: from the SMILES, or 0.
        solvent: Implicit solvent (ALPB), e.g. "water"; gas phase if None.
        energy_window_kcal_mol: Keep protomers up to this energy above the lowest.

    Returns:
        The protomers' charge, and for each protomer the protonated atom (e.g.
        "N4", 1-based index in the input), relative energy (kcal/mol), population,
        energy (Hartree), and SMILES; plus the XYZ file of all protomers.
    """
    return _site_search(
        molecule, "--protonate", "protonated.xyz", method, charge, solvent,
        energy_window_kcal_mol, +1,
    )  # fmt: skip


def deprotonation_sites(
    molecule: str,
    method: Method = "gfn2",
    charge: int | None = None,
    solvent: str | None = None,
    energy_window_kcal_mol: float = 30.0,
) -> dict:
    """Which proton a molecule most likely loses: deprotomers ranked by energy.

    Args:
        molecule: SMILES or an XYZ file.
        method: "gfn2" (default) or "gfnff".
        charge: Charge before deprotonation. Default: from the SMILES, or 0.
        solvent: Implicit solvent (ALPB), e.g. "water" (recommended for anions).
        energy_window_kcal_mol: Keep deprotomers up to this energy above the lowest.

    Returns:
        The deprotomers' charge, and for each one the deprotonated atom, relative
        energy (kcal/mol), population, energy (Hartree), and SMILES; plus the XYZ file.
    """
    return _site_search(
        molecule, "--deprotonate", "deprotonated.xyz", method, charge, solvent,
        energy_window_kcal_mol, -1,
    )  # fmt: skip


def tautomers(
    molecule: str,
    method: Method = "gfn2",
    charge: int | None = None,
    solvent: str | None = None,
    energy_window_kcal_mol: float = 30.0,
) -> dict:
    """Tautomers of a molecule (proton shifts), ranked by energy.

    Args:
        molecule: SMILES or an XYZ file.
        method: "gfn2" (default) or "gfnff".
        charge: Total charge. Default: from the SMILES, or 0.
        solvent: Implicit solvent (ALPB); tautomer equilibria often depend strongly on it.
        energy_window_kcal_mol: Keep tautomers up to this energy above the lowest.

    Returns:
        For each tautomer: SMILES, relative energy (kcal/mol), population at
        298.15 K, and energy (Hartree); plus the XYZ file of all tautomers.
    """
    return _site_search(
        molecule, "--tautomerize", "tautomers.xyz", method, charge, solvent,
        energy_window_kcal_mol, 0,
    )  # fmt: skip
