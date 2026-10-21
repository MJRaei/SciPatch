---
name: phonopy
description: >-
  Phonon calculations with phonopy using the CHGNet universal potential (or EMT
  for simple metals): phonon band structure and density of states, dynamical
  stability (imaginary modes), Γ-point frequencies, zero-point energy, and
  vibrational free energy, entropy, and heat capacity versus temperature. Use to
  check whether a predicted or relaxed crystal is dynamically stable, or to
  estimate finite-temperature thermodynamics.
---

## Recipes

- **Is this structure stable?** Relax it first with the same force model
  (CHGNet `relax` with `fmax` ≤ 0.01), then `phonons(relaxed_structure)` and read
  `dynamically_stable` and `min_frequency_thz`. Imaginary modes (negative
  frequencies) mean the structure wants to distort.
- **Thermodynamics:** `phonons(structure, temperatures_k=[300, 600, 900])` gives
  free energy, entropy, and heat capacity at each temperature; compare free
  energies of polymorphs at the same temperature.
- **Show the evidence:** `band_plot` and `dos_plot` are PNG files to show the user.

## Interpreting results

- CHGNet frequencies are typically 10-20% too low (systematic softening); trust
  stability and trends more than absolute frequencies.
- Thermal values are per mole of primitive cells (`n_primitive_atoms` atoms);
  the `per_atom` heat capacity is easier to compare across materials.
- Supercells default to at least 10 Å per direction. If imaginary modes appear
  far from Γ only, try a larger supercell before concluding the crystal is unstable.
