---
name: robocrys
description: >-
  Describe a crystal structure in words with robocrystallographer: mineral
  prototype (rutile, perovskite, ...), space group, dimensionality (molecular,
  chains, layers, framework), coordination polyhedra and whether they share
  corners, edges, or faces, octahedral tilts, and bond lengths. site_environments
  gives each site's coordination number, neighbours and bond lengths, geometry,
  and its ChemEnv polyhedron with a continuous symmetry measure. Use to explain or
  compare structures from CIF or POSCAR files, or results of relaxations and
  structure prediction.
---

## Recipes

- **Explain a structure:** `describe(file)`; quote the description and the
  mineral (say "similar to" when `exact_match` is false).
- **Coordination details:** `site_environments(file)` → coordination numbers,
  bond-length ranges, polyhedra (`chemenv.symbol`, e.g. O:6 octahedron, T:4
  tetrahedron, T:6 trigonal prism) and their distortion (`continuous_symmetry_measure`).
- **Octahedral tilts:** tilt = 180° minus the corner `connection_angles_deg`.
- **Is it layered?** `dimensionality` 2 and `components[].orientation` (Miller
  indices of the layers); `van_der_waals_layers` lists the stacking.

## Pitfalls

- Oxidation states are guessed when absent; pass `oxidation_states=false` for
  intermetallics or if the guess is implausible.
- Disordered (partial occupancy) structures must be ordered first.
- Coordination numbers come from a geometric neighbour finder; long or weak
  contacts can change them.
