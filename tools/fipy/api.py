"""Diffusion and phase-field microstructure simulations with FiPy (NIST).

diffusion_1d solves Fick's second law through a slab, cylinder, or sphere with a
constant, Arrhenius, or concentration-dependent diffusivity: carburizing and
nitriding, dopant drive-in, diffusion couples, drying, and outgassing.
spinodal_decomposition solves the Cahn-Hilliard equation in 2D for the phase
separation and coarsening of a binary mixture.
"""

from __future__ import annotations

import csv
import functools
import math
import warnings
from typing import Literal

import numpy as np

GAS_CONSTANT = 8.314462618  # J/(mol K)
Geometry = Literal["slab", "cylinder", "sphere"]
STEP_MIN, STEP_FRACTION = 0.01, 0.02  # Cahn-Hilliard time steps (units of tau)


@functools.cache
def _quiet() -> None:
    warnings.filterwarnings("ignore")


def _diffusivity(diffusivity_m2_s, d0_m2_s, activation_energy_kj_mol, temperature_c, table):
    """Returns (function of concentration array -> D array, description)."""
    given = [diffusivity_m2_s is not None, d0_m2_s is not None, table is not None]
    if sum(given) != 1:
        raise ValueError(
            "Give exactly one of diffusivity_m2_s, d0_m2_s (with activation_energy_kj_mol "
            "and temperature_c), or diffusivity_table."
        )
    if diffusivity_m2_s is not None:
        if diffusivity_m2_s <= 0:
            raise ValueError("diffusivity_m2_s must be positive.")
        return (lambda c: np.full_like(c, diffusivity_m2_s)), {"diffusivity_m2_s": diffusivity_m2_s}
    if d0_m2_s is not None:
        if activation_energy_kj_mol is None or temperature_c is None:
            raise ValueError("d0_m2_s needs activation_energy_kj_mol and temperature_c.")
        kelvin = temperature_c + 273.15
        if d0_m2_s <= 0 or kelvin <= 0:
            raise ValueError("d0_m2_s and the absolute temperature must be positive.")
        value = d0_m2_s * math.exp(-activation_energy_kj_mol * 1e3 / (GAS_CONSTANT * kelvin))
        return (lambda c: np.full_like(c, value)), {
            "diffusivity_m2_s": value,
            "arrhenius": {
                "d0_m2_s": d0_m2_s,
                "activation_energy_kj_mol": activation_energy_kj_mol,
                "temperature_k": kelvin,
            },
        }
    rows = sorted((float(c), float(d)) for c, d in table)
    if len(rows) < 2 or any(d <= 0 for _, d in rows):
        raise ValueError("diffusivity_table needs at least two [concentration, D > 0] rows.")
    cs = np.array([r[0] for r in rows])
    log_d = np.log([r[1] for r in rows])
    return (lambda c: np.exp(np.interp(c, cs, log_d))), {
        "diffusivity_m2_s": {"min": float(np.exp(log_d.min())), "max": float(np.exp(log_d.max()))},
        "concentration_dependent": True,
    }


def _crossing(x: np.ndarray, c: np.ndarray, target: float) -> float | None:
    """First position from x = 0 where c crosses target (linear interpolation)."""
    sign = np.sign(c - target)
    for i in range(len(c) - 1):
        if sign[i] == 0:
            return float(x[i])
        if sign[i] != sign[i + 1]:
            return float(x[i] + (target - c[i]) * (x[i + 1] - x[i]) / (c[i + 1] - c[i]))
    return None


