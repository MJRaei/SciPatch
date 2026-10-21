---
name: catalyze
description: >-
  Lab automation and chemical safety (from the Catalyze hackathon assistant).
  simulate_protocol runs an Opentrons OT-2 or Flex Python protocol in Opentrons'
  simulator and reports errors (slots, volumes, tips, API misuse) with fixes,
  tips used, volumes moved, and the step-by-step run log; labware finds valid
  load names; chemical_safety returns a compound's identity, properties, and GHS
  hazard classification (EU harmonised first) from PubChem. Use before running a
  protocol on a robot and when planning safe handling of chemicals.
---

## Recipes

- **Write and check a protocol:** `labware("96 flat")` for valid load names →
  write the protocol (`metadata`/`requirements` with `apiLevel`; Flex needs
  `requirements = {"robotType": "Flex"}`) → `simulate_protocol(file)` → fix every
  error and re-run until `success` → read `runlog` and the volume totals.
- **Safety:** `chemical_safety("acetone")` → report the harmonised codes and
  pictograms; mention notified codes with their share of reports.

## Pitfalls

- Simulation success does not prove the chemistry or the volumes in wells are
  right; check the run log.
- OT-2 slots are 1-11; Flex slots are A1-D3.
- Names that look like SMILES are read as SMILES; pass `identifier="name"`.
