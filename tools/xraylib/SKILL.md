---
name: xraylib
description: >-
  X-ray interaction data (xraylib): how strongly a material absorbs X-rays at a
  given energy (mass attenuation, photoelectric, Compton, Rayleigh), transmission
  through a thickness and half-value layers, absorption-edge and emission-line
  energies (K-alpha, L-alpha, ...) with wavelengths and fluorescence yields, and
  identification of XRF/EDS peaks. Use for shielding and filter thickness,
  sample thickness for transmission XRD/XAS, choosing an X-ray source, and
  assigning fluorescence peaks.
---

## Recipes

- **How much gets through?** `attenuation("Pb", [60, 100], thickness_cm=0.2)`;
  for compounds give a formula and `density_g_cm3`, or a NIST material name
  (`materials()` lists them, e.g. "Water, Liquid", "Concrete, Ordinary").
- **Element lines and edges:** `element_xray_data("Mo")` (e.g. tube anode lines,
  absorption-edge filters).
- **What is this XRF/EDS peak?** `identify_peak(6.40)`; confirm with the
  element's other lines (e.g. K-beta at higher energy).

## Interpreting

- Half-value layer: thickness that halves the beam; ten-value layer is 3.3 times
  larger.
- Attenuation jumps up at absorption edges: an element absorbs strongly just
  above its own edge (useful for filters, a problem for fluorescence).

## Pitfalls

- Transmission assumes a narrow beam; real shields need build-up factors.
- Energies are in keV; wavelengths in Angstrom = 12.398 / E(keV).
