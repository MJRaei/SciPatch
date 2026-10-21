"""GFN2-xTB quantum chemistry for molecules, via the xtb program.

Molecules can be given as SMILES (a 3D structure is generated with RDKit) or as
a structure file that xtb reads directly (XYZ, Turbomole coord, SDF/MOL, PDB).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import numpy as np

Method = Literal["gfn2", "gfn1", "gfnff"]
SolvationModel = Literal["alpb", "gbsa"]
OptimizationLevel = Literal["crude", "sloppy", "loose", "normal", "tight", "vtight", "extreme"]

HARTREE_TO_EV = 27.211386245988
AU_DIPOLE_TO_DEBYE = 2.541746473
_ENERGY = re.compile(r"\|\s*TOTAL ENERGY\s+(-?\d+\.\d+)\s+Eh")
_GAP = re.compile(r"\|\s*HOMO-LUMO GAP\s+(-?\d+\.\d+)\s+eV")
_ENTHALPY = re.compile(r"\|\s*TOTAL ENTHALPY\s+(-?\d+\.\d+)\s+Eh")
_FREE_ENERGY = re.compile(r"\|\s*TOTAL FREE ENERGY\s+(-?\d+\.\d+)\s+Eh")
_ZPE = re.compile(r"::\s*zero point energy\s+(-?\d+\.\d+)\s+Eh")
_IMAGINARY = re.compile(r"#\s*imaginary freq\.\s+(\d+)")


def _last(pattern: re.Pattern, text: str) -> float | None:
    matches = pattern.findall(text)
    return float(matches[-1]) if matches else None


def _prepare(molecule: str, seed: int = 42) -> tuple[Path, int | None, str]:
    """Return an input file for xtb, the formal charge from SMILES, and the formula."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem, rdMolDescriptors

    RDLogger.DisableLog("rdApp.*")
    path = Path(molecule)
    if path.is_file():
        target = Path("input" + "".join(path.suffixes) if path.suffix else "coord")
        shutil.copyfile(path, target)
        return target, None, ""
    rdmol = Chem.MolFromSmiles(molecule)
    if rdmol is None:
        raise ValueError(f"'{molecule}' is neither a file nor a valid SMILES string.")
    rdmol = Chem.AddHs(rdmol)
    parameters = AllChem.ETKDGv3()
    parameters.randomSeed = seed
    if AllChem.EmbedMolecule(rdmol, parameters) != 0:
        raise ValueError("Could not generate 3D coordinates for this molecule.")
    if AllChem.MMFFHasAllMoleculeParams(rdmol):
        AllChem.MMFFOptimizeMolecule(rdmol, maxIters=2000)
    target = Path("input.xyz")
    Chem.MolToXYZFile(rdmol, str(target))
    return target, Chem.GetFormalCharge(rdmol), rdMolDescriptors.CalcMolFormula(rdmol)


def _arguments(
    method: str, charge: int, unpaired: int, solvent: str | None, model: str
) -> list[str]:
    args = ["--gfnff"] if method == "gfnff" else ["--gfn", method.removeprefix("gfn")]
    args += ["--chrg", str(charge), "--uhf", str(unpaired), "--json"]
    if solvent:
        args += [f"--{model}", solvent]
    return args


