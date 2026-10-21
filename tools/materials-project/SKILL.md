---
name: materials-project
description: >-
  Look up known inorganic materials in the Materials Project database: find
  materials by formula, elements, or chemical system; check thermodynamic
  stability (energy above the convex hull) and what unstable compounds decompose
  into; get band gaps, formation energies, magnetism, elastic moduli, and ICSD
  identifiers; and download crystal structures (CIF) to start simulations.
  Requires a free API key (MP_API_KEY).
---

## Recipes

- **Is a composition known and stable?** `search(formula="LiMnO2")`: results are
  sorted by energy above hull; 0 means on the hull (stable).
- **Explore a chemical system:** `search(chemsys="Li-Mn-O", max_energy_above_hull_ev=0.05)`.
- **Start a simulation from a known structure:** `get_structure("mp-18767")`, then
  pass the CIF path to ml-potentials, phonopy, or the structure tools.
- **Why is it unstable?** `details(material_id)` lists `decomposes_to`.

## Setup

The user needs a free key from https://next-gen.materialsproject.org/api,
stored once with `motel secret set MP_API_KEY`. If a call fails because the key
is missing, tell the user exactly that.

## Pitfalls

- These are PBE/PBE+U (or r2SCAN) DFT values: gaps are too small, and energies
  above hull have tens of meV/atom uncertainty.
- Report the `database_version` with any number you quote.
- Prefer materials that are not `theoretical` when the user asks what exists.
