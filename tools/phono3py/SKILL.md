---
name: phono3py
description: >-
  Lattice thermal conductivity of crystals from phonon-phonon scattering
  (phono3py): kappa vs temperature in the relaxation-time approximation or the
  full Boltzmann equation, with optional isotope scattering, from a universal
  ML potential (any crystal structure, minutes) or from your own DFT forces.
  Use for thermoelectrics, thermal barrier coatings, heat spreaders, and
  screening materials by thermal conductivity.
---

## Recipes

- **Screen a material:** `thermal_conductivity("Mg2Si.cif")`; kappa from 100 to
  1000 K, with a plot. Small cells take a minute; large or low-symmetry cells
  need many more force calculations (use `cutoff_pair_distance`, e.g. 5, to
  reduce them).
- **Check stability first:** `phonopy.phonons` on the same structure; imaginary
  modes make kappa meaningless.
- **Converge:** repeat with a denser `mesh` (e.g. 19x19x19 for small cells)
  until kappa changes by less than a few percent.
- **DFT quality:** run the displaced supercells of a phono3py_disp.yaml in your
  DFT code, then `thermal_conductivity("phono3py_disp.yaml", forces="FORCES_FC3")`.
- **Second opinion on ML values:** `model="TensorNet-MatPES-r2SCAN-2025.2"`.

## Pitfalls

- Lattice part only: not for metals, where electrons dominate.
- Values are for perfect single crystals; real samples conduct less.
- ML potentials often underestimate kappa; report the model with every number.
