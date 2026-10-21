---
name: pyopenms
description: >-
  Mass spectrometry calculations (pyOpenMS): exact masses and m/z of molecules
  and peptides with modifications, isotope patterns, in-silico protein digestion
  (trypsin and other proteases), theoretical fragment ions (b/y, c/z) for MS/MS,
  and summaries of mzML files. Use for "what m/z should I see", identifying a
  peak from its mass and isotope pattern, planning proteomics experiments, and
  checking peptide assignments.
---

## Recipes

- **Expected m/z:** `mass(formula="C8H10N4O2", charges=[1])` or
  `mass(peptide="SAMPLEM(Oxidation)K", charges=[1, 2, 3])`.
- **Is this peak my compound?** `isotope_pattern(formula=..., charge=1)` and
  compare peak spacing and relative intensities with the spectrum (Cl, Br, S give
  characteristic M+2 peaks).
- **Proteomics planning:** `digest(sequence_or_fasta, "Trypsin",
  missed_cleavages=1, min_length=6, max_length=30)` → `fragment_ions(peptide,
  max_charge=2)` for the peptides of interest.
- **Data file overview:** `mzml_summary("run.mzML")`.

## Interpreting

- Monoisotopic masses are for the most abundant isotopes; large molecules'
  most intense peak is often M+1 or higher (see isotope_pattern).
- Mass error in ppm = (measured - theoretical) / theoretical x 1e6.

## Pitfalls

- Modifications use OpenMS names in parentheses after the residue (e.g.
  "C(Carbamidomethyl)", "M(Oxidation)", "S(Phospho)").
- Adducts other than protons (Na+, NH4+, K+) are not included in `mass`; add
  their mass difference.
