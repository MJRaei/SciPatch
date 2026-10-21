"""Electrochemical impedance spectroscopy (EIS) with impedance.py.

Fit equivalent circuits (resistors, capacitors, constant-phase elements, Warburg
diffusion, Gerischer and transmission-line elements) to measured impedance
spectra, simulate spectra of a circuit, and check data quality with the
Kramers-Kronig (Lin-KK) test. Impedance uses Z = Z' + jZ'', with Z'' negative for
capacitive behaviour.
"""

from __future__ import annotations

import contextlib
import csv
import functools
import io
import math
import warnings
from pathlib import Path
from typing import Literal

import numpy as np

#: Common circuits by name (parameter order follows the circuit string).
PRESETS = {
    "randles": "R0-p(R1,C1)",
    "randles-cpe": "R0-p(R1,CPE1)",
    "randles-warburg": "R0-p(R1-W1,CPE1)",
    "two-arcs": "R0-p(R1,CPE1)-p(R2,CPE2)",
}
Instrument = Literal[
    "csv",
    "gamry",
    "autolab",
    "biologic",
    "parstat",
    "zplot",
    "versastudio",
    "powersuite",
    "chinstruments",
]


@functools.cache
def _quiet() -> None:
    warnings.filterwarnings("ignore")
    # impedance 1.7.1 evaluates circuit strings that, under NumPy 2, contain
    # "np.float64(...)"; make np resolvable there.
    from impedance.models.circuits.elements import circuit_elements

    circuit_elements.setdefault("np", np)


def _load(data: str, instrument: Instrument, drop_inductive: bool) -> tuple[np.ndarray, np.ndarray]:
    _quiet()
    from impedance import preprocessing

    path = Path(data)
    if not path.is_file():
        raise ValueError(f"Data file {data!r} not found.")
    if instrument == "csv":
        rows = []
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = [
                    p for p in line.replace(";", ",").replace("\t", ",").split(",") if p.strip()
                ]
                try:
                    rows.append([float(p) for p in parts[:3]])
                except ValueError:
                    continue  # header or comment line
        rows = [r for r in rows if len(r) == 3]
        if len(rows) < 5:
            raise ValueError("Expected at least 5 rows of frequency_hz, z_real_ohm, z_imag_ohm.")
        array = np.array(rows)
        frequencies, impedance = array[:, 0], array[:, 1] + 1j * array[:, 2]
    else:
        frequencies, impedance = preprocessing.readFile(str(path), instrument=instrument)
    order = np.argsort(frequencies)[::-1]
    frequencies, impedance = frequencies[order], impedance[order]
    if drop_inductive:
        frequencies, impedance = preprocessing.ignoreBelowX(frequencies, impedance)
    if len(frequencies) < 5:
        raise ValueError("Fewer than 5 points remain (inductive points removed).")
    return frequencies, impedance


def _circuit_string(circuit: str) -> str:
    return PRESETS.get(circuit, circuit)


def _parameter_names(circuit: str) -> list[str]:
    _quiet()
    from impedance.models.circuits import CustomCircuit
    from impedance.models.circuits.fitting import calculateCircuitLength

    try:
        count = calculateCircuitLength(circuit)
        return CustomCircuit(circuit, initial_guess=[1.0] * count).get_param_names()[0]
    except Exception as exc:
        raise ValueError(f"Cannot read the circuit {circuit!r}: {exc}") from exc


