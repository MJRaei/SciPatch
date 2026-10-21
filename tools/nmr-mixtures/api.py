"""Quantify chemical mixtures from 1H NMR spectra (MixSense).

Wraps the analysis scripts of MixSense (github.com/jdsanc/MixSense): deconvolution
of a mixture spectrum into reference spectra of its components by Wasserstein
distance (a SciPy port of Magnetstein, Domżał et al., Anal. Chem. 2024), mole
fractions across a reaction's time points, and 1H spectrum prediction from SMILES
with NMRdb.org's SPINUS predictor and nmrsim. MixSense's agent workflows, product
prediction (a Hugging Face service), and image digitizer are not used.

Spectra are two-column text files (ppm, intensity): CSV, or tab-separated .xy/.tsv.
"""

from __future__ import annotations

import contextlib
import csv
import functools
import importlib
import io
import math
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Literal

import numpy as np

#: Fit quality by Wasserstein distance, as MixSense reports it.
GOOD_FIT = 0.05
ACCEPTABLE_FIT = 0.15
#: nmrsim's full quantum simulation handles about this many coupled protons.
MAX_COUPLED_PROTONS = 11


@functools.cache
def _script(skill: str, module: str) -> ModuleType:
    """A MixSense script, imported from the pinned source checkout."""
    folder = str(Path(os.environ["MOTEL_SOURCE_DIR"]) / ".agents" / "skills" / skill / "scripts")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    return importlib.import_module(module)


def _load(path: str, baseline_correct: bool) -> np.ndarray:
    deconvolve = _script("nmr-analysis", "deconvolve")
    if not Path(path).is_file():
        raise ValueError(f"Spectrum file not found: {path}")
    try:
        spectrum = deconvolve.load_xy(path)
    except ValueError as exc:
        raise ValueError(f"{path}: expected two numeric columns, ppm and intensity.") from exc
    if len(spectrum) < 2:
        raise ValueError(f"{path}: a spectrum needs at least two points.")
    return deconvolve.baseline_correct(spectrum) if baseline_correct else spectrum


def _fit_label(distance: float) -> str:
    if distance < GOOD_FIT:
        return "good"
    return "acceptable" if distance < ACCEPTABLE_FIT else "poor"


def _check_components(
    components: list[str], protons: list[int], names: list[str] | None
) -> list[str]:
    if not components:
        raise ValueError("Give at least one reference spectrum in components.")
    if len(protons) != len(components):
        raise ValueError(
            "protons needs one count per component (1H atoms per molecule), "
            f"got {len(protons)} for {len(components)} components."
        )
    if any(count < 1 for count in protons):
        raise ValueError("Each component needs at least one proton to be seen by 1H NMR.")
    if names is not None and len(names) != len(components):
        raise ValueError(f"names needs one name per component, got {len(names)}.")
    return names or [Path(path).stem for path in components]


def _deconvolve(
    mixture: np.ndarray, references: list[np.ndarray], protons: list[int], kappa: float
) -> dict:
    result = _script("nmr-analysis", "deconvolve").deconvolve_spectra(
        mixture, references, protons, kappa=kappa
    )
    if math.isnan(result["wasserstein_distance"]):
        raise ValueError(
            "The deconvolution did not converge; check that the files are spectra on a "
            "ppm axis with positive intensities."
        )
    return result


def quantify_mixture(
    mixture: str,
    components: list[str],
    protons: list[int],
    names: list[str] | None = None,
    baseline_correct: bool = False,
    kappa: float = 0.25,
    plot: str = "deconvolution.png",
) -> dict:
    """Mole fractions of known components in a mixture, from 1H NMR spectra.

    The mixture spectrum is explained as a combination of the components' reference
    spectra (measured or predicted), allowing peaks to shift slightly; peak areas
    are converted to mole fractions with each molecule's number of protons.

    Args:
        mixture: Spectrum of the mixture (ppm, intensity).
        components: Reference spectrum of each component, same format.
        protons: Number of 1H atoms per molecule of each component (e.g. 18 for
            borneol, C10H18O); sets the conversion from areas to mole fractions.
        names: A name for each component (default: the file names).
        baseline_correct: Shift each spectrum so its lowest intensity is 0 (use for
            digitized or predicted spectra).
        kappa: Denoising penalty, in ppm: the largest shift at which mixture signal
            is still matched to a component rather than counted as unexplained.
        plot: PNG file for the diagnostic plot (an SVG is written next to it).

    Returns:
        Mole fractions per component (summing to 1), the Wasserstein distance with a
        fit label (good < 0.05, acceptable < 0.15, poor), the fraction of the
        mixture's signal that no component explains, and the plot's path.
    """
    labels = _check_components(components, protons, names)
    mix = _load(mixture, baseline_correct)
    references = [_load(path, baseline_correct) for path in components]
    result = _deconvolve(mix, references, protons, kappa)
    fractions = [float(value) for value in result["proportions"]]
    distance = float(result["wasserstein_distance"])
    _script("nmr-analysis", "plot").plot_deconvolution(
        mix, references, labels, fractions, distance, Path(plot)
    )
    return {
        "mole_fractions": dict(zip(labels, fractions, strict=True)),
        "wasserstein_distance": distance,
        "fit": _fit_label(distance),
        "unexplained_signal": float(result["noise"]),
        "plot": plot,
    }


