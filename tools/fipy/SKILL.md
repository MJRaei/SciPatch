---
name: fipy
description: >-
  Diffusion and phase-field microstructure simulations with NIST's FiPy.
  diffusion_1d gives concentration profiles through a slab, cylinder, or sphere
  for carburizing, nitriding, decarburization, dopant drive-in, diffusion
  couples, hydrogen charging, drying, and outgassing, with constant, Arrhenius
  (D0, Q, T), or concentration-dependent diffusivity; it finds case depths and
  the time to reach a concentration at a depth. spinodal_decomposition simulates
  phase separation and coarsening of a binary mixture (Cahn-Hilliard) and gives
  the characteristic length scale over time.
---

## Recipes

- **Case hardening time:** `diffusion_1d(length_m=0.005, diffusivity_m2_s=D,
  initial_concentration=c0, left=cs, target_concentration=c, target_position_m=x)`
  → `target.time_s`. Use `d0_m2_s`, `activation_energy_kj_mol`, `temperature_c`
  when D must come from Arrhenius data.
- **Case depth after a treatment:** give `times_s` and `target_concentration`
  without a position → `depth_at_target_m` at each time.
- **Diffusion couple:** `initial_concentration=1, right_initial_concentration=0`,
  both ends closed; `diffusivity_table=[[c, D], ...]` if D depends on composition.
- **Drying or outgassing of a particle or fibre:** `geometry="sphere"` or
  `"cylinder"`, `length_m` = radius, `right=0` →
  `fraction_to_equilibrium` over time.
- **Spinodal microstructure:** `spinodal_decomposition(mean_composition=0.4,
  time=500)`; show the plot; give W, kappa, and M to get metres and seconds.

## Interpreting

- `diffusion_length_m` = sqrt(D t) sets the penetration scale; profiles reach
  about 2 sqrt(D t).
- `far_end_changed_fraction` above ~0.01 means the body was not semi-infinite.
- Spinodal: decomposition only for compositions between the spinodal
  compositions; the early length scale equals `fastest_growing_wavelength`, and
  later domains coarsen (roughly as t^(1/3)).

## Pitfalls

- Concentration units are whatever you use consistently (wt%, at%, mol/m3).
- For a cylinder or sphere, x = 0 is the centre; the surface is `right`.
- Real carburizing and nitriding involve surface reactions and phase formation
  that this pure-diffusion model omits.
