# Motel tools

A collection of research tools for [Motel](../README.md), each one a tool
package: pinned upstream code, an isolated environment, typed functions, usage
notes for AI agents, stated validity limits, and **golden tests** that
reproduce published or upstream-tested values on every build.

| Tool | Field | What it does | Checked against |
|---|---|---|---|
| [chgnet](chgnet/) | materials | Energies, forces, stresses, magnetic moments, relaxation, and MD with the CHGNet universal potential | CHGNet's test suite (LiMnO₂ energy and relaxation) |
| [gpaw](gpaw/) | materials | DFT for crystals (plane waves, PAW): energies, forces, stress, relaxation, equation of state, band structures and gaps, magnetism | GPAW's test suite (Si); all-electron PBE equation of state (Delta benchmark); Fe moment |
| [mace](mace/) | materials, chemistry | The same with MACE-MP (89 elements) and MACE-OFF (organic molecules) | MACE's test suite (water); Si and Al lattice constants vs. experiment |
| [phonopy](phonopy/) | materials | Phonon bands and DOS, dynamical stability, vibrational free energy and heat capacity | Dulong-Petit limit; Γ-point symmetry of silicon |
| [pyscf](pyscf/) | chemistry | Ab initio quantum chemistry: HF, DFT, MP2, CCSD(T) energies, optimization, frequencies and thermochemistry, excited states (TDDFT) | PySCF's test suite (water HF, B3LYP, MP2, CCSD(T), frequencies; CIS of HF); NIST CCCBDB |
| [pymatgen-diffusion](pymatgen-diffusion/) | materials | Diffusivity, ionic conductivity, Haven ratio, and Arrhenius fits from MD trajectories | pymatgen-analysis-diffusion's test suite (LGPS at 600 K) |
| [pymatgen-structure](pymatgen-structure/) | materials | Space groups, standard cells, supercells, format conversion, XRD patterns, structure matching | pymatgen's XRD tests; olivine and diamond space groups |
| [matcalc](matcalc/) | materials | Elastic tensor and moduli, equation of state, thermal expansion and heat capacity (quasi-harmonic), formation energies, from universal potentials (TensorNet, M3GNet, CHGNet on MatPES) | matcalc's test suite (Li2O); all-electron PBE bulk modulus of Si |
| [materials-project](materials-project/) | materials | Search known materials, stability (energy above hull), properties, and structures | Silicon (mp-149); needs a free API key |
| [xtb](xtb/) | chemistry | GFN2-xTB energies, optimization, frequencies, and thermochemistry for molecules, with implicit solvent | xtb's test suite (propyne; GBSA solvation) |

Two more tools ship inside Motel itself: `ase-emt` (fast approximate
simulations of metals) and `rdkit-descriptors` (molecular properties from
SMILES).

## Installing

From a copy of this repository:

```bash
motel add tools/chgnet
```

From the published collection, add it once and install tools by name:

```bash
motel catalog add <repository-url>
motel catalog                      # browse
motel add chgnet
motel catalog update               # fetch new and updated tools
```

The Materials Project tool needs a free API key from
<https://next-gen.materialsproject.org/api>. `motel add materials-project` asks
for it; you can also add it later on the dashboard's Keys page, through the link
your AI app shows when the key is missing, or with `motel secret set MP_API_KEY`.

## Workflows

The tools are designed to be chained: outputs are files that the next tool
accepts.

- **Is a new material stable?** `materials-project.search` (known phases) →
  `chgnet.relax` and `mace.relax` (two independent potentials) →
  `gpaw.scf` on the relaxed structure (do DFT forces and stress agree?) →
  `phonopy.phonons` on the relaxed structure (dynamical stability).
- **Electronic structure:** `gpaw.scf` → `gpaw.band_structure` on its restart
  file (gap, direct or indirect, band edges; PBE gaps are too small).
- **How fast do ions move?** `pymatgen-structure.make_supercell` (≥ 100 atoms) →
  `chgnet.molecular_dynamics` or `mace.molecular_dynamics` at several temperatures
  (several ps each) → `pymatgen-diffusion.analyze_trajectory` →
  `pymatgen-diffusion.arrhenius_fit` (activation energy, room-temperature value).
- **Identify a structure:** `pymatgen-structure.symmetry` and `xrd_pattern`, then
  `compare` with candidates from `materials-project.get_structure`.
- **Molecules:** `xtb.optimize` from SMILES (fast pre-optimization) →
  `pyscf.optimize` and `pyscf.frequencies` with DFT (minimum? free energy) →
  `pyscf.single_point` with a larger basis or `ccsd(t)` for the final energy;
  `pyscf.excited_states` for UV-Vis.

## Licenses

Each tool's `motel.yaml` states its license. Note especially: MACE-OFF models
are for non-commercial use only (Academic Software License), Materials Project
data is CC BY 4.0, and xtb is LGPL-3.0. Upstream code is downloaded from its
original repository at install time and is not redistributed here.

## Adding a tool

See [Turning a repository into a tool](../docs/onboarding.md). A tool is
accepted when:

- [ ] `motel check tools/<name> --clean` passes;
- [ ] at least one golden test reproduces a published or upstream-tested value,
      and its `reference` names the exact source (never an invented one);
- [ ] a golden test with `raises:` shows that an input outside the tool's
      validity is refused, where that applies;
- [ ] `validity`, `citation`, and `license` are filled in;
- [ ] versions are pinned with `motel freeze tools/<name>`.

The **Tools** CI workflow rebuilds every changed tool from scratch on Linux and
macOS and runs its golden tests; all tools are re-checked weekly.
