---
name: pymatgen-diffusion
description: >-
  Analyze ion transport in molecular dynamics trajectories with
  pymatgen-analysis-diffusion: mean squared displacement (MSD), diffusivity,
  ionic conductivity, Haven ratio, and Arrhenius fits of activation energy with
  extrapolation to room temperature. Use after an MD run (e.g. ml-potentials'
  molecular_dynamics) to quantify Li, Na, or other ion diffusion in battery
  materials and solid electrolytes.
---

## Recipes

- **One MD run:** `analyze_trajectory(trajectory, specie="Li", temperature_k=600,
  frame_interval_fs=20)`. ml-potentials' `molecular_dynamics` returns both the
  `trajectory` path and `frame_interval_fs`; pass them through unchanged.
  Discard equilibration with `skip_initial_ps` (1 ps is usually enough). The
  default analysis needs more than 1 ps of trajectory after skipping; plan MD
  runs of several ps at least (tens of ps for a reliable diffusivity).
- **Activation energy and room-temperature value:** run MD at three or more
  temperatures (e.g. 800, 1000, 1200 K), analyze each, then call
  `arrhenius_fit(temperatures_k, diffusivities_cm2_s, extrapolate_to_k=300)`.
  Add `structure` and `specie` to also get the extrapolated conductivity.
- **Show the evidence:** the MSD plot (`msd_plot`) should rise linearly; a flat
  MSD means the ions only vibrated.

## Interpreting results

- Read `warnings` and `ions_moved_beyond_hop_distance` before quoting a
  diffusivity. With no hops, report "below the detection limit" instead of the
  number.
- `diffusivity_std_cm2_s` is a statistical error from the MSD fit, not the
  uncertainty of the method.
- A Haven ratio below 1 means correlated (concerted) ion motion; the
  conductivity from the tracer diffusivity then underestimates the real one.
- For an Arrhenius fit, the temperatures should all be in the same phase, and
  the runs should be long enough that each diffusivity is well converged.
