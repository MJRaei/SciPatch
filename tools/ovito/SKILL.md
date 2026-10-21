---
name: ovito
description: >-
  Analyze atomistic simulations of crystals with OVITO: classify each atom's
  local structure (FCC, BCC, HCP, icosahedral, diamond, other) by adaptive CNA or
  polyhedral template matching, count vacancies and interstitials (Wigner-Seitz),
  and extract dislocation lines with Burgers vectors and densities (DXA). Use on
  LAMMPS or other MD/relaxation output to follow melting, phase transformations,
  radiation damage, grain boundaries, stacking faults, and plasticity.
---

## Recipes

- **What phase is this?** `structure_types("dump.lammpstrj")` → counts and
  fractions per structure in the last frame; `main_fraction_by_frame` tracks
  melting or crystallization over a trajectory.
- **Hot or strained crystals:** `method="ptm"` (most robust to thermal noise).
- **Diamond/zincblende (Si, Ge, SiC, GaAs):** `method="diamond"`.
- **Stacking faults in fcc:** HCP-classified atoms inside an FCC crystal
  (`structure_types`, then look at `output` in OVITO).
- **Radiation damage:** `point_defects("cascade.dump", "perfect.data")` → vacancies,
  interstitials, Frenkel pairs per frame.
- **Plasticity:** `dislocations("deformed.dump", lattice="fcc")` → total length,
  density (m^-2), 1/2<110> perfect vs 1/6<112> Shockley partial lengths.
- **Chain with lammps:** pass the lammps tool's `trajectory` or `final_structure`.

## Pitfalls

- "Other" atoms are expected at surfaces, grain boundaries and defect cores.
- Give `lattice` = the material's crystal structure for DXA (bcc for Fe, W, Mo).
- Wigner-Seitz needs a defect-free reference with the same cell and orientation.
