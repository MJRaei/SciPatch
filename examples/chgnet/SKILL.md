---
name: chgnet
description: >-
  Fast machine-learning predictions for inorganic crystals with the CHGNet
  universal potential: energy, forces, stress, and magnetic moments of a
  structure; structure relaxation (positions and cell); and molecular dynamics.
  Use to pre-relax structures before DFT, screen candidate materials for
  stability, estimate oxidation states from magnetic moments, or simulate ionic
  motion (e.g. Li diffusion in battery materials).
---

## Recipes

- **Relax, then analyze:** `relax(structure)` returns the relaxed structure's
  path; pass it to `predict` or to other structure tools.
- **Stability screening:** relax each candidate, then compare
  `final_energy_ev_per_atom` with the Materials Project convex hull (CHGNet
  energies are MP-compatible). Treat differences below about 30 meV/atom as
  inconclusive.
- **Oxidation states:** predicted magnetic moments hint at oxidation states,
  e.g. on Mn about 3 μB suggests Mn4+ (d3), about 4 μB Mn3+ (d4), and about
  5 μB high-spin Mn2+ (d5). Use as a hint, not proof.
- **Diffusion:** `molecular_dynamics(structure, temperature_k=800, steps=5000)`
  runs in the background (progress is shown while it runs); collect the result
  later. Use a supercell of at least about 100 atoms. Pass the returned
  `trajectory` and `frame_interval_fs` to a diffusion-analysis tool.

## Parameters that matter

- `fmax`: 0.1 eV/Å is fine for screening atomic positions; use 0.02 to 0.05
  before computing phonons or comparing small energy differences.
- **Cell relaxation needs a tighter `fmax`.** With `relax_cell`, a stress counts
  as converged when stress × volume per atom < `fmax`, so at 0.1 eV/Å stresses
  up to about 1 GPa remain. Use `fmax` ≤ 0.01 for lattice constants.
- `model`: keep "0.3.0" unless you need r2SCAN-level energies ("r2scan").
- `device`: "cpu" is reproducible; "auto" uses a GPU if available, which is
  faster for MD.
