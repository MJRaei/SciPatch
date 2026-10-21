---
name: mdanalysis
description: >-
  Analyze molecular dynamics trajectories (GROMACS, AMBER, CHARMM/NAMD, LAMMPS,
  OpenMM, extended XYZ) with MDAnalysis: RMSD and RMSF of proteins or ligands,
  radius of gyration, radial distribution functions and coordination numbers,
  and mean squared displacement with diffusion coefficients. Use after an MD run
  (e.g. from the openmm, lammps, or mace tools) to check stability, flexibility,
  solvation shells, or transport.
---

## Recipes

- **What is in the files?** `info("system.pdb", "traj.dcd")`.
- **Protein stability:** `rmsd(top, traj)` (backbone) → plateaued RMSD means a
  stable fold; `radius_of_gyration(top, traj)` for compaction or unfolding.
- **Flexible regions:** `rmsf(top, traj)` → `most_mobile` residues.
- **Ligand pose stability:** `rmsd(top, traj, selection="resname LIG and not element H")`.
- **Solvation shell:** `rdf(top, traj, selection="element Li", selection2="name OW")`
  → first peak and coordination number.
- **Diffusion:** `msd(top, traj, selection="element Li")`; check `fit_r_squared`
  and the MSD plot, then refit with `fit_start_ps`/`fit_end_ps` on the linear part.
- **Motel MD outputs:** pass the `.extxyz` trajectory alone as `topology`, with
  `timestep_ps` = the tool's `frame_interval_fs` / 1000.

## Selections

`"protein"`, `"backbone"`, `"name CA"`, `"resname SOL and name OW"`,
`"element Li"`, `"resid 10:50"`, `"segid A"`, `"around 5 resname LIG"`,
combined with `and`, `or`, `not`.

## Pitfalls

- XTC/DCD need a topology (TPR, PSF, PRMTOP, GRO, PDB) with the same atom order.
- Some formats store no time step: pass `timestep_ps`, or times and D are off.
- MSD at long lag times is noisy; diffusion from short runs is uncertain.
