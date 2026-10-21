# Motel tools

A collection of research tools for [Motel](../README.md), each one a tool
package: pinned upstream code, an isolated environment, typed functions, usage
notes for AI agents, stated validity limits, and **golden tests** that
reproduce published or upstream-tested values on every build.

| Tool | Field | Runs on | What it does | Maturity | Checked against |
|---|---|---|---|---|---|
| [cantera](cantera/) | chemistry, engineering | Linux, macOS, Windows | Combustion chemistry: equilibrium, adiabatic flame temperatures, laminar flame speeds, ignition delays, species thermodynamics | established | NASA CEA flame temperatures; NIST-JANAF heat capacities; methane-air flame speed vs experiment |
| [crest](crest/) | chemistry | Linux, macOS, Windows (WSL) | Conformer search with Boltzmann populations, protonation and deprotonation sites, tautomers (GFN2-xTB) | established | Butane anti/gauche; pyridine, acetic acid, and keto-enol chemistry (NIST enthalpies) |
| [doping-knowledge](doping-knowledge/) | materials | Linux, macOS, Windows | What papers report about doping and intercalation of 2D and layered materials: 440 studies (dopants, methods, conditions, sites, phase transitions, property changes) and 1,443 cause-effect relationships with the authors' mechanisms, extracted by an LLM; from the ARIA hackathon project | experimental | Li-intercalated WTe2 record vs its paper (Wang et al. 2022); counts and a quoted mechanism from the knowledge base |
| [gpaw](gpaw/) | materials | Linux, macOS, Windows (WSL) | DFT for crystals (plane waves, PAW): energies, forces, stress, relaxation, equation of state, band structures and gaps, magnetism | established | GPAW's test suite (Si); all-electron PBE equation of state (Delta benchmark); Fe moment |
| [lammps](lammps/) | materials | Linux, macOS, Windows (WSL) | Classical MD and 0 K crystal properties with EAM, SW, Tersoff, AIREBO, SNAP, ACE or any LAMMPS pair style: lattice constants, cohesive energies, elastic tensors, NVT/NPT dynamics; your own input scripts | established | NIST Interatomic Potentials Repository (Cu, Fe, Si: lattice, cohesive energy, C11/C12/C44); LAMMPS benchmark log; equipartition |
| [materials-project](materials-project/) | materials | Linux, macOS, Windows | Search known materials, stability (energy above hull), properties, and structures | established | Silicon (mp-149); needs a free API key |
| [mdanalysis](mdanalysis/) | chemistry, biology, materials | Linux, macOS, Windows | MD trajectory analysis (GROMACS, AMBER, CHARMM, LAMMPS, OpenMM, extended XYZ): RMSD, RMSF, radius of gyration, g(r) and coordination numbers, MSD and diffusion coefficients | established | MDAnalysis's test suite (adenylate kinase RMSD); fcc coordination shell; random-walk Einstein relation |
| [ml-potentials](ml-potentials/) | materials, chemistry | Linux, macOS, Windows | Universal ML potentials (Orb-v3, MACE-MP/MPA, MACE-OFF, CHGNet, TensorNet/M3GNet) in one place: energies, forces, stresses, magnetic moments, relaxation, MD, elastic constants, equation of state, thermal expansion and heat capacity, formation energies, and side-by-side model comparison | published | The test suites of Orb (Cu), CHGNet (LiMnO₂ energy and relaxation), MACE (water), and matcalc (Li₂O); Si and Al lattice constants vs. experiment; all-electron PBE bulk modulus of Si |
| [nmr-mixtures](nmr-mixtures/) | chemistry | Linux, macOS, Windows | Mole fractions of known components in a mixture from 1H NMR spectra (Wasserstein deconvolution, robust to small peak shifts), composition over a reaction's time points, and predicted 1H spectra from SMILES; from the MixSense hackathon project | experimental | The original Magnetstein on MixSense's crude example; exact recovery of synthetic mixtures; measured ethyl acetate shifts (Fulmer et al. 2010) |
| [openbabel](openbabel/) | chemistry | Linux, macOS, Windows | Conversion between 100+ chemical formats, canonical SMILES/InChI/InChIKey, protonation at a pH, 3D coordinates, MMFF94/UFF/GAFF energies and minimization, partial charges | established | Halgren's MMFF94 validation suite (energies, terms, charges); PubChem identifiers; glycine zwitterion; rock-salt unit cell |
| [openmm](openmm/) | chemistry, biology | Linux, macOS, Windows | Molecular dynamics of proteins, nucleic acids, ligands and water: preparation, solvation, minimization, constant-pressure MD; small molecules with OpenFF Sage or GAFF; densities of molecular liquids | established | OpenMM's test suite vs Amber (ff14ipq energy); TIP3P density of water; NIST densities of liquid methanol and benzene |
| [ovito](ovito/) | materials | Linux, macOS, Windows | Local crystal structure of every atom (adaptive CNA, PTM, diamond), vacancies and interstitials (Wigner-Seitz), dislocation lines and Burgers vectors (DXA), for structures and trajectories | established | Exact answers for ideal fcc/bcc/hcp/diamond lattices, a vacancy, a Frenkel pair, and a Volterra screw dislocation |
| [peptide-assembly](peptide-assembly/) | chemistry, biology | Linux, macOS, Windows | Conditions for peptide self-assembly (pH, concentration, temperature, solvent, time) from the most similar of 989 curated records (SAPdb and literature), for fibers, hydrogels, and spheres; from the peptide-agent hackathon project | experimental | Fmoc-FF hydrogel in water (Mahler et al. 2006); exact self-match; on the held-out split, the nearest records' solvent is right 69% of the time |
| [phono3py](phono3py/) | materials | Linux, macOS, Windows | Lattice thermal conductivity vs temperature (RTA or full Boltzmann), from DFT forces or a universal ML potential | established | phono3py's test suite (Si with PBEsol forces, with and without isotopes) |
| [phonopy](phonopy/) | materials | Linux, macOS, Windows | Phonon bands and DOS, dynamical stability, vibrational free energy and heat capacity | established | Dulong-Petit limit; Γ-point symmetry of silicon |
| [pybamm](pybamm/) | materials, chemistry, engineering | Linux, macOS, Windows | Lithium-ion cells with physics-based models (Doyle-Fuller-Newman, single-particle): discharge curves, capacity and energy, rate capability, heating, CC-CV and other cycling protocols, with published cell parameters (LG M50 21700 and others) | established | LG M50 specification (18.2 Wh, ≥ 4.85 Ah, 3.63 V) at C/5; exact charge conservation over a CC-CV cycle |
| [pycalphad](pycalphad/) | materials | Linux, macOS, Windows | Alloy thermodynamics (CALPHAD): stable phases and their compositions, liquidus, solidus, and phase fractions during solidification, binary phase diagrams; COST507 light alloys and other published databases, or your own TDB | established | ITS-90 melting point of Al; Al-Si eutectic (Murray & McAlister 1984); Pb-Sn solder eutectic |
| [pymatgen-diffusion](pymatgen-diffusion/) | materials | Linux, macOS, Windows | Diffusivity, ionic conductivity, Haven ratio, and Arrhenius fits from MD trajectories | published | pymatgen-analysis-diffusion's test suite (LGPS at 600 K) |
| [pymatgen-structure](pymatgen-structure/) | materials | Linux, macOS, Windows | Space groups, standard cells, supercells, format conversion, XRD patterns, structure matching | established | pymatgen's XRD tests; olivine and diamond space groups |
| [pyscf](pyscf/) | chemistry | Linux, macOS, Windows | Ab initio quantum chemistry: HF, DFT, MP2, CCSD(T) energies, optimization, frequencies and thermochemistry, excited states (TDDFT) | established | PySCF's test suite (water HF, B3LYP, MP2, CCSD(T), frequencies; CIS of HF); NIST CCCBDB |
| [quantum-espresso](quantum-espresso/) | materials | Linux, macOS, Windows (WSL) | Plane-wave DFT with the verified SSSP pseudopotentials: energies, forces, stress, relaxation, equation of state, gaps, magnetism | established | Quantum ESPRESSO's test suite (Si); all-electron PBE equation of state (Delta benchmark); Fe moment |
| [rdkit](rdkit/) | chemistry | Linux, macOS, Windows | Similarity and substructure search, 3D conformers (ETKDG + MMFF94), standardization with InChI/InChIKey | established | RDKit's documentation (doctested similarities and searches); PubChem identifiers |
| [structural-analogs](structural-analogs/) | materials | Linux, macOS, Windows | Materials Project compounds with the same crystal structure type as a material or structure file, with band gaps, formation energies, stability, and volumes, for estimating properties by analogy; from the mp-property-analogies hackathon project | experimental | Rock-salt and diamond-structure analogs (KCl for NaCl, Ge for Si); needs a free API key |
| [synthesis-recipes](synthesis-recipes/) | materials, chemistry | Linux, macOS, Windows | Published synthesis recipes (41,300 text-mined solid-state and sol-gel recipes: precursors, reactions, temperatures, times, atmospheres, DOIs), similar Materials Project compositions, and suggested routes for new materials from their closest analogs; from the SKY hackathon agent | experimental | Exact composition-identity checks; recipe counts of the bundled dataset; NCA analog for a new NCA composition |
| [vina](vina/) | chemistry, biology | Linux, macOS, Windows | Protein-ligand docking: receptor and ligand preparation (SMILES or SDF), ranked poses with Vina/Vinardo scores, RMSD to a known pose, rescoring and local optimization | established | Vina's 1IEP tutorial (imatinib redocked within 2 Å, -13.2 kcal/mol), from the crystal ligand and from SMILES |
| [xtb](xtb/) | chemistry | Linux, macOS, Windows | GFN2-xTB energies, optimization, frequencies, and thermochemistry for molecules, with implicit solvent | established | xtb's test suite (propyne; GBSA solvation) |