def diffusion_1d(
    length_m: float,
    times_s: list[float] | None = None,
    diffusivity_m2_s: float | None = None,
    d0_m2_s: float | None = None,
    activation_energy_kj_mol: float | None = None,
    temperature_c: float | None = None,
    diffusivity_table: list[list[float]] | None = None,
    geometry: Geometry = "slab",
    initial_concentration: float = 0.0,
    right_initial_concentration: float | None = None,
    interface_m: float | None = None,
    left: float | Literal["closed"] = "closed",
    right: float | Literal["closed"] = "closed",
    left_flux: float | None = None,
    right_flux: float | None = None,
    positions_m: list[float] | None = None,
    target_concentration: float | None = None,
    target_position_m: float | None = None,
    cells: int = 400,
    table: str = "diffusion.csv",
    plot: str = "diffusion.png",
) -> dict:
    """Concentration profiles from Fick's second law in one dimension.

    x runs from 0 to length_m. For a slab, x = 0 is usually the surface (depth
    below it); for a cylinder or sphere, x is the radius, x = 0 is the centre
    (always closed), and the surface is the right end. For a semi-infinite body
    (carburizing a thick part), make length_m several times sqrt(D t); the result
    reports whether the far end was reached.

    Args:
        length_m: Slab thickness, or cylinder or sphere radius, in m.
        times_s: Times in s at which to report profiles. May be omitted when
            target_position_m is given; the run then stops when the target is reached.
        diffusivity_m2_s: Constant diffusion coefficient D in m2/s.
        d0_m2_s: Arrhenius pre-factor; D = D0 exp(-Q / R T).
        activation_energy_kj_mol: Arrhenius activation energy Q in kJ/mol.
        temperature_c: Temperature in degrees Celsius for the Arrhenius law.
        diffusivity_table: [[concentration, D], ...] for a concentration-dependent
            D (log D is interpolated linearly in concentration).
        geometry: "slab", "cylinder" (radial), or "sphere" (radial).
        initial_concentration: Uniform initial concentration (any unit: wt%,
            at%, mol/m3, ...), or the left side of a diffusion couple.
        right_initial_concentration: Right side of a diffusion couple.
        interface_m: Position of the couple interface (default: the middle).
        left: Fixed concentration at x = 0, or "closed" (no flux).
        right: Fixed concentration at x = length_m, or "closed" (no flux).
        left_flux: Constant flux into the body at x = 0 (concentration x m/s).
        right_flux: Constant flux into the body at x = length_m.
        positions_m: Positions at which to report the concentration at each time.
        target_concentration: With target_position_m, find the time at which the
            concentration there first reaches this value; without it, report the
            depth where the profile crosses this value at each time (case depth).
        target_position_m: Position for target_concentration.
        cells: Number of grid cells.
        table: CSV file for the profiles.
        plot: PNG file of the profiles.

    Returns:
        The diffusivity used; for each time the diffusion length sqrt(D t), the
        concentration at positions_m, the depth where the profile crosses
        target_concentration, the amount of solute (per m2 of slab, per m of
        cylinder, or per sphere) and the fraction of the uptake or loss toward
        equilibrium with the fixed surface concentration; the time to reach the
        target; and whether the far end was affected (semi-infinite check).
    """
    _quiet()
    import fipy

    if length_m <= 0 or cells < 10:
        raise ValueError("length_m must be positive, with at least 10 cells.")
    d_of_c, d_info = _diffusivity(
        diffusivity_m2_s, d0_m2_s, activation_energy_kj_mol, temperature_c, diffusivity_table
    )
    times = sorted({float(t) for t in times_s or []})
    if any(t <= 0 for t in times):
        raise ValueError("times_s must be positive.")
    if not times and target_position_m is None:
        raise ValueError("Give times_s, or target_concentration with target_position_m.")
    if target_position_m is not None and target_concentration is None:
        raise ValueError("target_position_m needs target_concentration.")
    if geometry != "slab" and (left != "closed" or left_flux is not None):
        raise ValueError(
            "For a cylinder or sphere x = 0 is the centre, which is closed; set the "
            "surface condition with right or right_flux."
        )
    for name, fixed, flux in (("left", left, left_flux), ("right", right, right_flux)):
        if fixed != "closed" and flux is not None:
            raise ValueError(f"Give either {name} (fixed concentration) or {name}_flux, not both.")
        if fixed != "closed" and not isinstance(fixed, int | float):
            raise ValueError(f"{name} must be a concentration or 'closed'.")

    dx = length_m / cells
    mesh = {
        "slab": fipy.Grid1D,
        "cylinder": fipy.CylindricalGrid1D,
        "sphere": fipy.SphericalGrid1D,
    }[geometry](nx=cells, dx=dx)
    x = np.asarray(mesh.cellCenters[0])
    c = fipy.CellVariable(mesh=mesh, value=float(initial_concentration), hasOld=True)
    if right_initial_concentration is not None:
        boundary = length_m / 2 if interface_m is None else interface_m
        if not 0 < boundary < length_m:
            raise ValueError("interface_m must lie inside the body.")
        c.setValue(float(right_initial_concentration), where=mesh.cellCenters[0] > boundary)
    if left != "closed":
        c.constrain(float(left), mesh.facesLeft)
    if right != "closed":
        c.constrain(float(right), mesh.facesRight)
    d_face = fipy.FaceVariable(mesh=mesh, value=d_of_c(np.asarray(c.faceValue)))
    equation = fipy.TransientTerm() == fipy.DiffusionTerm(coeff=d_face)
    if left_flux is not None:
        equation = equation + (mesh.facesLeft * float(left_flux)).divergence
    if right_flux is not None:
        equation = equation - (mesh.facesRight * float(right_flux)).divergence
    nonlinear = diffusivity_table is not None

    volumes = (
        np.asarray(mesh.cellVolumes)
        * {"slab": 1.0, "cylinder": 2 * math.pi, "sphere": 4 * math.pi}[geometry]
    )
    total_volume = volumes.sum()
    amount0 = float((np.asarray(c.value) * volumes).sum())
    fixed = {v for v in (left, right) if v != "closed"}
    equilibrium = (
        float(next(iter(fixed))) * total_volume
        if len(fixed) == 1 and left_flux is None and right_flux is None
        else None
    )
    initial = np.asarray(c.value).copy()
    d_max = d_info["diffusivity_m2_s"]["max"] if nonlinear else d_info["diffusivity_m2_s"]
    end = max(times) if times else 50 * length_m**2 / d_max
    want_target = target_position_m is not None
    if want_target and not 0 <= target_position_m <= length_m:
        raise ValueError("target_position_m must lie inside the body.")

    def value_at(position: float) -> float:
        return float(np.interp(position, x, np.asarray(c.value)))

    def advance(dt: float) -> None:
        c.updateOld()
        for _ in range(4 if nonlinear else 1):
            if nonlinear:
                d_face.setValue(d_of_c(np.asarray(c.faceValue)))
            equation.solve(var=c, dt=dt)

    target_time = None
    previous = value_at(target_position_m) if want_target else None
    snapshots: list[tuple[float, np.ndarray]] = []
    pending = list(times)
    t = 0.0
    dt = min(dx**2 / d_max, end * 1e-6)
    while pending or (want_target and target_time is None and t < end):
        next_stop = pending[0] if pending else end
        step = min(dt, next_stop - t)
        advance(step)
        t += step
        if want_target and target_time is None:
            now = value_at(target_position_m)
            if (previous - target_concentration) * (now - target_concentration) <= 0:
                fraction = (now - target_concentration) / (now - previous) if now != previous else 0
                target_time = t - step * fraction
            previous = now
        if pending and t >= pending[0] * (1 - 1e-12):
            snapshots.append((t, np.asarray(c.value).copy()))
            pending.pop(0)
        dt = min(dt * 1.02, max(0.01 * t, dt))
    if not times:
        snapshots.append((t, np.asarray(c.value).copy()))

    rows = []
    span = np.ptp(np.concatenate([initial] + [s for _, s in snapshots])) or 1.0
    for time, profile in snapshots:
        amount = float((profile * volumes).sum())
        entry = {"time_s": round(time, 6), "time_h": round(time / 3600, 6)}
        if not nonlinear:
            entry["diffusion_length_m"] = float(math.sqrt(d_info["diffusivity_m2_s"] * time))
        if positions_m:
            entry["concentration_at"] = [
                {"position_m": p, "concentration": float(np.interp(p, x, profile))}
                for p in positions_m
            ]
        if target_concentration is not None and not want_target:
            entry["depth_at_target_m"] = _crossing(x, profile, target_concentration)
        entry["amount"] = amount
        if equilibrium is not None and equilibrium != amount0:
            entry["fraction_to_equilibrium"] = (amount - amount0) / (equilibrium - amount0)
        rows.append(entry)

    far = -1 if geometry == "slab" and left != "closed" else 0
    far_change = max(abs(profile[far] - initial[far]) for _, profile in snapshots) / span
    result = {
        "geometry": geometry,
        "length_m": length_m,
        **d_info,
        "times": rows,
        "amount_unit": {
            "slab": "concentration x m (per m2 of surface)",
            "cylinder": "concentration x m2 (per m of length)",
            "sphere": "concentration x m3 (per sphere)",
        }[geometry],
        "far_end_changed_fraction": round(float(far_change), 6),
        "table": table,
        "plot": plot,
    }
    if want_target:
        result["target"] = {
            "position_m": target_position_m,
            "concentration": target_concentration,
            "time_s": target_time,
            "time_h": None if target_time is None else target_time / 3600,
        }
        if target_time is None:
            result["target"]["note"] = "Not reached within the simulated time."
    if far_change > 0.01 and geometry == "slab" and (left != "closed") != (right != "closed"):
        result["note"] = (
            "The profile reached the far end, so the body is not semi-infinite; "
            "increase length_m if a semi-infinite body was intended."
        )
    _write_profiles(table, x, snapshots)
    _plot_profiles(plot, x, initial, snapshots, geometry)
    return result


