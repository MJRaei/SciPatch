---
name: psi4
description: >-
  Interaction energies between two molecules with Psi4. sapt decomposes binding
  into electrostatics, exchange (Pauli repulsion), induction, and dispersion
  (SAPT0 to SAPT2+3, also open shell); interaction_energy gives counterpoise-
  corrected binding energies at HF, MP2, CCSD(T), DFT-D3 (b3lyp-d3bj,
  wb97x-d, ...), HF-3c, or CCSD(T)/CBS composites; benchmark_dimers provides
  the S22 and S66 reference complexes. Use for hydrogen bonds, pi-stacking,
  host-guest and drug-fragment contacts, and to explain why molecules bind.
---

## Recipes

- **Why do they bind?** `sapt(dimer="complex.xyz")` (SAPT0/jun-cc-pVDZ, fast)
  → report the four components and `dominant_attraction`.
- **How strongly?** `interaction_energy(dimer=..., method="b3lyp-d3bj",
  basis="aug-cc-pVDZ")` for larger systems; for small ones the benchmark recipe
  `method="mp2/aug-cc-pv[tq]z + D:ccsd(t)/aug-cc-pvdz"`.
- **Check a method:** `benchmark_dimers("S66")` → pick a complex →
  `interaction_energy(benchmark="S66-24", ...)` reports the deviation from the
  CCSD(T)/CBS reference.
- Build the complex with `rdkit.conformers`, `xtb.optimize`, or
  `crest.conformer_search`; the XYZ is split into two molecules automatically
  (or give `fragment_a_atoms`). Set `charge_a`/`charge_b` for ions.

## Pitfalls

- Energies are for the given geometry; optimize the complex first.
- SAPT0 is calibrated for jun-cc-pVDZ; larger basis sets do not make it better.
- CCSD(T) and SAPT2+ scale steeply; for larger complexes use SAPT0 or DFT-D3.
