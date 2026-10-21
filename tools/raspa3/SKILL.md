---
name: raspa3
description: >-
  Simulate gas adsorption in porous materials (zeolites, MOFs) by Monte Carlo
  with RASPA3: adsorption isotherms of CO2, N2, and methane, uptake and
  selectivity from mixtures such as CO2/N2 flue gas, Henry coefficients for fast
  screening, and heats of adsorption. Bundled frameworks: silicalite (MFI),
  HKUST-1 (Cu-BTC), MOF-5 (IRMOF-1), CALF-20; or any CIF file (e.g. from the CoRE
  MOF database). Use for carbon capture, methane storage, and comparing sorbents.
---

## Recipes

- **Isotherm:** `adsorption_isotherm("MFI", "CO2", 298, [0.1, 0.5, 1, 5])`; show
  the plot. Each pressure runs in parallel on the CPU cores.
- **Flue-gas selectivity:** `mixture_adsorption("CALF-20", {"CO2": 0.15, "N2":
  0.85}, 1.0, 298)`; report selectivity and uptake of each gas.
- **Quick screening of several materials:** `henry_coefficient(framework, ["CO2",
  "N2"])` for each; the CO2/N2 ratio is the low-pressure selectivity.
- **Your own material:** pass the CIF path; check `framework_force_field` and
  `framework_charges` in the result and tell the user what was used.

## Interpreting

- Loadings are absolute (mmol/g = mol/kg). They correspond to "total" uptake and
  exceed the excess uptake that experiments report, noticeably above ~10 bar.
- Every value has an error; if differences between materials are within the
  errors, rerun with more `cycles`.
- `enthalpy_of_adsorption_kj_per_mol` is negative; its magnitude is the isosteric
  heat.

## Pitfalls

- CIF files must be activated frameworks: remove solvent and counter-ions you do
  not want as part of the framework.
- Without partial charges in the CIF, CO2 and N2 uptakes are underestimated;
  prefer CIFs with DDEC or similar charges (CoRE MOF provides them).
- Open metal sites, flexibility, and defects are not modelled; expect 10-20%
  agreement with experiment at best, and N2 in silicalite comes out low.
- Defaults (5000 cycles) take minutes per point for CO2 in large cells.
