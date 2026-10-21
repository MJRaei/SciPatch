---
name: thermo
description: >-
  Chemical engineering thermodynamics: properties of about 20,000 chemicals
  (boiling and critical points, density, heat capacity, viscosity, thermal
  conductivity, vapor pressure, latent heat, surface tension), vapor-liquid
  equilibrium of mixtures (flash, bubble and dew points, T-x-y diagrams,
  azeotropes) with UNIFAC or Peng-Robinson, and pressure drop in pipes. Use for
  distillation and separation questions, "what boils first", azeotropes, physical
  property lookups for organics and solvents, and pipe sizing.
---

## Recipes

- **Property lookup:** `chemical("toluene", temperature_k=350)`; names, CAS, or
  SMILES work.
- **Distillation feasibility:** `binary_vle("ethanol", "water")`; show the T-x-y
  plot and report any azeotrope (it limits purity by plain distillation).
- **Bubble/dew point or flash:** `flash({"ethanol": 0.3, "water": 0.7},
  pressure_pa=101325, vapor_fraction=0)` (bubble), `vapor_fraction=1` (dew), or
  `temperature_k=...` for a split.
- **Gases and hydrocarbons at pressure:** `model="Peng-Robinson"`.
- **Pipe sizing:** `pipe_flow(diameter_m, length_m, volumetric_flow_m3_s=...,
  fluid="water", temperature_k=...)`.

## Interpreting

- Units are SI: Pa (1 bar = 1e5 Pa), K, kg/m3, J/kg, Pa s.
- UNIFAC is a group-contribution prediction: good for screening, check key
  results against measured VLE data before design.

## Pitfalls

- Do not use Peng-Robinson for alcohol-water or other strongly polar mixtures;
  use UNIFAC.
- Liquid-liquid phase splitting (e.g. butanol-water) is not detected.
