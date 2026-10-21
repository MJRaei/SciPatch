"""Universal machine-learned interatomic potentials: CHGNet, MACE, MatGL, and Orb in one place.

Energies, forces, stresses, relaxation, molecular dynamics, and materials
properties (elastic constants, equation of state, quasi-harmonic thermal
properties, formation energies via matcalc) with any of the supported models,
plus a side-by-side comparison of models. Structures are read with ASE or
pymatgen (CIF, POSCAR, extended XYZ, pymatgen JSON). Energies are in eV,
lengths in Angstrom, stresses and moduli in GPa.

Only models whose packages work together on Linux, macOS, and Windows are
included (MACE pins e3nn 0.4.4, which rules out SevenNet and MatterSim here).
"""

from __future__ import annotations

import functools
import time
import warnings
from typing import Any, Literal

import numpy as np

warnings.filterwarnings("ignore")

Model = Literal[
    "Orb-v3-conservative-inf-mpa",
    "Orb-v3-conservative-inf-omat",
    "MACE-MPA-0-medium",
    "MACE-MP-0-medium",
    "MACE-MP-0-small",
    "MACE-OFF23-small",
    "MACE-OFF23-medium",
    "CHGNet-0.3.0",
    "CHGNet-0.2.0",
    "CHGNet-r2SCAN",
    "TensorNet-MatPES-PBE-2025.2",
    "TensorNet-MatPES-r2SCAN-2025.2",
    "M3GNet-MatPES-PBE-2025.1",
    "CHGNet-MatPES-PBE-1M-2026.9",
    "CHGNet-MatPES-r2SCAN-1M-2026.9",
]
Precision = Literal["auto", "float32", "float64"]
Device = Literal["cpu", "cuda"]
DEFAULT_MODEL = "Orb-v3-conservative-inf-mpa"
#: One model of each family, for compare_models.
DEFAULT_COMPARISON = [
    "Orb-v3-conservative-inf-mpa",
    "MACE-MPA-0-medium",
    "TensorNet-MatPES-PBE-2025.2",
    "CHGNet-0.3.0",
]
#: Models trained on molecules only (organic chemistry), not on crystals.
_MOLECULAR = {"MACE-OFF23-small", "MACE-OFF23-medium"}
_MACE_MP = {
    "MACE-MPA-0-medium": "medium-mpa-0",
    "MACE-MP-0-medium": "medium",
    "MACE-MP-0-small": "small",
}
_CHGNET = {"CHGNet-0.3.0": "0.3.0", "CHGNet-0.2.0": "0.2.0", "CHGNet-r2SCAN": "r2scan"}
EV_PER_ANGSTROM3_TO_GPA = 160.21766208
_FRAME_INTERVAL = 10  # MD steps between saved trajectory frames


@functools.lru_cache(maxsize=6)
def _calculator(model: str, precision: str = "auto", device: str = "cpu") -> Any:
    """An ASE calculator for a model. "auto" precision: float64 for MACE, float32 otherwise."""
    if model in _MACE_MP or model in _MOLECULAR:
        from mace.calculators import mace_mp, mace_off

        dtype = "float32" if precision == "float32" else "float64"
        if model in _MOLECULAR:
            return mace_off(model=model.split("-")[-1], default_dtype=dtype, device=device)
        return mace_mp(model=_MACE_MP[model], default_dtype=dtype, device=device)
    if model in _CHGNET:
        from chgnet.model import CHGNet
        from chgnet.model.dynamics import CHGNetCalculator

        network = CHGNet.load(model_name=_CHGNET[model], verbose=False)
        return CHGNetCalculator(model=network, use_device=device)
    if model.startswith("Orb-"):
        from orb_models.forcefield import pretrained
        from orb_models.forcefield.inference.calculator import ORBCalculator

        name = model.lower()
        orb_precision = "float64" if precision == "float64" else "float32-high"
        # compile=False: torch.compile would need a C++ compiler on the user's computer.
        network, adapter = pretrained.ORB_PRETRAINED_MODELS[name](
            device=device, precision=orb_precision, compile=False
        )
        return ORBCalculator(network, adapter, device=device)
    import matcalc

    return matcalc.load_fp(model)


