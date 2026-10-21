"""Make the synthetic mixtures of the golden tests from the reference spectra here.

borneol.csv, isoborneol.csv, and crude.csv are MixSense's example spectra
(.agents/skills/nmr-analysis/examples/deconvolution at commit ce86a80).
ethyl_acetate.xy and ethanol.xy were predicted with this tool's predict_spectrum
(SPINUS, 400 MHz, 1 Hz lines); SPINUS leaves out ethanol's OH, so the ethanol
spectrum has 5 protons and ethyl acetate's 8.

A mixture is the sum of the reference spectra, each normalized to unit area and
weighted by its share of the area: for mole fractions x, that share is
x * protons / sum(x * protons). Run with: python make_data.py
"""

from pathlib import Path

import numpy as np

HERE = Path(__file__).parent


def spectrum(name: str) -> np.ndarray:
    delimiter = "\t" if name.endswith(".xy") else ","
    data = np.loadtxt(HERE / name, delimiter=delimiter, usecols=[0, 1])
    data[:, 1] = np.clip(data[:, 1], 0, None)
    data[:, 1] /= data[:, 1].sum()
    return data


def mixture(parts: list[tuple[str, float, int]], output: str) -> None:
    """Write a mixture of (file, mole fraction, protons) parts, all points of each."""
    areas = np.array([fraction * protons for _, fraction, protons in parts])
    areas /= areas.sum()
    rows = [
        np.column_stack([data[:, 0], area * data[:, 1]])
        for (name, _, _), area in zip(parts, areas, strict=True)
        for data in [spectrum(name)]
    ]
    combined = np.vstack(rows)
    combined = combined[np.argsort(combined[:, 0])]
    np.savetxt(HERE / output, combined, delimiter=",", fmt="%.10g")


mixture([("borneol.csv", 0.3, 18), ("isoborneol.csv", 0.7, 18)], "borneol30_isoborneol70.csv")
mixture([("borneol.csv", 0.9, 18), ("isoborneol.csv", 0.1, 18)], "t00min.csv")
mixture([("borneol.csv", 0.4, 18), ("isoborneol.csv", 0.6, 18)], "t30min.csv")
mixture([("ethyl_acetate.xy", 0.25, 8), ("ethanol.xy", 0.75, 5)], "etoac25_etoh75.csv")