def reaction_kinetics(
    spectra: list[str],
    times: list[float],
    components: list[str],
    protons: list[int],
    names: list[str] | None = None,
    time_unit: Literal["s", "min", "h"] = "min",
    baseline_correct: bool = False,
    kappa: float = 0.25,
    table: str = "kinetics.csv",
    plot: str = "kinetics.png",
) -> dict:
    """Mole fractions of known components over a reaction, from 1H NMR spectra at time points.

    Each spectrum is quantified as in quantify_mixture against the same references.

    Args:
        spectra: Mixture spectrum at each time point (ppm, intensity).
        times: Time of each spectrum, in time_unit.
        components: Reference spectrum of each component.
        protons: Number of 1H atoms per molecule of each component.
        names: A name for each component (default: the file names).
        time_unit: Unit of times: "s", "min", or "h".
        baseline_correct: Shift each spectrum so its lowest intensity is 0.
        kappa: Denoising penalty in ppm (see quantify_mixture).
        table: CSV file for the mole fractions over time.
        plot: PNG file for the mole fractions and fit quality over time.

    Returns:
        The times and, per component, its mole fraction at each time; the Wasserstein
        distance and fit label at each time; and the paths of the table and plot.
    """
    if len(times) != len(spectra):
        raise ValueError(
            f"times needs one value per spectrum, got {len(times)} for {len(spectra)}."
        )
    labels = _check_components(components, protons, names)
    references = [_load(path, baseline_correct) for path in components]
    fractions: list[dict[str, float]] = []
    distances: list[float] = []
    for time, path in zip(times, spectra, strict=True):
        result = _deconvolve(_load(path, baseline_correct), references, protons, kappa)
        fractions.append(dict(zip(labels, map(float, result["proportions"]), strict=True)))
        distances.append(float(result["wasserstein_distance"]))
        shares = "  ".join(f"{name}={fractions[-1][name]:.3f}" for name in labels)
        print(f"t = {time:g} {time_unit}: {shares}", flush=True)
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([f"time_{time_unit}", *labels, "wasserstein_distance"])
        for time, shares, distance in zip(times, fractions, distances, strict=True):
            writer.writerow([time, *(shares[name] for name in labels), distance])
    _script("nmr-analysis", "kinetics").save_kinetics_plot(
        times, time_unit, labels, fractions, distances, Path(plot)
    )
    return {
        "times": times,
        "mole_fractions": {name: [shares[name] for shares in fractions] for name in labels},
        "wasserstein_distance": distances,
        "fit": [_fit_label(distance) for distance in distances],
        "table": table,
        "plot": plot,
    }


def predict_spectrum(
    smiles: str,
    name: str | None = None,
    field_mhz: float = 400.0,
    linewidth_hz: float = 1.0,
    points: int = 8192,
) -> dict:
    """Predict a 1H NMR spectrum and signal list from SMILES (needs an internet connection).

    Chemical shifts and couplings come from NMRdb.org's SPINUS neural network; the
    spectrum is simulated with nmrsim, quantum-mechanically for up to 11 coupled
    protons and as single lines without splitting for larger molecules. Use the
    spectrum as a component reference in quantify_mixture.

    Args:
        smiles: Molecule as SMILES.
        name: File name stem for the outputs (default: derived from the SMILES).
        field_mhz: Spectrometer frequency in MHz; match the measured spectrum.
        linewidth_hz: Line width (full width at half maximum) in Hz.
        points: Number of points of the simulated spectrum.

    Returns:
        The number of protons, the signals (shift in ppm, number of protons,
        multiplicity, couplings in Hz), whether the multiplets were simulated, and
        the path of the spectrum file (.xy: ppm, intensity).
    """
    from rdkit import Chem

    predict = _script("nmr-predict", "predict_nmr")
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise ValueError(f"{smiles!r} is not valid SMILES.")
    hydrogens = sum(atom.GetTotalNumHs() for atom in molecule.GetAtoms())
    if hydrogens == 0:
        raise ValueError(f"{smiles} has no hydrogen atoms, so it has no 1H NMR spectrum.")
    atoms = predict.fetch_spinus(smiles)
    if not atoms:
        raise ValueError(f"NMRdb.org returned no prediction for {smiles}.")
    signals = predict.group_signals(atoms)
    coupled = len(atoms) <= MAX_COUPLED_PROTONS
    if coupled:
        with contextlib.redirect_stdout(io.StringIO()):  # nmrsim prints debugging lines
            ppm, intensity = predict.simulate_spectrum(
                atoms, field_mhz=field_mhz, n_points=points, linewidth_hz=linewidth_hz
            )
    else:
        # A full spin simulation needs 2^N states: one line per proton instead, as
        # MixSense does when nmrsim fails.
        ppm = np.linspace(-0.5, 12.0, points)
        half_width = linewidth_hz / 2
        intensity = sum(
            half_width**2 / (((ppm - atom["shift_ppm"]) * field_mhz) ** 2 + half_width**2)
            for atom in atoms
        )
        intensity = intensity / intensity.max()
    stem = name or re.sub(r"[^\w\-]", "_", smiles)[:40]
    path = f"{stem}.xy"
    predict.save_spectrum_xy(ppm, intensity, Path(path))
    return {
        "smiles": smiles,
        "protons": len(atoms),
        "signals": [
            {
                "shift_ppm": signal["shift_ppm"],
                "protons": signal["nH"],
                "multiplicity": signal["multiplicity"],
                "couplings_hz": signal["J_Hz"],
            }
            for signal in signals
        ],
        "multiplets_simulated": coupled,
        "spectrum": path,
    }
