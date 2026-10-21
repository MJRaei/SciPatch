"""Ion transport from molecular dynamics: MSD, diffusivity, conductivity, Arrhenius fits.

Wraps pymatgen-analysis-diffusion (Materials Virtual Lab). Trajectories can come
from any MD code that ASE can read: ASE .traj, extended XYZ, VASP XDATCAR or
vasprun.xml, LAMMPS dumps, and more.
"""

from __future__ import annotations

import warnings
from typing import Literal

import numpy as np

#: Ions that never move further than this (Å) are taken to have only vibrated.
HOP_DISTANCE_ANGSTROM = 1.5
#: pymatgen's "max" smoothing fits the MSD from this lag time (fs) onward.
MIN_FIT_START_FS = 1000.0


def _matplotlib():
    import matplotlib

    matplotlib.use("Agg")  # files only, never a window
    import matplotlib.pyplot as plt

    return plt


def analyze_trajectory(
    trajectory: str,
    specie: str,
    temperature_k: float,
    frame_interval_fs: float,
    skip_initial_ps: float = 0.0,
    smoothed: Literal["max", "constant", "none"] = "max",
    min_obs: int = 30,
    plot: str = "msd.png",
    msd_data: str = "msd.csv",
) -> dict:
    """Compute the diffusivity and ionic conductivity of one species from an MD trajectory.

    The mean squared displacement (MSD) of the species is computed over all time
    origins after removing the framework's drift, and its slope gives the
    diffusivity. The conductivity follows from the Nernst-Einstein relation.

    Args:
        trajectory: Trajectory file readable by ASE (.traj, .extxyz, XDATCAR,
            vasprun.xml, ...), with frames in time order.
        specie: Diffusing element, e.g. "Li" or "Na".
        temperature_k: Temperature of the MD run in K.
        frame_interval_fs: Time between consecutive frames in fs (MD time step
            times the save interval; CHGNet's molecular_dynamics reports it).
        skip_initial_ps: Equilibration time to discard from the start, in ps.
        smoothed: MSD averaging: "max" (default; all time origins, weighted),
            "constant" (fixed window), or "none" (single origin).
        min_obs: With "max", the minimum number of observations per time interval.
        plot: PNG file for the MSD plot.
        msd_data: CSV file for the MSD data (time in fs, MSD in Å²).

    Returns:
        Diffusivity (cm²/s) with its standard deviation and a, b, c components,
        conductivity (mS/cm), charge diffusivity and Haven ratio, the MSD at the
        longest time (Å²), how far the ions moved (Å), how many ions moved more
        than a typical hop distance, warnings about reliability, and the plot and
        data file paths.
    """
    from ase.io import read
    from pymatgen.analysis.diffusion.analyzer import DiffusionAnalyzer
    from pymatgen.io.ase import AseAtomsAdaptor

    if temperature_k <= 0 or frame_interval_fs <= 0 or skip_initial_ps < 0:
        raise ValueError("temperature_k and frame_interval_fs must be positive.")
    frames = read(trajectory, index=":")
    skip = round(skip_initial_ps * 1000 / frame_interval_fs)
    if len(frames) - skip < 10:
        raise ValueError(
            f"Only {len(frames) - skip} frames remain after skipping {skip}; "
            "need at least 10. Reduce skip_initial_ps or run longer."
        )
    duration_fs = (len(frames) - skip - 1) * frame_interval_fs
    if smoothed == "max" and duration_fs <= MIN_FIT_START_FS:
        raise ValueError(
            f"The trajectory covers {duration_fs / 1000:.2f} ps after skipping, but the "
            f"'max' analysis fits the MSD from {MIN_FIT_START_FS / 1000:.0f} ps onward. "
            "Run a longer MD (several ps; tens of ps for a reliable diffusivity), or use "
            "smoothed='none' for a rough look at a short run."
        )
    structures = [AseAtomsAdaptor.get_structure(atoms) for atoms in frames[skip:]]
    elements = {element.symbol for element in structures[0].composition.elements}
    if specie not in elements:
        raise ValueError(f"'{specie}' is not in the trajectory ({', '.join(sorted(elements))}).")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        analyzer = DiffusionAnalyzer.from_structures(
            structures,
            specie=specie,
            temperature=temperature_k,
            time_step=frame_interval_fs,
            step_skip=1,
            smoothed=False if smoothed == "none" else smoothed,
            min_obs=min_obs,
        )
        summary = analyzer.get_summary_dict()

    plt = _matplotlib()
    axes = analyzer.get_msd_plot()
    axes.figure.savefig(plot, dpi=150, bbox_inches="tight")
    plt.close(axes.figure)
    analyzer.export_msdt(msd_data)

    reach = analyzer.max_ion_displacements[analyzer.indices]
    hopped = int(np.sum(reach > HOP_DISTANCE_ANGSTROM))
    notes = []
    if hopped == 0:
        notes.append(
            f"No {specie} ion moved more than {HOP_DISTANCE_ANGSTROM} Å from its site: the ions "
            "only vibrated, so the diffusivity is noise, at most an upper bound. Run longer "
            "or hotter (and extrapolate with an Arrhenius fit)."
        )
    elif hopped < 0.2 * len(reach):
        notes.append(
            f"Only {hopped} of {len(reach)} {specie} ions moved more than "
            f"{HOP_DISTANCE_ANGSTROM} Å: statistics are poor; run longer for a reliable value."
        )
    if analyzer.max_framework_displacement > 1.0:
        notes.append(
            "Framework atoms moved more than 1 Å from their sites: the structure may be "
            "melting or decomposing, and the result may not describe the crystal."
        )

    return {
        "specie": specie,
        "temperature_k": temperature_k,
        "n_ions": len(reach),
        "n_frames": len(structures),
        "simulated_time_ps": (len(structures) - 1) * frame_interval_fs / 1000,
        "diffusivity_cm2_s": float(summary["D"]),
        "diffusivity_std_cm2_s": float(summary["D_sigma"]),
        "diffusivity_components_cm2_s": [float(x) for x in summary["D_components"]],
        "conductivity_ms_cm": float(summary["S"]),
        "conductivity_std_ms_cm": float(summary["S_sigma"]),
        "charge_diffusivity_cm2_s": float(summary["D_charge"]),
        "haven_ratio": float(summary["Haven_ratio"]),
        "msd_final_angstrom2": float(analyzer.msd[-1]),
        "max_ion_displacement_angstrom": float(reach.max()),
        "ions_moved_beyond_hop_distance": hopped,
        "max_framework_displacement_angstrom": float(analyzer.max_framework_displacement),
        "warnings": notes,
        "msd_plot": plot,
        "msd_data": msd_data,
    }


