"""Molecular mechanics and molecular dynamics with OpenMM.

Proteins, nucleic acids, water, and ions with standard force fields (Amber,
CHARMM), from PDB/mmCIF files, or any system prepared with Amber (prmtop and
inpcrd/rst7). Small molecules (ligands, solvents) are parameterized with the
Open Force Field (OpenFF Sage) or GAFF, with AM1-BCC charges. Energies are in
kJ/mol (and kcal/mol), lengths in nm.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

import numpy as np

WaterModel = Literal["tip3p", "tip3pfb", "opc", "spce", "tip4pew"]
ImplicitSolvent = Literal["obc2", "gbn2", "hct", "obc1", "gbn"]
Platform = Literal["auto", "CPU", "CUDA", "OpenCL", "Reference"]
SmallMoleculeForceField = Literal["openff-2.3.0", "openff-2.2.1", "gaff-2.2.20"]
DEFAULT_SMALL_FF = "openff-2.3.0"

KJ_PER_KCAL = 4.184
_AMBER_SUFFIXES = (".prmtop", ".parm7", ".top")
_MOLECULE_SUFFIXES = (".sdf", ".mol")
#: Water models: force field file and the name Modeller uses to build the box.
_WATER = {
    "tip3p": ("amber14/tip3p.xml", "tip3p"),
    "tip3pfb": ("amber14/tip3pfb.xml", "tip3p"),
    "opc": ("amber14/opc.xml", "tip4pew"),
    "spce": ("amber14/spce.xml", "spce"),
    "tip4pew": ("amber14/tip4pew.xml", "tip4pew"),
}


def _platform(name: Platform) -> Any:
    import openmm

    if name != "auto":
        return openmm.Platform.getPlatformByName(name)
    available = {
        openmm.Platform.getPlatform(i).getName() for i in range(openmm.Platform.getNumPlatforms())
    }
    for candidate in ("CUDA", "HIP", "CPU"):
        if candidate in available:
            return openmm.Platform.getPlatformByName(candidate)
    return openmm.Platform.getPlatformByName("Reference")


def _forcefield(
    forcefield: str,
    water_model: WaterModel,
    implicit: ImplicitSolvent | None,
    molecules: list[Any] | None = None,
    small_molecule_forcefield: str = DEFAULT_SMALL_FF,
) -> Any:
    from openmm import app

    files = [forcefield if forcefield.endswith(".xml") else f"{forcefield}.xml"]
    files.append(f"implicit/{implicit}.xml" if implicit else _WATER[water_model][0])
    try:
        field = app.ForceField(*files)
    except ValueError as exc:
        raise ValueError(
            f"Unknown force field {files}: {exc}. Common choices: amber14-all, amber19-all, "
            "charmm36_2024, amber99sbildn."
        ) from exc
    if molecules:
        field.registerTemplateGenerator(_generator(molecules, small_molecule_forcefield))
    return field


def _generator(molecules: list[Any], name: str) -> Any:
    """OpenMM template generator that parameterizes small molecules (AM1-BCC charges)."""
    from openmmforcefields.generators import GAFFTemplateGenerator, SMIRNOFFTemplateGenerator

    kind = GAFFTemplateGenerator if name.startswith("gaff") else SMIRNOFFTemplateGenerator
    return kind(molecules=molecules, forcefield=name).generator


def _read_molecules(paths: list[str] | None) -> list[Any]:
    """OpenFF molecules (with 3D coordinates) from SDF/MOL files."""
    from openff.toolkit import Molecule

    molecules: list[Any] = []
    for path in paths or []:
        if Path(path).suffix.lower() not in _MOLECULE_SUFFIXES:
            raise ValueError(f"{path}: give small molecules as SDF or MOL files (3D coordinates).")
        try:
            loaded = Molecule.from_file(path, allow_undefined_stereo=True)
        except Exception as exc:
            raise ValueError(
                f"Could not read {path}: {exc}. Small molecules need all hydrogens and bond orders."
            ) from exc
        for molecule in loaded if isinstance(loaded, list) else [loaded]:
            if not molecule.conformers:
                raise ValueError(f"{path} has no 3D coordinates.")
            molecules.append(molecule)
    return molecules


def _molecule_topology(molecule: Any) -> tuple[Any, Any]:
    """OpenMM topology and positions of one OpenFF molecule."""
    return molecule.to_topology().to_openmm(), molecule.conformers[0].to_openmm()


def _load(structure: str, coordinates: str | None) -> tuple[Any, Any, Any]:
    """(topology, positions, Amber prmtop or None) from a PDB/mmCIF file or Amber files."""
    from openmm import app

    path = Path(structure)
    if path.suffix.lower() in _AMBER_SUFFIXES:
        if coordinates is None:
            raise ValueError("An Amber topology needs coordinates: pass an inpcrd or rst7 file.")
        inpcrd = app.AmberInpcrdFile(coordinates)
        prmtop = app.AmberPrmtopFile(structure, periodicBoxVectors=inpcrd.boxVectors)
        return prmtop.topology, inpcrd.positions, prmtop
    if path.suffix.lower() in (".cif", ".mmcif", ".pdbx"):
        pdbx = app.PDBxFile(structure)
        return pdbx.topology, pdbx.positions, None
    pdb = app.PDBFile(structure)
    return pdb.topology, pdb.positions, None


def _create_system(
    topology: Any,
    prmtop: Any,
    forcefield: Any,
    cutoff_nm: float,
    constraints: Any,
    implicit: ImplicitSolvent | None,
) -> Any:
    from openmm import app, unit

    periodic = topology.getPeriodicBoxVectors() is not None and implicit is None
    method = app.PME if periodic else app.NoCutoff
    kwargs = {"nonbondedMethod": method, "constraints": constraints}
    if periodic:
        kwargs["nonbondedCutoff"] = cutoff_nm * unit.nanometer
    if prmtop is not None:
        if implicit:
            models = {"obc1": app.OBC1, "obc2": app.OBC2, "gbn": app.GBn, "gbn2": app.GBn2}
            kwargs["implicitSolvent"] = models.get(implicit, app.HCT)
        return prmtop.createSystem(**kwargs)
    try:
        return forcefield.createSystem(topology, **kwargs)
    except ValueError as exc:
        if "No template found" in str(exc):
            residue = str(exc).split("(")[-1].split(")")[0] if "(" in str(exc) else "?"
            raise ValueError(
                f"The force field has no parameters for residue {residue}. Proteins, nucleic "
                "acids, water, and ions are covered by the force field; give each small "
                "molecule (ligand) as an SDF file with 3D coordinates and hydrogens in "
                "small_molecules, and remove it from the PDB. Check also that the structure "
                "has hydrogens (simulate adds them to biomolecules) and standard residue names."
            ) from exc
        raise


def _energies(context: Any, system: Any) -> dict[str, float]:
    from openmm import unit

    components: dict[str, float] = {}
    for index, force in enumerate(system.getForces()):
        force.setForceGroup(index)
    context.reinitialize(preserveState=True)
    for index, force in enumerate(system.getForces()):
        state = context.getState(getEnergy=True, groups={index}, enforcePeriodicBox=True)
        value = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
        components[force.getName()] = components.get(force.getName(), 0.0) + value
    return {name: value for name, value in components.items() if value != 0.0}


def _system_inputs(
    structure: str,
    coordinates: str | None,
    small_molecules: list[str] | None,
) -> tuple[Any, Any, Any, list[Any]]:
    """Topology, positions, Amber prmtop (or None), and the small molecules to parameterize."""
    from openmm import app

    molecules = _read_molecules(small_molecules)
    if Path(structure).suffix.lower() in _MOLECULE_SUFFIXES:
        own = _read_molecules([structure])
        molecules = own + molecules
        topology, positions = _molecule_topology(own[0])
        modeller = app.Modeller(topology, positions)
        for molecule in own[1:]:
            modeller.add(*_molecule_topology(molecule))
        prmtop = None
    else:
        topology, positions, prmtop = _load(structure, coordinates)
        modeller = app.Modeller(topology, positions)
    if prmtop is None:
        for molecule in _read_molecules(small_molecules):
            modeller.add(*_molecule_topology(molecule))
        topology, positions = modeller.topology, modeller.positions
    return topology, positions, prmtop, molecules


def energy(
    structure: str,
    coordinates: str | None = None,
    small_molecules: list[str] | None = None,
    forcefield: str = "amber14-all",
    water_model: WaterModel = "tip3p",
    implicit_solvent: ImplicitSolvent | None = None,
    small_molecule_forcefield: SmallMoleculeForceField = DEFAULT_SMALL_FF,
    cutoff_nm: float = 1.0,
    platform: Platform = "auto",
) -> dict:
    """Potential energy of a system and its components (bonds, angles, torsions, nonbonded).

    Args:
        structure: PDB or mmCIF file with all atoms (including hydrogens), an SDF/MOL
            file of a small molecule, or an Amber topology (prmtop/parm7), which
            carries its own force field.
        coordinates: Amber inpcrd/rst7 coordinates (Amber topologies only).
        small_molecules: SDF/MOL files of ligands or other small molecules (3D
            coordinates, all hydrogens) to add to the structure.
        forcefield: OpenMM force field for biomolecules, e.g. "amber14-all",
            "amber19-all", "charmm36_2024".
        water_model: Water model matching the waters in the structure.
        implicit_solvent: Implicit solvent model ("obc2", "gbn2", ...) instead of
            explicit water; the structure must not contain water then.
        small_molecule_forcefield: "openff-2.3.0" (Sage; default), "openff-2.2.1",
            or "gaff-2.2.20".
        cutoff_nm: Nonbonded cutoff for periodic systems (PME), in nm.
        platform: OpenMM platform; "auto" picks a GPU if available, otherwise CPU.

    Returns:
        Total potential energy (kJ/mol and kcal/mol), energy by force term
        (kJ/mol), number of atoms, and whether the system is periodic.
    """
    import openmm
    from openmm import unit

    topology, positions, prmtop, molecules = _system_inputs(structure, coordinates, small_molecules)
    field = None
    if prmtop is None:
        field = _forcefield(
            forcefield, water_model, implicit_solvent, molecules, small_molecule_forcefield
        )
    system = _create_system(topology, prmtop, field, cutoff_nm, None, implicit_solvent)
    context = openmm.Context(system, openmm.VerletIntegrator(0.001), _platform(platform))
    context.setPositions(positions)
    state = context.getState(getEnergy=True, enforcePeriodicBox=True)
    total = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    return {
        "energy_kj_mol": total,
        "energy_kcal_mol": total / KJ_PER_KCAL,
        "components_kj_mol": _energies(context, system),
        "n_atoms": system.getNumParticles(),
        "periodic": topology.getPeriodicBoxVectors() is not None,
        "force_field": "Amber topology" if prmtop is not None else forcefield,
        "small_molecule_force_field": small_molecule_forcefield if molecules else None,
    }


def _prepare(
    structure: str,
    molecules: list[Any],
    forcefield: Any,
    water_model: WaterModel,
    implicit: ImplicitSolvent | None,
    fix_structure: bool,
    ph: float,
    padding_nm: float,
    box_nm: float | None,
    ionic_strength_molar: float,
) -> tuple[Any, Any]:
    """Complete the biomolecule, add small molecules, and solvate."""
    from openmm import Vec3, app, unit

    if structure == "water":
        if box_nm is None:
            raise ValueError("A pure water box needs box_nm, e.g. 2.5.")
        modeller = app.Modeller(app.Topology(), [])
    elif Path(structure).suffix.lower() in _MOLECULE_SUFFIXES:
        modeller = app.Modeller(app.Topology(), [])
    elif fix_structure and Path(structure).suffix.lower() in (".pdb", ".cif", ".mmcif", ".pdbx"):
        from pdbfixer import PDBFixer

        fixer = PDBFixer(filename=structure)
        fixer.findMissingResidues()
        fixer.missingResidues = {}  # never invent missing loops; only complete residues
        fixer.findNonstandardResidues()
        fixer.replaceNonstandardResidues()
        fixer.findMissingAtoms()
        fixer.addMissingAtoms()
        fixer.addMissingHydrogens(ph)
        modeller = app.Modeller(fixer.topology, fixer.positions)
    else:
        topology, positions, _ = _load(structure, None)
        modeller = app.Modeller(topology, positions)
    for molecule in molecules:
        modeller.add(*_molecule_topology(molecule))
    if implicit is None:
        kwargs: dict[str, Any] = {
            "model": _WATER[water_model][1],
            "ionicStrength": ionic_strength_molar * unit.molar,
            "neutralize": True,
        }
        if box_nm is not None:
            kwargs["boxSize"] = Vec3(box_nm, box_nm, box_nm) * unit.nanometer
        else:
            kwargs["padding"] = padding_nm * unit.nanometer
        modeller.addSolvent(forcefield, **kwargs)
    return modeller.topology, modeller.positions


def _density(state: Any, system: Any) -> float:
    from openmm import unit

    mass = sum(
        system.getParticleMass(i).value_in_unit(unit.dalton)
        for i in range(system.getNumParticles())
    )
    volume = state.getPeriodicBoxVolume().value_in_unit(unit.nanometer**3)
    return mass / volume * 1.66053906660 / 1000  # Da/nm^3 -> g/cm^3


def _backbone_rmsd(topology: Any, start: np.ndarray, end: np.ndarray) -> float | None:
    """RMSD (nm) of protein C-alpha atoms after optimal superposition, or None without protein."""
    indices = [atom.index for atom in topology.atoms() if atom.name == "CA"]
    if len(indices) < 3:
        return None
    a, b = start[indices] - start[indices].mean(0), end[indices] - end[indices].mean(0)
    u, _, vt = np.linalg.svd(a.T @ b)
    d = np.sign(np.linalg.det(u @ vt))
    rotation = u @ np.diag([1, 1, d]) @ vt
    return float(np.sqrt(((a @ rotation - b) ** 2).sum(1).mean()))


def _run_dynamics(
    topology: Any,
    positions: Any,
    system: Any,
    periodic: bool,
    temperature_k: float,
    pressure_bar: float | None,
    time_ps: float,
    equilibration_ps: float,
    timestep_fs: float,
    report_interval_ps: float,
    seed: int,
    platform: Platform,
) -> dict[str, Any]:
    """Minimize, equilibrate, and run production MD; returns averages and file paths."""
    import time

    import openmm
    from openmm import app, unit

    if time_ps < 0 or equilibration_ps < 0 or not 0.5 <= timestep_fs <= 4:
        raise ValueError("Times must be non-negative and timestep_fs between 0.5 and 4.")
    temperature = temperature_k * unit.kelvin
    if periodic and pressure_bar is not None:
        system.addForce(openmm.MonteCarloBarostat(pressure_bar * unit.bar, temperature))
    integrator = openmm.LangevinMiddleIntegrator(
        temperature, 1 / unit.picosecond, timestep_fs * unit.femtosecond
    )
    integrator.setRandomNumberSeed(seed)
    simulation = app.Simulation(topology, system, integrator, _platform(platform))
    simulation.context.setPositions(positions)
    print("Minimizing...", flush=True)
    simulation.minimizeEnergy()
    start = simulation.context.getState(getPositions=True, enforcePeriodicBox=periodic)
    with open("start.pdb", "w") as handle:
        app.PDBFile.writeFile(topology, start.getPositions(), handle)
    simulation.context.setVelocitiesToTemperature(temperature, seed)

    steps_per_ps = round(1000 / timestep_fs)
    interval = max(1, round(report_interval_ps * steps_per_ps))
    print(f"Equilibrating for {equilibration_ps} ps...", flush=True)
    simulation.step(round(equilibration_ps * steps_per_ps))

    production = round(time_ps * steps_per_ps)
    rows: list[tuple[float, float, float | None, float | None]] = []
    began = time.monotonic()
    if production:
        simulation.reporters.append(app.DCDReporter("trajectory.dcd", interval))
        progress = app.StateDataReporter(
            sys.stdout,
            interval * 10,
            step=True,
            time=True,
            temperature=True,
            density=periodic,
            speed=True,
            totalSteps=production,
            remainingTime=True,
        )
        simulation.reporters.append(progress)
        dof = 3 * system.getNumParticles() - system.getNumConstraints() - 3
        done = 0
        while done < production:
            chunk = min(interval, production - done)
            simulation.step(chunk)
            done += chunk
            state = simulation.context.getState(getEnergy=True)
            kinetic = state.getKineticEnergy()
            temp = (2 * kinetic / (dof * unit.MOLAR_GAS_CONSTANT_R)).value_in_unit(unit.kelvin)
            potential = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
            volume = state.getPeriodicBoxVolume().value_in_unit(unit.nanometer**3)
            rows.append((
                temp,
                potential,
                _density(state, system) if periodic else None,
                volume if periodic else None,
            ))  # fmt: skip
    elapsed = time.monotonic() - began
    final = simulation.context.getState(getPositions=True, enforcePeriodicBox=periodic)
    with open("final.pdb", "w") as handle:
        app.PDBFile.writeFile(topology, final.getPositions(), handle)
    _write_log(rows, report_interval_ps, "log.csv")

    data = np.array([[np.nan if v is None else v for v in row] for row in rows]) if rows else None

    def mean(i: int) -> float | None:
        if data is None or (i >= 2 and not periodic):
            return None
        return float(np.nanmean(data[:, i]))

    def std(i: int) -> float | None:
        if data is None or not periodic:
            return None
        return float(np.nanstd(data[:, i]))

    start_xyz = np.asarray(start.getPositions(asNumpy=True).value_in_unit(unit.nanometer))
    final_xyz = np.asarray(final.getPositions(asNumpy=True).value_in_unit(unit.nanometer))
    return {
        "n_atoms": system.getNumParticles(),
        "n_waters": sum(1 for residue in topology.residues() if residue.name == "HOH"),
        "periodic": periodic,
        "ensemble": "NPT" if periodic and pressure_bar is not None else "NVT",
        "production_ps": time_ps,
        "temperature_mean_k": mean(0),
        "potential_energy_mean_kj_mol": mean(1),
        "density_mean_g_cm3": mean(2),
        "density_std_g_cm3": std(2),
        "volume_mean_nm3": mean(3),
        "ca_rmsd_nm": _backbone_rmsd(topology, start_xyz, final_xyz),
        "speed_ns_per_day": (time_ps / 1000) / (elapsed / 86400) if production else None,
        "platform": simulation.context.getPlatform().getName(),
        "trajectory": "trajectory.dcd" if production else None,
        "start_structure": "start.pdb",
        "final_structure": "final.pdb",
        "log": "log.csv",
    }


def simulate(
    structure: str,
    small_molecules: list[str] | None = None,
    forcefield: str = "amber14-all",
    water_model: WaterModel = "tip3p",
    implicit_solvent: ImplicitSolvent | None = None,
    small_molecule_forcefield: SmallMoleculeForceField = DEFAULT_SMALL_FF,
    temperature_k: float = 300.0,
    pressure_bar: float | None = 1.0,
    time_ps: float = 100.0,
    equilibration_ps: float = 10.0,
    timestep_fs: float = 2.0,
    report_interval_ps: float = 1.0,
    padding_nm: float = 1.0,
    box_nm: float | None = None,
    ionic_strength_molar: float = 0.15,
    fix_structure: bool = True,
    ph: float = 7.0,
    cutoff_nm: float = 1.0,
    seed: int = 1,
    platform: Platform = "auto",
) -> dict:
    """Prepare and run molecular dynamics of a biomolecule, small molecule, or water.

    The biomolecule is completed (missing heavy atoms and hydrogens at the given
    pH; missing loops are not built), small molecules are added at their given
    coordinates and parameterized (OpenFF Sage or GAFF, AM1-BCC charges), and
    everything is solvated in a water box with ions, then minimized,
    equilibrated, and simulated with a Langevin thermostat (and a Monte Carlo
    barostat at constant pressure). Bonds to hydrogen are constrained.

    Args:
        structure: PDB or mmCIF file of the biomolecule (without ligands), an
            SDF/MOL file of a small molecule to simulate in water, or "water" for a
            pure water box (with box_nm).
        small_molecules: SDF/MOL files of ligands (3D pose, all hydrogens) to add,
            e.g. a docked ligand next to the protein.
        forcefield: OpenMM force field for biomolecules, e.g. "amber14-all"
            (default), "amber19-all", "charmm36_2024".
        water_model: "tip3p" (default), "tip3pfb", "opc", "spce", or "tip4pew".
        implicit_solvent: Use implicit solvent ("obc2", "gbn2", ...) instead of a
            water box (faster, no pressure control).
        small_molecule_forcefield: "openff-2.3.0" (Sage; default), "openff-2.2.1",
            or "gaff-2.2.20".
        temperature_k: Temperature in K.
        pressure_bar: Pressure in bar (NPT); None for constant volume (NVT).
        time_ps: Production time in ps (0: minimize and equilibrate only).
        equilibration_ps: Equilibration time in ps before production.
        timestep_fs: Time step in fs (2 fs with hydrogen bonds constrained).
        report_interval_ps: Interval between saved frames and log lines, in ps.
        padding_nm: Minimum water layer around the solutes, in nm.
        box_nm: Cubic box edge in nm instead of padding (required for "water").
        ionic_strength_molar: Salt (NaCl) concentration in mol/L; the system is
            neutralized in any case.
        fix_structure: Complete the biomolecule with PDBFixer first.
        ph: pH for adding hydrogens to the biomolecule.
        cutoff_nm: Nonbonded cutoff in nm (PME for electrostatics).
        seed: Random seed for initial velocities.
        platform: OpenMM platform; "auto" picks a GPU if available, otherwise CPU.

    Returns:
        Number of atoms and waters, averages over production (temperature K,
        potential energy kJ/mol, density g/cm^3 and box volume nm^3 when
        periodic), C-alpha RMSD from the start (nm), simulation speed (ns/day),
        and paths to the trajectory (DCD), the first and last frames (PDB), and
        the log (CSV).
    """
    from openmm import app

    molecules = _read_molecules(small_molecules)
    if Path(structure).suffix.lower() in _MOLECULE_SUFFIXES:
        molecules = _read_molecules([structure]) + molecules
    field = _forcefield(
        forcefield, water_model, implicit_solvent, molecules, small_molecule_forcefield
    )
    topology, positions = _prepare(
        structure,
        molecules,
        field,
        water_model,
        implicit_solvent,
        fix_structure,
        ph,
        padding_nm,
        box_nm,
        ionic_strength_molar,
    )
    system = _create_system(topology, None, field, cutoff_nm, app.HBonds, implicit_solvent)
    periodic = topology.getPeriodicBoxVectors() is not None and implicit_solvent is None
    return _run_dynamics(
        topology,
        positions,
        system,
        periodic,
        temperature_k,
        pressure_bar,
        time_ps,
        equilibration_ps,
        timestep_fs,
        report_interval_ps,
        seed,
        platform,
    )


def liquid(
    molecule: str,
    n_molecules: int = 200,
    small_molecule_forcefield: SmallMoleculeForceField = DEFAULT_SMALL_FF,
    temperature_k: float = 298.15,
    pressure_bar: float = 1.0,
    time_ps: float = 100.0,
    equilibration_ps: float = 50.0,
    timestep_fs: float = 2.0,
    report_interval_ps: float = 0.5,
    cutoff_nm: float = 0.9,
    seed: int = 1,
    platform: Platform = "auto",
) -> dict:
    """Simulate a pure molecular liquid at constant temperature and pressure (density).

    The box is filled with Packmol at a low starting density, the molecules are
    parameterized (OpenFF Sage or GAFF, AM1-BCC charges), and the liquid is
    equilibrated and simulated with a barostat.

    Args:
        molecule: SMILES of the molecule, e.g. "CO" (methanol) or "c1ccccc1".
        n_molecules: Number of molecules in the box.
        small_molecule_forcefield: "openff-2.3.0" (Sage; default), "openff-2.2.1",
            or "gaff-2.2.20".
        temperature_k: Temperature in K.
        pressure_bar: Pressure in bar.
        time_ps: Production time in ps (averages are taken over it).
        equilibration_ps: Equilibration time in ps (the box shrinks to its density).
        timestep_fs: Time step in fs.
        report_interval_ps: Interval between samples, in ps.
        cutoff_nm: Nonbonded cutoff in nm (Sage was fitted with 0.9 nm).
        seed: Random seed.
        platform: OpenMM platform.

    Returns:
        Mean density (g/cm^3) with its standard deviation over production, molar
        volume (cm^3/mol), mean temperature, number of atoms, and the trajectory,
        final structure, and log paths.
    """
    import subprocess

    from openff.toolkit import Molecule, Topology
    from openmm import Vec3, app, unit

    if not 20 <= n_molecules <= 5000:
        raise ValueError("Use between 20 and 5000 molecules.")
    try:
        species = Molecule.from_smiles(molecule, allow_undefined_stereo=True)
    except Exception as exc:
        raise ValueError(f"'{molecule}' is not a valid SMILES string: {exc}") from exc
    species.generate_conformers(n_conformers=1)
    species.to_file("molecule.pdb", file_format="PDB")
    mass_g_mol = sum(atom.mass.m for atom in species.atoms)
    # Start at about 60% of a typical liquid density so Packmol never overlaps molecules.
    volume_a3 = n_molecules * mass_g_mol / (0.6 * 0.6022)
    edge = volume_a3 ** (1 / 3)
    Path("packmol.inp").write_text(
        f"tolerance 2.0\nfiletype pdb\noutput packed.pdb\nseed {seed}\n"
        f"structure molecule.pdb\n  number {n_molecules}\n"
        f"  inside box 1. 1. 1. {edge - 1:.3f} {edge - 1:.3f} {edge - 1:.3f}\nend structure\n"
    )
    with open("packmol.inp") as stdin:
        packed = subprocess.run(["packmol"], stdin=stdin, capture_output=True, text=True)
    if "Success!" not in packed.stdout:
        raise RuntimeError("Packmol could not fill the box:\n" + packed.stdout[-1500:])
    topology = Topology.from_molecules([species] * n_molecules).to_openmm()
    positions = app.PDBFile("packed.pdb").getPositions()
    topology.setPeriodicBoxVectors(
        [Vec3(edge, 0, 0), Vec3(0, edge, 0), Vec3(0, 0, edge)] * unit.angstrom
    )
    field = app.ForceField()
    field.registerTemplateGenerator(_generator([species], small_molecule_forcefield))
    system = field.createSystem(
        topology,
        nonbondedMethod=app.PME,
        nonbondedCutoff=cutoff_nm * unit.nanometer,
        constraints=app.HBonds,
    )
    result = _run_dynamics(
        topology,
        positions,
        system,
        True,
        temperature_k,
        pressure_bar,
        time_ps,
        equilibration_ps,
        timestep_fs,
        report_interval_ps,
        seed,
        platform,
    )
    density = result["density_mean_g_cm3"]
    return {
        "molecule": molecule,
        "n_molecules": n_molecules,
        "force_field": small_molecule_forcefield,
        "density_mean_g_cm3": density,
        "density_std_g_cm3": result["density_std_g_cm3"],
        "molar_volume_cm3_mol": mass_g_mol / density if density else None,
        "temperature_mean_k": result["temperature_mean_k"],
        "n_atoms": result["n_atoms"],
        "speed_ns_per_day": result["speed_ns_per_day"],
        "trajectory": result["trajectory"],
        "final_structure": result["final_structure"],
        "log": result["log"],
    }


def _write_log(rows: list[tuple], interval_ps: float, path: str) -> None:
    with open(path, "w") as handle:
        handle.write("time_ps,temperature_k,potential_energy_kj_mol,density_g_cm3,volume_nm3\n")
        for i, row in enumerate(rows):
            cells = ["" if value is None else f"{value:.6g}" for value in row]
            handle.write(f"{(i + 1) * interval_ps:.6g}," + ",".join(cells) + "\n")


def minimize(
    structure: str,
    small_molecules: list[str] | None = None,
    forcefield: str = "amber14-all",
    water_model: WaterModel = "tip3p",
    implicit_solvent: ImplicitSolvent | None = None,
    small_molecule_forcefield: SmallMoleculeForceField = DEFAULT_SMALL_FF,
    coordinates: str | None = None,
    tolerance_kj_mol_nm: float = 10.0,
    output: str = "minimized.pdb",
    platform: Platform = "auto",
) -> dict:
    """Minimize the energy of a system as given (no atoms or solvent are added).

    Args:
        structure: PDB/mmCIF file with all atoms, an SDF/MOL file of a small
            molecule, or an Amber topology (with coordinates).
        small_molecules: SDF/MOL files of small molecules to add (see energy).
        forcefield: OpenMM force field for biomolecules (see energy).
        water_model: Water model matching the waters in the structure.
        implicit_solvent: Implicit solvent model instead of explicit water.
        small_molecule_forcefield: "openff-2.3.0" (default), "openff-2.2.1", or "gaff-2.2.20".
        coordinates: Amber inpcrd/rst7 coordinates (Amber topologies only).
        tolerance_kj_mol_nm: Stop when the largest force is below this (kJ/mol/nm).
        output: PDB file for the minimized structure.
        platform: OpenMM platform.

    Returns:
        Energy before and after (kJ/mol), the change, and the minimized structure path.
    """
    import openmm
    from openmm import app, unit

    topology, positions, prmtop, molecules = _system_inputs(structure, coordinates, small_molecules)
    field = None
    if prmtop is None:
        field = _forcefield(
            forcefield, water_model, implicit_solvent, molecules, small_molecule_forcefield
        )
    system = _create_system(topology, prmtop, field, 1.0, app.HBonds, implicit_solvent)
    simulation = app.Simulation(
        topology, system, openmm.VerletIntegrator(0.001), _platform(platform)
    )
    simulation.context.setPositions(positions)
    simulation.context.applyConstraints(1e-6)

    def current() -> float:
        state = simulation.context.getState(getEnergy=True)
        return state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)

    before = current()
    tolerance = tolerance_kj_mol_nm * unit.kilojoule_per_mole / unit.nanometer
    simulation.minimizeEnergy(tolerance=tolerance)
    after = current()
    state = simulation.context.getState(getPositions=True)
    with open(output, "w") as handle:
        app.PDBFile.writeFile(topology, state.getPositions(), handle)
    return {
        "energy_before_kj_mol": before,
        "energy_after_kj_mol": after,
        "energy_change_kj_mol": after - before,
        "n_atoms": system.getNumParticles(),
        "minimized_structure": output,
    }
