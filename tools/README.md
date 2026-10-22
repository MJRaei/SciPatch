# SciPatch tools

A collection of research tools for [SciPatch](../README.md), each one a tool
package: pinned upstream code, an isolated environment, typed functions, usage
notes for AI agents, stated validity limits, and **golden tests** that
reproduce published or upstream-tested values on every build.

| Tool | Field | Runs on | What it does | Maturity | Checked against |
|---|---|---|---|---|---|
| [aizynthfinder](aizynthfinder/) | chemistry | Linux, macOS, Windows | Retrosynthesis: ranked routes from purchasable starting materials (17.4 million ZINC compounds) or your own inventory, with each reaction step and route images; one-step precursor suggestions with feasibility; purchasability lookups | established | Textbook syntheses of paracetamol, aspirin (Olmsted 1998), and lidocaine in two steps (Reilly 1999); the published ZINC stock |
| [atombridge](atombridge/) | materials | Linux, macOS, Windows | Lattice vectors from atomic-resolution STEM/TEM images (from the AtomBridge hackathon project), figures and captions from paper PDFs with micrographs flagged, and overlap checks for structures | experimental | Synthetic lattices of known spacing (square, triangular, noisy rectangular); wurtzite ZnO from AtomBridge's example HRTEM image; exact figure and overlap checks |
| [atomic-shorts](atomic-shorts/) | chemistry, materials, physics | Linux, macOS, Windows | Short narrated science videos (from the AtomicShorts hackathon project): storyboard checks (narration time, terms to fact-check), Manim animation rendering with error reports, and text-to-speech narration | experimental | Manim's documented quality presets and exact scene durations; narration time at AtomicShorts' 140 words per minute; narration merged and the video extended |
| [cantera](cantera/) | chemistry, engineering | Linux, macOS, Windows | Combustion chemistry: equilibrium, adiabatic flame temperatures, laminar flame speeds, ignition delays, species thermodynamics | established | NASA CEA flame temperatures; NIST-JANAF heat capacities; methane-air flame speed vs experiment |
| [catalyze](catalyze/) | chemistry | Linux, macOS, Windows | Opentrons OT-2 and Flex protocol simulation with error checks and run logs, Opentrons labware lookup, and GHS hazard classifications from PubChem (from the Catalyze hackathon project) | experimental | Opentrons' documented default flow rate; exact volumes and tips of transfer and dilution protocols; ANSI/SLAS microplate footprint; EU harmonised classifications of ethanol and benzene |
| [clue](clue/) | materials | Linux, macOS, Windows | Metallicity predictions explained by counterfactuals (from the CLUE hackathon project): random-forest metal/non-metal classifier, crystal similarity (ElMD, SOAP, volume), and similar Materials Project compounds classified the other way | experimental | CLUE's own example predictions and MgF2 counterfactuals; copper and rock salt; exact supercell similarity; ElMD's documented CaTiO3-SrTiO3 distance |
| [coolprop](coolprop/) | engineering, chemistry | Linux, macOS, Windows | Reference-quality fluid properties for about 120 fluids and refrigerants (IAPWS-95 water, Span-Wagner CO2, ...): density, enthalpy, heat capacity, speed of sound, viscosity, thermal conductivity, saturation and latent heat, isobar tables, p-h and T-s diagrams, mixtures, brines, humid-air psychrometrics | established | IAPWS-95 verification tables (single-phase and saturation); NIST WebBook water, R134a, and nitrogen including viscosity and conductivity; Span-Wagner CO2 critical point |
| [crest](crest/) | chemistry | Linux, macOS, Windows (WSL) | Conformer search with Boltzmann populations, protonation and deprotonation sites, tautomers (GFN2-xTB) | established | Butane anti/gauche; pyridine, acetic acid, and keto-enol chemistry (NIST enthalpies) |
| [doping-knowledge](doping-knowledge/) | materials | Linux, macOS, Windows | What papers report about doping and intercalation of 2D and layered materials: 440 studies (dopants, methods, conditions, sites, phase transitions, property changes) and 1,443 cause-effect relationships with the authors' mechanisms, extracted by an LLM; from the ARIA hackathon project | experimental | Li-intercalated WTe2 record vs its paper (Wang et al. 2022); counts and a quoted mechanism from the knowledge base |
| [fipy](fipy/) | materials, chemistry | Linux, macOS, Windows | Diffusion through slabs, cylinders, and spheres (carburizing, diffusion couples, outgassing; constant, Arrhenius, or concentration-dependent D; case depth and treatment time) and spinodal decomposition and coarsening (Cahn-Hilliard) | established | Callister's carburizing example and Arrhenius data; Crank's analytic solutions for couples, cylinders, and spheres; Cahn's linear spinodal theory |
| [gpaw](gpaw/) | materials | Linux, macOS, Windows (WSL) | DFT for crystals (plane waves, PAW): energies, forces, stress, relaxation, equation of state, band structures and gaps, magnetism | established | GPAW's test suite (Si); all-electron PBE equation of state (Delta benchmark); Fe moment |
| [impedance](impedance/) | chemistry, materials, engineering | Linux, macOS, Windows | Electrochemical impedance spectroscopy: equivalent-circuit fitting (Randles, CPE, Warburg, transmission lines) of spectra from common potentiostats, circuit simulation, Lin-KK Kramers-Kronig validation | published | impedance.py's documented example fit and Lin-KK result; exact recovery of an analytic Randles spectrum; RC element at its characteristic frequency |
| [lammps](lammps/) | materials | Linux, macOS, Windows (WSL) | Classical MD and 0 K crystal properties with EAM, SW, Tersoff, AIREBO, SNAP, ACE or any LAMMPS pair style: lattice constants, cohesive energies, elastic tensors, NVT/NPT dynamics; your own input scripts | established | NIST Interatomic Potentials Repository (Cu, Fe, Si: lattice, cohesive energy, C11/C12/C44); LAMMPS benchmark log; equipartition |
| [larch](larch/) | materials, chemistry | Linux, macOS, Windows | X-ray absorption spectroscopy (xraylarch): edge energy and normalized XANES, EXAFS chi(k) and Fourier transforms, FEFF paths from a CIF, shell fitting (distances, coordination, Debye-Waller factors), linear-combination fitting with reference spectra | established | Larch's documented copper first-shell fit; Cu-Cu distance and FEFF fcc shells against copper's crystal structure; exact edge and mixture recoveries |
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
| [propka](propka/) | biology, chemistry | Linux, macOS, Windows | Protein pKa values and protonation states (PROPKA 3): pKa of every titratable group, protonation and charge at a chosen pH, net charge and isoelectric point, charge and folding free energy versus pH, comparison with measured values | established | NMR pKa values of lysozyme (Bartik et al. 1994, via PKAD-2); PROPKA's own regression test (HIV-1 protease with inhibitor); lysozyme disulfides and charge |
| [psi4](psi4/) | chemistry, materials | Linux, macOS, Windows | Intermolecular interaction energies: SAPT decomposition (electrostatics, exchange, induction, dispersion; open shell too), counterpoise-corrected HF, MP2, CCSD(T), DFT-D3, or CCSD(T)/CBS composites; S22 and S66 benchmark complexes | established | Psi4's own SAPT0 tests (water dimer, S22 ethene-ethyne, open-shell LiH); the S66 water dimer's CCSD(T)/CBS benchmark reproduced with the same recipe |
| [pvlib](pvlib/) | engineering | Linux, macOS, Windows | Solar energy: sun position (NREL SPA), sunrise and sunset, clear-sky irradiance, typical-year weather for any land location (PVGIS), and annual and monthly energy of fixed-tilt PV systems (PVWatts model: specific yield, capacity factor, performance ratio) | established | NREL SPA worked example; US Naval Observatory sunrise and sunset; PVGIS's own PV calculator for Munich; horizontal-plane identity |
| [pybamm](pybamm/) | materials, chemistry, engineering | Linux, macOS, Windows | Lithium-ion cells with physics-based models (Doyle-Fuller-Newman, single-particle): discharge curves, capacity and energy, rate capability, heating, CC-CV and other cycling protocols, with published cell parameters (LG M50 21700 and others) | established | LG M50 specification (18.2 Wh, ≥ 4.85 Ah, 3.63 V) at C/5; exact charge conservation over a CC-CV cycle |
| [pycalphad](pycalphad/) | materials | Linux, macOS, Windows | Alloy thermodynamics (CALPHAD): stable phases and their compositions, liquidus, solidus, and phase fractions during solidification, binary phase diagrams; COST507 light alloys and other published databases, or your own TDB | established | ITS-90 melting point of Al; Al-Si eutectic (Murray & McAlister 1984); Pb-Sn solder eutectic |
| [pymatgen-diffusion](pymatgen-diffusion/) | materials | Linux, macOS, Windows | Diffusivity, ionic conductivity, Haven ratio, and Arrhenius fits from MD trajectories | published | pymatgen-analysis-diffusion's test suite (LGPS at 600 K) |
| [pymatgen-structure](pymatgen-structure/) | materials | Linux, macOS, Windows | Space groups, standard cells, supercells, format conversion, XRD patterns, structure matching | established | pymatgen's XRD tests; olivine and diamond space groups |
| [pyopenms](pyopenms/) | chemistry, biology | Linux, macOS, Windows | Mass spectrometry: exact masses and m/z of molecules and modified peptides, isotope patterns, enzymatic digestion of proteins, theoretical fragment ions for MS/MS, mzML summaries | established | Exact masses from AME2020 atomic masses (angiotensin II), IUPAC chlorine isotope abundances, trypsin's cleavage rule, b/y ion masses, an OpenMS example mzML |
| [pyscf](pyscf/) | chemistry | Linux, macOS, Windows | Ab initio quantum chemistry: HF, DFT, MP2, CCSD(T) energies, optimization, frequencies and thermochemistry, excited states (TDDFT) | established | PySCF's test suite (water HF, B3LYP, MP2, CCSD(T), frequencies; CIS of HF); NIST CCCBDB |
| [pyxtal](pyxtal/) | materials, chemistry | Linux, macOS, Windows | Crystal structure generation by symmetry: random crystals of a composition in chosen or random space groups, molecular crystals from built-in molecules or SMILES, Wyckoff tables, compatible space groups; starting points for crystal structure prediction | established | International Tables: rock salt and diamond as the only fits in Fm-3m and Fd-3m, the Wyckoff positions of Fm-3m, a P2_1/c molecular crystal |
| [quantum-espresso](quantum-espresso/) | materials | Linux, macOS, Windows (WSL) | Plane-wave DFT with the verified SSSP pseudopotentials: energies, forces, stress, relaxation, equation of state, gaps, magnetism | established | Quantum ESPRESSO's test suite (Si); all-electron PBE equation of state (Delta benchmark); Fe moment |
| [raspa3](raspa3/) | materials, chemistry | Linux, macOS, Windows | Gas adsorption in zeolites and MOFs by Monte Carlo (GCMC, Widom): isotherms, uptake and selectivity from mixtures such as CO2/N2 flue gas, Henry coefficients, heats of adsorption for CO2, N2, and methane, in bundled frameworks (silicalite, HKUST-1, MOF-5, CALF-20) or any CIF | established | Measured methane and CO2 isotherms in silicalite (Abdul-Rehman et al. 1990; Siperstein & Myers 2001; Smit 2015); methane storage in HKUST-1 (Mason et al. 2014) |
| [reaktoro](reaktoro/) | chemistry, earth science, engineering | Linux, macOS, Windows | Aqueous and geochemical equilibrium with the PHREEQC databases: speciation of water analyses (pH, ionic strength, species, mineral saturation indices), mineral solubility and precipitation, water open to air or CO2, solubility versus temperature, Pitzer brines | established | PHREEQC 3 manual examples: gypsum in pure water, calcite open to atmospheric CO2, seawater speciation |
| [rdkit](rdkit/) | chemistry | Linux, macOS, Windows | Similarity and substructure search, 3D conformers (ETKDG + MMFF94), standardization with InChI/InChIKey | established | RDKit's documentation (doctested similarities and searches); PubChem identifiers |
| [robocrys](robocrys/) | materials, chemistry | Linux, macOS, Windows | Crystal structures described in words (robocrystallographer): mineral prototype, dimensionality, coordination polyhedra and their corner, edge, or face sharing, tilts, bond lengths; per-site environments with ChemEnv polyhedra | established | robocrystallographer's own tests (rutile SnO2, MAPI); textbook rock salt, cubic perovskite, 2H-MoS2, and solid CO2 from published structures |
| [structural-analogs](structural-analogs/) | materials | Linux, macOS, Windows | Materials Project compounds with the same crystal structure type as a material or structure file, with band gaps, formation energies, stability, and volumes, for estimating properties by analogy; from the mp-property-analogies hackathon project | experimental | Rock-salt and diamond-structure analogs (KCl for NaCl, Ge for Si); needs a free API key |
| [surfaces](surfaces/) | materials, chemistry | Linux, macOS, Windows | Slabs along any Miller plane with all terminations, adsorption sites (top, bridge, fcc/hcp and four-fold hollows) and adsorbate placement, and nanoparticle shapes from surface energies (Wulff, Winterbottom, decahedra, icosahedra; WulffPack) | established | WulffPack's own tests (truncated octahedron, supported particle); exact fcc slab spacings, surface cells, and adsorption-site geometry |
| [synthesis-recipes](synthesis-recipes/) | materials, chemistry | Linux, macOS, Windows | Published synthesis recipes (41,300 text-mined solid-state and sol-gel recipes: precursors, reactions, temperatures, times, atmospheres, DOIs), similar Materials Project compositions, and suggested routes for new materials from their closest analogs; from the SKY hackathon agent | experimental | Exact composition-identity checks; recipe counts of the bundled dataset; NCA analog for a new NCA composition |
| [thermo](thermo/) | chemistry, engineering | Linux, macOS, Windows | Chemical engineering thermodynamics: properties of about 20,000 chemicals, vapor-liquid equilibrium with UNIFAC, Peng-Robinson, or Raoult's law (flash, bubble and dew points, T-x-y diagrams, azeotropes), and pipe pressure drop | published | NIST constants of ethanol; IAPWS-95 vapor pressure of water; the ethanol-water azeotrope (Evans 1916); Hagen-Poiseuille and Prandtl-Karman pipe flow |
| [umadock](umadock/) | chemistry, biology | Linux, macOS, Windows | Protein-ligand docking scored by machine-learned potentials (from the UMA-Dock hackathon project): capped binding-site clusters from any PDB, RDKit conformers, AIMNet2 or MACE-OMOL-0 pose optimization, binding energy with strain and desolvation | experimental | UMA-Dock's documented SULT1A3 pocket; overlap-free site after filling residue gaps; paracetamol binds favourably, as UMA-Dock reports |
| [vina](vina/) | chemistry, biology | Linux, macOS, Windows | Protein-ligand docking: receptor and ligand preparation (SMILES or SDF), ranked poses with Vina/Vinardo scores, RMSD to a known pose, rescoring and local optimization | established | Vina's 1IEP tutorial (imatinib redocked within 2 Å, -13.2 kcal/mol), from the crystal ligand and from SMILES |
| [xraylib](xraylib/) | materials, physics, engineering | Linux, macOS, Windows | X-ray interactions: mass attenuation (photoelectric, Compton, Rayleigh) of elements, formulas, and NIST materials, transmission and half-value layers, absorption edges, emission lines and wavelengths, fluorescence yields, XRF/EDS peak identification | established | NIST attenuation tables (lead, water, lead K edge); NIST X-ray transition energies (Cu K-alpha1, Deslattes et al. 2003) |
| [xtb](xtb/) | chemistry | Linux, macOS, Windows | GFN2-xTB energies, optimization, frequencies, and thermochemistry for molecules, with implicit solvent | established | xtb's test suite (propyne; GBSA solvation) |
| [zeopp](zeopp/) | materials, chemistry | Linux, macOS, Windows (WSL) | Pore geometry of zeolites, MOFs, and cages: largest included and free (pore-limiting) sphere diameters overall and along each axis, channel dimensionality, and the surface area and pore volume available to a probe | established | IZA Database of Zeolite Structures (MFI, LTA, FAU pore diameters); exact geometry of a simple cubic lattice of spheres |