**Maturity** tells AI agents how far to trust a tool: *established* (mature,
widely used code, checked against independent references or exact results),
*published* (research code from a publication, less widely tested), or
*experimental* (little outside validation). Agents prefer established tools when
several fit and cross-check experimental ones; see
[Tool package format](../docs/tool-format.md#maturity).

**Runs on** comes from each tool's `motel.lock` (Linux x86-64, macOS on Apple
silicon, Windows); `motel info <tool>` also covers ARM Linux and Intel Macs, and
names what is missing where a tool cannot be installed. On Windows, OpenMM
handles proteins, nucleic acids, and water; its small-molecule features need
AmberTools, which has no Windows build; AutoDock Vina uses the official
Windows executable. **Windows (WSL)**: codes without Windows builds (CREST,
GPAW, LAMMPS, Quantum ESPRESSO, as their own documentation recommends) run
inside WSL with the same Linux packages; set it up once with `wsl --install`.

Two more tools ship inside Motel itself: `ase-emt` (fast approximate
simulations of metals) and `rdkit-descriptors` (molecular properties from
SMILES).

## Installing

From a copy of this repository:

```bash
motel add tools/ml-potentials
```

From the published collection, add it once and install tools by name:

```bash
motel catalog add <repository-url>
motel catalog                      # browse
motel add ml-potentials
motel catalog update               # fetch new and updated tools
```

