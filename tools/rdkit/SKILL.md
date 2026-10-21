---
name: rdkit
description: >-
  Cheminformatics with RDKit: rank molecules by fingerprint similarity to a
  query (Morgan/ECFP, Tanimoto), find molecules containing a substructure
  (SMARTS), generate and rank 3D conformers (ETKDG + MMFF94), and standardize
  structures (remove salts, neutralize, canonical tautomer) with canonical
  SMILES, InChI, and InChIKey. Use for virtual screening, deduplicating
  compound lists, preparing 3D structures for quantum chemistry, and comparing
  molecules across databases.
---

## Recipes

- **Find analogs:** `similarity_search("CC(=O)Nc1ccc(O)cc1", "library.sdf", top=20)`.
- **Filter by a group:** `substructure_search("[CX3](=O)[OX2H1]", molecules)`
  (carboxylic acids). Useful SMARTS: `c[NH1]` aromatic NH, `[#7+]` cations,
  `[OH]c` phenols, `C(=O)N` amides.
- **3D structures for quantum chemistry:** `conformers(smiles)` → refine the
  lowest few from `conformers_file` with `xtb.optimize`, then `pyscf.single_point`.
- **Same compound in two databases?** Compare `inchikey` from `standardize`
  (the first 14 characters encode connectivity, ignoring stereochemistry).

## Pitfalls

- Similarity values from different fingerprints or metrics are not comparable.
- SMARTS and SMILES patterns differ: the SMARTS `COC` needs aliphatic atoms.
- Conformer search is stochastic; for flexible molecules raise `n_conformers`.
- Molecular descriptors (logP, TPSA, Lipinski) are in the `rdkit-descriptors` tool.