**Maturity** tells AI agents how far to trust a tool: *established* (mature,
widely used code, checked against independent references or exact results),
*published* (research code from a publication, less widely tested), or
*experimental* (little outside validation). Agents prefer established tools when
several fit and cross-check experimental ones; see
[Tool package format](../docs/tool-format.md#maturity).

**Runs on** comes from each tool's `scipatch.lock` (Linux x86-64, macOS on Apple
silicon, Windows); `scipatch info <tool>` also covers ARM Linux and Intel Macs, and
names what is missing where a tool cannot be installed. On Windows, OpenMM
handles proteins, nucleic acids, and water; its small-molecule features need
AmberTools, which has no Windows build; AutoDock Vina uses the official
Windows executable. **Windows (WSL)**: codes without Windows builds (CREST,
GPAW, LAMMPS, and Quantum ESPRESSO, as their own documentation recommends, and
Zeo++) run inside WSL with the same Linux packages; set it up once with
`wsl --install`.

Two more tools ship inside SciPatch itself: `ase-emt` (fast approximate
simulations of metals) and `rdkit-descriptors` (molecular properties from
SMILES).

## Installing

From a copy of this repository:

```bash
scipatch add tools/ml-potentials
```

From the published collection, add it once and install tools by name:

```bash
scipatch catalog add https://github.com/MJRaei/SciPatch
scipatch catalog                      # browse
scipatch add ml-potentials
scipatch catalog update               # fetch new and updated tools
```

