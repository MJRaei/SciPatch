---
name: coolprop
description: >-
  Look up reference-quality properties of fluids (CoolProp): density, enthalpy,
  entropy, heat capacity, speed of sound, viscosity, thermal conductivity, boiling
  points, vapor pressure, latent heat, and surface tension for water/steam, CO2,
  refrigerants (R134a, R410A, R32, ammonia, ...), air, hydrocarbons, cryogens, and
  more; mixtures and brines; p-h and T-s diagrams; humid-air psychrometrics (dew
  point, wet bulb, humidity ratio). Use for heat-transfer and process
  calculations, refrigeration and power cycles, and any "what is the density or
  viscosity of X at T and p".
---

## Recipes

- **One state:** `state("Water", temperature_k=353.15, pressure_pa=2e5)`; any two
  of temperature, pressure, density, quality, enthalpy, entropy.
- **Boiling point or vapor pressure:** `saturation("Ammonia", pressure_pa=1e5)`
  or `saturation("R134a", temperature_k=263.15)`; includes the latent heat.
- **Property curves for a design range:** `isobar(fluid, pressure_pa, t_min_k,
  t_max_k)`; show the plot, and the CSV has every property.
- **Refrigeration or power cycle sketch:** `diagram("R134a", "PH")` or
  `diagram("Water", "TS")`; compute each cycle point with `state`.
- **Air conditioning:** `humid_air(dry_bulb_k, relative_humidity=0.6)`.
- **Which name?** `fluids("propane")` finds names, aliases, and model references.

## Interpreting

- All units are SI: Pa (1 bar = 1e5 Pa), J/kg, J/(kg K), Pa s. Convert for the
  user (e.g. kJ/kg, bar, mPa s, °C = K - 273.15).
- Enthalpy and entropy have arbitrary zero points (per fluid); use differences.
- A state exactly at quality 0 or 1 is "saturated liquid" or "saturated vapor";
  inside the dome, cp, speed of sound, and transport properties are null.

## Pitfalls

- Mixtures: write mole fractions, "Nitrogen[0.79]&Oxygen[0.21]"; R4xx blends are
  available as pseudo-pure fluids ("R410A") or as mixtures ("R410A.mix").
- Brines: "INCOMP::MEG-30%" (ethylene glycol, 30% by mass); check that the
  temperature is above the freezing point.
