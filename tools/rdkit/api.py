"""Cheminformatics with RDKit: similarity and substructure search, conformers, standardization.

Molecules are given as SMILES, a list of SMILES, or a file with many molecules
(SDF, or a SMILES file with one SMILES and an optional name per line).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

Fingerprint = Literal["morgan", "rdkit", "atompair", "torsion"]
Metric = Literal["tanimoto", "dice"]

_SMILES_SUFFIXES = (".smi", ".smiles", ".txt", ".csv")


def _quiet() -> None:
    from rdkit import RDLogger

    RDLogger.DisableLog("rdApp.*")


def _parse(smiles: str) -> Any:
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"'{smiles}' is not a valid SMILES string.")
    return mol


def _read_many(molecules: list[str] | str) -> tuple[list[tuple[str, Any]], list[str]]:
    """(name, molecule) pairs and the entries that could not be read."""
    from rdkit import Chem

    _quiet()
    entries: list[tuple[str, Any]] = []
    invalid: list[str] = []
    if isinstance(molecules, str) and Path(molecules).is_file():
        path = Path(molecules)
        if path.suffix.lower() == ".sdf":
            with Chem.SDMolSupplier(str(path)) as supplier:
                for index, mol in enumerate(supplier):
                    if mol is None:
                        invalid.append(f"record {index + 1}")
                        continue
                    name = mol.GetProp("_Name") if mol.HasProp("_Name") else ""
                    entries.append((name or f"record {index + 1}", mol))
            return entries, invalid
        if path.suffix.lower() not in _SMILES_SUFFIXES:
            raise ValueError("Use an SDF file or a SMILES file (.smi, .txt, .csv).")
        lines = [line.replace(",", " ").split() for line in path.read_text().splitlines()]
        items = [(" ".join(parts[1:]) or parts[0], parts[0]) for parts in lines if parts]
    else:
        listed = [molecules] if isinstance(molecules, str) else list(molecules)
        items = [(smiles, smiles) for smiles in listed]
    for name, smiles in items:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            invalid.append(smiles)
        else:
            entries.append((name, mol))
    return entries, invalid


def _fingerprinter(kind: Fingerprint, radius: int, n_bits: int, counts: bool) -> Any:
    from rdkit.Chem import rdFingerprintGenerator as generators

    if kind == "morgan":
        generator = generators.GetMorganGenerator(radius=radius, fpSize=n_bits)
    elif kind == "rdkit":
        generator = generators.GetRDKitFPGenerator(fpSize=n_bits)
    elif kind == "atompair":
        generator = generators.GetAtomPairGenerator(fpSize=n_bits)
    else:
        generator = generators.GetTopologicalTorsionGenerator(fpSize=n_bits)
    return generator.GetSparseCountFingerprint if counts else generator.GetFingerprint


def similarity_search(
    query: str,
    molecules: list[str] | str,
    fingerprint: Fingerprint = "morgan",
    radius: int = 2,
    n_bits: int = 2048,
    counts: bool = False,
    metric: Metric = "tanimoto",
    top: int = 50,
) -> dict:
    """Rank molecules by fingerprint similarity to a query molecule.

    Args:
        query: SMILES of the query molecule.
        molecules: SMILES, a list of SMILES, or an SDF/SMILES file to search.
        fingerprint: "morgan" (circular, ECFP-like; default), "rdkit" (paths),
            "atompair", or "torsion".
        radius: Morgan radius (2 is comparable to ECFP4).
        n_bits: Fingerprint length (bit vectors).
        counts: Use count fingerprints instead of bit vectors.
        metric: "tanimoto" (default) or "dice".
        top: Number of best matches to return.

    Returns:
        The query's canonical SMILES, the best matches (name, SMILES, similarity
        from 0 to 1, highest first), the number of molecules searched, and any
        entries that could not be read.
    """
    from rdkit import Chem, DataStructs

    _quiet()
    query_mol = _parse(query)
    entries, invalid = _read_many(molecules)
    fingerprint_of = _fingerprinter(fingerprint, radius, n_bits, counts)
    compare = DataStructs.DiceSimilarity if metric == "dice" else DataStructs.TanimotoSimilarity
    reference = fingerprint_of(query_mol)
    scored = [
        {
            "name": name,
            "smiles": Chem.MolToSmiles(mol),
            "similarity": float(compare(reference, fingerprint_of(mol))),
        }
        for name, mol in entries
    ]
    scored.sort(key=lambda item: -item["similarity"])
    return {
        "query": Chem.MolToSmiles(query_mol),
        "fingerprint": fingerprint,
        "metric": metric,
        "n_molecules": len(entries),
        "results": scored[: max(top, 0)],
        "invalid": invalid,
    }


def substructure_search(
    pattern: str,
    molecules: list[str] | str,
    pattern_type: Literal["smarts", "smiles"] = "smarts",
    use_chirality: bool = False,
    max_matches_per_molecule: int = 10,
) -> dict:
    """Find the molecules that contain a substructure, and where.

    Args:
        pattern: The substructure, as SMARTS (default; e.g. "c[NH1]" for an
            aromatic NH) or SMILES. SMARTS and SMILES differ: the SMARTS "COC"
            needs aliphatic carbons, the SMILES "COC" matches any.
        molecules: SMILES, a list of SMILES, or an SDF/SMILES file to search.
        pattern_type: "smarts" or "smiles".
        use_chirality: Require matching stereochemistry.
        max_matches_per_molecule: Most matches to report per molecule.

    Returns:
        The number of molecules searched and matched, and for each match the
        name, SMILES, and the atom indices (0-based, in the order of the pattern's atoms).
    """
    from rdkit import Chem

    _quiet()
    query = Chem.MolFromSmarts(pattern) if pattern_type == "smarts" else Chem.MolFromSmiles(pattern)
    if query is None:
        raise ValueError(f"'{pattern}' is not valid {pattern_type.upper()}.")
    entries, invalid = _read_many(molecules)
    matched = []
    for name, mol in entries:
        hits = mol.GetSubstructMatches(
            query, useChirality=use_chirality, maxMatches=max_matches_per_molecule
        )
        if hits:
            matched.append({
                "name": name,
                "smiles": Chem.MolToSmiles(mol),
                "atom_indices": [list(hit) for hit in hits],
            })  # fmt: skip
    return {
        "pattern": pattern,
        "n_molecules": len(entries),
        "n_matched": len(matched),
        "matches": matched,
        "invalid": invalid,
    }


def conformers(
    molecule: str,
    n_conformers: int = 30,
    force_field: Literal["mmff", "uff"] = "mmff",
    prune_rms: float = 0.5,
    energy_window_kcal_mol: float | None = 10.0,
    seed: int = 42,
    output: str = "conformers.sdf",
) -> dict:
    """Generate, optimize, and rank 3D conformers of a molecule.

    Conformers are embedded with ETKDG, optimized with the MMFF94 (or UFF)
    force field, and duplicates (heavy-atom RMSD below prune_rms after
    alignment) are removed.

    Args:
        molecule: SMILES of the molecule.
        n_conformers: Number of conformers to embed before deduplication.
        force_field: "mmff" (MMFF94, default) or "uff".
        prune_rms: RMSD threshold in Angstrom below which conformers are duplicates.
        energy_window_kcal_mol: Keep conformers within this energy of the lowest
            (None keeps all).
        seed: Random seed for embedding.
        output: SDF file with the conformers, lowest energy first, with their
            energies as properties.

    Returns:
        Numbers of embedded and unique conformers, their relative energies
        (kcal/mol, lowest first), the force field used, and the SDF path.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdMolAlign

    _quiet()
    if not 1 <= n_conformers <= 1000:
        raise ValueError("n_conformers must be between 1 and 1000.")
    mol = Chem.AddHs(_parse(molecule))
    parameters = AllChem.ETKDGv3()
    parameters.randomSeed = seed
    ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=n_conformers, params=parameters))
    if not ids:
        raise ValueError("Could not generate 3D coordinates for this molecule.")
    used = force_field
    if force_field == "mmff" and AllChem.MMFFHasAllMoleculeParams(mol):
        results = AllChem.MMFFOptimizeMoleculeConfs(mol, maxIters=2000)
    else:
        used = "uff"
        results = AllChem.UFFOptimizeMoleculeConfs(mol, maxIters=2000)
    energies = {cid: energy for cid, (_, energy) in zip(ids, results, strict=True)}
    heavy = Chem.RemoveHs(mol)
    kept: list[int] = []
    for cid in sorted(ids, key=energies.__getitem__):
        if all(rdMolAlign.GetBestRMS(heavy, heavy, k, cid) >= prune_rms for k in kept):
            kept.append(cid)
    lowest = energies[kept[0]]
    if energy_window_kcal_mol is not None:
        kept = [cid for cid in kept if energies[cid] - lowest <= energy_window_kcal_mol]
    with Chem.SDWriter(output) as writer:
        for rank, cid in enumerate(kept):
            mol.SetProp("_Name", f"conformer {rank + 1}")
            mol.SetDoubleProp("energy_kcal_mol", energies[cid])
            mol.SetDoubleProp("relative_energy_kcal_mol", energies[cid] - lowest)
            writer.write(mol, confId=cid)
    return {
        "smiles": Chem.MolToSmiles(Chem.RemoveHs(mol)),
        "force_field": "MMFF94" if used == "mmff" else "UFF",
        "n_embedded": len(ids),
        "n_unique": len(kept),
        "relative_energies_kcal_mol": [energies[cid] - lowest for cid in kept],
        "lowest_energy_kcal_mol": lowest,
        "conformers_file": output,
    }