The Materials Project and structural-analogs tools need a free API key from
<https://next-gen.materialsproject.org/api>. `scipatch add materials-project` asks
for it; you can also add it later on the dashboard's Keys page, through the link
your AI app shows when the key is missing, or with `scipatch secret set MP_API_KEY`.

## Workflows

The tools are designed to be chained: outputs are files that the next tool
accepts.

- **Is a new material stable?** `materials-project.search` (known phases) →
  `ml-potentials.relax` and `ml-potentials.compare_models` (do four independent
  potentials agree?) →
  `gpaw.scf` on the relaxed structure (do DFT forces and stress agree?) →
  `phonopy.phonons` on the relaxed structure (dynamical stability).
- **Crystal structure prediction:** `pyxtal.compatible_space_groups` →
  `pyxtal.random_crystals` (many structures, several formula units per cell) →
  `ml-potentials.relax` on each → the lowest energy per atom →
  `pymatgen-structure.symmetry` and `phonopy.phonons` on the best.
- **Electronic structure:** `gpaw.scf` → `gpaw.band_structure` on its restart
  file (gap, direct or indirect, band edges; PBE gaps are too small).
- **Batteries:** `ml-potentials` and `pymatgen-diffusion` for ion transport in an
  electrode or electrolyte material → `pybamm.discharge` and
  `pybamm.rate_capability` for the cell (capacity and energy versus rate, heating).
