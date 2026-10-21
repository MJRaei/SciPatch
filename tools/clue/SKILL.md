---
name: clue
description: >-
  Explainable metallicity predictions for crystals (CLUE). predict_metallicity
  classifies a crystal structure as metal or non-metal with a random forest
  trained on JARVIS-DFT; counterfactuals finds similar Materials Project
  compounds the model classifies the other way (the differences explain the
  prediction); similarity scores two crystals by composition (element mover's
  distance), local structure (SOAP), and volume per atom.
---

## Recipes

- **Why does the model call it a metal?** `predict_metallicity(file)` →
  `counterfactuals(file, top=10)` → `robocrys.describe` on the sample and on
  each counterfactual CIF → explain which differences (composition, bonding,
  coordination, dimensionality) flip the prediction; say when the model's
  reasoning looks physically wrong.
- **How alike are two crystals?** `similarity(a, b)`.

## Pitfalls

- The labels are DFT-based (gaps underestimated); treat predictions near a
  0.5 vote fraction as uncertain.
- Counterfactuals need a Materials Project API key and can take minutes.
