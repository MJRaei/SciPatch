---
name: larch
description: >-
  X-ray absorption spectroscopy (XAS, XANES, EXAFS) with xraylarch. normalize
  finds the edge energy E0 and edge step and normalizes a spectrum; exafs
  extracts chi(k) and |chi(R)|; feff_paths runs FEFF on a CIF to get scattering
  paths; fit_shells fits them to data for bond distances, coordination numbers,
  and Debye-Waller factors; linear_combination fits XANES as a mixture of
  reference spectra (oxidation states, phase fractions). Reads XDI, Athena-style
  .xmu, and column files from synchrotron beamlines.
---

## Recipes

- **Oxidation state or phases:** `normalize(sample)` → compare `e0_ev` and the
  white line with references → `linear_combination(sample, [ref1, ref2, ...])`.
- **Local structure:** `exafs(sample)` (look at |chi(R)|) → `feff_paths(model.cif,
  absorber="Fe")` → `fit_shells(sample, [first-shell file, ...], rmin=1, rmax=3)`;
  report R ± error, sigma², S0² or N, the R-factor (≲ 0.02 is good).
- **Coordination numbers:** fit S0² on a reference compound, then
  `fit_shells(..., amplitude=S0²)` on the sample.
- Columns: pass `columns={"i0": "i0", "it": "itrans"}` for raw transmission or
  `{"i0": "i0", "if": "ifluor"}` for fluorescence when there is no mu column.

## Pitfalls

- |chi(R)| peak positions are not distances (about 0.3-0.5 Å shorter).
- Keep the number of variables below `independent_points`.
- S0² and N (and sigma²) correlate strongly; fix one from a reference.
- FEFF needs an x86-64 computer (Rosetta 2 on Apple silicon).