- **Electrochemical impedance:** `impedance.kramers_kronig` (is the spectrum
  valid?) → `impedance.fit_circuit` (ohmic, charge-transfer, and diffusion
  contributions) → compare cells, temperatures, or states of charge.
- **Heat treatment by diffusion:** `pycalphad.equilibrium` (which phase at the
  treatment temperature?) → `fipy.diffusion_1d` with D0 and Q (case depth, or
  the time to reach a concentration at a depth).
- **Catalysis on surfaces:** `surfaces.make_slab` (any Miller plane and
  termination) → `surfaces.adsorption_sites` (place O, OH, CO, ... on top,
  bridge, or hollow sites) → `ml-potentials.relax` or DFT on both → adsorption
  energy; slab energies of several facets → `surfaces.wulff_shape` (particle
  shape and exposed facets).
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
- **From a micrograph to a structure:** `atombridge.extract_figures` on the
  paper → `atombridge.measure_lattice` on a clean region of the image (scale from
  the scale bar) → compare with candidates (`materials-project.search`,
  `pymatgen-structure.symmetry`) → `atombridge.check_structure` on what you build.
- **Why is it (not) a metal?** `clue.predict_metallicity` → `clue.counterfactuals`
  (similar Materials Project compounds classified the other way) →
  `robocrys.describe` on each to explain the difference; check with a band
  structure (`gpaw.band_structure`).