def standardize(
    molecules: list[str] | str,
    keep_largest_fragment: bool = True,
    neutralize: bool = True,
    canonical_tautomer: bool = True,
) -> dict:
    """Standardize molecules and give their identifiers (canonical SMILES, InChI, InChIKey).

    Standardization cleans up the structure (normalizes functional groups such
    as nitro groups, reionizes), optionally keeps the largest fragment (removing
    salts and solvents), neutralizes charges where possible, and picks a
    canonical tautomer, so that the same compound always gets the same identifiers.

    Args:
        molecules: SMILES, a list of SMILES, or an SDF/SMILES file.
        keep_largest_fragment: Remove counter-ions and solvents (keep the parent).
        neutralize: Neutralize charged groups where a neutral form exists.
        canonical_tautomer: Replace each molecule by its canonical tautomer.

    Returns:
        For each molecule: the input name, standardized canonical SMILES, InChI,
        InChIKey, formula, and molecular weight (g/mol); and any unreadable entries.
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors
    from rdkit.Chem.MolStandardize import rdMolStandardize

    entries, invalid = _read_many(molecules)
    chooser = rdMolStandardize.LargestFragmentChooser()
    uncharger = rdMolStandardize.Uncharger()
    tautomers = rdMolStandardize.TautomerEnumerator()
    results = []
    for name, mol in entries:
        clean = rdMolStandardize.Cleanup(mol)
        if keep_largest_fragment:
            clean = chooser.choose(clean)
        if neutralize:
            clean = uncharger.uncharge(clean)
        if canonical_tautomer:
            clean = tautomers.Canonicalize(clean)
        results.append({
            "input": name,
            "smiles": Chem.MolToSmiles(clean),
            "inchi": Chem.MolToInchi(clean),
            "inchikey": Chem.MolToInchiKey(clean),
            "formula": rdMolDescriptors.CalcMolFormula(clean),
            "molecular_weight": float(Descriptors.MolWt(clean)),
        })  # fmt: skip
    return {"n_molecules": len(results), "results": results, "invalid": invalid}