The Materials Project and structural-analogs tools need a free API key from
<https://next-gen.materialsproject.org/api>. `motel add materials-project` asks
for it; you can also add it later on the dashboard's Keys page, through the link
your AI app shows when the key is missing, or with `motel secret set MP_API_KEY`.

## Workflows

The tools are designed to be chained: outputs are files that the next tool
accepts.

- **Is a new material stable?** `materials-project.search` (known phases) →
  `ml-potentials.relax` and `ml-potentials.compare_models` (do four independent
  potentials agree?) →
  `gpaw.scf` on the relaxed structure (do DFT forces and stress agree?) →
  `phonopy.phonons` on the relaxed structure (dynamical stability).
- **Electronic structure:** `gpaw.scf` → `gpaw.band_structure` on its restart
  file (gap, direct or indirect, band edges; PBE gaps are too small).
- **Batteries:** `ml-potentials` and `pymatgen-diffusion` for ion transport in an
  electrode or electrolyte material → `pybamm.discharge` and
  `pybamm.rate_capability` for the cell (capacity and energy versus rate, heating).
- **How fast do ions move?** `pymatgen-structure.make_supercell` (≥ 100 atoms) →
  `ml-potentials.molecular_dynamics` at several temperatures
  (several ps each) → `pymatgen-diffusion.analyze_trajectory` →
  `pymatgen-diffusion.arrhenius_fit` (activation energy, room-temperature value).