- **Identify a structure:** `pymatgen-structure.symmetry` and `xrd_pattern`, then
  `compare` with candidates from `materials-project.get_structure`;
  `robocrys.describe` explains it in words (prototype, polyhedra, layers).
- **X-ray absorption (XANES/EXAFS):** `larch.normalize` (edge energy, white
  line) → `larch.linear_combination` with reference spectra (oxidation states,
  phase fractions); `larch.feff_paths` on a candidate structure →
  `larch.fit_shells` (distances, coordination numbers, disorder).
- **X-ray experiments:** `xraylib.element_xray_data` (source lines and absorption
  edges) → `xraylib.attenuation` for sample thickness, filters, or shielding →
  `xraylib.identify_peak` for fluorescence peaks; `pymatgen-structure.xrd_pattern`
  for diffraction.
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
- **Separations:** `thermo.binary_vle` (T-x-y diagram; an azeotrope limits plain
  distillation) → `thermo.flash` for feed and product streams →
  `thermo.pipe_flow` for the lines between units.
- **Refrigeration and power cycles:** `coolprop.state` and `coolprop.saturation`
  at each point of the cycle (work, heat, COP or efficiency) →
  `coolprop.diagram` to draw it on a p-h or T-s chart; `cantera` when the
  working fluid reacts.
- **Solar PV:** `pvlib.pvgis_weather` (typical year for the site) →
  `pvlib.pv_energy` for a few tilts and orientations (kWh/kWp, monthly profile)
  → `pvlib.solar_position` at critical dates to check shading.
