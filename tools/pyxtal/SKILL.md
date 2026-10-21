---
name: pyxtal
description: >-
  Generate crystal structures by symmetry (PyXtal): random crystals of a
  composition in a chosen or random space group, molecular (organic) crystals
  from built-in molecules or SMILES, Wyckoff position tables, and which space
  groups can hold a composition. Use for crystal structure prediction and
  polymorph searches (generate, then relax with ml-potentials and rank by
  energy), and for symmetry questions about space groups.
---

## Recipes

- **Structure prediction:** `compatible_space_groups({"Ti": 2, "O": 4})` →
  `random_crystals({"Ti": 2, "O": 4}, count=20)` (random compatible groups), and
  again with Z = 2 and 4 (e.g. {"Ti": 4, "O": 8}) → `ml-potentials.relax` each
  CIF → rank by energy per atom; check the best with
  `pymatgen-structure.symmetry`.
- **A specific space group:** `random_crystals(composition, space_group=62)`.
- **Organic polymorphs:** `molecular_crystals(["CC(=O)Nc1ccc(O)cc1"], [4], 14)`;
  try groups 14, 2, 19, 61, 4, 15, 33.
- **Symmetry lookup:** `wyckoff_positions(194)`.

## Interpreting

- Generated cells are unrelaxed (low densities are normal); compare energies
  only after relaxation.
- `space_group_found` can be higher than requested (special positions); keep
  the higher one.

## Pitfalls

- Composition counts are atoms per conventional cell, not formula units.
- Many structures are needed to find a ground state; tell the user how many
  were tried.
