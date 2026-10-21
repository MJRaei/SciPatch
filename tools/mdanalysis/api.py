"""Analysis of molecular dynamics trajectories with MDAnalysis.

Reads GROMACS (TPR, GRO, XTC, TRR), AMBER (PRMTOP, NetCDF), CHARMM/NAMD (PSF,
DCD), LAMMPS (data, DCD, dump), OpenMM and PDB files, and more. Extended XYZ and
ASE trajectories (as written by Motel's lammps and ml-potentials tools) are read
through ASE. Atom selections use the MDAnalysis selection language, e.g.
"protein and name CA", "resname SOL and name OW", "element Li". Distances are in
Angstrom and times in ps.
"""

from __future__ import annotations

import csv
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

#: Values returned in full; longer series are in the CSV file only.
MAX_LISTED = 1000
CM2_PER_S_PER_ANGSTROM2_PER_PS = 1e-4
_ASE_SUFFIXES = (".extxyz", ".traj")


def _ase_universe(path: str, timestep_ps: float | None):
    import MDAnalysis as mda
    from ase.io import read
    from MDAnalysis.coordinates.memory import MemoryReader

    frames = read(path, index=":")
    symbols = frames[0].get_chemical_symbols()
    universe = mda.Universe.empty(len(symbols), trajectory=False)
    for attribute in ("names", "types", "elements"):
        universe.add_TopologyAttr(attribute, symbols)
    universe.add_TopologyAttr("masses", frames[0].get_masses())
    universe.add_TopologyAttr("resnames", ["MOL"])
    universe.add_TopologyAttr("resids", [1])
    coordinates = np.array([frame.positions for frame in frames], dtype=np.float32)
    periodic = frames[0].cell.rank == 3
    dimensions = (
        np.array([frame.cell.cellpar() for frame in frames], dtype=np.float32) if periodic else None
    )
    universe.load_new(
        coordinates, format=MemoryReader, dimensions=dimensions, dt=timestep_ps or 1.0
    )
    return universe


def _universe(topology: str, trajectory: str | None, timestep_ps: float | None = None):
    import MDAnalysis as mda

    for path in filter(None, (topology, trajectory)):
        if not Path(path).is_file():
            raise ValueError(f"No such file: {path}")
    try:
        if Path(trajectory or topology).suffix.lower() in _ASE_SUFFIXES:
            return _ase_universe(trajectory or topology, timestep_ps)
        universe = mda.Universe(topology, trajectory) if trajectory else mda.Universe(topology)
    except Exception as exc:
        raise ValueError(f"MDAnalysis could not read {topology} {trajectory or ''}: {exc}") from exc
    if timestep_ps:
        universe.trajectory.dt = timestep_ps  # some formats store no time step
    return universe


def _select(universe, selection: str):
    try:
        group = universe.select_atoms(selection)
    except Exception as exc:
        raise ValueError(f"Invalid selection {selection!r}: {exc}") from exc
    if group.n_atoms == 0:
        raise ValueError(f"The selection {selection!r} matched no atoms.")
    return group


def _write_csv(path: str, header: list[str], columns: list) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(zip(*columns, strict=True))


def _plot(x, y, xlabel: str, ylabel: str, path: str, marker: str = "") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(6, 3.8))
    axes.plot(x, y, marker=marker)
    axes.set(xlabel=xlabel, ylabel=ylabel)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def _listed(values) -> list[float] | None:
    return [float(v) for v in values] if len(values) <= MAX_LISTED else None


def info(topology: str, trajectory: str | None = None, timestep_ps: float | None = None) -> dict:
    """Summary of a system and trajectory: atoms, residues, frames, time, and box.

    Args:
        topology: Topology or structure file (PSF, PRMTOP, TPR, GRO, PDB, LAMMPS
            data, ...), or an extended XYZ / ASE trajectory on its own.
        trajectory: Trajectory file (DCD, XTC, TRR, NetCDF, LAMMPS dump, ...).
        timestep_ps: Time between frames in ps, for formats that do not store it.

    Returns:
        Numbers of atoms, residues, segments, and frames; time between frames and
        total time (ps); the first frame's box (lengths in Angstrom, angles in
        degrees; None without periodic box); the most common residue names; and
        whether masses are known.
    """
    universe = _universe(topology, trajectory, timestep_ps)
    trajectory_ = universe.trajectory
    box = trajectory_.ts.dimensions
    names, counts = np.unique(universe.residues.resnames, return_counts=True)
    common = sorted(zip(counts.tolist(), names.tolist(), strict=True), reverse=True)[:10]
    return {
        "n_atoms": int(universe.atoms.n_atoms),
        "n_residues": int(universe.residues.n_residues),
        "n_segments": int(universe.segments.n_segments),
        "n_frames": int(trajectory_.n_frames),
        "time_between_frames_ps": float(trajectory_.dt),
        "total_time_ps": float(trajectory_.dt * (trajectory_.n_frames - 1)),
        "box": None
        if box is None
        else dict(zip(("a", "b", "c", "alpha", "beta", "gamma"), map(float, box), strict=True)),
        "residue_names": {name: int(count) for count, name in common},
        "has_masses": hasattr(universe.atoms, "masses"),
    }


