---
name: xtb
description: >-
  Fast semiempirical quantum chemistry for molecules with GFN2-xTB: energies,
  HOMO-LUMO gaps, dipole moments, partial charges, geometry optimization,
  vibrational (IR) frequencies, zero-point energy, enthalpy and Gibbs free
  energy, in the gas phase or implicit solvent (water, DMSO, toluene, ...).
  Accepts SMILES or structure files. Use for quick molecular geometries and
  energetics, comparing isomers or conformers, or checking that a structure is a
  true minimum before running expensive DFT.
---

## Recipes

- **Optimize a molecule from SMILES:** `optimize("CC(=O)Oc1ccccc1C(=O)O")`; the
  charge is taken from the SMILES (e.g. `[NH4+]` is +1). Pass the returned
  `optimized_structure` to other tools.
- **Is it a minimum? Thermochemistry?** `frequencies(molecule)` optimizes first,
  then reports `imaginary_frequencies` (0 for a minimum), the IR spectrum, and
  free energy at 298.15 K.
- **Reaction or isomer energies:** compute each species with the same method and
  solvent, subtract `energy_hartree` (or `free_energy_hartree`); 1 Eh =
  627.5 kcal/mol = 27.211 eV.
- **Solvent effects:** add `solvent="water"` (ALPB model).
- **Radicals and ions:** set `charge` and `unpaired_electrons` (e.g. 1 for a doublet).

## Pitfalls

- A SMILES gives one conformer; for flexible molecules, try a few `seed` values
  and keep the lowest energy.
- The HOMO-LUMO gap from tight binding is qualitative.
- Report the method (GFN2-xTB) and solvent model with every number.
