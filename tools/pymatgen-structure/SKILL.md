---
name: pymatgen-structure
description: >-
  Everyday crystal-structure operations: find the space group and symmetry,
  get standard conventional or primitive cells, build supercells, convert
  between CIF, POSCAR, extended XYZ and other formats, simulate a powder X-ray
  diffraction (XRD) pattern, and check whether two structures are the same.
  Use to prepare structures for simulation tools, identify phases, or compare
  computed structures with known ones.
---

## Recipes

- **Prepare a simulation cell:** `make_supercell(structure, scaling=[3, 2, 2])`.
  For MD, aim for at least about 100 atoms and at least about 10 Å along each
  direction; the returned lattice lengths tell you.
- **Identify a relaxed structure:** `symmetry(structure, symprec=0.1)` after a
  relaxation; compare with the space group you expected.
- **Compare with experiment:** `xrd_pattern(structure)` gives peak positions
  (2θ, Cu Kα by default) and the plot; match peak positions first.
- **Did the relaxation change the structure?** `compare(initial, relaxed)`;
  `match: false` means a real structural change, not just small displacements.
- **Hand files to other tools:** `convert(structure, output="POSCAR")` or
  `output="frames.extxyz"`.

## Pitfalls

- Default `symprec` (0.01 Å) is strict; computed or measured structures often
  need 0.1 Å. Report the tolerance with the space group.
- The primitive cell may look very different from the conventional one (e.g.
  rhombohedral vectors for fcc); use the conventional cell for lattice constants.
- Simulated intensities ignore texture and broadening; don't read too much into
  small intensity differences.
