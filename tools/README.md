# Motel tools

A collection of research tools for [Motel](../README.md), each one a tool
package: pinned upstream code, an isolated environment, typed functions, usage
notes for AI agents, stated validity limits, and **golden tests** that
reproduce published or upstream-tested values on every build.

| Tool | Field | Runs on | What it does | Checked against |
|---|---|---|---|---|
| [cantera](cantera/) | chemistry, engineering | Linux, macOS, Windows | Combustion chemistry: equilibrium, adiabatic flame temperatures, laminar flame speeds, ignition delays, species thermodynamics | NASA CEA flame temperatures; NIST-JANAF heat capacities; methane-air flame speed vs experiment |
| [chgnet](chgnet/) | materials | Linux, macOS, Windows | Energies, forces, stresses, magnetic moments, relaxation, and MD with the CHGNet universal potential | CHGNet's test suite (LiMnO₂ energy and relaxation) |
| [crest](crest/) | chemistry | Linux, macOS | Conformer search with Boltzmann populations, protonation and deprotonation sites, tautomers (GFN2-xTB) | Butane anti/gauche; pyridine, acetic acid, and keto-enol chemistry (NIST enthalpies) |
| [gpaw](gpaw/) | materials | Linux, macOS | DFT for crystals (plane waves, PAW): energies, forces, stress, relaxation, equation of state, band structures and gaps, magnetism | GPAW's test suite (Si); all-electron PBE equation of state (Delta benchmark); Fe moment |
| [lammps](lammps/) | materials | Linux, macOS | Classical MD and 0 K crystal properties with EAM, SW, Tersoff, AIREBO, SNAP, ACE or any LAMMPS pair style: lattice constants, cohesive energies, elastic tensors, NVT/NPT dynamics; your own input scripts | NIST Interatomic Potentials Repository (Cu, Fe, Si: lattice, cohesive energy, C11/C12/C44); LAMMPS benchmark log; equipartition |
| [mace](mace/) | materials, chemistry | Linux, macOS, Windows | The same with MACE-MP (89 elements) and MACE-OFF (organic molecules) | MACE's test suite (water); Si and Al lattice constants vs. experiment |
| [matcalc](matcalc/) | materials | Linux, macOS, Windows | Elastic tensor and moduli, equation of state, thermal expansion and heat capacity (quasi-harmonic), formation energies, from universal potentials (TensorNet, M3GNet, CHGNet on MatPES) | matcalc's test suite (Li2O); all-electron PBE bulk modulus of Si |
| [materials-project](materials-project/) | materials | Linux, macOS, Windows | Search known materials, stability (energy above hull), properties, and structures | Silicon (mp-149); needs a free API key |
| [mdanalysis](mdanalysis/) | chemistry, biology, materials | Linux, macOS, Windows | MD trajectory analysis (GROMACS, AMBER, CHARMM, LAMMPS, OpenMM, extended XYZ): RMSD, RMSF, radius of gyration, g(r) and coordination numbers, MSD and diffusion coefficients | MDAnalysis's test suite (adenylate kinase RMSD); fcc coordination shell; random-walk Einstein relation |
| [openbabel](openbabel/) | chemistry | Linux, macOS, Windows | Conversion between 100+ chemical formats, canonical SMILES/InChI/InChIKey, protonation at a pH, 3D coordinates, MMFF94/UFF/GAFF energies and minimization, partial charges | Halgren's MMFF94 validation suite (energies, terms, charges); PubChem identifiers; glycine zwitterion; rock-salt unit cell |
| [openmm](openmm/) | chemistry, biology | Linux, macOS, Windows | Molecular dynamics of proteins, nucleic acids, ligands and water: preparation, solvation, minimization, constant-pressure MD; small molecules with OpenFF Sage or GAFF; densities of molecular liquids | OpenMM's test suite vs Amber (ff14ipq energy); TIP3P density of water; NIST densities of liquid methanol and benzene |
| [ovito](ovito/) | materials | Linux, macOS, Windows | Local crystal structure of every atom (adaptive CNA, PTM, diamond), vacancies and interstitials (Wigner-Seitz), dislocation lines and Burgers vectors (DXA), for structures and trajectories | Exact answers for ideal fcc/bcc/hcp/diamond lattices, a vacancy, a Frenkel pair, and a Volterra screw dislocation |
| [phono3py](phono3py/) | materials | Linux, macOS, Windows | Lattice thermal conductivity vs temperature (RTA or full Boltzmann), from DFT forces or a universal ML potential | phono3py's test suite (Si with PBEsol forces, with and without isotopes) |
| [phonopy](phonopy/) | materials | Linux, macOS, Windows | Phonon bands and DOS, dynamical stability, vibrational free energy and heat capacity | Dulong-Petit limit; Γ-point symmetry of silicon |
| [pymatgen-diffusion](pymatgen-diffusion/) | materials | Linux, macOS, Windows | Diffusivity, ionic conductivity, Haven ratio, and Arrhenius fits from MD trajectories | pymatgen-analysis-diffusion's test suite (LGPS at 600 K) |
| [pymatgen-structure](pymatgen-structure/) | materials | Linux, macOS, Windows | Space groups, standard cells, supercells, format conversion, XRD patterns, structure matching | pymatgen's XRD tests; olivine and diamond space groups |
| [pyscf](pyscf/) | chemistry | Linux, macOS, Windows | Ab initio quantum chemistry: HF, DFT, MP2, CCSD(T) energies, optimization, frequencies and thermochemistry, excited states (TDDFT) | PySCF's test suite (water HF, B3LYP, MP2, CCSD(T), frequencies; CIS of HF); NIST CCCBDB |
| [quantum-espresso](quantum-espresso/) | materials | Linux, macOS | Plane-wave DFT with the verified SSSP pseudopotentials: energies, forces, stress, relaxation, equation of state, gaps, magnetism | Quantum ESPRESSO's test suite (Si); all-electron PBE equation of state (Delta benchmark); Fe moment |
| [rdkit](rdkit/) | chemistry | Linux, macOS, Windows | Similarity and substructure search, 3D conformers (ETKDG + MMFF94), standardization with InChI/InChIKey | RDKit's documentation (doctested similarities and searches); PubChem identifiers |
| [vina](vina/) | chemistry, biology | Linux, macOS, Windows | Protein-ligand docking: receptor and ligand preparation (SMILES or SDF), ranked poses with Vina/Vinardo scores, RMSD to a known pose, rescoring and local optimization | Vina's 1IEP tutorial (imatinib redocked within 2 Å, -13.2 kcal/mol), from the crystal ligand and from SMILES |
| [xtb](xtb/) | chemistry | Linux, macOS, Windows | GFN2-xTB energies, optimization, frequencies, and thermochemistry for molecules, with implicit solvent | xtb's test suite (propyne; GBSA solvation) |

