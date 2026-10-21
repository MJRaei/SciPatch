---
name: rdkit-descriptors
description: >-
  Compute properties of small molecules from SMILES with RDKit: molecular
  weight, formula, logP, polar surface area (TPSA), hydrogen-bond donors and
  acceptors, drug-likeness (QED, Lipinski rule of five), fingerprint similarity
  between molecules, and a force-field optimized 3D structure (SDF). Use for
  cheminformatics, screening compound lists, or preparing 3D inputs for
  simulation tools.
---

## Recipes

- **Profile a molecule:** `descriptors(smiles=...)`. Report weight, logP, TPSA
  and Lipinski violations together; they are usually read as a set.
- **Compare molecules:** `similarity(smiles_a, smiles_b)`. Tanimoto above about
  0.7 (ECFP4, 2048 bits) usually means close analogs; below 0.3, unrelated.
- **Get a 3D structure for other tools:** `conformer(smiles=...)` writes an SDF
  file and returns its absolute path; pass it to tools expecting a molecule file.
- **Screen a list:** call `descriptors` once per molecule; identical calls are
  cached, so re-screening is free.

## Pitfalls

- Names are not SMILES. Convert names such as "aspirin" to SMILES first.
- Salts and mixtures (SMILES with ".") are treated as one entity; strip
  counter-ions first if you want the parent compound.
- logP here is Crippen's estimate; say so when comparing with measured values
  or with PubChem's XLogP3.