def _write_profiles(path: str, x: np.ndarray, snapshots) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["position_m"] + [f"t={t:g}s" for t, _ in snapshots])
        for i, position in enumerate(x):
            writer.writerow([f"{position:.6g}"] + [f"{p[i]:.6g}" for _, p in snapshots])


def _plot_profiles(path: str, x, initial, snapshots, geometry: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scale, unit = (1e3, "mm") if x[-1] >= 1e-3 else (1e6, "µm")
    figure, axis = plt.subplots(figsize=(6, 4))
    axis.plot(x * scale, initial, "k:", label="initial")
    for time, profile in snapshots:
        label = f"{time / 3600:.3g} h" if time >= 3600 else f"{time:.3g} s"
        axis.plot(x * scale, profile, label=label)
    axis.set_xlabel(("depth" if geometry == "slab" else "radius") + f" ({unit})")
    axis.set_ylabel("concentration")
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def _characteristic_length(field: np.ndarray, spacing: float) -> float | None:
    """2 pi / <k>, the first moment of the circularly averaged structure factor."""
    fluctuation = field - field.mean()
    if fluctuation.std() < 1e-8:
        return None
    power = np.abs(np.fft.fft2(fluctuation)) ** 2
    k = 2 * np.pi * np.fft.fftfreq(field.shape[0], d=spacing)
    kx, ky = np.meshgrid(k, k, indexing="ij")
    magnitude = np.hypot(kx, ky)
    mask = magnitude > 0
    return float(2 * np.pi / ((magnitude[mask] * power[mask]).sum() / power[mask].sum()))


def spinodal_decomposition(
    mean_composition: float = 0.5,
    time: float = 500.0,
    size: float = 64.0,
    cells: int = 128,
    noise: float = 0.01,
    seed: int = 1,
    snapshots: int = 4,
    barrier_j_m3: float | None = None,
    gradient_energy_j_m: float | None = None,
    mobility_m5_j_s: float | None = None,
    plot: str = "spinodal.png",
    field: str = "composition.csv",
) -> dict:
    """Phase separation of a binary mixture (Cahn-Hilliard equation) in 2D.

    Free energy F = integral of W c^2 (1 - c)^2 + (kappa / 2) |grad c|^2, so the
    equilibrium phases are c = 0 and 1, and dc/dt = div(M grad(dF/dc)). Lengths
    are in units of l = sqrt(kappa / W) and times in tau = kappa / (M W^2);
    give W, kappa, and M to convert them to m and s.

    Args:
        mean_composition: Average composition c0 (0 to 1).
        time: Simulated time in units of tau.
        size: Side of the square, periodic box in units of l.
        cells: Grid cells per side.
        noise: Standard deviation of the initial composition fluctuations.
        seed: Random seed.
        snapshots: Number of microstructure snapshots in the plot.
        barrier_j_m3: Double-well height scale W in J/m3 (optional).
        gradient_energy_j_m: Gradient energy coefficient kappa in J/m (optional).
        mobility_m5_j_s: Mobility M in m5/(J s) (optional).
        plot: PNG with the microstructure snapshots.
        field: CSV of the final composition field (cells x cells).

    Returns:
        Whether c0 lies inside the spinodal (f'' < 0) and the spinodal
        compositions; the fastest-growing wavelength of linear (Cahn) theory; at
        each snapshot the time, characteristic length (from the structure
        factor), composition spread, fraction of the c > 1/2 phase, and the median
        composition of each phase;
        whether the mixture decomposed; interface width and energy; and the
        units used.
    """
    _quiet()
    import fipy

    if not 0 < mean_composition < 1:
        raise ValueError("mean_composition must be between 0 and 1.")
    if time <= 0 or size <= 0 or cells < 16 or snapshots < 1:
        raise ValueError("time and size must be positive, with at least 16 cells.")
    if cells > 512:
        raise ValueError("Use at most 512 cells per side.")
    physical = [barrier_j_m3, gradient_energy_j_m, mobility_m5_j_s]
    if any(v is not None for v in physical) and not all(v is not None and v > 0 for v in physical):
        raise ValueError(
            "Give all of barrier_j_m3, gradient_energy_j_m, and mobility_m5_j_s (> 0)."
        )

    spacing = size / cells
    mesh = fipy.PeriodicGrid2D(nx=cells, ny=cells, dx=spacing, dy=spacing)
    rng = np.random.default_rng(seed)
    c = fipy.CellVariable(mesh=mesh, value=mean_composition + noise * rng.standard_normal(cells**2))
    mu = fipy.CellVariable(mesh=mesh)
    # Dimensionless: f = c^2 (1 - c)^2, mu = f'(c) - lap c, dc/dt = lap mu.
    dfdc = 2 * c * (1 - c) * (1 - 2 * c)
    d2fdc2 = 2 * (1 - 6 * c * (1 - c))
    equation = (fipy.TransientTerm(var=c) == fipy.DiffusionTerm(coeff=1.0, var=mu)) & (
        fipy.ImplicitSourceTerm(coeff=1.0, var=mu)
        == fipy.ImplicitSourceTerm(coeff=d2fdc2, var=c)
        - d2fdc2 * c
        + dfdc
        - fipy.DiffusionTerm(coeff=1.0, var=c)
    )

    curvature = 2 * (1 - 6 * mean_composition * (1 - mean_composition))
    inside = curvature < 0
    wavelength = 2 * math.pi * math.sqrt(2 / -curvature) if inside else None
    # Fluctuations grow ~100-fold by t = ln(100) / R_max, with R_max = f''^2 / 4.
    onset = 4 * math.log(100) / curvature**2 if inside else 0.0
    start = min(1.2 * onset, time) if inside else time / 10 ** (snapshots - 1)
    targets = [float(v) for v in np.geomspace(start, time, snapshots)]
    if snapshots == 1 or start >= time:
        targets = [time]
    taken = []
    t = 0.0
    solver = fipy.solvers.scipy.LinearGMRESSolver(tolerance=1e-8)
    dt = 1e-2
    while targets:
        step = min(dt, targets[0] - t)
        equation.solve(dt=step, solver=solver)
        t += step
        if t >= targets[0] * (1 - 1e-12):
            taken.append((t, np.asarray(c.value).reshape(cells, cells).copy()))
            targets.pop(0)
        dt = max(STEP_MIN, STEP_FRACTION * t)

    def describe(time_value, grid):
        rich = grid > 0.5
        entry = {
            "time": round(float(time_value), 6),
            "characteristic_length": _characteristic_length(grid, spacing),
            "composition_std": float(grid.std()),
            "mean_composition": float(grid.mean()),
            "fraction_c_above_half": float(rich.mean()),
        }
        if 0 < rich.sum() < rich.size:
            entry["phase_compositions"] = [
                float(np.median(grid[~rich])),
                float(np.median(grid[rich])),
            ]
        return entry

    rows = [describe(*snapshot) for snapshot in taken]
    final = taken[-1][1]
    result = {
        "mean_composition": mean_composition,
        "inside_spinodal": inside,
        "spinodal_compositions": [(3 - math.sqrt(3)) / 6, (3 + math.sqrt(3)) / 6],
        "fastest_growing_wavelength": wavelength,
        "snapshots": rows,
        "decomposed": bool(final.std() > 0.25),
        "interface_width_10_90": 2 * math.sqrt(2) * math.atanh(0.8),
        "units": {"length": "l = sqrt(kappa / W)", "time": "tau = kappa / (M W^2)"},
        "plot": plot,
        "field": field,
    }
    if all(v is not None for v in physical):
        length_unit = math.sqrt(gradient_energy_j_m / barrier_j_m3)
        time_unit = gradient_energy_j_m / (mobility_m5_j_s * barrier_j_m3**2)
        result["units"].update({"length_m": length_unit, "time_s": time_unit})
        result["interface_energy_j_m2"] = math.sqrt(2 * gradient_energy_j_m * barrier_j_m3) / 6
    with open(field, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([[f"{v:.5f}" for v in row] for row in final])
    _plot_snapshots(plot, taken, size)
    return result


def _plot_snapshots(path: str, taken, size: float) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, len(taken), figsize=(3 * len(taken), 3.2), squeeze=False)
    for axis, (time_value, grid) in zip(axes[0], taken, strict=True):
        axis.imshow(grid, origin="lower", extent=(0, size, 0, size), vmin=0, vmax=1, cmap="RdBu_r")
        axis.set_title(f"t = {time_value:.3g}")
        axis.set_xticks([])
        axis.set_yticks([])
    figure.tight_layout()
    figure.savefig(path, dpi=110)
    plt.close(figure)
