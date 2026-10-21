---
name: doping-knowledge
description: >-
  Look up what papers report about doping and intercalation of 2D and layered
  materials (graphene, graphite, MoS2, WSe2, WTe2, Bi2Se3, FeSe, ...): which
  dopants and methods were used, under which conditions, where the dopant sits,
  phase transitions, and changes in band gap, carrier density, or
  superconductivity, plus the authors' cause-effect mechanisms. Use to plan a
  doping experiment, find precedents for a dopant, or explain an observed change.
---

## Recipes

- **What is known for a host and dopant:** `find_doping(host="MoS2", dopant="Re")`.
  Without a dopant, `find_doping(host="graphene")` lists every study of the host.
- **Mechanisms behind an effect:** `find_mechanisms("charge transfer band gap")`;
  the strongest-supported relationships come first.
- **What is covered at all:** `overview()` lists the most studied hosts,
  dopants, and methods.

## Interpreting

- Each study lists only what its paper reported; check `paper` (a title) before
  relying on a number, because the records were extracted by an LLM. Example of
  a likely extraction error: the WTe2 lithium study lists 300 °C for a
  room-temperature electrochemical cell whose measurements were at 300 K.
- `confidence` is the paper's own support for a relationship, from
  "experimentally proven" to "hypothesized".

## Pitfalls

- Words, not meaning: try synonyms ("intercalation", "doping", "adsorption";
  "CDW", "charge density wave") and formula spellings ("WTe2").
- A few hundred papers only: no match does not mean nothing is known.
