"""Chemical file conversion, identifiers, force fields, and partial charges with Open Babel.

Molecules can be given as files in any of Open Babel's 140+ formats (format from
the file extension) or as SMILES strings (other line notations with
input_format, e.g. "inchi"). Energies are in kcal/mol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np

ForceField = Literal["MMFF94", "MMFF94s", "UFF", "GAFF", "Ghemical"]
ChargeMethod = Literal["gasteiger", "mmff94", "eem", "qeq", "qtpie", "eqeq"]
KJ_PER_KCAL = 4.184
DEBYE_PER_E_ANGSTROM = 4.803204
#: Molecules described in full in returned lists (files can hold many more).
MAX_LISTED = 100


def _ob():
    from openbabel import openbabel as ob

    ob.obErrorLog.SetOutputLevel(-1)  # keep messages for our errors, print nothing
    return ob


def _last_error(ob) -> str:
    messages = [
        *ob.obErrorLog.GetMessagesOfLevel(ob.obWarning),
        *ob.obErrorLog.GetMessagesOfLevel(ob.obError),
    ]
    lines = [line.strip() for line in "\n".join(messages).splitlines()]
    lines = [line for line in lines if line and not line.startswith(("===", "***"))]
    return lines[-1] if lines else ""


def _format(path: str, given: str | None) -> str:
    if given:
        return given.lower()
    suffixes = Path(path).name.lower().split(".")[1:]
    return suffixes[-1] if suffixes else ""


def _read(molecule: str, input_format: str | None = None) -> list:
    """Molecules from a file, a SMILES string, or another line notation."""
    from openbabel import pybel

    ob = _ob()
    ob.obErrorLog.ClearLog()
    path = Path(molecule).expanduser()
    try:
        if path.is_file():
            fmt = _format(str(path), input_format)
            if fmt not in pybel.informats:
                raise ValueError(
                    f"Open Babel cannot read '.{fmt}' files; pass input_format (see list_formats)."
                )
            molecules = list(pybel.readfile(fmt, str(path)))
        else:
            fmt = (input_format or "smi").lower()
            if fmt not in pybel.informats:
                raise ValueError(f"Unknown input format '{fmt}' (see list_formats).")
            molecules = [pybel.readstring(fmt, molecule.strip())]
    except OSError as exc:
        reason = (_last_error(ob) or str(exc)).rstrip(".")
        raise ValueError(
            f"{molecule!r} is neither a readable file nor a valid {input_format or 'SMILES'} "
            f"string ({reason})."
        ) from exc
    molecules = [mol for mol in molecules if mol.OBMol.NumAtoms() > 0]
    if not molecules:
        raise ValueError(f"No molecules could be read from {molecule!r}.")
    return molecules


def _has_3d(mol) -> bool:
    return mol.OBMol.GetDimension() == 3 and not _all_zero(mol)


def _all_zero(mol) -> bool:
    return not np.any([atom.coords for atom in mol.atoms])


def _ensure_3d(mol) -> bool:
    """Generate 3D coordinates if the molecule has none; True if generated."""
    if _has_3d(mol):
        return False
    mol.make3D(forcefield="mmff94", steps=200)
    return True


def _forcefield(name: str, mol):
    ob = _ob()
    ff = ob.OBForceField.FindForceField(name)
    if ff is None:
        raise ValueError(f"Unknown force field {name}.")
    if not ff.Setup(mol.OBMol):
        raise ValueError(
            f"{name} has no parameters for {mol.formula} (atom types missing); try UFF, "
            "which covers the whole periodic table."
        )
    return ff


def _to_kcal(ff) -> float:
    return 1 / KJ_PER_KCAL if ff.GetUnit().startswith("kJ") else 1.0


def _terms(ff, name: str) -> dict:
    scale = _to_kcal(ff)
    terms = {
        "bond_stretching": ff.E_Bond(False),
        "angle_bending": ff.E_Angle(False),
        "torsion": ff.E_Torsion(False),
        "out_of_plane": ff.E_OOP(False),
        "van_der_waals": ff.E_VDW(False),
        "electrostatic": ff.E_Electrostatic(False),
    }
    if name.startswith("MMFF94"):
        terms["stretch_bend"] = ff.E_StrBnd(False)
    return {key: float(value * scale) for key, value in terms.items()}


def list_formats() -> dict:
    """File formats Open Babel can read and write.

    Returns:
        Input and output formats (extension: description).
    """
    from openbabel import pybel

    return {
        "input_formats": dict(sorted(pybel.informats.items())),
        "output_formats": dict(sorted(pybel.outformats.items())),
    }


def identifiers(molecule: str, input_format: str | None = None) -> dict:
    """Canonical SMILES, InChI, InChIKey, formula, and masses of molecules.

    Args:
        molecule: SMILES string or molecule file (SDF, MOL2, PDB, XYZ, CIF, ...).
        input_format: Format of the file or string if not clear from the
            extension, e.g. "inchi" for an InChI string.

    Returns:
        For each molecule (up to 100 listed): title, formula, molecular weight
        (g/mol), monoisotopic mass, total charge, spin multiplicity, atom counts,
        canonical SMILES, InChI, and InChIKey; and the number of molecules.
    """
    molecules = _read(molecule, input_format)
    rows = []
    for mol in molecules[:MAX_LISTED]:
        rows.append(
            {
                "title": mol.title,
                "formula": mol.formula,
                "molecular_weight": float(mol.molwt),
                "exact_mass": float(mol.exactmass),
                "charge": int(mol.charge),
                "spin_multiplicity": int(mol.spin),
                "n_atoms": int(mol.OBMol.NumAtoms()),
                "n_heavy_atoms": int(mol.OBMol.NumHvyAtoms()),
                "canonical_smiles": mol.write("can").split("\t")[0].strip(),
                "inchi": mol.write("inchi").strip(),
                "inchikey": mol.write("inchikey").strip(),
            }
        )
    return {"molecules": rows, "n_molecules": len(molecules)}


def convert(
    molecule: str,
    output: str,
    input_format: str | None = None,
    output_format: str | None = None,
    hydrogens: Literal["keep", "add", "remove", "ph"] = "keep",
    ph: float = 7.4,
    coordinates: Literal["keep", "3d", "2d"] = "keep",
    fill_unit_cell: bool = False,
) -> dict:
    """Convert molecules or crystal structures between file formats.

    Args:
        molecule: Input file in any supported format, or a SMILES string.
        output: Output file; its extension sets the format (e.g. "out.sdf",
            "ligand.mol2", "mol.xyz", "frame.pdb", "input.gjf" for Gaussian,
            "mol.orcainp" for ORCA, "ligand.pdbqt" for AutoDock, "cell.cif").
        input_format: Input format if not clear from the extension.
        output_format: Output format if not clear from the extension.
        hydrogens: "keep", "add" (all hydrogens), "remove", or "ph" (protonation
            state for the given pH, from Open Babel's rule-based pKa model).
        ph: pH for hydrogens="ph".
        coordinates: "keep", "3d" (generate a 3D structure with MMFF94; needed when
            converting SMILES to 3D formats), or "2d" (2D layout for drawing).
        fill_unit_cell: Expand a CIF's asymmetric unit to the full unit cell with
            its space-group symmetry.

    Returns:
        The output file, the number of molecules written, the formats used, and
        the canonical SMILES and atom count of the first molecules.
    """
    from openbabel import pybel

    ob = _ob()
    fmt = _format(output, output_format)
    if fmt not in pybel.outformats:
        raise ValueError(f"Open Babel cannot write '{fmt}'; pass output_format (see list_formats).")
    molecules = _read(molecule, input_format)
    written = []
    with pybel.Outputfile(fmt, output, overwrite=True) as handle:
        for mol in molecules:
            if fill_unit_cell:
                if mol.OBMol.GetData(ob.UnitCell) is None:
                    raise ValueError("fill_unit_cell needs a crystal structure with a unit cell.")
                ob.OBOp.FindType("fillUC").Do(mol.OBMol, "strict")
            if hydrogens == "remove":
                mol.removeh()
            elif hydrogens == "add":
                mol.addh()
            elif hydrogens == "ph":
                mol.OBMol.CorrectForPH(ph)
                mol.addh()
            if coordinates == "3d":
                mol.make3D(forcefield="mmff94", steps=200)
            elif coordinates == "2d":
                ob.OBOp.FindType("gen2D").Do(mol.OBMol)
            handle.write(mol)
            written.append(mol)
    return {
        "output": output,
        "output_format": fmt,
        "n_molecules": len(written),
        "molecules": [
            {
                "canonical_smiles": mol.write("can").split("\t")[0].strip(),
                "formula": mol.formula,
                "n_atoms": int(mol.OBMol.NumAtoms()),
            }
            for mol in written[:MAX_LISTED]
        ],
    }


def energy(
    molecule: str,
    forcefield: ForceField = "MMFF94",
    input_format: str | None = None,
) -> dict:
    """Force-field energy of molecules at their given geometry (no optimization).

    Args:
        molecule: Molecule file with 3D coordinates, or a SMILES string (a 3D
            structure is generated first).
        forcefield: "MMFF94" (default; organic and drug-like molecules), "MMFF94s"
            (planar amide nitrogens, for conformer comparisons), "UFF" (all
            elements, including metals), "GAFF", or "Ghemical".
        input_format: Format if not clear from the extension.

    Returns:
        For each molecule (up to 100 listed): total energy and its terms in
        kcal/mol (bond, angle, stretch-bend for MMFF94, torsion, out-of-plane,
        van der Waals, electrostatic), and whether coordinates were generated.
    """
    rows = []
    for mol in _read(molecule, input_format)[:MAX_LISTED]:
        generated = _ensure_3d(mol)
        ff = _forcefield(forcefield, mol)
        rows.append(
            {
                "title": mol.title,
                "formula": mol.formula,
                "energy_kcal_mol": float(ff.Energy(False) * _to_kcal(ff)),
                "terms_kcal_mol": _terms(ff, forcefield),
                "coordinates_generated": generated,
            }
        )
    return {"forcefield": forcefield, "molecules": rows, "n_molecules": len(rows)}


def minimize(
    molecule: str,
    forcefield: ForceField = "MMFF94",
    steps: int = 5000,
    convergence: float = 1e-7,
    output: str = "minimized.sdf",
    input_format: str | None = None,
) -> dict:
    """Minimize molecules with a force field (conjugate gradients) and save them.

    Args:
        molecule: Molecule file or SMILES string (a 3D structure is generated).
        forcefield: Force field, see energy.
        steps: Maximum number of optimization steps.
        convergence: Energy change (kcal/mol) between steps at which to stop.
        output: Output file for the minimized molecules (format from extension).
        input_format: Format if not clear from the extension.

    Returns:
        For each molecule (up to 100 listed): energy before and after
        (kcal/mol), heavy-atom RMSD between start and minimum (Angstrom), and the
        output file.
    """
    from openbabel import pybel

    if steps < 1 or convergence <= 0:
        raise ValueError("steps and convergence must be positive.")
    molecules = _read(molecule, input_format)
    rows = []
    with pybel.Outputfile(_format(output, None), output, overwrite=True) as handle:
        for mol in molecules:
            _ensure_3d(mol)
            ff = _forcefield(forcefield, mol)
            scale = _to_kcal(ff)
            start = np.array([atom.coords for atom in mol.atoms])
            before = ff.Energy(False) * scale
            ff.ConjugateGradients(steps, convergence / scale)
            ff.GetCoordinates(mol.OBMol)
            end = np.array([atom.coords for atom in mol.atoms])
            heavy = np.array([atom.atomicnum > 1 for atom in mol.atoms])
            rmsd = (
                float(np.sqrt(((start - end)[heavy] ** 2).sum(axis=1).mean()))
                if heavy.any()
                else 0.0
            )
            handle.write(mol)
            if len(rows) < MAX_LISTED:
                rows.append(
                    {
                        "title": mol.title,
                        "formula": mol.formula,
                        "initial_energy_kcal_mol": float(before),
                        "final_energy_kcal_mol": float(ff.Energy(False) * scale),
                        "heavy_atom_rmsd_angstrom": rmsd,
                    }
                )
    return {
        "forcefield": forcefield,
        "molecules": rows,
        "n_molecules": len(molecules),
        "output": output,
    }


def partial_charges(
    molecule: str,
    method: ChargeMethod = "gasteiger",
    input_format: str | None = None,
) -> dict:
    """Atomic partial charges and the dipole moment they give.

    Args:
        molecule: Molecule file or SMILES string (for the dipole a 3D structure is
            generated if needed).
        method: "gasteiger" (Gasteiger-Marsili; fast, topology only), "mmff94"
            (MMFF94 bond-charge increments), "eem" (electronegativity equalization,
            fitted to B3LYP Mulliken charges), "qeq" or "qtpie" (charge
            equilibration), or "eqeq" (for crystals and MOFs).
        input_format: Format if not clear from the extension.

    Returns:
        For the first molecule: the element and partial charge of each atom, the
        total charge, and the dipole moment (Debye) from the charges and 3D
        coordinates; and the number of molecules read.
    """
    ob = _ob()
    molecules = _read(molecule, input_format)
    mol = molecules[0]
    _ensure_3d(mol)
    model = ob.OBChargeModel.FindType(method)
    if model is None or not model.ComputeCharges(mol.OBMol):
        raise ValueError(f"Could not assign {method} charges to {mol.formula}.")
    charges = [float(q) for q in model.GetPartialCharges()]
    coordinates = np.array([atom.coords for atom in mol.atoms])
    dipole = (np.array(charges)[:, None] * coordinates).sum(axis=0) * DEBYE_PER_E_ANGSTROM
    return {
        "method": method,
        "formula": mol.formula,
        "elements": [ob.GetSymbol(atom.atomicnum) for atom in mol.atoms],
        "charges": charges,
        "total_charge": float(sum(charges)),
        "dipole_debye": float(np.linalg.norm(dipole)) if round(sum(charges), 6) == 0 else None,
        "n_molecules": len(molecules),
    }
