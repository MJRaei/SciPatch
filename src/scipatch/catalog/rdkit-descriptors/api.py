"""RDKit: molecular descriptors, similarity, and 3D conformers from SMILES."""

from __future__ import annotations

from typing import Literal


def _molecule(smiles: str):
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")  # parse errors are reported through the exception below
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise ValueError(f"'{smiles}' is not a valid SMILES string.")
    return molecule


def descriptors(smiles: str) -> dict:
    """Compute common molecular descriptors and drug-likeness measures for one molecule.

    Args:
        smiles: The molecule as a SMILES string, e.g. "CC(=O)Oc1ccccc1C(=O)O" (aspirin).

    Returns:
        Canonical SMILES, formula, molecular weight (g/mol), exact mass (Da),
        Crippen logP, topological polar surface area (Å²), hydrogen-bond donors and
        acceptors, rotatable bonds, ring counts, fraction of sp3 carbons, QED
        drug-likeness (0 to 1), and the number of Lipinski rule-of-five violations.
    """
    from rdkit import Chem
    from rdkit.Chem import QED, Crippen, Descriptors, Lipinski, rdMolDescriptors

    molecule = _molecule(smiles)
    weight = Descriptors.MolWt(molecule)
    logp = Crippen.MolLogP(molecule)
    donors = Lipinski.NumHDonors(molecule)
    acceptors = Lipinski.NumHAcceptors(molecule)
    violations = sum([weight > 500, logp > 5, donors > 5, acceptors > 10])
    return {
        "canonical_smiles": Chem.MolToSmiles(molecule),
        "formula": rdMolDescriptors.CalcMolFormula(molecule),
        "molecular_weight_g_mol": round(weight, 4),
        "exact_mass_da": round(Descriptors.ExactMolWt(molecule), 5),
        "logp": round(logp, 4),
        "tpsa_angstrom2": round(rdMolDescriptors.CalcTPSA(molecule), 3),
        "h_bond_donors": donors,
        "h_bond_acceptors": acceptors,
        "rotatable_bonds": Lipinski.NumRotatableBonds(molecule),
        "rings": rdMolDescriptors.CalcNumRings(molecule),
        "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(molecule),
        "heavy_atoms": molecule.GetNumHeavyAtoms(),
        "fraction_sp3": round(rdMolDescriptors.CalcFractionCSP3(molecule), 4),
        "qed": round(QED.qed(molecule), 4),
        "lipinski_violations": int(violations),
    }


def similarity(smiles_a: str, smiles_b: str, radius: int = 2, n_bits: int = 2048) -> dict:
    """Tanimoto similarity of two molecules from Morgan (ECFP-like) fingerprints.

    Args:
        smiles_a: First molecule as SMILES.
        smiles_b: Second molecule as SMILES.
        radius: Morgan radius (2 corresponds to ECFP4).
        n_bits: Fingerprint length in bits.

    Returns:
        Tanimoto similarity between 0 (nothing shared) and 1 (identical fingerprints).
    """
    from rdkit import DataStructs
    from rdkit.Chem import rdFingerprintGenerator

    if radius < 1 or n_bits < 64:
        raise ValueError("Use radius >= 1 and n_bits >= 64.")
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=n_bits)
    first = generator.GetFingerprint(_molecule(smiles_a))
    second = generator.GetFingerprint(_molecule(smiles_b))
    return {"tanimoto": round(DataStructs.TanimotoSimilarity(first, second), 4)}


def conformer(
    smiles: str,
    force_field: Literal["mmff", "uff"] = "mmff",
    seed: int = 42,
    output: str = "conformer.sdf",
) -> dict:
    """Generate a 3D structure (ETKDG embedding) and optimize it with a force field.

    Args:
        smiles: The molecule as a SMILES string.
        force_field: "mmff" (MMFF94, organic molecules) or "uff" (broader coverage).
        seed: Random seed for the embedding, for reproducible geometries.
        output: SDF file to write the optimized 3D structure to.

    Returns:
        Path of the SDF file, the force-field energy (kcal/mol), whether the
        optimization converged, and the number of atoms including hydrogens.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem

    molecule = Chem.AddHs(_molecule(smiles))
    parameters = AllChem.ETKDGv3()
    parameters.randomSeed = seed
    if AllChem.EmbedMolecule(molecule, parameters) != 0:
        raise ValueError("Could not generate 3D coordinates for this molecule.")
    if force_field == "mmff":
        properties = AllChem.MMFFGetMoleculeProperties(molecule)
        if properties is None:
            raise ValueError("MMFF has no parameters for this molecule; try force_field='uff'.")
        field = AllChem.MMFFGetMoleculeForceField(molecule, properties)
    else:
        field = AllChem.UFFGetMoleculeForceField(molecule)
    not_converged = field.Minimize(maxIts=2000)
    writer = Chem.SDWriter(output)
    writer.write(molecule)
    writer.close()
    return {
        "conformer": output,
        "energy_kcal_mol": round(field.CalcEnergy(), 4),
        "converged": not_converged == 0,
        "n_atoms": molecule.GetNumAtoms(),
    }
