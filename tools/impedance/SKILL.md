---
name: impedance
description: >-
  Analyse electrochemical impedance spectra (EIS) with impedance.py: fit
  equivalent circuits (Randles, constant-phase elements, Warburg diffusion,
  Gerischer, transmission lines) to get ohmic, charge-transfer, and diffusion
  resistances and capacitances; simulate spectra of a circuit; and check data
  quality with the Kramers-Kronig (Lin-KK) test. Reads CSV and Gamry, Autolab,
  BioLogic, Parstat, ZPlot, VersaStudio, PowerSuite, and CH Instruments files.
  Use for batteries, fuel cells, corrosion, coatings, and sensors.
---

## Recipes

- **Check the data first:** `kramers_kronig(file)`; if not valid within ~1%,
  results of any fit are doubtful (drift, nonlinearity).
- **Fit:** `fit_circuit(file, "randles-cpe")` for one arc,
  `"randles-warburg"` for an arc plus diffusion tail, `"two-arcs"`, or a custom
  string such as `"R0-p(R1,CPE1)-p(R2-Wo1,CPE2)"` with `initial_guess`; show the
  plot and report each parameter with its error.
- **What would a circuit look like?** `simulate("R0-p(R1-W1,CPE1)", [...])`.

## Interpreting

- R0: ohmic (electrolyte, contacts); R1 in parallel with a capacitance/CPE:
  charge transfer; Warburg: diffusion; arc top frequency 1/(2 pi R C).
- `rms_relative_residual` of a few percent or less indicates an adequate fit.

## Pitfalls

- Several circuits can fit equally well; justify the circuit physically.
- CPE parameters (Q, n) are not a capacitance; convert before comparing.
- CSV columns are frequency, Z', Z'' with Z'' negative for capacitive data.