def rmsd(
    topology: str,
    trajectory: str | None = None,
    selection: str = "backbone",
    reference_frame: int = 0,
    timestep_ps: float | None = None,
    output: str = "rmsd.csv",
    plot: str = "rmsd.png",
) -> dict:
    """Root-mean-square deviation of each frame from a reference frame after superposition.

    Args:
        topology: Topology or structure file, see info.
        trajectory: Trajectory file.
        selection: Atoms to superpose and compare, e.g. "backbone" (default),
            "protein and name CA", "resname LIG", "not element H".
        reference_frame: Index of the reference frame (0 = first).
        timestep_ps: Time between frames in ps, if the files do not store it.
        output: CSV file with frame, time, and RMSD.
        plot: PNG of RMSD vs time.

    Returns:
        RMSD of each frame (Angstrom; listed up to 1000 frames), its mean and
        maximum, the last frame's RMSD, number of atoms compared, and the files.
    """
    from MDAnalysis.analysis import rms

    universe = _universe(topology, trajectory, timestep_ps)
    group = _select(universe, selection)
    n_frames = universe.trajectory.n_frames
    if not -n_frames <= reference_frame < n_frames:
        raise ValueError(f"reference_frame must be within the {n_frames} frames.")
    analysis = rms.RMSD(group, select="all", ref_frame=reference_frame % n_frames).run()
    frames, times, values = analysis.results.rmsd.T
    _write_csv(output, ["frame", "time_ps", "rmsd_angstrom"], [frames.astype(int), times, values])
    _plot(times, values, "time (ps)", f"RMSD of {selection} (Å)", plot)
    return {
        "selection": selection,
        "n_atoms": int(group.n_atoms),
        "n_frames": len(values),
        "rmsd_angstrom": _listed(values),
        "mean_rmsd_angstrom": float(values.mean()),
        "max_rmsd_angstrom": float(values.max()),
        "final_rmsd_angstrom": float(values[-1]),
        "output": output,
        "plot": plot,
    }


def rmsf(
    topology: str,
    trajectory: str | None = None,
    selection: str = "protein and name CA",
    output: str = "rmsf.csv",
    plot: str = "rmsf.png",
) -> dict:
    """Root-mean-square fluctuation of each atom about its average position.

    Frames are first superposed on the average structure of the selection, so
    overall rotation and translation do not count as fluctuation.

    Args:
        topology: Topology or structure file, see info.
        trajectory: Trajectory file (needs at least two frames).
        selection: Atoms to analyze; "protein and name CA" (default) gives one
            value per residue.
        output: CSV file with atom index, residue, and RMSF.
        plot: PNG of RMSF along the residues.

    Returns:
        RMSF of each atom (Angstrom; listed up to 1000 atoms) with its residue
        number and name, the mean, and the five most mobile residues.
    """
    from MDAnalysis.analysis import align

    universe = _universe(topology, trajectory)
    group = _select(universe, selection)
    if universe.trajectory.n_frames < 2:
        raise ValueError("RMSF needs a trajectory with at least two frames.")
    average = align.AverageStructure(universe, select=selection).run().results.positions
    reference = average - average.mean(axis=0)
    total = np.zeros((group.n_atoms, 3))
    squares = np.zeros(group.n_atoms)
    for _ in universe.trajectory:
        mobile = group.positions - group.positions.mean(axis=0)
        rotation, _ = align.rotation_matrix(mobile, reference)
        fitted = mobile @ rotation.T
        total += fitted
        squares += (fitted**2).sum(axis=1)
    n = universe.trajectory.n_frames
    mean = total / n
    values = np.sqrt(np.maximum(squares / n - (mean**2).sum(axis=1), 0))
    resids, resnames = group.resids, group.resnames
    _write_csv(
        output,
        ["atom_index", "resid", "resname", "atom_name", "rmsf_angstrom"],
        [group.indices, resids, resnames, group.names, values],
    )
    _plot(resids, values, "residue", "RMSF (Å)", plot)
    top = np.argsort(values)[::-1][:5]
    return {
        "selection": selection,
        "n_atoms": int(group.n_atoms),
        "rmsf_angstrom": _listed(values),
        "resids": [int(r) for r in resids] if len(values) <= MAX_LISTED else None,
        "mean_rmsf_angstrom": float(values.mean()),
        "most_mobile": [
            {
                "resid": int(resids[i]),
                "resname": str(resnames[i]),
                "rmsf_angstrom": float(values[i]),
            }
            for i in top
        ],
        "output": output,
        "plot": plot,
    }


