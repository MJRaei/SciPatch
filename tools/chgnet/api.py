"""CHGNet: energies, forces, stresses, magnetic moments, relaxation, and MD for crystals.

CHGNet is a universal machine-learning interatomic potential pretrained on the
Materials Project trajectory dataset (MPtrj). It predicts properties of
inorganic crystals across the periodic table in seconds on a CPU.
"""

from __future__ import annotations

import functools
import warnings
from typing import Literal

import numpy as np

Model = Literal["0.3.0", "0.2.0", "r2scan"]
_FRAME_INTERVAL = 10  # MD steps between saved trajectory frames
Device = Literal["cpu", "auto", "cuda", "mps"]


@functools.lru_cache(maxsize=3)
def _model(name: str):
    from chgnet.model import CHGNet

    return CHGNet.load(model_name=name, verbose=False)


def _structure(path: str):
    from pymatgen.core import Structure

    warnings.filterwarnings("ignore", module="pymatgen")
    return Structure.from_file(path)


def _device(device: str) -> str | None:
    return None if device == "auto" else device


def predict(structure: str, model: Model = "0.3.0", device: Device = "cpu") -> dict:
    """Predict energy, forces, stress, and magnetic moments of a crystal (no relaxation).

    Args:
        structure: Path to the structure file (CIF, POSCAR, or extended XYZ).
        model: Pretrained model: "0.3.0" (default, MPtrj PBE/PBE+U), "0.2.0" (version
            in the paper), or "r2scan" (transfer-learned to r2SCAN).
        device: Where to run: "cpu" (reproducible), "auto", "cuda", or "mps".

    Returns:
        Energy per atom (eV/atom), total energy (eV), forces (eV/Å, one row per
        site), stress tensor (GPa), magnetic moments (μB per site), the largest
        force (eV/Å), formula, and number of sites.
    """
    from chgnet.utils import determine_device

    crystal = _structure(structure)
    network = _model(model).to(determine_device(_device(device)))
    prediction = network.predict_structure(crystal)
    forces = np.asarray(prediction["f"])
    return {
        "formula": crystal.composition.reduced_formula,
        "n_sites": len(crystal),
        "energy_ev_per_atom": float(prediction["e"]),
        "energy_ev": float(prediction["e"]) * len(crystal),
        "forces_ev_per_angstrom": forces.tolist(),
        "max_force_ev_per_angstrom": float(np.linalg.norm(forces, axis=1).max()),
        "stress_gpa": np.asarray(prediction["s"]).tolist(),
        "magmoms_mu_b": np.asarray(prediction["m"]).tolist(),
    }


def relax(
    structure: str,
    fmax: float = 0.1,
    steps: int = 500,
    relax_cell: bool = True,
    model: Model = "0.3.0",
    device: Device = "cpu",
    output: str = "relaxed.cif",
) -> dict:
    """Relax a crystal structure (atomic positions and, optionally, the cell) with CHGNet.

    Uses the FIRE optimizer; with relax_cell, the cell is relaxed to zero stress
    with ASE's FrechetCellFilter.

    Args:
        structure: Path to the starting structure file.
        fmax: Force convergence threshold in eV/Å. With relax_cell it also limits the
            residual stress (to roughly fmax / volume per atom: 0.1 eV/Å is about
            1 GPa), so use 0.01 or less when the lattice constant matters.
        steps: Maximum number of optimizer steps.
        relax_cell: Also relax the cell shape and volume.
        model: Pretrained model: "0.3.0", "0.2.0", or "r2scan".
        device: Where to run: "cpu" (reproducible), "auto", "cuda", or "mps".
        output: File for the relaxed structure (CIF), including predicted magmoms.

    Returns:
        Initial and final energies (eV and eV/atom), steps taken, whether it
        converged, volume before and after (Å³), final magnetic moments (μB), and
        the relaxed structure's path.
    """
    from chgnet.model import StructOptimizer

    if fmax <= 0:
        raise ValueError("fmax must be positive (eV/Å).")
    crystal = _structure(structure)
    optimizer = StructOptimizer(model=_model(model), use_device=_device(device))
    result = optimizer.relax(
        crystal, fmax=fmax, steps=steps, relax_cell=relax_cell, verbose=False
    )
    final = result["final_structure"]
    trajectory = result["trajectory"]
    final.to(filename=output)
    energies = [float(e) for e in trajectory.energies]
    last_forces = np.asarray(trajectory.forces[-1])
    return {
        "formula": final.composition.reduced_formula,
        "initial_energy_ev": energies[0],
        "final_energy_ev": energies[-1],
        "final_energy_ev_per_atom": energies[-1] / len(final),
        "steps": len(energies) - 1,
        "converged": bool(np.linalg.norm(last_forces, axis=1).max() <= fmax),
        "initial_volume_angstrom3": float(crystal.volume),
        "final_volume_angstrom3": float(final.volume),
        "magmoms_mu_b": [float(m) for m in final.site_properties.get("magmom", [])],
        "relaxed_structure": output,
    }