def _check_model(model: str) -> None:
    if model not in Model.__args__:  # type: ignore[attr-defined]
        raise ValueError(f"Unknown model {model!r}; choose one of: {', '.join(Model.__args__)}.")  # type: ignore[attr-defined]


def _crystal_model(model: str) -> None:
    _check_model(model)
    if model in _MOLECULAR:
        raise ValueError(
            f"{model} is trained on organic molecules, not crystals; use a materials model "
            f"such as {DEFAULT_MODEL}."
        )


def _read(path: str) -> Any:
    from ase.io import read

    try:
        return read(path)
    except Exception as exc:
        raise ValueError(f"Could not read a structure from {path}: {exc}") from exc


def _periodic(atoms: Any) -> bool:
    return bool(atoms.pbc.all()) and atoms.cell.rank == 3


def _structure(path: str) -> Any:
    """A pymatgen crystal structure, for matcalc's property calculators."""
    from pymatgen.core import Structure

    try:
        structure = Structure.from_file(path)
    except Exception as exc:
        raise ValueError(
            f"Could not read a periodic crystal structure from {path}: {exc}. Use CIF, POSCAR, "
            "or pymatgen JSON; for molecules, use predict or relax."
        ) from exc
    if not structure.is_ordered:
        raise ValueError(
            "The structure has partial occupancies, but a potential needs one atom per site. "
            "Order it first (e.g. enumerate orderings of a supercell) and compute each ordering."
        )
    return structure


def _cell(atoms: Any) -> dict[str, float]:
    a, b, c, alpha, beta, gamma = atoms.cell.cellpar()
    return {
        "a_angstrom": float(a),
        "b_angstrom": float(b),
        "c_angstrom": float(c),
        "alpha_deg": float(alpha),
        "beta_deg": float(beta),
        "gamma_deg": float(gamma),
        "volume_per_atom_angstrom3": float(atoms.get_volume() / len(atoms)),
    }


def _lattice(structure: Any) -> dict[str, float]:
    a, b, c = structure.lattice.abc
    alpha, beta, gamma = structure.lattice.angles
    return {
        "a_angstrom": float(a),
        "b_angstrom": float(b),
        "c_angstrom": float(c),
        "alpha_deg": float(alpha),
        "beta_deg": float(beta),
        "gamma_deg": float(gamma),
        "volume_per_atom_angstrom3": float(structure.volume / len(structure)),
    }


def predict(
    structure: str,
    model: Model = DEFAULT_MODEL,
    precision: Precision = "auto",
    device: Device = "cpu",
) -> dict:
    """Energy, forces, stress, and (CHGNet) magnetic moments of a structure or molecule.

    Args:
        structure: Crystal (CIF, POSCAR, extended XYZ) or molecule (XYZ) file.
        model: Universal potential. Materials: Orb-v3 (default; MPtrj and
            Alexandria, PBE/PBE+U), MACE-MPA-0, MACE-MP-0, CHGNet (MPtrj, with
            magnetic moments), TensorNet/M3GNet/CHGNet-MatPES (pure PBE or
            r2SCAN), and "omat" or r2SCAN variants. Organic molecules: MACE-OFF23
            (non-commercial license).
        precision: "auto" (float64 for MACE, the models' default otherwise),
            "float32" (faster), or "float64".
        device: "cpu" (reproducible) or "cuda".

    Returns:
        Formula, number of atoms, energy (eV and eV/atom), forces (eV/Å, one row
        per atom) and the largest force, the stress tensor for crystals (GPa),
        and magnetic moments (μB per atom) for CHGNet models.
    """
    _check_model(model)
    atoms = _read(structure)
    atoms.calc = _calculator(model, precision, device)
    energy = float(atoms.get_potential_energy())
    forces = atoms.get_forces()
    result: dict[str, Any] = {
        "model": model,
        "formula": atoms.get_chemical_formula(mode="metal"),
        "n_atoms": len(atoms),
        "energy_ev": energy,
        "energy_ev_per_atom": energy / len(atoms),
        "forces_ev_per_angstrom": forces.tolist(),
        "max_force_ev_per_angstrom": float(np.linalg.norm(forces, axis=1).max()),
        "stress_gpa": None,
        "magmoms_mu_b": None,
    }
    if _periodic(atoms):
        stress = atoms.get_stress(voigt=False) * EV_PER_ANGSTROM3_TO_GPA
        result["stress_gpa"] = stress.tolist()
    magmoms = atoms.calc.results.get("magmoms")
    if magmoms is not None:
        result["magmoms_mu_b"] = np.asarray(magmoms, dtype=float).tolist()
    return result


