---
name: ml-potentials
description: >-
  Fast machine-learned predictions for crystals and molecules with universal
  potentials (Orb-v3, MACE-MP/MPA, MACE-OFF, CHGNet, TensorNet/M3GNet): energy,
  forces, stress, magnetic moments, relaxation, molecular dynamics, elastic
  constants, bulk modulus, thermal expansion and heat capacity, formation
  energies, and side-by-side model comparison. Use to pre-relax structures
  before DFT, screen materials for stability and stiffness, simulate ionic
  motion, or get a quick, cross-checked estimate where DFT is too slow.
---

## Recipes

- **Relax, then analyze:** `relax(structure)` (Orb-v3 by default) returns the
  relaxed structure's path; pass it to `predict`, the property functions, or
  other tools.
- **Lattice constant:** `relax(structure, fmax=0.005)`, then read `lattice`.
- **Is this prediction trustworthy?** `compare_models(structure)`: four model
  families relax the same crystal; `volume_spread_percent` above a few percent,
  or one model far from the others, means check with DFT (gpaw, quantum-espresso).
- **Stiffness:** `elastic_constants(structure)` → bulk, shear, Young's moduli,
  Poisson's ratio; Pugh's ratio bulk/shear > 1.75 suggests ductile behavior.
- **Thermal expansion and heat capacity:** `thermal_properties(structure)`
  (quasi-harmonic; minutes). Volumetric expansion: divide by 3 for the linear
  coefficient of a cubic crystal.
- **Stable against the elements?** `formation_energy(structure)`; for stability
  against competing compounds, use materials-project.
- **Oxidation states (hint):** `predict(..., model="CHGNet-0.3.0")` returns
  magnetic moments: about 3 μB on Mn suggests Mn4+, 4 μB Mn3+, 5 μB Mn2+.
- **Organic molecules:** `predict` or `relax` with `model="MACE-OFF23-small"`
  (non-commercial license).
- **Diffusion:** `molecular_dynamics(structure, temperature_k=800, steps=5000)`
  on a supercell of about 100 atoms or more, then pymatgen-diffusion with the
  returned `trajectory` and `frame_interval_fs`.

## Choosing a model

- `Orb-v3-conservative-inf-mpa` (default): the most accurate here on materials
  benchmarks; MP-compatible energies.
- `MACE-MPA-0-medium`: independent second opinion; `MACE-MP-0-medium` to
  reproduce the MACE-MP paper.
- `CHGNet-0.3.0`: fast, with magnetic moments.
- `TensorNet-MatPES-PBE-2025.2`: fastest; pure PBE (no +U); `-r2SCAN-` variants
  are closer to experiment for many solids.

## Pitfalls

- Energies from models trained on different data (MPtrj, MatPES, OMat24) are
  not comparable; compare structures and properties instead.
- With cell relaxation, `fmax` also bounds the residual stress: use ≤ 0.01 for
  lattice constants.
- PBE-trained models inherit PBE errors (softer elastic moduli, larger lattices).
- Report the model with every number.
