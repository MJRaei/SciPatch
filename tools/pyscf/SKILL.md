---
name: pyscf
description: >-
  Accurate ab initio quantum chemistry for molecules with PySCF: Hartree-Fock,
  DFT (B3LYP, PBE0, wB97X, M06-2X, ...), MP2, and CCSD(T) energies; HOMO-LUMO
  gaps, dipole moments, and charges; geometry optimization; vibrational
  frequencies, zero-point energy, enthalpy and Gibbs free energy; and excited
  states and UV-Vis spectra (TDDFT). Accepts SMILES, structure files, or
  coordinates. Use when results must be more accurate than semiempirical (xtb)
  or force-field methods, for reaction and conformer energies, or as a
  reference to check machine-learned potentials.
---

## Recipes

- **Energy and properties:** `single_point("CCO", method="b3lyp", basis="def2-svp")`.
  Charge and radicals come from the SMILES (`[NH4+]` is +1, `[CH3]` has one
  unpaired electron); for files, pass `charge` and `unpaired_electrons`.
- **Typical workflow:** `xtb.optimize` (fast pre-optimization) →
  `pyscf.optimize(optimized_structure, method="b3lyp", basis="def2-svp")` →
  `pyscf.frequencies(..., optimize_first=False)` on that geometry (0 imaginary
  frequencies confirms a minimum) → `single_point` with a larger basis
  (`def2-tzvp`) for the final energy.
- **Reaction energies:** compute every species with the same method and basis
  and subtract `energy_hartree` (1 Eh = 627.51 kcal/mol = 27.211 eV); for free
  energies, subtract `free_energy_hartree` from `frequencies`.
- **Benchmark-quality energies of small molecules:** `method="ccsd(t)"` with
  `basis="cc-pvtz"` (feasible up to roughly 10 heavy atoms with cc-pVDZ, fewer
  with cc-pVTZ).
- **UV-Vis:** `excited_states(molecule, method="cam-b3lyp", basis="def2-svpd")`;
  bright states have large `oscillator_strengths`, and `wavelengths_nm` gives
  the absorption positions.
- **Inline geometry:** `molecule="O 0 0 0; H 0 0.757 0.587; H 0 -0.757 0.587"` (Angstrom).

## Choosing method and basis

| Purpose | Method | Basis |
|---|---|---|
| quick test | hf or b3lyp | sto-3g, 6-31g |
| geometries, frequencies | b3lyp, pbe0 | def2-svp |
| reaction energies | pbe0, wb97x, m06-2x | def2-tzvp |
| reference values (small molecules) | ccsd(t) | cc-pvtz |
| excited states | cam-b3lyp, wb97x | def2-svpd, aug-cc-pvdz |

## Pitfalls

- No dispersion correction is applied: binding energies of non-covalent
  complexes and conformer energies from b3lyp or pbe0 are unreliable.
- Cost grows quickly: DFT with def2-svp handles a few dozen atoms in minutes;
  frequencies cost much more than single points; CCSD(T) scales as N^7.
- A SMILES gives one conformer; for flexible molecules, explore conformers
  (e.g. with xtb) before comparing energies.
- Report method, basis, and whether the geometry was optimized with every number.