def molecular_dynamics(
    structure: str,
    temperature_k: float = 300.0,
    steps: int = 1000,
    timestep_fs: float = 2.0,
    ensemble: Literal["nvt", "npt", "nve"] = "nvt",
    seed: int = 0,
    model: Model = "0.3.0",
    device: Device = "auto",
    trajectory: str = "md.traj",
) -> dict:
    """Run molecular dynamics with CHGNet and save the trajectory.

    Velocities start from a Maxwell-Boltzmann distribution at temperature_k, so
    the run begins at the target temperature and is reproducible for a given seed.

    Args:
        structure: Path to the starting structure file.
        temperature_k: Target (and starting) temperature in K.
        steps: Number of MD steps.
        timestep_fs: Time step in fs (2 fs is typical; use 0.5 to 1 fs with hydrogen).
        ensemble: "nvt" (Berendsen thermostat), "npt", or "nve".
        seed: Random seed for the initial velocities.
        model: Pretrained model: "0.3.0", "0.2.0", or "r2scan".
        device: Where to run: "auto" (GPU if available), "cpu", "cuda", or "mps".
        trajectory: ASE trajectory file to write (readable with ase.io.read).

    Returns:
        Simulated time (ps), final temperature (K), final potential energy
        (eV/atom), the trajectory and log file paths, the number of saved frames,
        and the time between saved frames (fs), which diffusion analysis needs.
    """
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary
    from chgnet.model.dynamics import MolecularDynamics
    from pymatgen.io.ase import AseAtomsAdaptor

    if steps < 1 or timestep_fs <= 0:
        raise ValueError("steps must be at least 1 and timestep_fs positive.")
    atoms = AseAtomsAdaptor.get_atoms(_structure(structure))
    MaxwellBoltzmannDistribution(
        atoms, temperature_K=temperature_k, rng=np.random.default_rng(seed), force_temp=True
    )
    Stationary(atoms)
    md = MolecularDynamics(
        atoms=atoms,
        model=_model(model),
        ensemble=ensemble,
        temperature=temperature_k,
        timestep=timestep_fs,
        trajectory=trajectory,
        logfile="md.log",
        loginterval=_FRAME_INTERVAL,
        use_device=_device(device),
    )

    def report_progress() -> None:
        energy = float(md.atoms.get_potential_energy()) / len(md.atoms)
        print(
            f"step {md.dyn.nsteps}/{steps}: T = {md.atoms.get_temperature():.0f} K, "
            f"E_pot = {energy:.4f} eV/atom"
        )

    md.dyn.attach(report_progress, interval=max(1, steps // 50))
    md.run(steps)
    atoms = md.atoms
    return {
        "simulated_time_ps": steps * timestep_fs / 1000,
        "final_temperature_k": float(atoms.get_temperature()),
        "final_energy_ev_per_atom": float(atoms.get_potential_energy()) / len(atoms),
        "trajectory": trajectory,
        "n_frames": steps // _FRAME_INTERVAL + 1,
        "frame_interval_fs": timestep_fs * _FRAME_INTERVAL,
        "log": "md.log",
    }
