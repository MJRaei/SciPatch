---
name: crest
description: >-
  Explore conformers, protonation and deprotonation sites, and tautomers of
  molecules with CREST and GFN2-xTB: find all low-energy conformers with
  Boltzmann populations, the most basic or acidic site, and the most stable
  tautomer, in the gas phase or implicit solvent. Use before DFT
  (pyscf) on flexible molecules, to choose the right protonation state, or
  to compare tautomers. Accepts SMILES or XYZ files.
---

## Recipes

- **Conformers for DFT:** `conformer_search("CCOC(=O)c1ccccc1O")` → refine the
  first few structures in `conformers_file` with `pyscf.optimize`.
- **Fast first look:** `mode="quick"`; for large, flexible molecules
  `method="gfn2//gfnff"`.
- **In solution:** `solvent="water"` (ALPB); protonation states and tautomers
  depend strongly on it.
- **Which site is protonated?** `protonation_sites(smiles)`: `site` names the
  atom (element + 1-based index in the input), `smiles` the protomer.
- **Acidity:** `deprotonation_sites(smiles, solvent="water")`.
- **Tautomers:** `tautomers(smiles, solvent="water")`.

## Pitfalls

- GFN2-xTB energies are approximate: differences below about 1-2 kcal/mol
  (conformers) or a few kcal/mol (protomers, tautomers) are not reliable.
  Refine with DFT.
- The search is stochastic; repeat for flexible molecules.
- Conformer searches of drug-sized molecules take minutes to an hour (long-running).
