---
name: zeopp
description: >-
  Pore geometry of porous materials (Zeo++): largest cavity diameter, pore-
  limiting diameter (largest free sphere), free sphere along each axis, channel
  dimensionality, and the surface area and pore volume available to a probe
  molecule, for zeolites, MOFs, COFs, and cages from a CIF. Use for "will this
  molecule fit through the pores", screening frameworks before adsorption
  simulations, and comparing pore sizes with zeolite database values.
---

## Recipes

- **Does a molecule fit?** `pore_geometry(cif)`; compare
  `largest_free_sphere_angstrom` with the molecule's kinetic diameter (CO2 3.3,
  N2 3.64, CH4 3.8, benzene 5.85 Å).
- **Surface area and pore volume for a gas:** `probe_radius=1.86` (N2) or
  `probe_radius=0` for the geometric pore volume.
- **Zeolites against the IZA database:** `radii="iza"`.
- **Before adsorption:** screen pores here, then `raspa3.adsorption_isotherm` on
  the promising CIFs.

## Interpreting

- Largest included sphere = largest cavity; largest free sphere = the narrowest
  window along the best path (what limits diffusion).
- `channel_dimensionality` 0 means the probe cannot travel through the
  framework (only isolated cavities).

## Pitfalls

- Remove solvent and guest molecules from the CIF first; resolve disorder.
- Values depend on the radius set; quote it when comparing with literature.
