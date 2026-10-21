---
name: pybamm
description: >-
  Simulate lithium-ion battery cells with physics-based models (PyBaMM): discharge
  curves, usable capacity and energy, average voltage, rate capability, cell
  heating, and cycling protocols such as CC-CV charging, rests, and power steps,
  for published cells (LG M50 21700 NMC811/graphite-SiOx, NCA, LFP, sodium-ion,
  and more). Use for "how much energy at 2C", "how hot does the cell get",
  charging protocols, and comparing cells.
---

## Recipes

- **Capacity and energy at a rate:** `discharge(c_rate=1)` with the default
  Chen2020 (LG M50) cell; show the plot.
- **Rate capability:** `rate_capability([0.2, 0.5, 1, 2])`: relative capacity
  shows how much is lost at high current.
- **Charging protocol or drive cycle:** `run_experiment(["Charge at 1C until 4.2
  V", "Hold at 4.2 V until C/50", "Rest for 1 hour", "Discharge at 2 W for 10
  minutes"])`; per-step charge (Ah, negative when charging), energy, end voltage.
- **Other cells:** `parameter_sets()` lists them (chemistry and source); pick one
  close to the user's cell and say which.

## Interpreting

- Capacity depends on rate, temperature, and cut-off voltage; quote all three.
- "DFN" is the reference model; "SPMe" is faster and fine up to about 1C; "SPM"
  only at low rates.
- With `thermal="lumped"` the cell heats up; isothermal results at high rates
  overstate performance for cells without strong cooling.

## Pitfalls

- No ageing: repeated cycles are identical. Degradation needs a parameter set
  with degradation parameters and PyBaMM's degradation options.
- Parameter sets describe specific cells; results for a different cell are
  only indicative.
