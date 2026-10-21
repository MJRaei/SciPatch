"""X-ray interactions with matter from xraylib.

Mass attenuation coefficients (photoelectric, Compton, Rayleigh, total) of
elements, chemical formulas, and NIST reference materials, transmission and
half-value layers, absorption-edge and emission-line energies with relative
intensities and fluorescence yields, and identification of X-ray fluorescence
peaks. Energies in keV, attenuation in cm2/g.
"""

from __future__ import annotations

import csv
import functools
import math

#: Lines reported for each element: xraylib macro name, Siegbahn label, IUPAC label.
LINES = [
    ("KL3_LINE", "Ka1", "K-L3"),
    ("KL2_LINE", "Ka2", "K-L2"),
    ("KM3_LINE", "Kb1", "K-M3"),
    ("KN3_LINE", "Kb2", "K-N3"),
    ("L3M5_LINE", "La1", "L3-M5"),
    ("L3M4_LINE", "La2", "L3-M4"),
    ("L2M4_LINE", "Lb1", "L2-M4"),
    ("L3N5_LINE", "Lb2", "L3-N5"),
    ("L2N4_LINE", "Lg1", "L2-N4"),
    ("M5N7_LINE", "Ma1", "M5-N7"),
]
SHELLS = ["K_SHELL", "L1_SHELL", "L2_SHELL", "L3_SHELL", "M1_SHELL", "M5_SHELL"]
HC_KEV_ANGSTROM = 12.398419843320026  # h c in keV Å (CODATA 2018)


@functools.cache
def _xrl():
    import xraylib

    return xraylib


def _call(function, *args) -> float | None:
    try:
        value = function(*args)
    except ValueError:
        return None
    return float(value) if value else None


def _material(material: str, density_g_cm3: float | None):
    """Return (label, kind, cross-section function, density)."""
    xrl = _xrl()
    text = material.strip()
    if text in xrl.GetCompoundDataNISTList():
        data = xrl.GetCompoundDataNISTByName(text)
        return (
            text,
            "NIST reference material",
            lambda name, e: getattr(xrl, f"{name}_CP")(text, e),
            (density_g_cm3 or data["density"]),
        )
    try:
        z = xrl.SymbolToAtomicNumber(text)
    except ValueError:
        z = 0
    if z:
        return (
            text,
            "element",
            lambda name, e: getattr(xrl, name)(z, e),
            (density_g_cm3 or xrl.ElementDensity(z)),
        )
    try:
        xrl.CompoundParser(text)
    except ValueError as exc:
        raise ValueError(
            f"{material!r} is not an element, a chemical formula, or a NIST material name "
            "(see materials())."
        ) from exc
    return text, "compound", lambda name, e: getattr(xrl, f"{name}_CP")(text, e), density_g_cm3


def attenuation(
    material: str,
    energies_kev: list[float] | None = None,
    density_g_cm3: float | None = None,
    thickness_cm: float | None = None,
    e_min_kev: float = 1.0,
    e_max_kev: float = 150.0,
    table: str = "attenuation.csv",
    plot: str = "attenuation.png",
) -> dict:
    """Mass attenuation of X-rays in a material, and transmission through a thickness.

    Args:
        material: Element symbol ("Pb"), chemical formula ("SiO2",
            "Ca5(PO4)3OH"), or NIST reference material ("Water, Liquid",
            "Bone, Cortical (ICRP)", "Polyethylene"; see materials()).
        energies_kev: Photon energies in keV to report (default 10, 20, 50, 100).
        density_g_cm3: Density for linear attenuation (default: the element's or
            the NIST material's; needed for formulas).
        thickness_cm: Thickness for the transmitted fraction.
        e_min_kev: Lowest energy of the plotted curve.
        e_max_kev: Highest energy of the plotted curve.
        table: CSV of the curve.
        plot: PNG of mass attenuation versus energy (log-log).

    Returns:
        At each energy: total, photoelectric, Compton (incoherent), and Rayleigh
        (coherent) mass attenuation coefficients (cm2/g); with a density, the linear
        attenuation coefficient (1/cm), half-value layer, and mean free path (cm);
        with a thickness, the transmitted fraction.
    """
    label, kind, cross_section, density = _material(material, density_g_cm3)
    rows = []
    for energy in energies_kev or [10.0, 20.0, 50.0, 100.0]:
        if energy <= 0:
            raise ValueError("Energies must be positive.")
        row = {
            "energy_kev": energy,
            "total_cm2_g": _round(cross_section("CS_Total", energy)),
            "photoelectric_cm2_g": _round(cross_section("CS_Photo", energy)),
            "compton_cm2_g": _round(cross_section("CS_Compt", energy)),
            "rayleigh_cm2_g": _round(cross_section("CS_Rayl", energy)),
        }
        if density:
            linear = row["total_cm2_g"] * density
            row["linear_attenuation_per_cm"] = _round(linear)
            row["half_value_layer_cm"] = _round(math.log(2) / linear)
            row["mean_free_path_cm"] = _round(1 / linear)
            if thickness_cm is not None:
                row["transmission"] = _round(math.exp(-linear * thickness_cm))
        rows.append(row)
    _curve(label, cross_section, e_min_kev, e_max_kev, table, plot)
    return {
        "material": label,
        "kind": kind,
        "density_g_cm3": density,
        "thickness_cm": thickness_cm,
        "energies": rows,
        "table": table,
        "plot": plot,
    }


