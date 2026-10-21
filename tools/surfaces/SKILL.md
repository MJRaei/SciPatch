---
name: surfaces
description: >-
  Surfaces and nanoparticles. make_slab cuts any crystal (file or element
  symbol) along a Miller plane and lists its terminations; adsorption_sites
  finds top, bridge, fcc/hcp hollow, and four-fold hollow sites and places
  adsorbates (H, C, N, O, S, OH, CO, NO, H2O, NH3, CH3); wulff_shape gives the
  equilibrium nanoparticle shape and facet fractions from surface energies
  (free, on a support, decahedral, icosahedral) with an atomistic model. Use to
  set up catalysis and surface calculations and to predict particle shapes.
---

## Recipes

- **Adsorption energy:** `make_slab("Pt", [1,1,1], layers=4, supercell=[2,2])` →
  `adsorption_sites(slab, adsorbate="O", site="fcc_hollow")` → relax slab and
  slab+adsorbate with `ml-potentials.relax` (or DFT) → E(ads) = E(slab+X) −
  E(slab) − E(X reference).
- **Surface energies → particle shape:** slabs for (111), (100), (110) →
  energies from ml-potentials or DFT → gamma = (E_slab − N E_bulk) / (2 A) →
  `wulff_shape({"111": g111, "100": g100, "110": g110}, structure="Pt")`.
- **Supported particle:** `kind="winterbottom"`, `interface_energy` (negative
  = wetting), `interface_direction="111"`.

## Pitfalls

- Slabs are unrelaxed; freeze the bottom layers and relax the rest.
- Check `terminations` for compounds: different terminations have different
  chemistry; polar ones need symmetric slabs or dipole corrections.
- Wulff shapes ignore edges and corners; small clusters can differ.
