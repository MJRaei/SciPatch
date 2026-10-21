---
name: peptide-assembly
description: >-
  Suggest conditions for a peptide to self-assemble (into fibers, hydrogels,
  spheres): pH, concentration, temperature, solvent, and time from the most
  similar of 989 published self-assembly records (SAPdb and literature, mostly
  di- and tripeptides, with Fmoc, Boc, acetyl, and amide terminal groups). Use
  for "how do I get FF / Fmoc-FF / my peptide to form fibers or a gel", or to find
  published conditions for similar peptides.
---

## Recipes

- **Conditions for a target morphology:** `suggest_conditions("FF",
  morphology="fiber", n_terminal="Fmoc")`: read the medians and ranges, the
  solvents, and `similarity` (how close the records are), then the records and
  their references.
- **What is known about similar peptides:** `similar_peptides(sequence)` lists
  records of any outcome, including "none" (no assembly reported), which is
  useful to see conditions that failed.

## Interpreting

- `similarity.same_sequence` > 0 means the peptide itself is in the data;
  otherwise the suggestion comes from relatives (similarity 0.7 is about two
  changes in seven residues; below 0.5, little guidance).
- Terminal groups matter as much as the sequence (Fmoc-FF gels, free FF
  often forms tubes or nothing under the same conditions): pass the peptide's
  own terminal groups.
- References are DOI links, or record numbers of the compilation the data
  comes from (SAPdb or the summaries in peptide-agent's data/README.md).

## Pitfalls

- The data is small and uneven; many records lack time or temperature.
- Similarity is by edit distance, blind to which substitutions are
  conservative.