def arrhenius_fit(
    temperatures_k: list[float],
    diffusivities_cm2_s: list[float],
    diffusivity_errors_cm2_s: list[float] | None = None,
    mode: Literal["linear", "exp"] = "linear",
    extrapolate_to_k: float | None = None,
    structure: str | None = None,
    specie: str | None = None,
    plot: str = "arrhenius.png",
) -> dict:
    """Fit diffusivities at several temperatures to an Arrhenius law, D = D0 exp(-Ea / kT).

    Optionally extrapolates the diffusivity (and, given a structure and species,
    the ionic conductivity) to another temperature such as 300 K.

    Args:
        temperatures_k: Temperatures in K, at least two (three or more for an error).
        diffusivities_cm2_s: Diffusivities at those temperatures in cm²/s.
        diffusivity_errors_cm2_s: Absolute errors of the diffusivities in cm²/s (optional).
        mode: "linear" fits ln(D) against 1/T (default); "exp" fits D against T
            and should be used only with errors.
        extrapolate_to_k: Temperature in K to extrapolate to, e.g. 300.
        structure: Structure file, needed to convert the extrapolated diffusivity to
            a conductivity (the number density of the species).
        specie: Diffusing element, needed with structure, e.g. "Li".
        plot: PNG file for the Arrhenius plot.

    Returns:
        Activation energy (eV) and its standard error, the prefactor D0 (cm²/s),
        the extrapolated diffusivity (cm²/s) and conductivity (mS/cm) if requested,
        and the plot path.
    """
    from pymatgen.analysis.diffusion.analyzer import (
        fit_arrhenius,
        get_arrhenius_plot,
        get_extrapolated_conductivity,
        get_extrapolated_diffusivity,
    )

    temps = np.asarray(temperatures_k, dtype=float)
    diffusivities = np.asarray(diffusivities_cm2_s, dtype=float)
    errors = None if diffusivity_errors_cm2_s is None else np.asarray(diffusivity_errors_cm2_s)
    if len(temps) < 2 or len(temps) != len(diffusivities):
        raise ValueError("Give at least two temperatures and one diffusivity per temperature.")
    if np.any(temps <= 0) or np.any(diffusivities <= 0):
        raise ValueError("Temperatures and diffusivities must be positive.")
    if (structure is None) != (specie is None):
        raise ValueError("Give both structure and specie to extrapolate the conductivity.")

    activation, prefactor, activation_error = fit_arrhenius(temps, diffusivities, mode, errors)
    result: dict = {
        "activation_energy_ev": float(activation),
        "activation_energy_std_ev": None if activation_error is None else float(activation_error),
        "prefactor_cm2_s": float(prefactor),
    }
    if extrapolate_to_k is not None:
        result["extrapolated_temperature_k"] = extrapolate_to_k
        result["extrapolated_diffusivity_cm2_s"] = float(
            get_extrapolated_diffusivity(temps, diffusivities, extrapolate_to_k)
        )
        if structure is not None:
            from pymatgen.core import Structure

            result["extrapolated_conductivity_ms_cm"] = float(
                get_extrapolated_conductivity(
                    temps, diffusivities, extrapolate_to_k, Structure.from_file(structure), specie
                )
            )

    plt = _matplotlib()
    axes = get_arrhenius_plot(temps, diffusivities, errors, mode=mode)
    axes.figure.savefig(plot, dpi=150, bbox_inches="tight")
    plt.close(axes.figure)
    result["plot"] = plot
    return result