def radius_of_gyration(
    topology: str,
    trajectory: str | None = None,
    selection: str = "protein",
    timestep_ps: float | None = None,
    output: str = "rgyr.csv",
    plot: str = "rgyr.png",
) -> dict:
    """Mass-weighted radius of gyration of a selection in each frame.

    Args:
        topology: Topology or structure file, see info.
        trajectory: Trajectory file.
        selection: Atoms to include (default "protein").
        timestep_ps: Time between frames in ps, if the files do not store it.
        output: CSV file with frame, time, and radius of gyration.
        plot: PNG of the radius of gyration vs time.

    Returns:
        Radius of gyration of each frame (Angstrom; listed up to 1000 frames),
        mean, standard deviation, first and last values.
    """
    universe = _universe(topology, trajectory, timestep_ps)
    group = _select(universe, selection)
    times, values = [], []
    for ts in universe.trajectory:
        times.append(ts.time)
        values.append(group.radius_of_gyration())
    values_ = np.array(values)
    _write_csv(output, ["time_ps", "rgyr_angstrom"], [times, values_])
    _plot(times, values_, "time (ps)", "radius of gyration (Å)", plot)
    return {
        "selection": selection,
        "n_atoms": int(group.n_atoms),
        "rgyr_angstrom": _listed(values_),
        "mean_rgyr_angstrom": float(values_.mean()),
        "std_rgyr_angstrom": float(values_.std()),
        "first_rgyr_angstrom": float(values_[0]),
        "final_rgyr_angstrom": float(values_[-1]),
        "output": output,
        "plot": plot,
    }


def rdf(
    topology: str,
    trajectory: str | None = None,
    selection: str = "all",
    selection2: str | None = None,
    r_max: float = 10.0,
    n_bins: int = 200,
    output: str = "rdf.csv",
    plot: str = "rdf.png",
) -> dict:
    """Radial distribution function g(r) and coordination numbers (periodic systems).

    Args:
        topology: Topology or structure file, see info.
        trajectory: Trajectory file (frames are averaged).
        selection: Central atoms, e.g. "name OW" or "element Li".
        selection2: Neighbor atoms (default: the same as selection; an atom is
            then not counted as its own neighbor).
        r_max: Largest distance in Angstrom; at most half the shortest box length.
        n_bins: Number of distance bins.
        output: CSV with r, g(r), and the running coordination number.
        plot: PNG of g(r).

    Returns:
        Positions (Angstrom) and heights of the first peak and the first minimum
        after it, the coordination number (neighbors per central atom) up to that
        minimum, and r, g(r) and the running coordination number at each bin.
    """
    from MDAnalysis.analysis.rdf import InterRDF

    universe = _universe(topology, trajectory)
    box = universe.trajectory.ts.dimensions
    if box is None or not np.all(box[:3] > 0):
        raise ValueError("g(r) needs a periodic box; the files define none.")
    if r_max <= 0 or r_max > min(box[:3]) / 2 + 1e-6 or n_bins < 10:
        raise ValueError(
            f"r_max must be positive and at most half the box ({min(box[:3]) / 2:.2f} Å); "
            "n_bins at least 10."
        )
    first = _select(universe, selection)
    second = _select(universe, selection2) if selection2 else first
    same = selection2 is None or set(first.indices) == set(second.indices)
    analysis = InterRDF(
        first, second, nbins=n_bins, range=(0.0, r_max), exclusion_block=(1, 1) if same else None
    ).run()
    r, g = analysis.results.bins, analysis.results.rdf
    running = np.cumsum(analysis.results.count) / (first.n_atoms * analysis.n_frames)
    peak = int(np.argmax(g))
    after = peak + int(np.argmin(g[peak:]))
    # First minimum: the first bin after the peak where g starts rising again.
    for index in range(peak + 1, len(g) - 1):
        if g[index] <= g[index + 1] and g[index] < g[peak]:
            after = index
            break
    _write_csv(output, ["r_angstrom", "g_r", "coordination_number"], [r, g, running])
    _plot(r, g, "r (Å)", "g(r)", plot)
    return {
        "selection": selection,
        "selection2": selection2 or selection,
        "n_frames": int(analysis.n_frames),
        "first_peak_r_angstrom": float(r[peak]),
        "first_peak_g": float(g[peak]),
        "first_minimum_r_angstrom": float(r[after]),
        "coordination_number": float(running[after]),
        "r_angstrom": _listed(r),
        "g_r": _listed(g),
        "running_coordination_number": _listed(running),
        "output": output,
        "plot": plot,
    }


