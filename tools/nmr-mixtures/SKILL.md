---
name: nmr-mixtures
description: >-
  Quantify what is in a chemical mixture from its 1H NMR spectrum: mole
  fractions of known components (reaction yield, conversion, selectivity,
  isomer or diastereomer ratios from a crude NMR), how the composition changes
  over a reaction's time points (kinetics), and predicted 1H spectra from SMILES
  to use as references when no measured spectrum of a component is available.
  Input spectra are two-column text files (ppm, intensity).
---

## Recipes

- **Crude reaction mixture:** list every species that gives signals (starting
  material, products, by-products, remaining reagents, solvent), get a reference
  spectrum for each (measured if possible, else `predict_spectrum`), then
  `quantify_mixture(mixture, components, protons)`.
- **Proton counts:** `protons` is the number of protons that show up in each
  reference spectrum. For a predicted spectrum use the `protons` it returns:
  SPINUS leaves out OH and NH protons (ethanol gives 5, not 6). For measured
  references count all protons whose signals appear.
- **Kinetics:** `reaction_kinetics(spectra, times, components, protons)` with the
  same references at every time point; read the table or plot of mole fractions
  versus time.
- **Image of a spectrum:** digitize it first (a two-column ppm, intensity file);
  this tool does not read images.

## Interpreting

- `fit`: good (Wasserstein distance < 0.05), acceptable (< 0.15), poor. Report
  fractions with a poor fit only with a strong caveat.
- `unexplained_signal` is the share of the mixture's signal that no component
  accounts for. Above about 0.1, a component is probably missing (solvent,
  reagent, by-product) or a reference is shifted; add it and run again. In
  MixSense's camphor-reduction example, quantified with borneol and isoborneol
  only, it is 0.36; MixSense's own workflow also includes camphor and methanol.
- `kappa` (0.25 ppm) is the largest peak shift that is still matched; correct a
  larger referencing offset in the mixture first.
- Show the user `plot`: the mixture, each component scaled by its fraction, and
  the fit with residual.

## Pitfalls

- Predicted spectra are approximate (shifts can be off by a few tenths of a ppm,
  more near OH and NH groups: ethanol's CH2 comes out at 3.31 instead of
  3.72 ppm), so fractions from predicted references are estimates; use measured
  references for quantitative results.
- Molecules with more than 11 coupled protons get predicted lines without
  splitting (`multiplets_simulated` is false).
- `predict_spectrum` sends the molecule to NMRdb.org; do not use it for
  confidential structures without the user's agreement.
