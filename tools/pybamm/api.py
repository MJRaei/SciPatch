"""Lithium-ion battery cells with PyBaMM: discharge curves, rate capability, and experiments.

Physics-based models (Doyle-Fuller-Newman, single-particle with electrolyte) with
published parameter sets for real cells, e.g. Chen2020: the LG M50 21700 cell (NMC811
and graphite-SiOx, 5 Ah) measured by Chen et al. (2020).
"""

from __future__ import annotations

import csv
import functools
import re
import warnings
from typing import Any, Literal

import numpy as np

Model = Literal["DFN", "SPMe", "SPM"]
Thermal = Literal["isothermal", "lumped"]


@functools.cache
def _pybamm() -> Any:
    warnings.filterwarnings("ignore")
    import pybamm

    pybamm.set_logging_level("ERROR")
    return pybamm


def _parameters(parameter_set: str, temperature_c: float) -> Any:
    pybamm = _pybamm()
    if parameter_set not in pybamm.parameter_sets:
        raise ValueError(
            f"Unknown parameter set {parameter_set!r}; choose one of "
            f"{', '.join(sorted(pybamm.parameter_sets))} (see parameter_sets)."
        )
    values = pybamm.ParameterValues(parameter_set)
    kelvin = temperature_c + 273.15
    values.update({"Ambient temperature [K]": kelvin, "Initial temperature [K]": kelvin})
    return values


def _model(model: str, thermal: str) -> Any:
    pybamm = _pybamm()
    options = {"thermal": thermal} if thermal != "isothermal" else {}
    return {
        "DFN": pybamm.lithium_ion.DFN,
        "SPMe": pybamm.lithium_ion.SPMe,
        "SPM": pybamm.lithium_ion.SPM,
    }[model](options=options)


def _solve(
    steps: list[str], model: str, parameter_set: str, temperature_c: float, thermal: str, soc: float
) -> tuple[Any, Any]:
    pybamm = _pybamm()
    values = _parameters(parameter_set, temperature_c)
    try:
        experiment = pybamm.Experiment(steps)
    except Exception as exc:
        raise ValueError(f"Could not read the experiment steps: {exc}") from exc
    simulation = pybamm.Simulation(
        _model(model, thermal), parameter_values=values, experiment=experiment
    )
    return simulation.solve(initial_soc=soc), values


def _series(solution: Any) -> dict[str, np.ndarray]:
    series = {
        "time_h": solution["Time [h]"].entries,
        "voltage_v": solution["Voltage [V]"].entries,
        "current_a": solution["Current [A]"].entries,
        "discharge_capacity_ah": solution["Discharge capacity [A.h]"].entries,
    }
    temperature = solution["X-averaged cell temperature [K]"].entries
    series["temperature_c"] = np.asarray(temperature) - 273.15
    return series


def _energy_wh(series: dict[str, np.ndarray]) -> float:
    """Energy delivered (positive for discharge) by integrating voltage x current."""
    power = series["voltage_v"] * series["current_a"]
    return float(np.sum((power[1:] + power[:-1]) / 2 * np.diff(series["time_h"])))


def _write(series: dict[str, np.ndarray], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(series))
        writer.writerows(zip(*(np.round(values, 6) for values in series.values()), strict=True))


def _plot(curves: list[tuple[str, dict[str, np.ndarray]]], x: str, path: str, xlabel: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(6.5, 4))
    for label, series in curves:
        axes.plot(series[x], series["voltage_v"], label=label)
    axes.set(xlabel=xlabel, ylabel="Voltage (V)")
    if len(curves) > 1:
        axes.legend(fontsize=8)
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def discharge(
    c_rate: float = 1.0,
    model: Model = "DFN",
    parameter_set: str = "Chen2020",
    temperature_c: float = 25.0,
    thermal: Thermal = "isothermal",
    cutoff_v: float | None = None,
    table: str = "discharge.csv",
    plot: str = "discharge.png",
) -> dict:
    """Constant-current discharge of a fully charged cell: capacity, energy, and voltage curve.

    Args:
        c_rate: Discharge current as a C-rate (1 = the nominal capacity in one hour).
        model: "DFN" (Doyle-Fuller-Newman, most complete), "SPMe" (single particle
            with electrolyte, faster), or "SPM" (single particle, low rates only).
        parameter_set: Published cell parameters, e.g. "Chen2020" (LG M50 21700);
            see parameter_sets.
        temperature_c: Ambient and initial temperature in °C.
        thermal: "isothermal", or "lumped" to let the cell heat up.
        cutoff_v: Discharge end voltage in V (default: the parameter set's).
        table: CSV file for time, voltage, current, capacity, and temperature.
        plot: PNG file for voltage versus capacity.

    Returns:
        Capacity in Ah and energy in Wh delivered to the cut-off, average voltage,
        duration, initial and final voltage, maximum temperature, and file paths.
    """
    if c_rate <= 0:
        raise ValueError("c_rate must be positive.")
    values = _parameters(parameter_set, temperature_c)
    cutoff = cutoff_v if cutoff_v is not None else values["Lower voltage cut-off [V]"]
    solution, _ = _solve(
        [f"Discharge at {c_rate}C until {cutoff} V"],
        model,
        parameter_set,
        temperature_c,
        thermal,
        1.0,
    )
    series = _series(solution)
    capacity = float(series["discharge_capacity_ah"][-1] - series["discharge_capacity_ah"][0])
    energy = _energy_wh(series)
    _write(series, table)
    _plot([(f"{c_rate}C", series)], "discharge_capacity_ah", plot, "Discharge capacity (Ah)")
    return {
        "capacity_ah": round(capacity, 5),
        "energy_wh": round(energy, 4),
        "average_voltage_v": round(energy / capacity, 4) if capacity else None,
        "duration_h": round(float(series["time_h"][-1] - series["time_h"][0]), 4),
        "initial_voltage_v": round(float(series["voltage_v"][0]), 4),
        "final_voltage_v": round(float(series["voltage_v"][-1]), 4),
        "max_temperature_c": round(float(np.max(series["temperature_c"])), 2),
        "nominal_capacity_ah": float(values["Nominal cell capacity [A.h]"]),
        "table": table,
        "plot": plot,
    }