- **Water chemistry and scaling:** `reaktoro.speciate` on the water analysis
  (saturation indices) → `reaktoro.mineral_equilibrium` for how much calcite or
  gypsum would precipitate → `reaktoro.solubility_curve` for heated sections.
- **Carbon capture and gas storage:** `zeopp.pore_geometry` (do CO2 and N2 fit
  through the windows?) → `raspa3.henry_coefficient` for each candidate CIF
  (CO2/N2 selectivity at low pressure) →
  `raspa3.mixture_adsorption` with flue gas (15% CO2, 85% N2) and
  `raspa3.adsorption_isotherm` for the best ones (uptake between adsorption and
  desorption pressures).
- **Defects and plasticity:** `lammps.run_script` with your deformation or
  cascade input → `ovito.dislocations` (line length, Burgers vectors, density)
  and `ovito.point_defects` (vacancies, interstitials per frame).
- **Protein protonation:** `propka.fetch_pdb` → `propka.protein_pka` at the
  working pH (which His, Asp, and Glu are charged, which pKa values are shifted) →
  use those states when preparing `openmm` or `vina` inputs.
- **Docking:** `openbabel.convert` (protonate the ligand for pH 7.4) →
  `vina.dock` (redock the crystal ligand first to validate the box) →
  `openmm.simulate` with the best pose as `small_molecules` →
  `mdanalysis.rmsd` on `start.pdb` + `trajectory.dcd` (does the pose stay?).
- **How to make it (molecules)?** `aizynthfinder.retrosynthesis` (routes back to
  purchasable compounds, or `custom_stock` with what is on the shelf) →
  `aizynthfinder.single_step` for alternatives at a difficult step → look up
  conditions for each step before lab work.
- **What did my reaction give?** For each expected species, a measured
  reference spectrum or `nmr-mixtures.predict_spectrum` →
  `nmr-mixtures.quantify_mixture` on the crude 1H NMR (yield, selectivity,
  isomer ratio) → `nmr-mixtures.reaction_kinetics` for spectra over time.
- **Mass spectrometry:** `pyopenms.mass` and `pyopenms.isotope_pattern` for the
  expected ions → compare with the measured spectrum; for proteins
  `pyopenms.digest` → `pyopenms.fragment_ions` for the peptides of interest.
- **Why do two molecules bind?** `crest.conformer_search` or `xtb.optimize` on
  the complex → `psi4.sapt` (electrostatics, exchange, induction, dispersion) →
  `psi4.interaction_energy` with DFT-D3 or, for small complexes, CCSD(T)/CBS.
- **Automating a lab procedure:** `catalyze.chemical_safety` for each reagent
  (hazards, handling) → `catalyze.labware` for valid labware → write the Opentrons
  protocol → `catalyze.simulate_protocol` until it runs cleanly → check the
  volumes and run log before the robot.
- **Explain a result in a short video:** write a storyboard →
  `atomic-shorts.check_storyboard` (length, terms to verify) → Manim code →
  `atomic-shorts.render_scene` (fix errors it reports) → `atomic-shorts.narrate`.
- **Chemical files:** `openbabel.convert` and `openbabel.identifiers` move
  molecules between programs and formats and give InChIKeys for lookups.

## Licenses

Each tool's `scipatch.yaml` states its license. Note especially: MACE-OFF models
are for non-commercial use only (Academic Software License), Materials Project
data is CC BY 4.0, xtb is LGPL-3.0, and LAMMPS and Open Babel are GPL-2.0.
Upstream code, potential files, and pseudopotentials are downloaded from their
original sources at install time and are not redistributed here. Small test
inputs taken from upstream projects (the LAMMPS benchmark input, the Vina 1IEP
tutorial files, an excerpt of MDAnalysis's adenylate kinase trajectory,
molecules of the MMFF94 validation suite, MixSense's example spectra,
impedance.py's example spectrum, xraylarch's example XAFS spectra, Psi4's test
complexes, robocrystallographer's test structures, crystal structures from the
Crystallography Open Database, IZA zeolite frameworks, RASPA3's HKUST-1
structure, PROPKA's 1HPX test structure, an OpenMS example spectrum, and a PVGIS
typical year for Munich from the European Commission's JRC) keep their sources'
terms; each golden test names its source.

## Adding a tool

See [Turning a repository into a tool](../docs/onboarding.md). A tool is
accepted when:

- [ ] `scipatch check tools/<name> --clean` passes;
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
- [ ] versions are pinned for every platform with `scipatch freeze tools/<name>`.
