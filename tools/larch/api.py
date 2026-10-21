"""X-ray absorption spectroscopy (XANES and EXAFS) with xraylarch.

normalize finds the edge energy and edge step and normalizes a spectrum;
exafs extracts chi(k) and its Fourier transform; feff_paths runs FEFF on a
crystal structure to get scattering paths; fit_shells fits those paths to
measured EXAFS (distances, coordination, disorder); linear_combination fits a
XANES spectrum as a mixture of reference spectra.
"""

from __future__ import annotations

import csv
import functools
import glob
import math
import os
import platform
import warnings
from pathlib import Path
from typing import Literal

import numpy as np

Window = Literal["hanning", "kaiser", "parzen", "welch", "sine", "gaussian"]
MU_NAMES = ("mu", "xmu", "mutrans", "mu_trans", "mufluor", "mu_fluor", "mu_e", "norm")


@functools.cache
def _quiet() -> None:
    warnings.filterwarnings("ignore")


def _load(spectrum: str, columns: dict | None):
    """Read a spectrum; returns a Larch group with energy and mu."""
    _quiet()
    from larch.io import read_ascii

    file = Path(spectrum)
    if not file.is_file():
        raise ValueError(f"Spectrum file {spectrum!r} not found.")
    try:
        group = read_ascii(str(file))
    except Exception as exc:
        raise ValueError(f"Could not read {file.name} as a column data file: {exc}") from exc
    labels = list(group.array_labels)
    data = {label: np.asarray(getattr(group, label), dtype=float) for label in labels}
    columns = {k.lower(): v for k, v in (columns or {}).items()}

    def column(name: str) -> np.ndarray:
        if name not in data:
            raise ValueError(f"Column {name!r} not in {file.name}; columns: {', '.join(labels)}.")
        return data[name]

    energy = column(columns.get("energy", labels[0]))
    if "mu" in columns:
        mu = column(columns["mu"])
        how = f"column {columns['mu']}"
    elif "i0" in columns and "it" in columns:
        mu = np.log(column(columns["i0"]) / column(columns["it"]))
        how = f"ln({columns['i0']}/{columns['it']}) (transmission)"
    elif "i0" in columns and "if" in columns:
        mu = column(columns["if"]) / column(columns["i0"])
        how = f"{columns['if']}/{columns['i0']} (fluorescence)"
    else:
        name = next((n for n in MU_NAMES if n in data), None)
        if name:
            mu, how = data[name], f"column {name}"
        elif "i0" in data and "itrans" in data:
            mu, how = np.log(data["i0"] / data["itrans"]), "ln(i0/itrans) (transmission)"
        elif len(labels) >= 2:
            mu, how = data[labels[1]], f"column {labels[1]}"
        else:
            raise ValueError(f"{file.name} needs at least energy and mu columns.")
    if energy.max() < 100:  # keV
        energy = energy * 1000.0
    order = np.argsort(energy)
    energy, mu = energy[order], mu[order]
    keep = np.concatenate([[True], np.diff(energy) > 0]) & np.isfinite(mu)
    from larch import Group

    loaded = Group(energy=energy[keep], mu=mu[keep], filename=file.name)
    loaded.mu_source = how
    return loaded


def _pre_edge(group, e0, pre1, pre2, norm1, norm2, nnorm):
    from larch.xafs import pre_edge

    pre_edge(
        group, e0=e0, pre1=pre1, pre2=pre2, norm1=norm1, norm2=norm2, nnorm=nnorm, make_flat=True
    )


def _plot(path: str, panels) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, len(panels), figsize=(5.5 * len(panels), 4), squeeze=False)
    for axis, (xlabel, ylabel, curves) in zip(axes[0], panels, strict=True):
        for x, y, label, style in curves:
            axis.plot(x, y, style, label=label)
        axis.set_xlabel(xlabel)
        axis.set_ylabel(ylabel)
        axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def _write(path: str, header: list[str], columns) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in zip(*columns, strict=True):
            writer.writerow([f"{v:.8g}" for v in row])


