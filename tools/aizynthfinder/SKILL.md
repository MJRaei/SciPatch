---
name: aizynthfinder
description: >-
  Plan how to synthesize a molecule (retrosynthesis): routes back to purchasable
  starting materials (17.4 million ZINC compounds) or the user's own inventory,
  ranked, with each reaction step and route images; one-step precursor
  suggestions with feasibility scores; and checks whether compounds are
  purchasable. Uses AiZynthFinder's template network trained on US patent
  reactions. Use for "how do I make this molecule", "what could this be made
  from", and "can I buy these starting materials".
---

## Recipes

- **Route to a target:** `retrosynthesis(smiles)`; show `routes[0].image` and
  list `reactions` (forward order: starting materials first).
- **Only what is on the shelf:** `retrosynthesis(smiles, use_zinc=False,
  custom_stock=[...])` or a file with one SMILES per line.
- **Ideas for the last step:** `single_step(smiles)`; prefer suggestions with high
  `feasibility` and frequent templates (`template_occurrences`).
- **Hard targets** (rings formed late, complex scaffolds): `ring_breaker=True`,
  `iteration_limit=300`, a longer `time_limit_s`.

## Interpreting

- `solved` means every starting material is in the stock; compare several routes
  rather than trusting the first.
- `policy_probability` ranks templates for a product; it is not a yield.
- Reagents, solvents, conditions, and protecting groups are not given: look up
  precedents for each step before lab work.

## Pitfalls

- Stereocentres and regiochemistry are not checked; verify that each step makes
  the right isomer.
- ZINC availability is from 2020; confirm suppliers and prices before ordering.
- An unsolved search does not mean no route exists: try more iterations, the
  ring breaker, or a custom stock with known intermediates.
