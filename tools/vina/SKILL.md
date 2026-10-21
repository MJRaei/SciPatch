---
name: vina
description: >-
  Dock small molecules into protein binding sites with AutoDock Vina: ranked
  binding poses with Vina or Vinardo scores (kcal/mol), RMSD to a known ligand
  pose, and an SDF of the poses; score or locally optimize an existing pose. Use
  for structure-based drug design, pose prediction, comparing ligands for one
  target, or checking whether a molecule fits a pocket.
---

## Recipes

- **Site known from a crystal ligand:** `dock("protein_H.pdb", "CC(=O)Nc1ccc(O)cc1",
  box_from_ligand="crystal_ligand.sdf")`.
- **Site known by coordinates:** `dock(..., center=[x, y, z], size=[20, 20, 20])`.
- **Validate the setup first:** redock the crystal ligand with
  `reference_ligand="crystal_ligand.sdf"`; top pose RMSD < 2 Å means the box and
  preparation work.
- **Flexible ligands (> 8 rotatable bonds):** `exhaustiveness=32` and repeat with
  another `seed`.
- **Rescore a pose:** `score("protein_H.pdb", "pose.sdf", optimize=True)`.
- **Prepare inputs:** add receptor hydrogens with PDBFixer or reduce, or the
  openbabel tool (`convert("protein.pdb", "protein_H.pdb", hydrogens="ph")`;
  check histidine states); protonate ligands for pH 7.4 the same way.
- **Refine top poses:** MD with the openmm tool (small molecules via OpenFF).

## Pitfalls

- The receptor must contain hydrogens; remove waters and other ligands you do not
  want in the site.
- Scores are approximate; do not read differences below about 1-2 kcal/mol as
  real affinity differences.
- The box must enclose the whole site but not much more (larger boxes need more
  exhaustiveness).
