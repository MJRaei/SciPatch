---
name: quantum-espresso
description: >-
  First-principles DFT for crystals with Quantum ESPRESSO (pw.x) and the
  verified SSSP pseudopotentials: total energies, forces and stress, relaxation
  of atoms and cell, equation of state (lattice constant, bulk modulus), Fermi
  level, band gaps, and magnetization, with cutoffs chosen automatically. Use
  as a reference to check machine-learned potentials, for electronic and
  magnetic properties, and when results must match the widely used
  Quantum ESPRESSO + SSSP standard (e.g. Materials Cloud workflows).
---

## Recipes

- **Ground state:** `scf("structure.cif")`; the pw.x input and output are kept
  (`input_file`, `output_file`) for inspection or reuse.
- **Relax:** `relax("structure.cif")` (cell and atoms, zero pressure).
- **Lattice constant and bulk modulus:** `equation_of_state(structure)`.
- **Second DFT opinion:** compare with `gpaw.scf` on the same structure; both
  are PBE, so energy differences should agree within a few meV/atom.
- **Your own pseudopotentials:** `pseudopotentials={"Si": "Si.UPF"}` with
  `ecutwfc_ry` (and `ecutrho_ry` for ultrasoft or PAW).

## Pitfalls

- PBE band gaps are too small; do not report them as experimental gaps.
- Raise `ecutwfc_ry` (by about 30%) when stresses or lattice constants must be
  very precise.
- pw.x uses all cores of this computer; large or metallic cells still take long.
- Report the functional, pseudopotentials, cutoffs, and k-points (`settings`).