def _guess(names: list[str], frequencies: np.ndarray, impedance: np.ndarray) -> list[float]:
    """Order-of-magnitude starting values from the spectrum (high-frequency intercept,
    arc width, and the frequency of the arc's top)."""
    real, imag = impedance.real, -impedance.imag
    r0 = max(float(real.min()), 1e-6)
    arcs = sum(1 for n in names if n.startswith(("C", "CPE")) and not n.endswith("_1"))
    width = max(float(real.max()) - r0, 1e-6) / max(arcs, 1)
    omega = 2 * math.pi * float(frequencies[int(np.argmax(imag))])
    guesses = []
    for name in names:
        if name == "R0" or (name.startswith("R") and name == names[0]):
            guesses.append(r0)
        elif name.startswith("R"):
            guesses.append(width)
        elif name.startswith("CPE") and name.endswith("_1"):
            guesses.append(0.9)
        elif name.startswith(("C", "CPE")):
            guesses.append(1 / (omega * width))
        elif name.startswith("W") and "_" not in name:
            guesses.append(width / 10)
        elif name.startswith(("Wo", "Ws")):
            guesses.append(width if name.endswith("_0") else 1.0)
        elif name.startswith("L"):
            guesses.append(1e-6)
        else:
            guesses.append(1.0)
    return guesses


def fit_circuit(
    data: str,
    circuit: str = "randles-cpe",
    initial_guess: list[float] | None = None,
    instrument: Instrument = "csv",
    drop_inductive: bool = True,
    global_fit: bool = False,
    table: str = "fit.csv",
    plot: str = "fit.png",
) -> dict:
    """Fit an equivalent circuit to an impedance spectrum.

    Args:
        data: Spectrum file. For "csv": columns frequency (Hz), Z' (Ohm), Z'' (Ohm,
            negative when capacitive), header lines ignored. Other instruments use
            their native export formats.
        circuit: A preset ("randles" R0-p(R1,C1), "randles-cpe" R0-p(R1,CPE1),
            "randles-warburg" R0-p(R1-W1,CPE1), "two-arcs"
            R0-p(R1,CPE1)-p(R2,CPE2)) or a circuit string with elements R, C, L,
            CPE, W, Wo, Ws, G, Gs, Zarc, TLMQ, T joined in series ("-") and
            parallel ("p(...,...)"); see elements().
        initial_guess: Starting values in parameter order (default: estimated
            from the spectrum).
        instrument: File format: "csv", "gamry", "autolab", "biologic", "parstat",
            "zplot", "versastudio", "powersuite", or "chinstruments".
        drop_inductive: Remove points with Z'' > 0 (inductive, usually cables).
        global_fit: Use basin-hopping global optimization (slower; for poor
            starting values).
        table: CSV with the data and the fitted spectrum.
        plot: PNG with Nyquist and Bode plots of data and fit.

    Returns:
        Each parameter with its value, standard error, and unit; the RMS of the
        residuals in Ohm and relative to |Z|; the frequency range used; and the
        file paths.
    """
    _quiet()
    from impedance.models.circuits import CustomCircuit

    string = _circuit_string(circuit)
    names = _parameter_names(string)
    frequencies, impedance = _load(data, instrument, drop_inductive)
    guess = initial_guess or _guess(names, frequencies, impedance)
    if len(guess) != len(names):
        raise ValueError(
            f"The circuit has {len(names)} parameters ({', '.join(names)}); "
            f"got {len(guess)} guesses."
        )
    model = CustomCircuit(string, initial_guess=list(guess))
    try:
        model.fit(frequencies, impedance, global_opt=global_fit)
    except Exception as exc:
        raise ValueError(
            f"The fit did not converge: {exc}; try initial_guess or global_fit."
        ) from exc
    fitted = model.predict(frequencies)
    _, units = model.get_param_names()
    errors = model.conf_ if model.conf_ is not None else [None] * len(names)
    parameters = [
        {
            "name": name,
            "value": float(f"{value:.6g}"),
            "std_error": None if error is None or not np.isfinite(error) else float(f"{error:.3g}"),
            "unit": unit,
        }
        for name, value, error, unit in zip(names, model.parameters_, errors, units, strict=True)
    ]
    residual = np.abs(fitted - impedance)
    _write(table, frequencies, impedance, fitted)
    _plot(frequencies, impedance, fitted, string, plot)
    return {
        "circuit": string,
        "parameters": parameters,
        "rms_residual_ohm": float(f"{np.sqrt(np.mean(residual**2)):.4g}"),
        "rms_relative_residual": float(
            f"{np.sqrt(np.mean((residual / np.abs(impedance)) ** 2)):.4g}"
        ),
        "points": len(frequencies),
        "frequency_range_hz": [float(frequencies.min()), float(frequencies.max())],
        "table": table,
        "plot": plot,
    }