def normalize(
    spectrum: str,
    columns: dict | None = None,
    e0: float | None = None,
    pre1: float | None = None,
    pre2: float | None = None,
    norm1: float | None = None,
    norm2: float | None = None,
    nnorm: int | None = None,
    table: str = "normalized.csv",
    plot: str = "normalized.png",
) -> dict:
    """Edge energy, edge step, and normalized XANES of an absorption spectrum.

    Args:
        spectrum: Column data file (XDI, Athena-style .xmu, CSV, ...) with energy in
            eV (or keV).
        columns: Which columns to use, e.g. {"energy": "energy", "mu": "mutrans"},
            {"i0": "i0", "it": "itrans"} (transmission, mu = ln(i0/it)), or
            {"i0": "i0", "if": "ifluor"} (fluorescence, mu = if/i0). By default a
            column named mu, xmu, mutrans, ... or i0 and itrans is used.
        e0: Edge energy in eV (default: maximum of the derivative).
        pre1: Start of the pre-edge range, eV relative to E0 (default automatic).
        pre2: End of the pre-edge range, eV relative to E0.
        norm1: Start of the normalization range, eV relative to E0.
        norm2: End of the normalization range, eV relative to E0.
        nnorm: Degree of the post-edge polynomial (0-3).
        table: CSV with energy, mu, normalized, and flattened mu.
        plot: PNG of the normalized spectrum.

    Returns:
        E0, edge step, ranges used, the white-line (first maximum after the edge)
        energy and normalized height, and how mu was obtained.
    """
    group = _load(spectrum, columns)
    _pre_edge(group, e0, pre1, pre2, norm1, norm2, nnorm)
    above = group.energy > group.e0
    window = above & (group.energy < group.e0 + 40)
    white = None
    if window.any():
        index = np.argmax(np.where(window, group.norm, -np.inf))
        white = {"energy_ev": float(group.energy[index]), "height": float(group.norm[index])}
    _write(
        table,
        ["energy_ev", "mu", "norm", "flat"],
        [group.energy, group.mu, group.norm, group.flat],
    )
    _plot(
        plot,
        [
            (
                "energy (eV)",
                "normalized mu(E)",
                [(group.energy, group.flat, group.filename, "-")],
            )
        ],
    )
    params = group.pre_edge_details
    return {
        "spectrum": group.filename,
        "mu_from": group.mu_source,
        "e0_ev": float(group.e0),
        "edge_step": float(group.edge_step),
        "pre_edge_range_ev": [float(params.pre1), float(params.pre2)],
        "normalization_range_ev": [float(params.norm1), float(params.norm2)],
        "post_edge_polynomial_degree": int(params.nnorm),
        "white_line": white,
        "points": len(group.energy),
        "table": table,
        "plot": plot,
    }


def _chi(group, rbkg, kweight, e0):
    from larch.xafs import autobk

    autobk(group, rbkg=rbkg, kweight=kweight, e0=e0)


def exafs(
    spectrum: str,
    columns: dict | None = None,
    e0: float | None = None,
    rbkg: float = 1.0,
    kweight: int = 2,
    kmin: float = 2.0,
    kmax: float | None = None,
    dk: float = 1.0,
    window: Window = "hanning",
    table: str = "exafs.csv",
    plot: str = "exafs.png",
) -> dict:
    """EXAFS chi(k) and its Fourier transform |chi(R)|.

    Args:
        spectrum: Column data file with energy and mu (see normalize).
        columns: Column selection (see normalize).
        e0: Edge energy in eV (default: from the data).
        rbkg: Background cutoff radius in Angstrom (AUTOBK), about half the
            first-shell distance.
        kweight: k-weight for the background and the transform.
        kmin: Start of the Fourier transform k-range (1/Angstrom).
        kmax: End of the k-range (default: the end of the data minus 1).
        dk: Window taper width (1/Angstrom).
        window: Fourier transform window.
        table: CSV with k, chi(k), and k^w chi(k).
        plot: PNG of k^w chi(k) and |chi(R)|.

    Returns:
        E0, edge step, k-range, the main peaks of |chi(R)| (positions are not
        phase-corrected: real distances are typically 0.3-0.5 Angstrom longer),
        and the number of independent points 2 dk dR / pi for 1-3 Angstrom.
    """
    from larch.xafs import xftf

    group = _load(spectrum, columns)
    _chi(group, rbkg, kweight, e0)
    top = float(group.k.max())
    kmax = min(kmax or top - 1.0, top)
    if kmax <= kmin:
        raise ValueError(f"kmax ({kmax:.1f}) must exceed kmin; the data reach k = {top:.1f}.")
    xftf(group, kmin=kmin, kmax=kmax, dk=dk, kweight=kweight, window=window)
    r, magnitude = np.asarray(group.r), np.asarray(group.chir_mag)
    peaks = [
        i
        for i in range(1, len(r) - 1)
        if magnitude[i] > magnitude[i - 1] and magnitude[i] >= magnitude[i + 1] and r[i] > rbkg
    ]
    peaks = sorted(peaks, key=lambda i: -magnitude[i])[:4]
    _write(
        table,
        ["k_inv_angstrom", "chi", f"k{kweight}_chi"],
        [group.k, group.chi, group.chi * group.k**kweight],
    )
    _plot(
        plot,
        [
            (
                "k (1/Å)",
                f"k^{kweight} chi(k)",
                [(group.k, group.chi * group.k**kweight, group.filename, "-")],
            ),
            ("R (Å)", "|chi(R)|", [(r[r < 8], magnitude[r < 8], group.filename, "-")]),
        ],
    )
    return {
        "spectrum": group.filename,
        "e0_ev": float(group.e0),
        "edge_step": float(group.edge_step),
        "k_range": [kmin, round(kmax, 3)],
        "kweight": kweight,
        "chir_peaks": [
            {"r_angstrom": round(float(r[i]), 3), "magnitude": float(magnitude[i])}
            for i in sorted(peaks, key=lambda i: r[i])
        ],
        "independent_points_1_to_3_angstrom": round(2 * (kmax - kmin) * 2.0 / math.pi, 1),
        "table": table,
        "plot": plot,
    }