**Runs on** comes from each tool's `motel.lock` (Linux x86-64, macOS on Apple
silicon, Windows); `motel info <tool>` also covers ARM Linux and Intel Macs, and
names what is missing where a tool cannot be installed. On Windows, OpenMM
handles proteins, nucleic acids, and water; its small-molecule features need
AmberTools, which has no Windows build; AutoDock Vina uses the official
Windows executable. The Linux-only codes (CREST, GPAW, LAMMPS, Quantum ESPRESSO)
run on Windows under WSL.

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
- **Metals and semiconductors at scale:** `lammps.list_potentials` →
  `lammps.crystal_properties` (lattice and elastic constants; compare with
  `matcalc.elastic_constants` or DFT) → `lammps.simulate` at several temperatures
  (NPT: thermal expansion; heating: melting) → `ovito.structure_types` on the
  trajectory (phase of each atom per frame) and `mdanalysis.rdf` / `mdanalysis.msd`.
- **Defects and plasticity:** `lammps.run_script` with your deformation or
  cascade input → `ovito.dislocations` (line length, Burgers vectors, density)
  and `ovito.point_defects` (vacancies, interstitials per frame).
- **Docking:** `openbabel.convert` (protonate the ligand for pH 7.4) →
  `vina.dock` (redock the crystal ligand first to validate the box) →
  `openmm.simulate` with the best pose as `small_molecules` →
  `mdanalysis.rmsd` on `start.pdb` + `trajectory.dcd` (does the pose stay?).
- **Chemical files:** `openbabel.convert` and `openbabel.identifiers` move
  molecules between programs and formats and give InChIKeys for lookups.

## Licenses

Each tool's `motel.yaml` states its license. Note especially: MACE-OFF models
are for non-commercial use only (Academic Software License), Materials Project
data is CC BY 4.0, xtb is LGPL-3.0, and LAMMPS and Open Babel are GPL-2.0.
Upstream code, potential files, and pseudopotentials are downloaded from their
original sources at install time and are not redistributed here. Small test
inputs taken from upstream projects (the LAMMPS benchmark input, the Vina 1IEP
tutorial files, an excerpt of MDAnalysis's adenylate kinase trajectory, and
molecules of the MMFF94 validation suite) keep their projects' licenses; each
golden test names its source.

## Adding a tool

See [Turning a repository into a tool](../docs/onboarding.md). A tool is
accepted when:

- [ ] `motel check tools/<name> --clean` passes;
- [ ] at least one golden test reproduces a published or upstream-tested value,
      and its `reference` names the exact source (never an invented one);
- [ ] a golden test with `raises:` shows that an input outside the tool's
      validity is refused, where that applies;
- [ ] `validity`, `citation`, and `license` are filled in;
- [ ] versions are pinned for every platform with `motel freeze tools/<name>`.

The **Tools** CI workflow rebuilds every changed tool from scratch on Linux,
macOS, and Windows (where its `motel.lock` says it can be installed) and runs its
golden tests; all tools are re-checked weekly.