def rate_capability(
    c_rates: list[float] | None = None,
    model: Model = "DFN",
    parameter_set: str = "Chen2020",
    temperature_c: float = 25.0,
    thermal: Thermal = "isothermal",
    plot: str = "rate_capability.png",
) -> dict:
    """Capacity and energy at several discharge rates, and the voltage curves.

    Args:
        c_rates: Discharge C-rates (default 0.2, 0.5, 1, 2, 3).
        model: "DFN", "SPMe", or "SPM" (see discharge).
        parameter_set: Published cell parameters; see parameter_sets.
        temperature_c: Ambient and initial temperature in °C.
        thermal: "isothermal", or "lumped" to let the cell heat up.
        plot: PNG file with the voltage curves at each rate.

    Returns:
        Per rate: capacity (Ah), energy (Wh), and capacity relative to the lowest
        rate; and the plot path.
    """
    rates = sorted(c_rates or [0.2, 0.5, 1.0, 2.0, 3.0])
    if not rates or rates[0] <= 0:
        raise ValueError("c_rates must be positive.")
    values = _parameters(parameter_set, temperature_c)
    cutoff = values["Lower voltage cut-off [V]"]
    rows, curves = [], []
    for rate in rates:
        solution, _ = _solve(
            [f"Discharge at {rate}C until {cutoff} V"],
            model,
            parameter_set,
            temperature_c,
            thermal,
            1.0,
        )
        series = _series(solution)
        capacity = float(series["discharge_capacity_ah"][-1] - series["discharge_capacity_ah"][0])
        rows.append(
            {
                "c_rate": rate,
                "capacity_ah": round(capacity, 5),
                "energy_wh": round(_energy_wh(series), 4),
            }
        )
        curves.append((f"{rate}C", series))
        print(f"{rate}C: {capacity:.4f} Ah", flush=True)
    for row in rows:
        row["relative_capacity"] = round(row["capacity_ah"] / rows[0]["capacity_ah"], 5)
    _plot(curves, "discharge_capacity_ah", plot, "Discharge capacity (Ah)")
    return {"rates": rows, "plot": plot}


def run_experiment(
    steps: list[str],
    cycles: int = 1,
    model: Model = "DFN",
    parameter_set: str = "Chen2020",
    temperature_c: float = 25.0,
    thermal: Thermal = "isothermal",
    initial_soc: float = 1.0,
    table: str = "experiment.csv",
    plot: str = "experiment.png",
) -> dict:
    """Run a cycling protocol written as steps, e.g. CC-CV charge then discharge.

    Steps use PyBaMM's experiment language: "Discharge at 1C until 2.5 V",
    "Charge at 0.5C until 4.2 V", "Hold at 4.2 V until C/50", "Rest for 1 hour",
    "Discharge at 2 W for 10 minutes", "Charge at 1 A until 4.1 V".

    Args:
        steps: The steps of one cycle, in order.
        cycles: How many times to repeat them.
        model: "DFN", "SPMe", or "SPM" (see discharge).
        parameter_set: Published cell parameters; see parameter_sets.
        temperature_c: Ambient and initial temperature in °C.
        thermal: "isothermal", or "lumped" to let the cell heat up.
        initial_soc: State of charge at the start, 0 to 1.
        table: CSV file for the time series.
        plot: PNG file for voltage versus time.

    Returns:
        For each step: what it was, its duration in hours, the charge passed in Ah
        (positive when discharging), the energy in Wh, and the end voltage; the
        final voltage; and the file paths.
    """
    if not steps or cycles < 1:
        raise ValueError("Give at least one step and one cycle.")
    if not 0 <= initial_soc <= 1:
        raise ValueError("initial_soc must be between 0 and 1.")
    solution, _ = _solve(steps * cycles, model, parameter_set, temperature_c, thermal, initial_soc)
    done = [step for cycle in solution.cycles for step in cycle.steps]
    results = []
    for text, step in zip(steps * cycles, done, strict=False):  # stops early at a cut-off
        series = _series(step)
        capacity = series["discharge_capacity_ah"]
        results.append(
            {
                "step": text,
                "duration_h": round(float(series["time_h"][-1] - series["time_h"][0]), 5),
                "charge_ah": round(float(capacity[-1] - capacity[0]), 5),
                "energy_wh": round(_energy_wh(series), 4),
                "end_voltage_v": round(float(series["voltage_v"][-1]), 4),
            }
        )
    series = _series(solution)
    _write(series, table)
    _plot([("", series)], "time_h", plot, "Time (h)")
    return {
        "steps": results,
        "final_voltage_v": round(float(series["voltage_v"][-1]), 4),
        "table": table,
        "plot": plot,
    }


def parameter_sets() -> dict:
    """Published lithium-ion parameter sets available, with what each describes.

    Returns:
        For each parameter set: the first lines of its description (cell, chemistry,
        and source).
    """
    pybamm = _pybamm()
    described = {}
    for name in sorted(pybamm.parameter_sets):
        try:
            text = pybamm.parameter_sets.get_docstring(name)
        except Exception:
            text = ""
        text = re.sub(r":footcite:t?:`([^`]*)`", r"\1", text)
        described[name] = " ".join(text.split("\n\n")[0].split())[:400]
    return {"parameter_sets": described}
