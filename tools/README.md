# Motel tools

A collection of research tools for [Motel](../README.md), each one a tool
package: pinned upstream code, an isolated environment, typed functions, usage
notes for AI agents, stated validity limits, and **golden tests** that
reproduce published or upstream-tested values on every build.

| Tool | Field | What it does | Checked against |
|---|---|---|---|
| [chgnet](chgnet/) | materials | Energies, forces, stresses, magnetic moments, relaxation, and MD with the CHGNet universal potential | CHGNet's test suite (LiMnO₂ energy and relaxation) |
| [mace](mace/) | materials, chemistry | The same with MACE-MP (89 elements) and MACE-OFF (organic molecules) | MACE's test suite (water); Si and Al lattice constants vs. experiment |
| [phonopy](phonopy/) | materials | Phonon bands and DOS, dynamical stability, vibrational free energy and heat capacity | Dulong-Petit limit; Γ-point symmetry of silicon |
| [pymatgen-diffusion](pymatgen-diffusion/) | materials | Diffusivity, ionic conductivity, Haven ratio, and Arrhenius fits from MD trajectories | pymatgen-analysis-diffusion's test suite (LGPS at 600 K) |
| [pymatgen-structure](pymatgen-structure/) | materials | Space groups, standard cells, supercells, format conversion, XRD patterns, structure matching | pymatgen's XRD tests; olivine and diamond space groups |
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
<https://next-gen.materialsproject.org/api>: `motel secret set MP_API_KEY`.

## Workflows

The tools are designed to be chained: outputs are files that the next tool
accepts.

- **Is a new material stable?** `materials-project.search` (known phases) →
  `chgnet.relax` and `mace.relax` (two independent potentials) →
  `phonopy.phonons` on the relaxed structure (dynamical stability).
- **How fast do ions move?** `pymatgen-structure.make_supercell` (≥ 100 atoms) →
  `chgnet.molecular_dynamics` or `mace.molecular_dynamics` at several temperatures
  (several ps each) → `pymatgen-diffusion.analyze_trajectory` →
  `pymatgen-diffusion.arrhenius_fit` (activation energy, room-temperature value).
- **Identify a structure:** `pymatgen-structure.symmetry` and `xrd_pattern`, then
  `compare` with candidates from `materials-project.get_structure`.
- **Molecules:** `xtb.optimize` from SMILES → `xtb.frequencies` (minimum? free
  energy) → `mace.predict` with an `off23` model as a second opinion.

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
