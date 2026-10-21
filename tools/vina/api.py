"""Protein-ligand docking with AutoDock Vina.

Receptors are given as PDB files with hydrogens (converted to rigid PDBQT with
Open Babel) or as prepared PDBQT files. Ligands are given as SMILES (a 3D
conformer is generated) or SDF/MOL/MOL2 files, and prepared with Meeko. Affinities
are Vina scores in kcal/mol; distances are in Angstrom.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Literal

import numpy as np

Scoring = Literal["vina", "vinardo"]


def _receptor(path: str, output: str) -> str:
    """A rigid receptor PDBQT: the file itself, or converted from PDB with Open Babel."""
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"No such receptor file: {path}")
    if source.suffix.lower() == ".pdbqt":
        return str(source)
    if source.suffix.lower() not in (".pdb", ".ent"):
        raise ValueError("The receptor must be a PDB file (with hydrogens) or a PDBQT file.")
    from openbabel import openbabel as ob
    from openbabel import pybel

    ob.obErrorLog.SetOutputLevel(-1)
    molecule = next(pybel.readfile("pdb", str(source)))
    if not any(atom.atomicnum == 1 for atom in molecule.atoms):
        raise ValueError(
            "The receptor PDB has no hydrogens. Add them first (e.g. with PDBFixer, reduce, "
            "or Open Babel for a pH), so polar hydrogens can be typed."
        )
    conversion = ob.OBConversion()
    conversion.SetOutFormat("pdbqt")
    conversion.AddOption("r", ob.OBConversion.OUTOPTIONS)  # rigid: no torsion tree
    conversion.AddOption("x", ob.OBConversion.OUTOPTIONS)  # no ROOT/BRANCH records
    conversion.WriteFile(molecule.OBMol, output)
    conversion.CloseOutFile()
    return output


def _rdkit_ligand(ligand: str, seed: int):
    from rdkit import Chem
    from rdkit.Chem import AllChem

    path = Path(ligand)
    if path.is_file():
        suffix = path.suffix.lower()
        if suffix in (".sdf", ".mol"):
            molecule = Chem.MolFromMolFile(str(path), removeHs=False)
        elif suffix == ".mol2":
            molecule = Chem.MolFromMol2File(str(path), removeHs=False)
        else:
            raise ValueError("Ligand files must be SDF, MOL, or MOL2 (or give a SMILES string).")
        if molecule is None:
            raise ValueError(f"RDKit could not read the ligand in {ligand}.")
        if all(atom.GetAtomicNum() != 1 for atom in molecule.GetAtoms()):
            molecule = Chem.AddHs(molecule, addCoords=True)
        return molecule, False
    molecule = Chem.MolFromSmiles(ligand)
    if molecule is None:
        raise ValueError(f"{ligand!r} is neither a ligand file nor a valid SMILES string.")
    molecule = Chem.AddHs(molecule)
    if AllChem.EmbedMolecule(molecule, randomSeed=seed) != 0:
        raise ValueError("Could not generate a 3D structure for the ligand.")
    AllChem.MMFFOptimizeMolecule(molecule)
    return molecule, True


def _ligand_pdbqt(molecule) -> str:
    from meeko import MoleculePreparation, PDBQTWriterLegacy

    setups = MoleculePreparation().prepare(molecule)
    pdbqt, ok, error = PDBQTWriterLegacy.write_string(setups[0])
    if not ok:
        raise ValueError(f"Meeko could not prepare the ligand: {error}")
    return pdbqt


def _box(center, size, box_from_ligand: str | None, padding: float):
    if box_from_ligand:
        from rdkit import Chem

        reference = (
            Chem.MolFromMolFile(box_from_ligand)
            if box_from_ligand.endswith((".sdf", ".mol"))
            else None
        )
        if reference is None:
            raise ValueError(
                "box_from_ligand must be an SDF or MOL file of a ligand in the pocket."
            )
        coordinates = reference.GetConformer().GetPositions()
        low, high = coordinates.min(axis=0), coordinates.max(axis=0)
        return ((low + high) / 2).tolist(), (high - low + 2 * padding).tolist()
    if center is None:
        raise ValueError(
            "Give the search box: center (and size), or box_from_ligand with a ligand "
            "file in the binding site."
        )
    if len(center) != 3 or len(size) != 3 or min(size) <= 0:
        raise ValueError("center and size must be three numbers each, size positive.")
    return [float(c) for c in center], [float(s) for s in size]


def _poses(pdbqt: str):
    """RDKit molecules (with hydrogens) for the docked poses in a Vina PDBQT string."""
    from meeko import PDBQTMolecule, RDKitMolCreate

    molecules = RDKitMolCreate.from_pdbqt_mol(PDBQTMolecule(pdbqt, skip_typing=True))
    return molecules[0]


def _rmsd(probe, reference) -> float:
    """Symmetry-aware heavy-atom RMSD in place (no superposition)."""
    from rdkit import Chem
    from rdkit.Chem import rdMolAlign

    return float(rdMolAlign.CalcRMS(Chem.RemoveHs(probe), Chem.RemoveHs(reference)))


def dock(
    receptor: str,
    ligand: str,
    center: list[float] | None = None,
    size: list[float] | None = None,
    box_from_ligand: str | None = None,
    padding: float = 6.0,
    exhaustiveness: int = 16,
    n_poses: int = 9,
    energy_range: float = 3.0,
    scoring: Scoring = "vina",
    reference_ligand: str | None = None,
    seed: int = 42,
    cpu: int = 0,
    output: str = "docked.sdf",
) -> dict:
    """Dock a ligand into a receptor binding site and rank the poses.

    Args:
        receptor: Receptor PDB file with hydrogens (converted to PDBQT), or a
            prepared PDBQT file.
        ligand: SMILES string (a 3D conformer is generated; protonate it for the
            pH of interest first) or an SDF/MOL/MOL2 file.
        center: Center of the search box (x, y, z) in Angstrom.
        size: Edge lengths of the search box in Angstrom (default 20, 20, 20).
        box_from_ligand: SDF/MOL of a ligand in the site (e.g. the crystal ligand);
            the box encloses it plus padding. Replaces center and size.
        padding: Margin around box_from_ligand, Angstrom.
        exhaustiveness: Search effort (default 16; 32 for flexible ligands).
        n_poses: Number of poses to return.
        energy_range: Largest score difference to the best pose, kcal/mol.
        scoring: "vina" (default) or "vinardo".
        reference_ligand: SDF/MOL of the known pose (same molecule), to report
            each pose's RMSD from it (redocking).
        seed: Random seed of the search.
        cpu: CPU threads (0 = all).
        output: SDF file with the poses (with hydrogens), best first.

    Returns:
        For each pose: Vina score (kcal/mol), heavy-atom RMSD from the best pose,
        and RMSD from the reference ligand if given; the best score,
        the box, the receptor PDBQT used, and the output file.
    """
    from rdkit import Chem
    from vina import Vina

    if exhaustiveness < 1 or n_poses < 1:
        raise ValueError("exhaustiveness and n_poses must be positive.")
    box_center, box_size = _box(center, size or [20.0, 20.0, 20.0], box_from_ligand, padding)
    receptor_pdbqt = _receptor(receptor, "receptor.pdbqt")
    molecule, generated = _rdkit_ligand(ligand, seed)
    engine = Vina(sf_name=scoring, cpu=cpu, seed=seed, verbosity=0)
    engine.set_receptor(rigid_pdbqt_filename=receptor_pdbqt)
    engine.set_ligand_from_string(_ligand_pdbqt(molecule))
    engine.compute_vina_maps(center=box_center, box_size=box_size)
    engine.dock(exhaustiveness=exhaustiveness, n_poses=max(20, n_poses))
    pdbqt = engine.poses(n_poses=n_poses, energy_range=energy_range)
    energies = np.asarray(engine.energies(n_poses=n_poses, energy_range=energy_range))
    poses = _poses(pdbqt)
    reference = None
    if reference_ligand:
        reference = Chem.MolFromMolFile(reference_ligand)
        if reference is None:
            raise ValueError(f"RDKit could not read the reference ligand {reference_ligand}.")
    conformers = [poses.GetConformer(c.GetId()) for c in poses.GetConformers()]
    rows = []
    writer = Chem.SDWriter(output)
    best = None
    for rank, (conformer, energy) in enumerate(zip(conformers, energies, strict=False), 1):
        pose = Chem.Mol(poses, confId=conformer.GetId())
        pose.RemoveAllConformers()
        pose.AddConformer(Chem.Conformer(conformer), assignId=True)
        best = best or pose
        row = {
            "rank": rank,
            "affinity_kcal_mol": float(energy[0]),
            "rmsd_from_best_angstrom": 0.0 if rank == 1 else _rmsd(pose, best),
        }
        if reference is not None:
            row["rmsd_to_reference_angstrom"] = _rmsd(pose, reference)
        pose.SetProp("_Name", f"pose {rank}")
        pose.SetProp("vina_affinity_kcal_mol", f"{energy[0]:.3f}")
        writer.write(pose)
        rows.append(row)
    writer.close()
    return {
        "scoring": scoring,
        "best_affinity_kcal_mol": rows[0]["affinity_kcal_mol"],
        "poses": rows,
        "n_poses": len(rows),
        "box_center": box_center,
        "box_size": box_size,
        "ligand_conformer_generated": generated,
        "receptor_pdbqt": receptor_pdbqt,
        "output": output,
    }


def score(
    receptor: str,
    ligand: str,
    optimize: bool = False,
    scoring: Scoring = "vina",
    padding: float = 5.0,
    output: str = "scored.sdf",
) -> dict:
    """Score a ligand pose already placed in the binding site, optionally after local optimization.

    Args:
        receptor: Receptor PDB file with hydrogens, or a prepared PDBQT file.
        ligand: SDF/MOL/MOL2 file of the ligand in its pose (e.g. a crystal
            structure or a pose from another program).
        optimize: Minimize the pose locally before scoring.
        scoring: "vina" (default) or "vinardo".
        padding: Margin of the scoring box around the ligand, Angstrom.
        output: SDF with the scored (and optimized) pose.

    Returns:
        The Vina score (kcal/mol), the ligand-receptor energy it is computed
        from, the ligand's internal energy, the rotatable-bond (entropy)
        correction, and with optimize the heavy-atom RMSD the pose moved.
    """
    from rdkit import Chem
    from vina import Vina

    molecule, generated = _rdkit_ligand(ligand, 0)
    if generated:
        raise ValueError("score needs a ligand file with a pose in the binding site.")
    coordinates = molecule.GetConformer().GetPositions()
    low, high = coordinates.min(axis=0), coordinates.max(axis=0)
    receptor_pdbqt = _receptor(receptor, "receptor.pdbqt")
    engine = Vina(sf_name=scoring, cpu=1, verbosity=0)
    engine.set_receptor(rigid_pdbqt_filename=receptor_pdbqt)
    engine.set_ligand_from_string(_ligand_pdbqt(molecule))
    engine.compute_vina_maps(
        center=((low + high) / 2).tolist(), box_size=(high - low + 2 * padding).tolist()
    )
    moved = None
    if optimize:
        engine.optimize()
        with tempfile.TemporaryDirectory(prefix="motel-vina-") as tmp:
            optimized = Path(tmp) / "pose.pdbqt"
            engine.write_pose(str(optimized), overwrite=True)
            pose = _poses(optimized.read_text())
        moved = _rmsd(pose, molecule)
    else:
        pose = molecule
    energies = np.asarray(engine.score())
    pose.SetProp("vina_affinity_kcal_mol", f"{energies[0]:.3f}")
    writer = Chem.SDWriter(output)
    writer.write(pose)
    writer.close()
    return {
        "scoring": scoring,
        # score() returns: total, ligand-receptor, flex-receptor, other, flex intra,
        # ligand intra, rotatable-bond correction, ligand intra of the unbound pose.
        "affinity_kcal_mol": float(energies[0]),
        "intermolecular_kcal_mol": float(energies[1]),
        "ligand_internal_kcal_mol": float(energies[5]),
        "rotatable_bond_correction_kcal_mol": float(energies[6]),
        "optimized": optimize,
        "rmsd_moved_angstrom": moved,
        "receptor_pdbqt": receptor_pdbqt,
        "output": output,
    }
