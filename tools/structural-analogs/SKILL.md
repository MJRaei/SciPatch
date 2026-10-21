---
name: structural-analogs
description: >-
  Find materials with the same crystal structure type (isostructural analogs,
  prototypes) in the Materials Project for a material ID or a structure file,
  with their band gaps, formation energies, stability, and volumes. Use to
  estimate the properties of a new or hypothetical compound by analogy, to find
  element substitutions in a known structure, or to see which chemistries adopt
  a structure type. Needs a free Materials Project API key.
---

## Recipes

- **Estimate a new compound's properties:** relax its structure (ml-potentials),
  then `structural_analogs(structure="relaxed.cif")`. Reason by analogy across
  the closest analogs: "A is to B as C is to D", e.g. how swapping Na for K
  changes the volume, then apply the same change to the target. State which
  analogs the estimate rests on.
- **Substitutions in a known structure:** `structural_analogs(material_id=...)`,
  then read which elements occupy each site in stable analogs
  (`energy_above_hull_ev_per_atom` near 0).
- Check candidates with materials-project (stability, details) and
  ml-potentials or DFT (energies) before trusting an analogy.

## Interpreting

- `rms` is the structural mismatch (0 = identical arrangement after scaling).
  `kinship` counts the reference's elements that an analog has, or replaces by
  an element of the same periodic-table group: for NaCl, KCl scores 2 and MgO 0.
  The list is best first: closest match, then highest kinship, then most stable.
  `loose_matches_left_out` counts matches above `max_rms` (0.3), which are often
  a different structure type.
- `properties` gives the median and range over all analogs: a wide band gap
  range means the elements matter more than the structure.
- The project's tests with GPT-5-mini: analogies lowered the mean error of
  formation energies (0.64 to 0.35 eV/atom) and volumes (110 to 71 Å³ per
  cell) but not of band gaps (0.96 to 1.01 eV). Use analogies for formation
  energy and volume; compute band gaps instead.

## Pitfalls

- Values are DFT (PBE) values from the Materials Project, not experiment.
- Common structure types have many analogs: cubic perovskites (SrTiO3) have
  about 1,400, compared in about 20 s; read the first ones, or use `properties`.
