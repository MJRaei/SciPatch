---
name: ase-emt
description: >-
  Quick, approximate atomistic simulations of simple metals (Al, Cu, Ag, Au, Ni,
  Pd, Pt) with ASE's effective-medium theory (EMT): build bulk crystals, compute
  energies and forces, relax structures, and find equilibrium lattice constants
  and bulk moduli. Use for teaching, fast sanity checks, or testing a workflow
  before running DFT or machine-learned potentials.
---

## Recipes

- **Lattice constant and bulk modulus:** `equation_of_state(element="Cu")`. One
  call, no files needed.
- **Make a structure to feed other tools:** `build_bulk(element="Au", repeat=2)`
  writes `bulk.cif` and returns its absolute path. Pass that path to `energy`,
  `relax`, or to structure-based tools from other packages.
- **Relax a structure:** `relax(structure=<path>)`. Use `relax_cell=true` to
  also relax the volume; the relaxed structure path is returned.

## Interpreting results

- EMT energies are measured from EMT's own reference state, so a perfect crystal
  has an energy close to **zero**, not a cohesive energy. Only compare energy
  differences computed with EMT.
- Lattice constants are usually within 1 to 2% of experiment; treat bulk moduli
  and anything involving surfaces or defects as qualitative.
- For other elements (Fe, Si, O, ...) the tool raises an error by design; use
  a universal ML potential or DFT tool instead.