- **Properties of a new compound by analogy:** `ml-potentials.relax` →
  `structural-analogs.structural_analogs` on the relaxed structure (same
  structure type, known properties) → estimate formation energy and volume from
  the closest analogs; compute band gaps (gpaw, quantum-espresso).
- **How to make it?** `materials-project.details` (is the target stable?) →
  `synthesis-recipes.recipes` (precursors and temperatures from papers) or, for
  a new composition, `synthesis-recipes.suggest_routes` (closest analogs with
  recipes) → read the cited papers before going to the lab.
- **Identify a structure:** `pymatgen-structure.symmetry` and `xrd_pattern`, then
  `compare` with candidates from `materials-project.get_structure`.
- **Molecules:** `xtb.optimize` from SMILES (fast pre-optimization) →
  `pyscf.optimize` and `pyscf.frequencies` with DFT (minimum? free energy) →
  `pyscf.single_point` with a larger basis or `ccsd(t)` for the final energy;
  `pyscf.excited_states` for UV-Vis.
- **Metals and semiconductors at scale:** `lammps.list_potentials` →
  `lammps.crystal_properties` (lattice and elastic constants; compare with
  `ml-potentials.elastic_constants` or DFT) → `lammps.simulate` at several temperatures
  (NPT: thermal expansion; heating: melting) → `ovito.structure_types` on the
  trajectory (phase of each atom per frame) and `mdanalysis.rdf` / `mdanalysis.msd`.
- **Alloys:** `pycalphad.solidification` (melting range, phases while cooling) →
  `pycalphad.equilibrium` at the heat-treatment temperature → `lammps` or
  `ml-potentials` for the stable phases' properties.
- **Defects and plasticity:** `lammps.run_script` with your deformation or
  cascade input → `ovito.dislocations` (line length, Burgers vectors, density)
  and `ovito.point_defects` (vacancies, interstitials per frame).
- **Docking:** `openbabel.convert` (protonate the ligand for pH 7.4) →
  `vina.dock` (redock the crystal ligand first to validate the box) →
  `openmm.simulate` with the best pose as `small_molecules` →
  `mdanalysis.rmsd` on `start.pdb` + `trajectory.dcd` (does the pose stay?).
- **What did my reaction give?** For each expected species, a measured
  reference spectrum or `nmr-mixtures.predict_spectrum` →
  `nmr-mixtures.quantify_mixture` on the crude 1H NMR (yield, selectivity,
  isomer ratio) → `nmr-mixtures.reaction_kinetics` for spectra over time.
- **Chemical files:** `openbabel.convert` and `openbabel.identifiers` move
  molecules between programs and formats and give InChIKeys for lookups.

## Licenses

Each tool's `motel.yaml` states its license. Note especially: MACE-OFF models
are for non-commercial use only (Academic Software License), Materials Project
data is CC BY 4.0, xtb is LGPL-3.0, and LAMMPS and Open Babel are GPL-2.0.
Upstream code, potential files, and pseudopotentials are downloaded from their
original sources at install time and are not redistributed here. Small test
inputs taken from upstream projects (the LAMMPS benchmark input, the Vina 1IEP
tutorial files, an excerpt of MDAnalysis's adenylate kinase trajectory,
molecules of the MMFF94 validation suite, and MixSense's example spectra) keep
their projects' licenses; each golden test names its source.

## Adding a tool

See [Turning a repository into a tool](../docs/onboarding.md). A tool is
accepted when:

- [ ] `motel check tools/<name> --clean` passes;
- [ ] at least one golden test reproduces a published or upstream-tested value,
      and its `reference` names the exact source (never an invented one);
- [ ] one fast golden test exercising the main computation is marked
      `quick: true` (installs run only the quick tests);
- [ ] a golden test with `raises:` shows that an input outside the tool's
      validity is refused, where that applies;
- [ ] `validity`, `citation`, and `license` are filled in;
- [ ] every golden test with expected values says what it is checked `against`,
      and `maturity` is the level that evidence supports (new projects without a
      publication are `experimental`);
- [ ] versions are pinned for every platform with `motel freeze tools/<name>`.

The **Tools** CI workflow rebuilds every changed tool from scratch on Linux,
macOS, and Windows (where its `motel.lock` says it can be installed) and runs its
golden tests; all tools are re-checked weekly.
