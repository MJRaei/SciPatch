---
name: synthesis-recipes
description: >-
  Find how an inorganic material has been made: published synthesis recipes
  (precursors, balanced reactions, heating temperatures and times, atmospheres;
  41,300 text-mined solid-state and sol-gel recipes with DOIs), the most common
  precursor sets and temperatures, similar compositions in the Materials
  Project, and suggested routes for a new material from its closest analogs
  with known recipes. Use for "how do I synthesize X", choosing precursors or a
  calcination temperature, or planning a first synthesis of a new composition.
---

## Recipes

- **How has X been made?** `recipes("LiCoO2", synthesis_type="solid-state")`:
  read `common_precursors` and `highest_temperature_c` first (they summarize all
  recipes), then the individual recipes with DOIs.
- **A new composition:** `suggest_routes("LiNi0.85Co0.1Al0.05O2")` returns the
  nearest compositions that have recipes, with what to add or remove. Adapt the
  most common precursor set of the closest source.
- **Analogs in the Materials Project:** `similar_materials(formula)`, then
  materials-project (stability, structure) or ml-potentials for the candidates.
- **Is the target stable at all?** Check its energy above the hull with
  materials-project before planning a synthesis.

## Interpreting

- `distance` compares compositions only (standardized Magpie features): 0 is the
  same composition; the same elements in slightly different amounts are
  typically below 0.5; several units means different chemistry (for Li3InCl6 the
  nearest recipes are lithium tin sulfides at 3.6), so the "routes" give little
  guidance.
- Temperatures are the highest heating step of each recipe, in °C; `time_h` in
  hours.
- Text-mining errors are common: precursor formulas such as "LiHO" mean LiOH,
  and some recipes list unrelated precursors. Always give the user the DOI and
  advise reading the paper before an experiment.

## Pitfalls

- Doped and non-stoichiometric targets are separate entries; use
  suggest_routes to find them.
- The data stops around 2019-2020; new materials families (e.g. halide solid
  electrolytes) may have no close analogs.
- The first `suggest_routes` call after installing builds an index (about a
  minute); later calls take seconds.
