---
name: atombridge
description: >-
  Electron micrographs and papers toward crystal structures (AtomBridge).
  measure_lattice gives the two in-plane lattice vectors (lengths and angle) of
  an atomic-resolution STEM/TEM image from its scale and writes the 2D cell as a
  CIF; extract_figures pulls the figures and captions out of a paper's PDF and
  flags electron micrographs; check_structure reports atoms that are too close.
  Use to measure lattice spacings from images, compare them with known phases,
  and sanity-check structures built from them.
---

## Recipes

- **Lattice from a paper:** `extract_figures(paper.pdf, only_micrographs=true)`
  → read the scale bar (nm per pixel = bar length / bar pixels) →
  `measure_lattice(figure.png, nm_per_pixel, crop=[x, y, w, h])` on a clean,
  periodic region → compare a, b, gamma with candidate phases (e.g.
  `materials-project.search`, `pymatgen-structure.symmetry`).
- **Check a built structure:** `check_structure(file.cif)` before relaxing it.

## Interpreting

- The result is the projected lattice of the imaged zone axis; a hexagonal
  pattern gives gamma near 60° or 120° (equivalent).
- Look at the overlay image to confirm the detected columns and vectors.

## Pitfalls

- Errors scale with the scale bar; measure its pixel length carefully.
- Annotations, scale bars, and edges inside the crop confuse the detection.