def _run(input_file: Path, args: list[str]) -> tuple[str, dict]:
    completed = subprocess.run(
        ["xtb", str(input_file), *args], capture_output=True, text=True, check=False
    )
    output = completed.stdout + completed.stderr
    Path("xtb.out").write_text(output, encoding="utf-8")
    if completed.returncode != 0 or "abnormal termination" in output:
        tail = "\n".join(output.splitlines()[-15:])
        raise RuntimeError(f"xtb failed (exit code {completed.returncode}):\n{tail}")
    try:
        data = json.loads(Path("xtbout.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    return output, data


def _electronic(output: str, data: dict) -> dict:
    energy = _last(_ENERGY, output)
    gap = _last(_GAP, output)
    dipole = data.get("dipole / a.u.")
    charges = data.get("partial charges")
    return {
        "energy_hartree": energy,
        "energy_ev": None if energy is None else energy * HARTREE_TO_EV,
        "homo_lumo_gap_ev": gap,
        "dipole_debye": None
        if dipole is None
        else float(np.linalg.norm(dipole)) * AU_DIPOLE_TO_DEBYE,
        "partial_charges": charges,
    }


def _setup(molecule: str, charge: int | None, seed: int = 42) -> tuple[Path, int, str]:
    input_file, smiles_charge, formula = _prepare(molecule, seed)
    if charge is None:
        charge = smiles_charge or 0
    return input_file, charge, formula


def single_point(
    molecule: str,
    charge: int | None = None,
    unpaired_electrons: int = 0,
    method: Method = "gfn2",
    solvent: str | None = None,
    solvation_model: SolvationModel = "alpb",
) -> dict:
    """Compute the energy, HOMO-LUMO gap, dipole moment, and partial charges of a molecule.

    Args:
        molecule: SMILES string (3D coordinates are generated) or a structure file
            (XYZ, Turbomole coord, SDF/MOL, PDB) used as is.
        charge: Total charge. Default: the formal charge in the SMILES, or 0 for files.
        unpaired_electrons: Number of unpaired electrons (0 for a closed-shell singlet).
        method: "gfn2" (default, GFN2-xTB), "gfn1" (GFN1-xTB), or "gfnff" (force field).
        solvent: Implicit solvent name such as "water", "methanol", "dmso", "toluene";
            None for the gas phase.
        solvation_model: "alpb" (recommended) or "gbsa".

    Returns:
        Total energy (Hartree and eV), HOMO-LUMO gap (eV), dipole moment (Debye),
        partial charges (e), the charge and settings used, and the input structure.
    """
    input_file, charge, formula = _setup(molecule, charge)
    output, data = _run(
        input_file, _arguments(method, charge, unpaired_electrons, solvent, solvation_model)
    )
    return {
        "formula": formula or None,
        "n_atoms": len(data.get("partial charges") or []) or None,
        "charge": charge,
        "unpaired_electrons": unpaired_electrons,
        "method": method,
        "solvent": solvent,
        **_electronic(output, data),
        "input_structure": str(input_file),
    }


def optimize(
    molecule: str,
    charge: int | None = None,
    unpaired_electrons: int = 0,
    method: Method = "gfn2",
    solvent: str | None = None,
    solvation_model: SolvationModel = "alpb",
    level: OptimizationLevel = "normal",
    seed: int = 42,
) -> dict:
    """Optimize a molecule's geometry, then report its energy and properties.

    Args:
        molecule: SMILES string or a structure file (see single_point).
        charge: Total charge. Default: the formal charge in the SMILES, or 0 for files.
        unpaired_electrons: Number of unpaired electrons.
        method: "gfn2", "gfn1", or "gfnff".
        solvent: Implicit solvent name, or None for the gas phase.
        solvation_model: "alpb" or "gbsa".
        level: Convergence level, from "crude" to "extreme" ("tight" before frequencies).
        seed: Random seed for generating 3D coordinates from SMILES.

    Returns:
        Final energy (Hartree and eV), HOMO-LUMO gap (eV), dipole (Debye), partial
        charges, whether the optimization converged, and the optimized structure path.
    """
    input_file, charge, formula = _setup(molecule, charge, seed)
    args = _arguments(method, charge, unpaired_electrons, solvent, solvation_model)
    output, data = _run(input_file, [*args, "--opt", level])
    produced = _optimized_structure()
    return {
        "formula": formula or None,
        "n_atoms": len(data.get("partial charges") or []) or None,
        "charge": charge,
        "method": method,
        "solvent": solvent,
        **_electronic(output, data),
        "converged": "GEOMETRY OPTIMIZATION CONVERGED" in output,
        "optimized_structure": str(produced[0]) if produced else None,
    }


def _optimized_structure() -> list[Path]:
    """The final optimized geometry (not the xtbopt.log trajectory)."""
    return sorted(p for p in Path().glob("xtbopt.*") if p.suffix != ".log")


def _coordinates(structure: Path) -> np.ndarray | None:
    """Cartesian coordinates from an XYZ or Turbomole coord file (None for other formats)."""
    lines = structure.read_text().splitlines()
    if structure.suffix == ".xyz":
        rows = [line.split()[1:4] for line in lines[2:] if line.strip()]
    elif lines and lines[0].strip().startswith("$coord"):
        rows = []
        for line in lines[1:]:
            if line.strip().startswith("$"):
                break
            rows.append(line.split()[:3])
    else:
        return None
    return np.array([[float(value) for value in row] for row in rows])


def _vibrations(frequencies: list[float], structure: Path) -> list[float]:
    """Drop the 6 (5 for linear molecules) translations and rotations."""
    coordinates = _coordinates(structure)
    linear = coordinates is not None and (
        len(coordinates) < 3 or np.linalg.svd(coordinates - coordinates.mean(0))[1][1] < 1e-3
    )
    ordered = sorted(frequencies, key=abs)
    return sorted(ordered[5 if linear else 6 :])


def frequencies(
    molecule: str,
    charge: int | None = None,
    unpaired_electrons: int = 0,
    method: Method = "gfn2",
    solvent: str | None = None,
    solvation_model: SolvationModel = "alpb",
    optimize_first: bool = True,
    seed: int = 42,
) -> dict:
    """Vibrational frequencies, IR intensities, and thermochemistry at 298.15 K and 1 atm.

    Frequencies are only meaningful at a stationary point, so by default the
    geometry is optimized (tightly) first.

    Args:
        molecule: SMILES string or a structure file (see single_point).
        charge: Total charge. Default: the formal charge in the SMILES, or 0 for files.
        unpaired_electrons: Number of unpaired electrons.
        method: "gfn2", "gfn1", or "gfnff".
        solvent: Implicit solvent name, or None for the gas phase.
        solvation_model: "alpb" or "gbsa".
        optimize_first: Optimize the geometry before the frequency calculation.
        seed: Random seed for generating 3D coordinates from SMILES.

    Returns:
        Vibrational frequencies (cm⁻¹, imaginary ones negative) with IR intensities
        (km/mol), the number of imaginary frequencies, zero-point energy, enthalpy and
        Gibbs free energy (Hartree), the electronic energy (Hartree), and, if
        optimized, the optimized structure path.
    """
    input_file, charge, formula = _setup(molecule, charge, seed)
    args = _arguments(method, charge, unpaired_electrons, solvent, solvation_model)
    output, data = _run(input_file, [*args, "--ohess" if optimize_first else "--hess"])
    produced = _optimized_structure()
    geometry = produced[0] if produced else input_file
    all_frequencies = data.get("vibrational frequencies / rcm") or []
    intensities = data.get("IR intensities / km/mol") or []
    vibrations = _vibrations(all_frequencies, geometry)
    ir = {round(f, 4): i for f, i in zip(all_frequencies, intensities, strict=False)}
    return {
        "formula": formula or None,
        "charge": charge,
        "method": method,
        "solvent": solvent,
        "energy_hartree": _last(_ENERGY, output),
        "frequencies_cm1": vibrations,
        "ir_intensities_km_mol": [ir.get(round(f, 4)) for f in vibrations],
        "imaginary_frequencies": int(_last(_IMAGINARY, output) or 0),
        "zero_point_energy_hartree": _last(_ZPE, output),
        "enthalpy_hartree": _last(_ENTHALPY, output),
        "free_energy_hartree": _last(_FREE_ENERGY, output),
        "optimized_structure": str(produced[0]) if produced else None,
    }