def _feff_error(exc: Exception) -> RuntimeError:
    hint = ""
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        hint = (
            " FEFF is an Intel program; on Apple silicon it needs Rosetta 2 "
            "(install with: softwareupdate --install-rosetta)."
        )
    elif platform.machine().lower() in ("aarch64", "arm64"):
        hint = " FEFF is only available for x86-64 computers."
    return RuntimeError(f"FEFF failed: {exc}.{hint}")


def feff_paths(
    structure: str,
    absorber: str,
    edge: Literal["K", "L1", "L2", "L3"] = "K",
    radius: float = 6.0,
    absorber_site: int = 1,
    folder: str = "feff",
) -> dict:
    """Scattering paths around an absorbing atom from FEFF8L.

    Args:
        structure: CIF file of the crystal.
        absorber: Element of the absorbing atom (e.g. "Cu").
        edge: Absorption edge.
        radius: Cluster and path radius in Angstrom.
        absorber_site: Which crystallographic site of that element (1, 2, ...).
        folder: Output folder for feff.inp and the feffNNNN.dat path files.

    Returns:
        The paths sorted by length: file, effective distance (Angstrom),
        degeneracy, number of legs, and atoms; the single-scattering shells
        separately. Use the files in fit_shells.
    """
    _quiet()
    from larch.xafs import feff8l, feffpath
    from larixite import cif2feffinp

    file = Path(structure)
    if not file.is_file():
        raise ValueError(f"Structure file {structure!r} not found.")
    if not 2.0 <= radius <= 10.0:
        raise ValueError("radius must be between 2 and 10 Angstrom.")
    try:
        text = cif2feffinp(
            file.read_text(encoding="utf-8", errors="replace"),
            absorber,
            edge=edge,
            cluster_size=radius,
            absorber_site=absorber_site,
        )
    except Exception as exc:
        raise ValueError(f"Could not build a FEFF input from {file.name}: {exc}") from exc
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    for old in glob.glob(str(out / "feff0*.dat")):
        os.remove(old)
    (out / "feff.inp").write_text(text, encoding="utf-8")
    try:
        feff8l(feffinp="feff.inp", folder=str(out), verbose=False)
    except Exception as exc:
        raise _feff_error(exc) from exc
    files = sorted(glob.glob(str(out / "feff0*.dat")))
    if not files:
        log = out / "feffrun_feff8l_pot.log"
        raise _feff_error(RuntimeError(log.read_text()[-400:] if log.is_file() else "no paths"))
    paths = []
    for name in files:
        path = feffpath(name)
        paths.append(
            {
                "file": name,
                "reff_angstrom": round(float(path.reff), 4),
                "degeneracy": float(path.degen),
                "legs": int(path.nleg),
                "atoms": [str(atom[0]) for atom in path.geom],
            }
        )
    paths.sort(key=lambda p: p["reff_angstrom"])
    return {
        "structure": file.name,
        "absorber": absorber,
        "edge": edge,
        "folder": str(out),
        "paths": paths,
        "single_scattering": [p for p in paths if p["legs"] == 2],
    }