def relax(
    structure: str,
    model: Model = DEFAULT_MODEL,
    fmax: float = 0.05,
    steps: int = 500,
    relax_cell: bool = True,
    precision: Precision = "auto",
    device: Device = "cpu",
    output: str | None = None,
) -> dict:
    """Relax atomic positions (and, for crystals, the cell) with the FIRE optimizer.

    Args:
        structure: Starting crystal or molecule file.
        model: Universal potential (see predict).
        fmax: Force convergence threshold in eV/Å. With relax_cell it also limits
            the residual stress (roughly fmax / volume per atom), so use 0.01 or
            less when the lattice constant matters.
        steps: Maximum number of optimizer steps.
        relax_cell: Also relax the cell shape and volume (crystals only), with
            ASE's FrechetCellFilter.
        precision: See predict.
        device: "cpu" or "cuda".
        output: File for the relaxed structure. Default: relaxed.cif for crystals,
            relaxed.xyz for molecules.

    Returns:
        Initial and final energies (eV) and final energy per atom, steps, whether
        it converged, final magnetic moments for CHGNet, and for crystals the
        volume before and after (Å³) and the final lattice; plus the file path.
    """
    from ase.filters import FrechetCellFilter
    from ase.io import write
    from ase.optimize import FIRE

    _check_model(model)
    if fmax <= 0:
        raise ValueError("fmax must be positive (eV/Å).")
    atoms = _read(structure)
    periodic = _periodic(atoms)
    atoms.calc = _calculator(model, precision, device)
    initial_energy = float(atoms.get_potential_energy())
    initial_volume = float(atoms.get_volume()) if periodic else None
    target = FrechetCellFilter(atoms) if relax_cell and periodic else atoms
    optimizer = FIRE(target, logfile="-")  # progress goes to the run's output
    converged = bool(optimizer.run(fmax=fmax, steps=steps))
    final_energy = float(atoms.get_potential_energy())
    magmoms = atoms.calc.results.get("magmoms")
    output = output or ("relaxed.cif" if periodic else "relaxed.xyz")
    write(output, atoms)
    result: dict[str, Any] = {
        "model": model,
        "formula": atoms.get_chemical_formula(mode="metal"),
        "initial_energy_ev": initial_energy,
        "final_energy_ev": final_energy,
        "final_energy_ev_per_atom": final_energy / len(atoms),
        "steps": int(optimizer.nsteps),
        "converged": converged,
        "magmoms_mu_b": None if magmoms is None else np.asarray(magmoms, dtype=float).tolist(),
        "relaxed_structure": output,
    }
    if periodic:
        result.update(
            initial_volume_angstrom3=initial_volume,
            final_volume_angstrom3=float(atoms.get_volume()),
            lattice=_cell(atoms),
        )
    return result


