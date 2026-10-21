---
name: gpaw
description: >-
  First-principles density functional theory (DFT) for crystals with GPAW
  (plane waves, PAW): total energies, forces and stress, relaxation of atoms
  and lattice, equation of state (equilibrium volume, bulk modulus), band
  structures and band gaps, Fermi level, and magnetic moments. Use as the
  reference method to check machine-learned potentials (CHGNet, MACE), for
  electronic properties such as gaps and metallicity, and for magnetism.
---

## Recipes

- **Ground state:** `scf("LiFePO4.cif")` gives the energy, gap, stress,
  and magnetic moments, and writes `scf.gpw` for `band_structure`.
- **Check an ML potential:** relax with `chgnet.relax` or `mace.relax` (fast),
  then `gpaw.scf` on the relaxed structure. Compare forces and stress (near zero
  if the ML structure is right) and energy differences between structures, not
  absolute energies across codes.
- **Lattice constant and bulk modulus:** `equation_of_state(structure)` near the
  expected volume; or `relax(structure)` for low-symmetry cells.
- **Band structure:** `band_structure("scf.gpw")` reuses the ground state;
  `band_gap_ev` and `gap_is_direct` follow the high-symmetry path.
- **Convergence check:** repeat a key number with a higher `ecut_ev` (e.g. 500 →
  700) and `kpoint_density` (4 → 6); keep the settings once it changes by less
  than about 1 meV/atom.

## Cost

Run time grows with atoms³ and with the k-point count. A 2-atom cell takes
seconds to a minute, 20-50 atoms take minutes to hours, and magnetic or
metallic systems cost more (spin and denser k-points). For large cells, lower
`kpoint_density` (the mesh needs fewer points as the cell grows), and start
from a structure pre-relaxed with an ML potential.

## Pitfalls

- PBE band gaps are too small (Si: about 0.6 eV vs 1.17 eV measured); do not
  report them as experimental gaps.
- Transition-metal oxides often need DFT+U, which is not set up here.
- Spin polarization switches on automatically for Cr, Mn, Fe, Co, Ni, and Gd,
  starting ferromagnetic; set moments in the structure file (extended XYZ) for
  antiferromagnets.
- Report the functional, cutoff, and k-point mesh (`settings`) with every number.
