---
name: reaktoro
description: >-
  Water and geochemical equilibrium (Reaktoro with PHREEQC databases): speciation
  of a water analysis (pH, ionic strength, species, saturation indices for
  calcite, gypsum, barite, silica, ...), mineral solubility and how much
  dissolves or precipitates, water in contact with air or CO2, solubility versus
  temperature, and brines (Pitzer). Use for scaling risk in process and cooling
  water, groundwater and seawater chemistry, CO2 in water, and "will this mineral
  precipitate".
---

## Recipes

- **Water analysis:** `speciate({"Ca": 80, "Mg": 20, "Na": 30, "Cl": 50, "SO4":
  60, "HCO3": 250}, units="mg/L", ph=7.6)`; positive saturation indices mean
  supersaturated (scaling risk), negative undersaturated.
- **Solubility:** `mineral_equilibrium(["Gypsum"])`, or with a background water
  `solutes={"Na": 0.5, "Cl": 0.5}`; Ca molality is the solubility.
- **Open to air:** `mineral_equilibrium(["Calcite"], gases={"CO2(g)": 0.00042})`
  (CO2 partial pressure in bar).
- **Versus temperature:** `solubility_curve("Gypsum", 0, 100)`.
- **Names:** `minerals(["Ca", "C", "S"])` lists minerals and gases of a database.

## Interpreting

- `dissolved_mmol` is per 1 kg of water with 1 mol of each mineral to start;
  negative values are precipitation.
- `charge_balance_error_percent` above ~5% means the analysis is incomplete or
  wrong; report it.

## Pitfalls

- Give the measured pH when you have it; otherwise the pH comes from charge
  balance and is sensitive to analysis errors.
- Above ~1 mol/kg ionic strength use `database="pitzer"`.
- Saturation does not mean precipitation: kinetics and nucleation are not
  modelled.
