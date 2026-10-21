---
name: openmm
description: >-
  Molecular dynamics of proteins, nucleic acids, and water with OpenMM: prepare
  a PDB structure (missing atoms, hydrogens at a chosen pH), solvate it with
  water and ions, minimize, equilibrate, and run constant-pressure MD; report
  temperature, density, energies, and RMSD, and write the trajectory. Ligands
  and other small molecules are parameterized with OpenFF Sage or GAFF; pure
  molecular liquids can be simulated for their density. Also computes and
  minimizes force-field energies of Amber-prepared systems. Use for
  structural stability and dynamics of biomolecules and protein-ligand
  complexes, solvent properties, and preparing structures for further modeling.
---

## Recipes

- **Is a protein structure stable in water?** `simulate("1abc.pdb", time_ps=1000)`
  (long-running; check `speed_ns_per_day` first with a short run). A C-alpha
  RMSD that levels off below about 0.2-0.3 nm means the fold is stable on that
  time scale; a steady rise means it is unfolding or the starting model is poor.
- **Faster, rougher:** `implicit_solvent="gbn2"` replaces the water box
  (no density or pressure).
- **Energies of an Amber system:** `energy("system.prmtop", coordinates="system.rst7")`
  gives the total and per-term energies; `minimize` relaxes clashes.
- **Protein with a ligand:** remove the ligand from the PDB, give its pose as an
  SDF with hydrogens: `simulate("protein.pdb", small_molecules=["ligand.sdf"])`.
  Check the ligand's protonation state first (e.g. `crest.protonation_sites`).
- **A molecule in water:** `simulate("molecule.sdf", box_nm=3)`; make the SDF with
  `rdkit.conformers` or `xtb.optimize`.
- **Liquid density:** `liquid("CCO")` (ethanol; about 5 minutes on a CPU).
- **Water properties:** `simulate("water", box_nm=3, water_model="opc")`.
- **Analyze the trajectory:** `trajectory.dcd` with `start_structure` (PDB) as
  the topology, in VMD, PyMOL, or MDTraj.

## Pitfalls

- Ligands left inside the PDB are refused; give them as SDF files instead.
- Small-molecule parameters (OpenFF Sage, AM1-BCC charges) take seconds to
  minutes per new molecule the first time.
- Missing loops are not rebuilt; chain breaks stay. Check the input structure.
- Nanoseconds are short: no folding, binding, or large conformational changes.
  Repeat with different `seed` values before trusting a trend.
- Use a box large enough that the solute never meets its periodic image
  (padding_nm of at least 1.0).
