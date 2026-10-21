---
name: cantera
description: >-
  Combustion and gas-phase chemistry with Cantera: adiabatic flame
  temperatures, chemical equilibrium compositions, laminar flame speeds,
  ignition delay times, and thermodynamic properties (Cp, H, S, G) of species,
  with detailed reaction mechanisms (GRI-Mech 3.0 for natural gas and hydrogen).
  Use for fuel and flame questions, emissions (CO, NO at equilibrium), and
  high-temperature gas thermodynamics.
---

## Recipes

- **How hot does it burn?** `adiabatic_flame_temperature("CH4:1")`; scan with
  `equivalence_ratio=[0.6, 0.8, 1.0, 1.2, 1.4]` (plot included).
- **Hydrogen blending:** `fuel="CH4:0.7, H2:0.3"` in any function.
- **Oxy-fuel:** `oxidizer="O2:1"`.
- **Flame speed:** `flame_speed("CH4:1", equivalence_ratio=0.8)` (tens of
  seconds); hydrogen: `mechanism="h2o2.yaml"`.
- **Ignition:** `ignition_delay("CH4:1", temperature_k=1400, pressure_atm=10)`.
- **Equilibrium of any mixture:** `equilibrium("CO2:1, H2:1", 1200)`.
- **Other fuels:** pass a Cantera YAML mechanism file (convert Chemkin files
  with Cantera's ck2yaml); `nasa_gas.yaml` has thermodynamics for many species.

## Pitfalls

- GRI-Mech 3.0 has no octane, diesel, or other large hydrocarbons; a missing
  species is refused. Use a mechanism made for that fuel.
- Adiabatic temperatures are upper bounds; real flames lose heat.
- Report the mechanism with every number.