def fit_shells(
    spectrum: str,
    paths: list[str],
    columns: dict | None = None,
    e0: float | None = None,
    rbkg: float = 1.0,
    kweight: int = 2,
    kmin: float = 3.0,
    kmax: float | None = None,
    dk: float = 4.0,
    window: Window = "kaiser",
    rmin: float = 1.0,
    rmax: float = 3.0,
    amplitude: float | None = None,
    table: str = "shell_fit.csv",
    plot: str = "shell_fit.png",
) -> dict:
    """Fit FEFF scattering paths to measured EXAFS (the EXAFS equation, in R space).

    Each path gets its own distance change (delta R) and Debye-Waller factor
    (sigma^2); the amplitude reduction factor S0^2 and the energy shift delta E0 are
    shared. Coordination numbers are the paths' degeneracies times S0^2.

    Args:
        spectrum: Column data file with energy and mu (see normalize).
        paths: FEFF path files (feffNNNN.dat), e.g. from feff_paths.
        columns: Column selection (see normalize).
        e0: Edge energy in eV (default: from the data).
        rbkg: Background cutoff radius in Angstrom.
        kweight: k-weight of the fit.
        kmin: Start of the k-range (1/Angstrom).
        kmax: End of the k-range (default: the end of the data minus 1).
        dk: Window taper width.
        window: Fourier transform window.
        rmin: Start of the R fitting range (Angstrom).
        rmax: End of the R fitting range.
        amplitude: Fix S0^2 at this value (e.g. from a reference compound) and fit
            the coordination numbers instead.
        table: CSV with k, data and fit k^w chi(k).
        plot: PNG of data and fit in k and R space.

    Returns:
        S0^2 (or the coordination numbers) and delta E0, and for each path its
        fitted distance, delta R, sigma^2, and coordination, with uncertainties;
        R-factor, reduced chi-square, independent points, and variables.
    """
    _quiet()
    from larch.fitting import guess, param, param_group
    from larch.xafs import feffit, feffit_dataset, feffit_transform, feffpath, xftf

    if not paths:
        raise ValueError("Give at least one FEFF path file.")
    for name in paths:
        if not Path(name).is_file():
            raise ValueError(f"Path file {name!r} not found.")
    group = _load(spectrum, columns)
    _chi(group, rbkg, kweight, e0)
    top = float(group.k.max())
    kmax = min(kmax or top - 1.0, top)
    parameters = {"del_e0": guess(0.0)}
    if amplitude is None:
        parameters["amp"] = param(1.0, vary=True)
    feff = []
    for i, name in enumerate(paths, start=1):
        parameters[f"dr{i}"] = guess(0.0)
        parameters[f"ss{i}"] = param(0.003, vary=True, min=0.0)
        if amplitude is not None:
            parameters[f"cn{i}"] = param(feffpath(name).degen, vary=True, min=0.0)
            s02 = f"{amplitude} * cn{i} / {feffpath(name).degen}"
        else:
            s02 = "amp"
        feff.append(feffpath(name, s02=s02, e0="del_e0", sigma2=f"ss{i}", deltar=f"dr{i}"))
    pars = param_group(**parameters)
    transform = feffit_transform(
        kmin=kmin, kmax=kmax, kweight=kweight, dk=dk, window=window, rmin=rmin, rmax=rmax
    )
    dataset = feffit_dataset(data=group, pathlist=feff, transform=transform)
    out = feffit(pars, dataset)
    fitted = out.paramgroup

    def value(name: str) -> dict:
        p = getattr(fitted, name)
        return {"value": float(p.value), "error": None if p.stderr is None else float(p.stderr)}

    shells = []
    for i, path in enumerate(feff, start=1):
        dr = value(f"dr{i}")
        entry = {
            "file": paths[i - 1],
            "atoms": [str(atom[0]) for atom in path.geom],
            "legs": int(path.nleg),
            "reff_angstrom": float(path.reff),
            "r_angstrom": {"value": float(path.reff) + dr["value"], "error": dr["error"]},
            "delta_r_angstrom": dr,
            "sigma2_angstrom2": value(f"ss{i}"),
        }
        if amplitude is None:
            entry["degeneracy"] = float(path.degen)
        else:
            entry["coordination_number"] = value(f"cn{i}")
        shells.append(entry)
    model = dataset.model
    data_k = group.chi * group.k**kweight
    xftf(model, kmin=kmin, kmax=kmax, dk=dk, kweight=kweight, window=window)
    _write(
        table,
        ["k_inv_angstrom", "data_kw_chi", "fit_kw_chi"],
        [group.k, data_k, np.interp(group.k, model.k, model.chi * model.k**kweight)],
    )
    xftf(group, kmin=kmin, kmax=kmax, dk=dk, kweight=kweight, window=window)
    _plot(
        plot,
        [
            (
                "k (1/Å)",
                f"k^{kweight} chi(k)",
                [
                    (group.k, data_k, "data", "-"),
                    (model.k, model.chi * model.k**kweight, "fit", "--"),
                ],
            ),
            (
                "R (Å)",
                "|chi(R)|",
                [
                    (group.r[group.r < 6], group.chir_mag[group.r < 6], "data", "-"),
                    (model.r[model.r < 6], model.chir_mag[model.r < 6], "fit", "--"),
                ],
            ),
        ],
    )
    result = {
        "spectrum": group.filename,
        "e0_ev": float(group.e0),
        "k_range": [kmin, round(kmax, 3)],
        "r_range": [rmin, rmax],
        "kweight": kweight,
        "delta_e0_ev": value("del_e0"),
        "shells": shells,
        "r_factor": float(out.rfactor),
        "reduced_chi_square": float(out.chi2_reduced),
        "independent_points": float(out.n_independent),
        "variables": int(out.nvarys),
        "table": table,
        "plot": plot,
    }
    if amplitude is None:
        result["s02"] = value("amp")
    else:
        result["s02_fixed"] = amplitude
    if out.nvarys > out.n_independent:
        result["warning"] = "More variables than independent points; the fit is underdetermined."
    return result


