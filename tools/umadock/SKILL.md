---
name: umadock
description: >-
  Protein-ligand docking scored by machine-learned interatomic potentials
  (UMA-Dock). prepare_site cuts a capped, protonated binding-site cluster from a
  PDB file or id around a crystal ligand; dock places RDKit conformers of a
  SMILES in it, optimizes the best poses with AIMNet2 (default) or MACE-OMOL-0,
  and returns interaction, strain, desolvation, and binding energies with the
  optimized complex. Use to rank candidate ligands for one pocket.
---

## Recipes

- `prepare_site("2A3R", "LDP", chain="A")` (the crystal ligand's residue name
  defines the pocket; pick one chain of an oligomer) → check
  `overlapping_pairs_below_0_9_angstrom` is 0.
- `dock("CC(=O)Nc1ccc(O)cc1", site="site/site.json", conformers=3, tries=200)`
  → compare `best_binding_kcal_mol` across ligands docked the same way.
- Cross-check poses and ranking with `vina.dock`; refine promising complexes
  with `openmm.simulate`.

## Pitfalls

- Binding energies are electronic energies in a gas-phase cluster: compare
  ligands, not with experimental affinities; magnitudes differ by potential.
- AIMNet2 has no metals; use model="mace-omol" for metal sites (slow on CPU;
  non-commercial licence).
- Results depend on random placement: use enough tries and the same seed.