def _write(path: str, frequencies, data, model) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        header = ["frequency_hz", "z_real_ohm", "z_imag_ohm"]
        writer.writerow(header + (["fit_real_ohm", "fit_imag_ohm"] if model is not None else []))
        for index, f in enumerate(frequencies):
            row = [f"{f:.6g}", f"{data[index].real:.6g}", f"{data[index].imag:.6g}"]
            if model is not None:
                row += [f"{model[index].real:.6g}", f"{model[index].imag:.6g}"]
            writer.writerow(row)


def _plot(frequencies, data, model, title: str, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, (nyquist, bode) = plt.subplots(1, 2, figsize=(10, 4))
    if data is not None:
        nyquist.plot(data.real, -data.imag, "o", markersize=3, label="data")
        bode.loglog(frequencies, np.abs(data), "o", markersize=3, label="|Z| data")
    if model is not None:
        nyquist.plot(model.real, -model.imag, "-", label="model")
        bode.loglog(frequencies, np.abs(model), "-", label="|Z| model")
    nyquist.set(xlabel="Z' (Ω)", ylabel="-Z'' (Ω)", title=title)
    nyquist.set_aspect("equal", adjustable="datalim")
    nyquist.legend()
    bode.set(xlabel="Frequency (Hz)", ylabel="|Z| (Ω)")
    phase = bode.twinx()
    shown = data if data is not None else model
    phase.semilogx(frequencies, -np.degrees(np.angle(shown)), "k:", label="-phase")
    phase.set_ylabel("-Phase (°)")
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def simulate(
    circuit: str,
    parameters: list[float],
    f_min_hz: float = 0.01,
    f_max_hz: float = 1e5,
    points_per_decade: int = 10,
    table: str = "spectrum.csv",
    plot: str = "spectrum.png",
) -> dict:
    """Impedance spectrum of a circuit with given parameter values.

    Args:
        circuit: Preset name or circuit string (see fit_circuit).
        parameters: Values in parameter order (see elements() for units).
        f_min_hz: Lowest frequency in Hz.
        f_max_hz: Highest frequency in Hz.
        points_per_decade: Frequencies per decade (log-spaced).
        table: CSV of the spectrum (writable as fit_circuit input).
        plot: PNG with Nyquist and Bode plots.

    Returns:
        The parameter names, impedance at the lowest and highest frequency, the
        frequency of the largest -Z'' (arc top), and the file paths.
    """
    _quiet()
    from impedance.models.circuits import CustomCircuit

    string = _circuit_string(circuit)
    names = _parameter_names(string)
    if len(parameters) != len(names):
        raise ValueError(f"The circuit has {len(names)} parameters ({', '.join(names)}).")
    if not 0 < f_min_hz < f_max_hz:
        raise ValueError("Need 0 < f_min_hz < f_max_hz.")
    count = max(2, round(math.log10(f_max_hz / f_min_hz) * points_per_decade) + 1)
    frequencies = np.logspace(math.log10(f_max_hz), math.log10(f_min_hz), count)
    model = CustomCircuit(string, constants=dict(zip(names, parameters, strict=True)))
    impedance = model.predict(frequencies)
    _write(table, frequencies, impedance, None)
    _plot(frequencies, None, impedance, string, plot)
    top = int(np.argmax(-impedance.imag))
    return {
        "circuit": string,
        "parameter_names": names,
        "z_at_f_max_ohm": [float(f"{impedance[0].real:.8g}"), float(f"{impedance[0].imag:.8g}")],
        "z_at_f_min_ohm": [float(f"{impedance[-1].real:.8g}"), float(f"{impedance[-1].imag:.8g}")],
        "arc_top_frequency_hz": float(f"{frequencies[top]:.6g}"),
        "table": table,
        "plot": plot,
    }


def impedance_at(circuit: str, parameters: list[float], frequencies_hz: list[float]) -> dict:
    """Impedance of a circuit at chosen frequencies.

    Args:
        circuit: Preset name or circuit string.
        parameters: Values in parameter order.
        frequencies_hz: Frequencies in Hz.

    Returns:
        For each frequency: Z' and Z'' (Ohm), |Z| (Ohm), and phase (degrees).
    """
    _quiet()
    from impedance.models.circuits import CustomCircuit

    string = _circuit_string(circuit)
    names = _parameter_names(string)
    if len(parameters) != len(names):
        raise ValueError(f"The circuit has {len(names)} parameters ({', '.join(names)}).")
    model = CustomCircuit(string, constants=dict(zip(names, parameters, strict=True)))
    values = model.predict(np.asarray(frequencies_hz, dtype=float))
    return {
        "circuit": string,
        "points": [
            {
                "frequency_hz": f,
                "z_real_ohm": float(f"{z.real:.10g}"),
                "z_imag_ohm": float(f"{z.imag:.10g}"),
                "z_abs_ohm": float(f"{abs(z):.10g}"),
                "phase_deg": float(f"{math.degrees(math.atan2(z.imag, z.real)):.8g}"),
            }
            for f, z in zip(frequencies_hz, values, strict=True)
        ],
    }


def kramers_kronig(
    data: str,
    instrument: Instrument = "csv",
    drop_inductive: bool = True,
    max_frequency_hz: float | None = None,
) -> dict:
    """Lin-KK test of whether a spectrum is consistent with a linear, stable, causal system.

    Uses the settings of impedance.py's documentation (cutoff mu < 0.5, complex fit,
    with a series capacitance; M. Schönleber et al., Electrochim. Acta 131, 20 (2014)).

    Args:
        data: Spectrum file (see fit_circuit).
        instrument: File format.
        drop_inductive: Remove points with Z'' > 0 first.
        max_frequency_hz: Ignore frequencies above this (e.g. cable artefacts).

    Returns:
        The number of RC elements used, the overfitting measure mu, the largest
        real and imaginary residuals relative to |Z|, and whether all residuals
        are below 1% (a common acceptance level; drift, non-stationarity, or
        nonlinearity show as larger, systematic residuals).
    """
    _quiet()
    from impedance.validation import linKK

    frequencies, impedance = _load(data, instrument, drop_inductive)
    if max_frequency_hz is not None:
        keep = frequencies < max_frequency_hz
        frequencies, impedance = frequencies[keep], impedance[keep]
    with contextlib.redirect_stdout(io.StringIO()):  # linKK prints its progress
        elements, mu, _, real, imaginary = linKK(
            frequencies, impedance, c=0.5, max_M=100, fit_type="complex", add_cap=True
        )
    worst_real, worst_imag = float(np.max(np.abs(real))), float(np.max(np.abs(imaginary)))
    return {
        "rc_elements": int(elements),
        "mu": float(f"{mu:.4g}"),
        "max_real_residual": float(f"{worst_real:.4g}"),
        "max_imag_residual": float(f"{worst_imag:.4g}"),
        "valid_within_1_percent": bool(max(worst_real, worst_imag) < 0.01),
    }


def elements() -> dict:
    """Circuit elements available in circuit strings, with their parameters and units.

    Returns:
        For each element: description, number of parameters, and their units.
    """
    _quiet()
    from impedance.models.circuits.elements import circuit_elements

    rows = {}
    for name, function in circuit_elements.items():
        if not callable(function) or name in ("s", "p", "np", "K"):
            continue
        rows[name] = {
            "description": (function.__doc__ or "").strip().splitlines()[0],
            "parameters": getattr(function, "num_params", None),
            "units": getattr(function, "units", None),
        }
    return {"elements": rows, "presets": PRESETS}
