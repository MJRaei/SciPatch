---
name: pycalphad
description: >-
  Alloy thermodynamics with CALPHAD databases: which phases are stable at a
  temperature and composition (and how much of each), melting and solidification
  ranges (liquidus, solidus, eutectics), phase fractions versus temperature, and
  binary phase diagrams. Bundled databases: COST507 (light alloys: Al, Mg, Si,
  Cu, Fe, Ni, Ti, Zn, ...), Al-Fe, Al-Mg, Al-Ni, Al-Zn, Cu-Mg, Pb-Sn solders;
  or any TDB file. Use for alloy design, heat treatment windows, casting, and
  soldering temperatures.
---

## Recipes

- **Melting range of an alloy:** `solidification("COST507", "AL", {"SI": 7,
  "MG": 0.3})` gives liquidus and solidus (equilibrium) and phase fractions
  versus temperature; show the plot.
- **Which phases at a heat-treatment temperature:** `equilibrium("COST507",
  "AL", {"CU": 4}, 773)`.
- **Phase diagram of a binary:** `phase_diagram("Pb-Sn", ["PB", "SN"], 300, 650)`.
- **Which database:** `database_info()` lists the bundled ones; check that every
  element of the alloy is in the chosen database before relying on it.

## Interpreting

- Compositions are wt% by default (`basis="mole"` for at%); the balance element
  makes up the rest. Fractions of phases are fractions of atoms.
- Equilibrium solidification overestimates the solidus of real castings; tell
  the user when this matters (segregation, Scheil conditions).
- Phase names come from the database: FCC_A1 is the fcc solid solution (e.g.
  aluminium), DIAMOND_A4 silicon, BCT_A5 tin, LIQUID the melt; numbered
  copies (e.g. FCC_A1#2) are a second composition set of the same phase.

## Pitfalls

- A database of binary assessments extrapolates for multicomponent alloys;
  prefer a database assessed for the system.
- `phase_diagram` maps the whole composition range and takes longer for large
  databases; narrow the temperature range when possible.
