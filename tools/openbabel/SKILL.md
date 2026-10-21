---
name: openbabel
description: >-
  Convert chemical files between 100+ formats (SDF, MOL2, PDB, XYZ, CIF,
  Gaussian, ORCA, GAMESS, CML, SMILES, InChI, ...), get canonical SMILES, InChI
  and InChIKeys, protonate molecules for a pH, generate 3D coordinates, compute
  and minimize MMFF94/UFF/GAFF force-field energies, and assign partial charges.
  Use to prepare inputs for other programs, identify or deduplicate molecules,
  fill crystal unit cells, or get quick force-field geometries.
---

## Recipes

- **Prepare a QM input:** `convert("CCO", "ethanol.xyz", coordinates="3d")`, or
  `output="ethanol.gjf"` (Gaussian), `"ethanol.orcainp"` (ORCA), `"ethanol.inp"`
  (GAMESS), `"ethanol.nw"` (NWChem), `"ligand.pdbqt"` (AutoDock).
- **Identify molecules:** `identifiers("molecules.sdf")` → canonical SMILES,
  InChIKey (for database lookups and deduplication), formula, masses.
- **From InChI:** `identifiers("InChI=1S/...", input_format="inchi")`.
- **Docking/MD ligand prep:** `convert("ligand.sdf", "ligand.mol2", hydrogens="ph", ph=7.4)`.
- **Crystal to molecule file:** `convert("structure.cif", "cell.xyz", fill_unit_cell=True)`.
- **Quick geometry:** `minimize("mol.sdf")` (MMFF94); metals or unusual
  elements: `forcefield="UFF"`.
- **Charges:** `partial_charges("mol.sdf", method="mmff94")`.
- **All formats:** `list_formats()`.

## Pitfalls

- Force-field energies compare conformers of one molecule only; they are not
  heats of formation.
- pH protonation is rule-based; groups with pKa near the pH may be wrong.
- `coordinates="3d"` gives one reasonable conformer, not the lowest one; use the
  crest or rdkit tools for conformer searches.
- Converting to SMILES or InChI drops coordinates; converting SMILES to 3D
  formats needs `coordinates="3d"`.