def linear_combination(
    spectrum: str,
    standards: list[str],
    columns: dict | None = None,
    emin: float = -20.0,
    emax: float = 60.0,
    sum_to_one: bool = True,
    nonnegative: bool = True,
    plot: str = "lcf.png",
) -> dict:
    """Fit a normalized XANES spectrum as a mixture of reference spectra.

    Args:
        spectrum: Spectrum of the sample (see normalize for formats).
        standards: Spectra of the reference compounds, measured at the same edge.
        columns: Column selection, applied to all files (see normalize).
        emin: Start of the fit range, eV relative to the sample's E0.
        emax: End of the fit range, eV relative to the sample's E0.
        sum_to_one: Force the weights to add up to 1.
        nonnegative: Keep weights between 0 and 1.
        plot: PNG of the sample, fit, and weighted components.

    Returns:
        The weight of each standard (in the order given) with its uncertainty,
        their sum, R-factor,
        reduced chi-square, and the fitted energy range.
    """
    from larch.math import lincombo_fit

    if len(standards) < 2:
        raise ValueError("Give at least two standards.")
    sample = _load(spectrum, columns)
    _pre_edge(sample, None, None, None, None, None, None)
    components = []
    for name in standards:
        component = _load(name, columns)
        _pre_edge(component, None, None, None, None, None, None)
        components.append(component)
    if len({c.filename for c in components}) != len(components):
        raise ValueError("Standards need different file names.")
    limits = (0.0, 1.0) if nonnegative else (None, None)
    result = lincombo_fit(
        sample,
        components,
        minvals=[limits[0]] * len(components),
        maxvals=[limits[1]] * len(components),
        arrayname="norm",
        xmin=sample.e0 + emin,
        xmax=sample.e0 + emax,
        sum_to_one=sum_to_one,
    )
    weights = []
    for component in components:
        p = result.params[component.filename]
        weights.append(
            {
                "standard": component.filename,
                "weight": float(p.value),
                "error": None if p.stderr is None else float(p.stderr),
            }
        )
    _plot(
        plot,
        [
            (
                "energy (eV)",
                "normalized mu(E)",
                [
                    (result.xdata, result.ydata, sample.filename, "-"),
                    (result.xdata, result.yfit, "fit", "--"),
                ]
                + [
                    (result.xdata, y, f"{label} (weighted)", ":")
                    for label, y in result.ycomps.items()
                ],
            )
        ],
    )
    return {
        "spectrum": sample.filename,
        "e0_ev": float(sample.e0),
        "energy_range_ev": [float(sample.e0 + emin), float(sample.e0 + emax)],
        "weights": weights,
        "sum_of_weights": float(sum(w["weight"] for w in weights)),
        "r_factor": float(result.rfactor),
        "reduced_chi_square": float(result.redchi),
        "plot": plot,
    }
