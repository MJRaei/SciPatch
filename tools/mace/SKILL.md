---
name: mace
description: >-
  Machine-learned foundation potentials from the MACE family: energies, forces,
  stresses, relaxations, and molecular dynamics for inorganic materials across
  89 elements (MACE-MP) and for organic molecules (MACE-OFF). Use as a fast
  alternative to DFT, to pre-relax structures, or as an independent second
  opinion next to CHGNet; the function names and outputs match the CHGNet tool.
---

## Recipes

- **Cross-check another potential:** run the same `predict` or `relax` call here
  and with CHGNet; agreement within ~20-30 meV/atom and ~0.5% in lattice
  constants is typical. Report both when they disagree.
- **Lattice constant:** `relax(structure, fmax=0.005)` (cell relaxation is on by
  default), then read `lattice`.
- **Organic molecules:** `predict(molecule.xyz, model="off23-small")` or
  `relax(..., model="off23-small")`. MACE-MP models also run on molecules, but
  MACE-OFF is trained for them. Check the license (non-commercial) first.
- **Molecular dynamics:** `molecular_dynamics(structure, temperature_k=800,
  steps=5000)` runs in the background with progress; pass `trajectory` and
  `frame_interval_fs` to a diffusion-analysis tool.

## Choosing a model

- `mpa-0-medium` (default): newest, trained on MPtrj + Alexandria; best general choice.
- `mp-0-medium`: the model described in the MACE-MP paper; use to reproduce published work.
- `mp-0-small`: faster, less accurate; for large systems or long MD.
- `off23-small` / `off23-medium`: organic molecules only; Academic Software
  License (no commercial use).

Use `precision="float64"` (default) for relaxations, energy differences, and
phonons; `float32` is faster for MD.