def _round(value: float | None) -> float | None:
    return None if value is None else float(f"{value:.6g}")


def _curve(label, cross_section, e_min, e_max, table, plot) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    if not 0 < e_min < e_max:
        raise ValueError("Need 0 < e_min_kev < e_max_kev.")
    energies = np.geomspace(e_min, e_max, 400)
    series = {
        name: [cross_section(f"CS_{key}", float(e)) for e in energies]
        for name, key in (
            ("total", "Total"),
            ("photoelectric", "Photo"),
            ("compton", "Compt"),
            ("rayleigh", "Rayl"),
        )
    }
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["energy_kev", *[f"{name}_cm2_g" for name in series]])
        for index, energy in enumerate(energies):
            writer.writerow([round(float(energy), 5), *[f"{series[n][index]:.6g}" for n in series]])
    figure, axes = plt.subplots(figsize=(6.5, 4.5))
    for name, values in series.items():
        axes.loglog(energies, values, label=name, linewidth=2 if name == "total" else 1)
    axes.set(xlabel="Photon energy (keV)", ylabel="Mass attenuation (cm²/g)", title=label)
    axes.legend()
    figure.savefig(plot, dpi=150, bbox_inches="tight")
    plt.close(figure)


def element_xray_data(element: str) -> dict:
    """Absorption edges, emission lines, and fluorescence yields of an element.

    Args:
        element: Element symbol, e.g. "Cu".

    Returns:
        Atomic number and weight, density; edge energies (keV) and jump factors
        for the K, L1-L3, M1, and M5 shells; fluorescence yields; and the main
        emission lines (Siegbahn and IUPAC names) with energy (keV), wavelength
        (Å), and relative intensity within their shell.
    """
    xrl = _xrl()
    try:
        z = xrl.SymbolToAtomicNumber(element.strip())
    except ValueError as exc:
        raise ValueError(f"{element!r} is not an element symbol.") from exc
    edges = {}
    for shell in SHELLS:
        index = getattr(xrl, shell)
        energy = _call(xrl.EdgeEnergy, z, index)
        if energy:
            edges[shell.removesuffix("_SHELL")] = {
                "energy_kev": round(energy, 5),
                "jump_factor": _round(_call(xrl.JumpFactor, z, index)),
                "fluorescence_yield": _round(_call(xrl.FluorYield, z, index)),
            }
    lines = []
    for macro, siegbahn, iupac in LINES:
        index = getattr(xrl, macro)
        energy = _call(xrl.LineEnergy, z, index)
        if not energy:
            continue
        lines.append(
            {
                "line": siegbahn,
                "iupac": iupac,
                "energy_kev": round(energy, 5),
                "wavelength_angstrom": round(HC_KEV_ANGSTROM / energy, 6),
                "relative_intensity": _round(_call(xrl.RadRate, z, index)),
            }
        )
    return {
        "element": xrl.AtomicNumberToSymbol(z),
        "atomic_number": z,
        "atomic_weight": _round(xrl.AtomicWeight(z)),
        "density_g_cm3": _round(_call(xrl.ElementDensity, z)),
        "edges": edges,
        "lines": lines,
    }


def identify_peak(energy_kev: float, tolerance_kev: float = 0.05, max_candidates: int = 10) -> dict:
    """Candidate elements and lines for an X-ray fluorescence or EDS peak.

    Args:
        energy_kev: Peak energy in keV.
        tolerance_kev: Accept lines within this distance.
        max_candidates: Number of candidates to return.

    Returns:
        Candidate lines sorted by distance from the peak, each with element,
        line, energy, and relative intensity; check that the element's other
        strong lines are also present before assigning a peak.
    """
    xrl = _xrl()
    if energy_kev <= 0 or tolerance_kev <= 0:
        raise ValueError("energy_kev and tolerance_kev must be positive.")
    found = []
    for z in range(3, 99):
        for macro, siegbahn, iupac in LINES:
            energy = _call(xrl.LineEnergy, z, getattr(xrl, macro))
            if energy and abs(energy - energy_kev) <= tolerance_kev:
                found.append(
                    {
                        "element": xrl.AtomicNumberToSymbol(z),
                        "line": siegbahn,
                        "iupac": iupac,
                        "energy_kev": round(energy, 5),
                        "difference_kev": round(energy - energy_kev, 5),
                        "relative_intensity": _round(_call(xrl.RadRate, z, getattr(xrl, macro))),
                    }
                )
    found.sort(key=lambda row: abs(row["difference_kev"]))
    return {
        "energy_kev": energy_kev,
        "tolerance_kev": tolerance_kev,
        "candidates": found[:max_candidates],
    }


def materials() -> dict:
    """NIST reference materials available by name (with their densities).

    Returns:
        Material names and densities (g/cm3).
    """
    xrl = _xrl()
    return {
        "materials": {
            name: xrl.GetCompoundDataNISTByName(name)["density"]
            for name in xrl.GetCompoundDataNISTList()
        }
    }