def molecular_dynamics(
    structure: str,
    model: Model = DEFAULT_MODEL,
    temperature_k: float = 300.0,
    steps: int = 1000,
    timestep_fs: float = 1.0,
    ensemble: Literal["nvt", "nve"] = "nvt",
    seed: int = 0,
    precision: Precision = "float32",
    device: Device = "cpu",
    trajectory: str = "md.traj",
) -> dict:
    """Run molecular dynamics and save the trajectory.

    Velocities start from a Maxwell-Boltzmann distribution at temperature_k. NVT
    uses the Bussi stochastic velocity-rescaling thermostat.

    Args:
        structure: Starting crystal or molecule file.
        model: Universal potential (see predict).
        temperature_k: Target (and starting) temperature in K.
        steps: Number of MD steps.
        timestep_fs: Time step in fs (1 fs is safe; up to 2 fs without hydrogen).
        ensemble: "nvt" (constant temperature) or "nve" (constant energy).
        seed: Random seed for the initial velocities and the thermostat.
        precision: "float32" (default for MD; faster), "float64", or "auto".
        device: "cpu" or "cuda".
        trajectory: ASE trajectory file to write.

    Returns:
        Simulated time (ps), final temperature (K), final potential energy
        (eV/atom), the trajectory path, the number of saved frames, and the time
        between saved frames (fs), which diffusion analysis needs.
    """
    from ase import units
    from ase.io.trajectory import Trajectory
    from ase.md.bussi import Bussi
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary
    from ase.md.verlet import VelocityVerlet

    _check_model(model)
    if steps < 1 or timestep_fs <= 0 or temperature_k <= 0:
        raise ValueError("steps, timestep_fs, and temperature_k must be positive.")
    atoms = _read(structure)
    atoms.calc = _calculator(model, precision, device)
    rng = np.random.default_rng(seed)
    MaxwellBoltzmannDistribution(atoms, temperature_K=temperature_k, rng=rng, force_temp=True)
    Stationary(atoms)
    if ensemble == "nvt":
        dynamics = Bussi(
            atoms, timestep_fs * units.fs, temperature_K=temperature_k, taut=100 * units.fs, rng=rng
        )
    else:
        dynamics = VelocityVerlet(atoms, timestep_fs * units.fs)
    with Trajectory(trajectory, "w", atoms) as writer:
        dynamics.attach(writer.write, interval=_FRAME_INTERVAL)

        def report_progress() -> None:
            energy = float(atoms.get_potential_energy()) / len(atoms)
            print(
                f"step {dynamics.nsteps}/{steps}: T = {atoms.get_temperature():.0f} K, "
                f"E_pot = {energy:.4f} eV/atom"
            )

        dynamics.attach(report_progress, interval=max(1, steps // 50))
        dynamics.run(steps)
    return {
        "model": model,
        "simulated_time_ps": steps * timestep_fs / 1000,
        "final_temperature_k": float(atoms.get_temperature()),
        "final_energy_ev_per_atom": float(atoms.get_potential_energy()) / len(atoms),
        "trajectory": trajectory,
        "n_frames": steps // _FRAME_INTERVAL + 1,
        "frame_interval_fs": timestep_fs * _FRAME_INTERVAL,
    }


def _strains(maximum: float) -> list[float]:
    if not 0 < maximum <= 0.1:
        raise ValueError("Strains must be between 0 and 0.1 (10%).")
    return [-maximum, -maximum / 2, maximum / 2, maximum]


def elastic_constants(
    structure: str,
    model: Model = DEFAULT_MODEL,
    relax: bool = True,
    fmax: float = 0.05,
    max_normal_strain: float = 0.01,
    max_shear_strain: float = 0.06,
) -> dict:
    """Full elastic tensor and moduli from stress-strain fits.

    Args:
        structure: Crystal structure file.
        model: Materials potential (see predict).
        relax: Relax the structure (atoms and cell) first; elastic constants are
            only meaningful at equilibrium.
        fmax: Force convergence for relaxations, eV/Angstrom.
        max_normal_strain: Largest normal strain (0.01 = 1%).
        max_shear_strain: Largest shear strain.

    Returns:
        The elastic tensor in Voigt notation (6x6, GPa), Voigt-Reuss-Hill bulk
        and shear moduli, Young's modulus (GPa), Poisson's ratio, whether the
        crystal is mechanically stable (all eigenvalues of the tensor positive),
        the fit quality, and the relaxed lattice.
    """
    import matcalc

    _crystal_model(model)
    calc = matcalc.ElasticityCalc(
        _calculator(model),
        norm_strains=_strains(max_normal_strain),
        shear_strains=_strains(max_shear_strain),
        fmax=fmax,
        relax_structure=relax,
        use_equilibrium=True,
        units_GPa=True,
    )
    result = calc.calc(_structure(structure))
    voigt = np.asarray(result["elastic_tensor"].voigt, dtype=float)
    bulk = float(result["bulk_modulus_vrh"])
    shear = float(result["shear_modulus_vrh"])
    eigenvalues = np.linalg.eigvalsh((voigt + voigt.T) / 2)
    return {
        "model": model,
        "elastic_tensor_voigt_gpa": voigt.round(4).tolist(),
        "bulk_modulus_vrh_gpa": bulk,
        "shear_modulus_vrh_gpa": shear,
        "youngs_modulus_gpa": 9 * bulk * shear / (3 * bulk + shear),
        "poisson_ratio": (3 * bulk - 2 * shear) / (2 * (3 * bulk + shear)),
        "mechanically_stable": bool(eigenvalues.min() > 0),
        "fit_r2": float(result["r2_score_mean"]),
        "lattice": _lattice(result["final_structure"]),
    }


def equation_of_state(
    structure: str,
    model: Model = DEFAULT_MODEL,
    relax: bool = True,
    fmax: float = 0.05,
    max_strain: float = 0.1,
    n_points: int = 11,
    plot: str = "eos.png",
) -> dict:
    """Bulk modulus and equilibrium volume from a Birch-Murnaghan equation of state.

    Args:
        structure: Crystal structure file.
        model: Materials potential (see predict).
        relax: Relax the structure first, and the atoms at each strained volume.
        fmax: Force convergence for relaxations, eV/Angstrom.
        max_strain: Largest linear strain (0.1 = 10%) on each side.
        n_points: Number of volumes.
        plot: PNG file of the energy-volume curve.

    Returns:
        Bulk modulus (GPa), equilibrium volume and energy per atom from the fit,
        the fit quality, the computed points, and the plot path.
    """
    import matcalc
    from ase.eos import EquationOfState
    from ase.units import GPa

    _crystal_model(model)
    calc = matcalc.EOSCalc(
        _calculator(model),
        max_abs_strain=max_strain,
        n_points=n_points,
        fmax=fmax,
        relax_structure=relax,
    )
    crystal = _structure(structure)
    result = calc.calc(crystal)
    n = len(crystal)
    volumes = np.asarray(result["eos"]["volumes"], dtype=float) / n
    energies = np.asarray(result["eos"]["energies"], dtype=float) / n
    eos = EquationOfState(volumes, energies, eos="birchmurnaghan")
    v0, e0, bulk = eos.fit()
    _save_plot(eos.plot(show=False), plot)
    return {
        "model": model,
        "bulk_modulus_gpa": float(result["bulk_modulus_bm"]),
        "bulk_modulus_per_atom_fit_gpa": float(bulk / GPa),
        "volume_per_atom_angstrom3": float(v0),
        "energy_per_atom_ev": float(e0),
        "fit_r2": float(result["r2_score_bm"]),
        "volumes_angstrom3_per_atom": volumes.tolist(),
        "energies_ev_per_atom": energies.tolist(),
        "plot": plot,
    }


def thermal_properties(
    structure: str,
    model: Model = DEFAULT_MODEL,
    t_max: float = 1000.0,
    t_step: float = 50.0,
    report_temperatures: list[float] | None = None,
    supercell: list[int] | None = None,
    scale_range: float = 0.03,
    n_volumes: int = 7,
    relax: bool = True,
    fmax: float = 0.05,
    table: str = "thermal_properties.csv",
    plot: str = "thermal_properties.png",
) -> dict:
    """Thermal expansion, heat capacity, and free energy vs temperature (quasi-harmonic).

    Phonons are computed at several volumes, and the free energy is minimized
    over volume at each temperature (quasi-harmonic approximation).

    Args:
        structure: Crystal structure file.
        model: Materials potential (see predict).
        t_max: Highest temperature, K.
        t_step: Temperature step, K.
        report_temperatures: Temperatures to report in the result (K); the full
            curves are in the table. Default: 300 K and t_max.
        supercell: Phonon supercell, e.g. [2, 2, 2]. Default: automatic.
        scale_range: Largest relative change of the lattice parameters (0.03 = 3%).
        n_volumes: Number of volumes (odd numbers include the input volume).
        relax: Relax the structure first.
        fmax: Force convergence for relaxations, eV/Angstrom.
        table: CSV file with all properties at every temperature.
        plot: PNG file with thermal expansion and heat capacity vs temperature.

    Returns:
        At each reported temperature: the equilibrium cell volume (Angstrom^3),
        volumetric thermal expansion coefficient (1/K; the linear coefficient of a
        cubic crystal is a third of it), heat capacity at constant pressure (J/K
        per mole of input cells, and per mole of atoms), bulk modulus (GPa),
        Gruneisen parameter, and Gibbs free energy (eV per cell); plus the table
        and plot.
    """
    import matcalc

    _crystal_model(model)
    if not 3 <= n_volumes <= 15 or not 0.005 <= scale_range <= 0.1:
        raise ValueError("Use 3 to 15 volumes and a scale_range between 0.005 and 0.1.")
    temperatures = report_temperatures or [300.0, t_max]
    phonon_kwargs = {}
    if supercell is not None:
        if len(supercell) != 3 or any(int(n) != n or n < 1 for n in supercell):
            raise ValueError("supercell must be three positive integers, e.g. [2, 2, 2].")
        phonon_kwargs["supercell_matrix"] = np.diag([int(n) for n in supercell]).tolist()
    calc = matcalc.QHACalc(
        calculator=_calculator(model),
        t_step=t_step,
        t_max=t_max,
        scale_factors=np.linspace(1 - scale_range, 1 + scale_range, n_volumes).tolist(),
        fmax=fmax,
        relax_structure=relax,
        phonon_calc_kwargs=phonon_kwargs or None,
    )
    crystal = _structure(structure)
    result = calc.calc(crystal)
    grid = np.asarray(result["temperatures"], dtype=float)
    columns = {
        "temperature_k": grid,
        "volume_angstrom3": result["qha"].volume_temperature,
        "thermal_expansion_per_k": result["thermal_expansion_coefficients"],
        "heat_capacity_p_j_per_k_mol": result["heat_capacity_P"],
        "bulk_modulus_gpa": result["bulk_modulus_P"],
        "gruneisen_parameter": result["gruneisen_parameters"],
        "gibbs_free_energy_ev": result["gibbs_free_energies"],
    }
    columns = {k: np.asarray(v, dtype=float)[: len(grid)] for k, v in columns.items()}
    _write_table(columns, table)
    _plot_thermal(columns, plot)
    n = len(crystal)
    report = []
    for temperature in temperatures:
        i = int(np.argmin(abs(grid - temperature)))
        row = {k: float(v[i]) for k, v in columns.items()}
        row["heat_capacity_p_j_per_k_per_mol_atoms"] = row["heat_capacity_p_j_per_k_mol"] / n
        report.append(row)
    return {"model": model, "n_atoms_in_cell": n, "at": report, "table": table, "plot": plot}


def formation_energy(structure: str, model: Model = DEFAULT_MODEL, relax: bool = True) -> dict:
    """Formation energy (from the elements) and cohesive energy per atom.

    Args:
        structure: Crystal structure file.
        model: Materials potential (see predict). MatPES models use the MatPES
            elemental reference energies; the others compute the elemental
            ground states (Materials Project structures) with the same model, so
            the energies are consistent.
        relax: Relax the structure first.

    Returns:
        Formation energy per atom relative to the elemental ground states (eV/atom),
        cohesive energy per atom relative to isolated atoms (eV/atom; MatPES
        models only, otherwise None), the total energy, the reference used, and
        the relaxed lattice.
    """
    import matcalc

    _crystal_model(model)
    if "MatPES" in model:
        references = "MatPES-r2SCAN" if "r2SCAN" in model else "MatPES-PBE"
        calc = matcalc.EnergeticsCalc(
            _calculator(model), elemental_refs=references, relax_structure=relax
        )
    else:
        references = f"MP elemental ground states, computed with {model}"
        calc = matcalc.EnergeticsCalc(
            _calculator(model),
            elemental_refs="MP-PBE",
            use_gs_reference=True,
            relax_structure=relax,
        )
    result = calc.calc(_structure(structure))
    cohesive = result.get("cohesive_energy_per_atom")
    return {
        "model": model,
        "elemental_references": references,
        "formation_energy_per_atom_ev": float(result["formation_energy_per_atom"]),
        # Needs isolated-atom energies from the training data (MatPES models only).
        "cohesive_energy_per_atom_ev": None if cohesive is None else float(cohesive),
        "energy_ev": float(result["energy"]),
        "lattice": _lattice(result["final_structure"]),
    }


def compare_models(
    structure: str,
    models: list[Model] | None = None,
    fmax: float = 0.01,
    steps: int = 500,
) -> dict:
    """Relax one crystal with several models and compare their lattices.

    Agreement between independently trained models is a quick plausibility check;
    disagreement flags structures where none should be trusted without DFT.
    Energies are listed but are only comparable between models trained on the
    same data (e.g. MatPES PBE vs MPtrj PBE+U differ systematically).

    Args:
        structure: Crystal structure file.
        models: Models to compare. Default: one of each family (Orb-v3,
            MACE-MPA-0, TensorNet-MatPES-PBE, CHGNet 0.3.0).
        fmax: Force convergence threshold for the relaxations, eV/Å.
        steps: Maximum optimizer steps per model.

    Returns:
        For each model: relaxed lattice, volume per atom, energy per atom,
        whether it converged, and the time taken; plus the spread of the volume
        per atom over the models (max - min, percent of the mean) and the model
        whose volume is furthest from the mean.
    """
    from ase.filters import FrechetCellFilter
    from ase.optimize import FIRE

    chosen = list(models or DEFAULT_COMPARISON)
    for model in chosen:
        _crystal_model(model)
    rows = []
    for model in chosen:
        atoms = _read(structure)
        if not _periodic(atoms):
            raise ValueError("compare_models needs a crystal (periodic structure).")
        started = time.time()
        atoms.calc = _calculator(model)
        optimizer = FIRE(FrechetCellFilter(atoms), logfile=None)
        converged = bool(optimizer.run(fmax=fmax, steps=steps))
        print(f"{model}: relaxed in {optimizer.nsteps} steps", flush=True)
        rows.append(
            {
                "model": model,
                "lattice": _cell(atoms),
                "volume_per_atom_angstrom3": float(atoms.get_volume() / len(atoms)),
                "energy_ev_per_atom": float(atoms.get_potential_energy() / len(atoms)),
                "converged": converged,
                "seconds": round(time.time() - started, 1),
            }
        )
    volumes = np.array([row["volume_per_atom_angstrom3"] for row in rows])
    mean = float(volumes.mean())
    outlier = rows[int(np.argmax(abs(volumes - mean)))]["model"]
    return {
        "models": rows,
        "mean_volume_per_atom_angstrom3": mean,
        "volume_spread_percent": float((volumes.max() - volumes.min()) / mean * 100),
        "furthest_from_mean": outlier,
    }


def _write_table(columns: dict[str, np.ndarray], path: str) -> None:
    data = np.column_stack(list(columns.values()))
    np.savetxt(path, data, delimiter=",", header=",".join(columns), comments="")


def _save_plot(axes: Any, path: str) -> None:
    import matplotlib.pyplot as plt

    axes.figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(axes.figure)


def _plot_thermal(columns: dict[str, np.ndarray], path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, (left, right) = plt.subplots(1, 2, figsize=(9, 3.5))
    left.plot(columns["temperature_k"], columns["thermal_expansion_per_k"] * 1e6)
    left.set(xlabel="T (K)", ylabel="volumetric thermal expansion (10⁻⁶/K)")
    right.plot(columns["temperature_k"], columns["heat_capacity_p_j_per_k_mol"])
    right.set(xlabel="T (K)", ylabel="C_p (J/K/mol of cell)")
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
