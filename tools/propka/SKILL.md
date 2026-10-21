---
name: propka
description: >-
  Predict protein pKa values and protonation states (PROPKA 3): the pKa of every
  Asp, Glu, His, Cys, Tyr, Lys, Arg, terminus, and ligand group in a structure,
  which residues are protonated at a given pH, net charge, isoelectric point,
  and charge and stability versus pH. Use before MD or docking (choose
  protonation states), to find catalytic or buried residues with shifted pKa,
  and for "what is the charge or pI of this protein".
---

## Recipes

- **Protonation states at pH 7.4:** `fetch_pdb("1UBQ")` → `protein_pka("1UBQ.pdb",
  ph=7.4)`; list groups whose `protonated_at_ph` differs from the usual state
  (e.g. neutral Asp/Glu, charged His) and the `strongly_shifted` ones.
- **Charge and pI:** `charge_curve(structure)`; show the plot.
- **With a bound ligand:** `keep_hetero=True` so the ligand affects nearby pKa
  values; check the ligand's groups.
- **Benchmark against measurements:** pass `experimental={"E35": 6.2, ...}`.

## Interpreting

- Model pKa values: Asp 3.8, Glu 4.5, His 6.5, Cys 9.0, Tyr 10.0, Lys 10.5,
  Arg 12.5; large shifts point to buried, hydrogen-bonded, or catalytic groups.
- Predictions within ~1 pH unit of measurements are typical; His and buried
  groups are least reliable.

## Pitfalls

- Use the biological assembly or all chains of an oligomer; interfaces shift
  pKa values.
- Missing side chains or alternate conformations change results; model them
  first if possible.