def msd(
    topology: str,
    trajectory: str | None = None,
    selection: str = "all",
    dimensions: str = "xyz",
    fit_start_ps: float | None = None,
    fit_end_ps: float | None = None,
    timestep_ps: float | None = None,
    output: str = "msd.csv",
    plot: str = "msd.png",
) -> dict:
    """Mean squared displacement and self-diffusion coefficient (Einstein relation).

    Atoms that cross periodic boundaries are unwrapped first, so wrapped
    trajectories are fine. D = slope / (2 d) for the d dimensions analyzed.

    Args:
        topology: Topology or structure file, see info.
        trajectory: Trajectory file with evenly spaced frames.
        selection: Diffusing atoms, e.g. "element Li" or "resname SOL and name OW".
        dimensions: "xyz" (default), or "xy", "z", ... for diffusion in a plane
            or along an axis.
        fit_start_ps: Start of the linear fit in lag time; default 10% of the
            trajectory (skips the short-time ballistic regime).
        fit_end_ps: End of the fit; default 50% of the trajectory (longer lags
            have few time origins and are noisy).
        timestep_ps: Time between frames in ps, if the files do not store it.
        output: CSV of lag time and MSD.
        plot: PNG of MSD vs lag time with the fit.

    Returns:
        Diffusion coefficient in Angstrom^2/ps and cm^2/s with the fit window and
        R^2, the number of atoms, and the MSD at each lag time (listed up to 1000).
    """
    from MDAnalysis.analysis.msd import EinsteinMSD

    if dimensions not in ("xyz", "xy", "yz", "xz", "x", "y", "z"):
        raise ValueError('dimensions must be one of "xyz", "xy", "yz", "xz", "x", "y", "z".')
    universe = _universe(topology, trajectory, timestep_ps)
    group = _select(universe, selection)
    n_frames = universe.trajectory.n_frames
    if n_frames < 10:
        raise ValueError("The trajectory has fewer than 10 frames; MSD needs more.")
    if universe.trajectory.ts.dimensions is not None:
        from MDAnalysis.transformations.nojump import NoJump

        universe.trajectory.add_transformations(NoJump())
    analysis = EinsteinMSD(group, select="all", msd_type=dimensions, fft=True).run()
    values = analysis.results.timeseries
    lags = np.arange(n_frames) * universe.trajectory.dt
    total = lags[-1]
    start = 0.1 * total if fit_start_ps is None else fit_start_ps
    end = 0.5 * total if fit_end_ps is None else fit_end_ps
    window = (lags >= start) & (lags <= end)
    if window.sum() < 3:
        raise ValueError("The fit window holds fewer than 3 lag times; widen it.")
    slope, intercept = np.polyfit(lags[window], values[window], 1)
    fitted = slope * lags[window] + intercept
    residual = ((values[window] - fitted) ** 2).sum()
    r_squared = 1 - residual / ((values[window] - values[window].mean()) ** 2).sum()
    diffusion = slope / (2 * len(dimensions))
    _write_csv(output, ["lag_time_ps", "msd_angstrom2"], [lags, values])
    _plot_msd(lags, values, lags[window], fitted, plot)
    return {
        "selection": selection,
        "n_atoms": int(group.n_atoms),
        "dimensions": dimensions,
        "diffusion_coefficient_angstrom2_ps": float(diffusion),
        "diffusion_coefficient_cm2_s": float(diffusion * CM2_PER_S_PER_ANGSTROM2_PER_PS),
        "fit_window_ps": [float(start), float(end)],
        "fit_r_squared": float(r_squared),
        "lag_time_ps": _listed(lags),
        "msd_angstrom2": _listed(values),
        "output": output,
        "plot": plot,
    }


def _plot_msd(lags, values, fit_lags, fitted, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(6, 3.8))
    axes.plot(lags, values, label="MSD")
    axes.plot(fit_lags, fitted, "--", label="linear fit")
    axes.set(xlabel="lag time (ps)", ylabel="MSD (Å²)")
    axes.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
