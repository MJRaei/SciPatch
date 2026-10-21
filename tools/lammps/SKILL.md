---
name: lammps
description: >-
  Classical molecular dynamics and crystal properties with LAMMPS: relaxed
  lattice constants, cohesive energies and full elastic tensors at 0 K, and
  NVT/NPT/NVE molecular dynamics of metals, semiconductors, carbon, liquids and
  amorphous solids with EAM, Stillinger-Weber, Tersoff, AIREBO, SNAP, ACE, or any
  LAMMPS pair style; or run your own LAMMPS input script. Use for systems of
  thousands to millions of atoms where DFT is too slow, when a fitted potential
  exists for the elements.
---

## Recipes

- **Which potentials exist?** `list_potentials(["Cu", "Ni"])`; pick one and cite
  the paper it returns. More: NIST Interatomic Potentials Repository or OpenKIM;
  pass the downloaded file's path as `potential`.
- **Lattice + elastic constants:** `crystal_properties("Cu.cif", "Cu_mishin1.eam.alloy")`
  with a conventional cell → `elastic_constants_gpa.C11/C12/C44`, `bulk_modulus_gpa`.
- **Alloys from single-element EAM files:** `potential=["Cu_u3.eam", "Ni_u3.eam"]`.
- **Any pair style:** `pair_style="lj/cut 10.0", pair_coeff=["* * 0.0104 3.40"]`
  (atom types follow the order in which elements first appear).
- **Thermal expansion / liquid density:** `simulate(..., ensemble="npt",
  temperature_k=T)` at several T → `average_cell_lengths_angstrom`,
  `average_density_g_cm3`. Use `barostat="iso"` for liquids.
- **Diffusion:** `simulate(...)` at high T, then the pymatgen-diffusion tool on
  `trajectory` with `frame_interval_fs`.
- **Your own input:** `run_script("in.melt", files=["data.system"], processes=4)`.
  Installed potentials can be named without a path in the script.
- **ReaxFF** (combustion, oxidation, reactive chemistry): `run_script` with
  `units real`, `pair_style reaxff NULL`, `fix qeq/reaxff`; the CHO, Fe-O-C-H,
  Zn-O-H and ammonia-borane force fields are installed.

## Pitfalls

- A potential is only as good as its fit. The bundled Tersoff Si gives C44 = 10 GPa
  (experiment 80); always report the potential and compare with experiment or DFT.
- Cohesive energies from SNAP/ACE models are not meaningful (fitted to DFT total
  energies); compare their energy differences instead.
- Elastic constants are in the LAMMPS frame; for crystal-axis values give the
  conventional cell (cubic axes along x, y, z).
- MD averages from short runs or small cells are noisy; repeat with more steps
  and check the standard deviations returned.
- Use 0.5 fs time steps with hydrogen (AIREBO/REBO hydrocarbons).
