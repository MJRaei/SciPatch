"""MACE foundation potentials: MACE-MP (materials) and MACE-OFF (organic molecules).

The functions and output names mirror the CHGNet tool on purpose, so the two
potentials can be compared call for call.
"""

from __future__ import annotations

import functools
import warnings
from typing import Literal

import numpy as np

Model = Literal["mpa-0-medium", "mp-0-medium", "mp-0-small", "off23-small", "off23-medium"]
Precision = Literal["float64", "float32"]
Device = Literal["cpu", "cuda"]

EV_PER_ANGSTROM3_TO_GPA = 160.21766208
_FRAME_INTERVAL = 10  # MD steps between saved trajectory frames
_MP_MODELS = {"mpa-0-medium": "medium-mpa-0", "mp-0-medium": "medium", "mp-0-small": "small"}
_OFF_MODELS = {"off23-small": "small", "off23-medium": "medium"}


@functools.lru_cache(maxsize=4)
def _calculator(model: str, precision: str, device: str):
    from mace.calculators import mace_mp, mace_off

    warnings.filterwarnings("ignore")
    if model in _MP_MODELS:
        return mace_mp(model=_MP_MODELS[model], default_dtype=precision, device=device)
    return mace_off(model=_OFF_MODELS[model], default_dtype=precision, device=device)


def _read(path: str):
    from ase.io import read

    try:
        return read(path)
    except Exception as exc:
        raise ValueError(f"Could not read a structure from {path}: {exc}") from exc


def _periodic(atoms) -> bool:
    return bool(atoms.pbc.all()) and atoms.cell.rank == 3


def predict(
    structure: str,
    model: Model = "mpa-0-medium",
    precision: Precision = "float64",
    device: Device = "cpu",
) -> dict:
    """Predict the energy, forces, and stress of a structure or molecule (no relaxation).

    Args:
        structure: Path to a structure (CIF, POSCAR, extended XYZ) or molecule (XYZ) file.
        model: "mpa-0-medium" (default; materials, MPtrj + sAlex), "mp-0-medium"
            (materials, the MACE-MP-0 paper model), "mp-0-small" (faster), or
            "off23-small" / "off23-medium" (organic molecules, non-commercial license).
        precision: "float64" (accurate; use for relaxations and comparisons) or
            "float32" (faster).
        device: "cpu" or "cuda".

    Returns:
        Formula, number of atoms, total energy (eV) and energy per atom (eV/atom),
        forces (eV/Å, one row per atom), the largest force (eV/Å), and for
        periodic structures the stress tensor (GPa).
    """
    atoms = _read(structure)
    atoms.calc = _calculator(model, precision, device)
    energy = float(atoms.get_potential_energy())
    forces = atoms.get_forces()
    result = {
        "formula": atoms.get_chemical_formula(mode="metal"),
        "n_atoms": len(atoms),
        "model": model,
        "energy_ev": energy,
        "energy_ev_per_atom": energy / len(atoms),
        "forces_ev_per_angstrom": forces.tolist(),
        "max_force_ev_per_angstrom": float(np.linalg.norm(forces, axis=1).max()),
        "stress_gpa": None,
    }
    if _periodic(atoms):
        stress = atoms.get_stress(voigt=False) * EV_PER_ANGSTROM3_TO_GPA
        result["stress_gpa"] = stress.tolist()
    return result


def relax(
    structure: str,
    fmax: float = 0.05,
    steps: int = 500,
    relax_cell: bool = True,
    model: Model = "mpa-0-medium",
    precision: Precision = "float64",
    device: Device = "cpu",
    output: str | None = None,
) -> dict:
    """Relax atomic positions (and, for crystals, the cell) with the FIRE optimizer.

    Args:
        structure: Path to the starting structure or molecule file.
        fmax: Force convergence threshold in eV/Å. With relax_cell it also limits the
            residual stress (to roughly fmax / volume per atom), so use 0.01 or less
            when the lattice constant matters.
        steps: Maximum number of optimizer steps.
        relax_cell: Also relax the cell shape and volume (crystals only).
        model: Model name, see predict.
        precision: "float64" (recommended) or "float32".
        device: "cpu" or "cuda".
        output: File for the relaxed structure. Default: relaxed.cif for crystals,
            relaxed.xyz for molecules.

    Returns:
        Initial and final energies (eV) and final energy per atom (eV/atom), the
        number of steps, whether it converged, and for crystals the volume before
        and after (Å³) and the final lattice parameters (Å, degrees); plus the
        relaxed structure's path.
    """
    from ase.filters import FrechetCellFilter
    from ase.io import write
    from ase.optimize import FIRE

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
    output = output or ("relaxed.cif" if periodic else "relaxed.xyz")
    write(output, atoms)
    result = {
        "formula": atoms.get_chemical_formula(mode="metal"),
        "model": model,
        "initial_energy_ev": initial_energy,
        "final_energy_ev": final_energy,
        "final_energy_ev_per_atom": final_energy / len(atoms),
        "steps": int(optimizer.nsteps),
        "converged": converged,
        "relaxed_structure": output,
    }
    if periodic:
        a, b, c, alpha, beta, gamma = atoms.cell.cellpar()
        result.update(
            initial_volume_angstrom3=initial_volume,
            final_volume_angstrom3=float(atoms.get_volume()),
            lattice={
                "a_angstrom": float(a),
                "b_angstrom": float(b),
                "c_angstrom": float(c),
                "alpha_deg": float(alpha),
                "beta_deg": float(beta),
                "gamma_deg": float(gamma),
            },
        )
    return result


def molecular_dynamics(
    structure: str,
    temperature_k: float = 300.0,
    steps: int = 1000,
    timestep_fs: float = 1.0,
    ensemble: Literal["nvt", "nve"] = "nvt",
    seed: int = 0,
    model: Model = "mpa-0-medium",
    precision: Precision = "float32",
    device: Device = "cpu",
    trajectory: str = "md.traj",
) -> dict:
    """Run molecular dynamics and save the trajectory.

    Velocities start from a Maxwell-Boltzmann distribution at temperature_k. NVT
    uses the Bussi stochastic velocity-rescaling thermostat.

    Args:
        structure: Path to the starting structure or molecule file.
        temperature_k: Target (and starting) temperature in K.
        steps: Number of MD steps.
        timestep_fs: Time step in fs (1 fs is safe; up to 2 fs without hydrogen).
        ensemble: "nvt" (constant temperature) or "nve" (constant energy).
        seed: Random seed for the initial velocities and the thermostat.
        model: Model name, see predict.
        precision: "float32" (default for MD; faster) or "float64".
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
        "simulated_time_ps": steps * timestep_fs / 1000,
        "final_temperature_k": float(atoms.get_temperature()),
        "final_energy_ev_per_atom": float(atoms.get_potential_energy()) / len(atoms),
        "trajectory": trajectory,
        "n_frames": steps // _FRAME_INTERVAL + 1,
        "frame_interval_fs": timestep_fs * _FRAME_INTERVAL,
    }
