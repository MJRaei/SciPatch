---
name: matcalc
description: >-
  Mechanical and thermal properties of crystals from universal machine-learned
  potentials (matcalc with MatGL's TensorNet, M3GNet, and CHGNet models trained
  on MatPES): the full elastic tensor, bulk, shear and Young's moduli, Poisson's
  ratio and mechanical stability; equation of state; thermal expansion, heat
  capacity, and Gibbs free energy vs temperature (quasi-harmonic); and
  formation and cohesive energies. Use for fast screening of stiffness,
  ductility, thermal behavior, and stability of many materials.
---

## Recipes

- **Stiffness:** `elastic_constants("Li2O.cif")`; `bulk_modulus_vrh_gpa`,
  `shear_modulus_vrh_gpa`, and `poisson_ratio`. Pugh's ratio
  `bulk/shear > 1.75` suggests ductile behavior, below it brittle.
  `mechanically_stable: false` means the structure is not a minimum.
- **Thermal expansion and heat capacity:** `thermal_properties(structure)`
  (minutes; long-running). `at` lists 300 K and `t_max`; the CSV `table` has
  every temperature. The thermal expansion is volumetric (divide by 3 for the
  linear coefficient of a cubic crystal).
- **Is a compound stable against the elements?** `formation_energy(structure)`;
  negative is favorable. For stability against other compounds, compare with
  competing phases (`materials-project.search`).
- **Second opinion:** rerun with `model="TensorNet-MatPES-r2SCAN-2025.2"` (r2SCAN,
  closer to experiment for many solids) or `"CHGNet-MatPES-PBE-1M-2026.9"`;
  large disagreement between models signals low reliability.
- **Check against DFT:** `gpaw.equation_of_state` on the same structure.

## Pitfalls

- PBE-trained models reproduce PBE, which underestimates elastic moduli; do
  not compare them one-to-one with experiment.
- Relax first (the default): elastic constants of an unrelaxed structure are wrong.
- Quasi-harmonic results are meaningless if the phonons have imaginary modes
  (check with `phonopy.phonons` first) and unreliable near melting.
- Formation energies lack the Materials Project's anion corrections.
- Report the model name with every number.
