"""Thermophysical properties of fluids with CoolProp: reference equations of state.

About 120 pure fluids and refrigerants (water by IAPWS-95, CO2 by Span-Wagner,
R134a by Tillner-Roth and Baehr, ...), predefined refrigerant blends such as R410A,
mixtures written as "Nitrogen[0.79]&Oxygen[0.21]" (mole fractions), aqueous brines
such as "INCOMP::MEG-30%", and humid air. All values are in SI units: K, Pa,
kg/m3, J/kg, J/(kg K), Pa s, W/(m K).
"""

from __future__ import annotations

import csv
import functools
import math
from typing import Literal

INPUTS = {
    "temperature_k": "T",
    "pressure_pa": "P",
    "density_kg_m3": "D",
    "quality": "Q",
    "enthalpy_j_per_kg": "H",
    "entropy_j_per_kg_k": "S",
}
#: Output name -> CoolProp key; the last group is undefined inside the two-phase dome.
EQUILIBRIUM = {
    "temperature_k": "T",
    "pressure_pa": "P",
    "density_kg_m3": "D",
    "enthalpy_j_per_kg": "H",
    "entropy_j_per_kg_k": "S",
    "internal_energy_j_per_kg": "U",
}
SINGLE_PHASE = {
    "cp_j_per_kg_k": "Cpmass",
    "cv_j_per_kg_k": "Cvmass",
    "speed_of_sound_m_s": "A",
    "compressibility_factor": "Z",
    "viscosity_pa_s": "V",
    "thermal_conductivity_w_m_k": "L",
    "prandtl": "Prandtl",
}


@functools.cache
def _cp():
    import CoolProp.CoolProp as CP

    return CP


def _number(value: float) -> float | None:
    return float(f"{value:.10g}") if math.isfinite(value) else None


def _check_fluid(fluid: str) -> None:
    try:
        _cp().PropsSI("molar_mass", fluid)
    except ValueError as exc:
        if any(text in str(exc) for text in ("not a valid fluid", "is a valid fluid", "not found")):
            raise ValueError(
                f"Unknown fluid {fluid!r}; see fluids() for names and aliases, or write a "
                "mixture as 'Nitrogen[0.79]&Oxygen[0.21]'."
            ) from exc


def _props(keys: dict[str, str], fluid: str, inputs: list) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for name, key in keys.items():
        try:
            values[name] = _number(_cp().PropsSI(key, *inputs, fluid))
        except ValueError:
            values[name] = None  # e.g. no transport model for this fluid
    return values


def state(
    fluid: str,
    temperature_k: float | None = None,
    pressure_pa: float | None = None,
    density_kg_m3: float | None = None,
    quality: float | None = None,
    enthalpy_j_per_kg: float | None = None,
    entropy_j_per_kg_k: float | None = None,
) -> dict:
    """Properties of a fluid at a state fixed by exactly two inputs.

    Args:
        fluid: Fluid name or alias (e.g. "Water", "CO2", "R134a", "Air", "R410A"),
            a mixture "A[x]&B[y]" with mole fractions, or "INCOMP::<brine>".
        temperature_k: Temperature in K.
        pressure_pa: Pressure in Pa.
        density_kg_m3: Density in kg/m3.
        quality: Vapor mass fraction, 0 (saturated liquid) to 1 (saturated vapor).
        enthalpy_j_per_kg: Specific enthalpy in J/kg.
        entropy_j_per_kg_k: Specific entropy in J/(kg K).

    Returns:
        Phase, temperature, pressure, density, enthalpy, entropy, internal energy,
        quality (two-phase states only), heat capacities, speed of sound,
        compressibility factor, viscosity, thermal conductivity, and Prandtl
        number. Properties that are undefined (inside the two-phase dome) or have no
        model for the fluid are null.
    """
    given = {
        name: value
        for name, value in {
            "temperature_k": temperature_k,
            "pressure_pa": pressure_pa,
            "density_kg_m3": density_kg_m3,
            "quality": quality,
            "enthalpy_j_per_kg": enthalpy_j_per_kg,
            "entropy_j_per_kg_k": entropy_j_per_kg_k,
        }.items()
        if value is not None
    }
    if len(given) != 2:
        raise ValueError(f"Give exactly two inputs (got {', '.join(given) or 'none'}).")
    _check_fluid(fluid)
    inputs = [part for name, value in given.items() for part in (INPUTS[name], value)]
    CP = _cp()
    try:
        CP.PropsSI("T", *inputs, fluid)
    except ValueError as exc:
        raise ValueError(f"CoolProp could not find this state of {fluid}: {exc}") from exc
    values = _props(EQUILIBRIUM, fluid, inputs)
    try:
        phase = CP.PhaseSI(*inputs, fluid)
        vapor_fraction = CP.PropsSI("Q", *inputs, fluid)
    except ValueError:  # incompressible liquids have no vapor
        phase, vapor_fraction = "liquid", -1.0
    two_phase = 0 < vapor_fraction < 1
    if two_phase:
        phase = "two-phase"
    elif phase == "twophase":  # exactly on the saturation curve
        phase = "saturated vapor" if vapor_fraction >= 1 else "saturated liquid"
    result = {"fluid": fluid, "phase": phase, **values}
    result["quality"] = _number(vapor_fraction) if two_phase else None
    single = _props(SINGLE_PHASE, fluid, inputs)
    result.update({name: None if two_phase else value for name, value in single.items()})
    return result


def saturation(
    fluid: str, temperature_k: float | None = None, pressure_pa: float | None = None
) -> dict:
    """Saturated liquid and vapor at a temperature or a pressure.

    Args:
        fluid: A pure fluid or predefined blend (see fluids).
        temperature_k: Saturation temperature in K (give this or pressure_pa).
        pressure_pa: Saturation pressure in Pa.

    Returns:
        Saturation temperature and pressure; for the liquid and the vapor: density,
        enthalpy, entropy, heat capacity, viscosity, and thermal conductivity; the
        enthalpy of vaporization (J/kg) and the surface tension (N/m).
    """
    if (temperature_k is None) == (pressure_pa is None):
        raise ValueError("Give either temperature_k or pressure_pa.")
    _check_fluid(fluid)
    given = ["T", temperature_k] if temperature_k is not None else ["P", pressure_pa]
    keys = {
        "density_kg_m3": "D",
        "enthalpy_j_per_kg": "H",
        "entropy_j_per_kg_k": "S",
        "cp_j_per_kg_k": "Cpmass",
        "viscosity_pa_s": "V",
        "thermal_conductivity_w_m_k": "L",
    }
    try:
        liquid = _props(keys, fluid, [*given, "Q", 0])
        vapor = _props(keys, fluid, [*given, "Q", 1])
        common = _props({"temperature_k": "T", "pressure_pa": "P"}, fluid, [*given, "Q", 0])
    except ValueError as exc:
        raise ValueError(f"No saturation state of {fluid} there: {exc}") from exc
    if common["temperature_k"] is None or common["pressure_pa"] is None:
        raise ValueError(
            f"No saturation state of {fluid} there (outside triple point to critical point)."
        )
    surface = _props({"surface_tension_n_m": "I"}, fluid, [*given, "Q", 0])
    latent = (
        vapor["enthalpy_j_per_kg"] - liquid["enthalpy_j_per_kg"]
        if vapor["enthalpy_j_per_kg"] is not None and liquid["enthalpy_j_per_kg"] is not None
        else None
    )
    return {
        "fluid": fluid,
        **common,
        "liquid": liquid,
        "vapor": vapor,
        "enthalpy_of_vaporization_j_per_kg": None if latent is None else _number(latent),
        **surface,
    }


def isobar(
    fluid: str,
    pressure_pa: float,
    t_min_k: float,
    t_max_k: float,
    points: int = 60,
    table: str = "isobar.csv",
    plot: str = "isobar.png",
) -> dict:
    """Properties versus temperature at constant pressure, across any phase change.

    Args:
        fluid: Fluid name, alias, mixture, or brine (see state).
        pressure_pa: Pressure in Pa.
        t_min_k: Lowest temperature in K.
        t_max_k: Highest temperature in K.
        points: Number of temperatures.
        table: CSV file with every property at every temperature.
        plot: PNG with density, heat capacity, viscosity, and thermal conductivity.

    Returns:
        The phases met along the isobar, the saturation temperature at this
        pressure if it is crossed, and the file paths.
    """
    if not t_min_k < t_max_k or points < 2:
        raise ValueError("Need t_min_k < t_max_k and at least two points.")
    _check_fluid(fluid)
    rows = []
    for index in range(points):
        temperature = t_min_k + (t_max_k - t_min_k) * index / (points - 1)
        try:
            phase = _cp().PhaseSI("T", temperature, "P", pressure_pa, fluid)
        except ValueError:
            continue
        values = _props(
            {**EQUILIBRIUM, **SINGLE_PHASE}, fluid, ["T", temperature, "P", pressure_pa]
        )
        rows.append({"phase": phase, **values})
    if not rows:
        raise ValueError(f"CoolProp has no states of {fluid} along this isobar.")
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _plot_isobar(rows, f"{fluid} at {pressure_pa / 1e5:g} bar", plot)
    boiling = None
    phases = list(dict.fromkeys(row["phase"] for row in rows))
    if "liquid" in phases and "gas" in phases:
        boiling = _number(_cp().PropsSI("T", "P", pressure_pa, "Q", 0, fluid))
    return {
        "fluid": fluid,
        "pressure_pa": pressure_pa,
        "phases": phases,
        "saturation_temperature_k": boiling,
        "points": len(rows),
        "table": table,
        "plot": plot,
    }


def _plot_isobar(rows: list[dict], title: str, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    panels = [
        ("density_kg_m3", "Density (kg/m³)"),
        ("cp_j_per_kg_k", "cp (J/(kg K))"),
        ("viscosity_pa_s", "Viscosity (Pa s)"),
        ("thermal_conductivity_w_m_k", "Thermal conductivity (W/(m K))"),
    ]
    figure, axes = plt.subplots(2, 2, figsize=(8, 6), sharex=True)
    for axis, (key, label) in zip(axes.flat, panels, strict=True):
        points = [(row["temperature_k"], row[key]) for row in rows if row[key] is not None]
        if points:
            axis.plot(*zip(*points, strict=True), marker=".", markersize=3)
        axis.set_ylabel(label)
    for axis in axes[1]:
        axis.set_xlabel("Temperature (K)")
    figure.suptitle(title)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def diagram(fluid: str, kind: Literal["PH", "TS"] = "PH", plot: str = "diagram.png") -> dict:
    """Pressure-enthalpy or temperature-entropy diagram with the saturation dome.

    Args:
        fluid: A pure fluid or predefined blend, e.g. a refrigerant.
        kind: "PH" (log pressure vs enthalpy, with isotherms; refrigeration cycles)
            or "TS" (temperature vs entropy, with isobars; power cycles).
        plot: PNG file.

    Returns:
        The plot path, and the critical and triple points of the fluid.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _check_fluid(fluid)
    constants = _constants(fluid)
    t_crit, p_crit = constants["critical_temperature_k"], constants["critical_pressure_pa"]
    t_triple = constants["triple_point_temperature_k"]
    if t_crit is None or p_crit is None or t_triple is None:
        raise ValueError(f"{fluid} has no saturation dome (e.g. a brine or a mixture).")
    PropsSI = _cp().PropsSI
    x_key = "H" if kind == "PH" else "S"
    t_low = max(t_triple, 0.55 * t_crit)

    def x(*inputs: object) -> float:
        return PropsSI(x_key, *inputs, fluid) / 1000

    figure, axes = plt.subplots(figsize=(7, 5))
    # Saturation dome: up the liquid line, through the critical point, down the vapor line.
    dome_t = list(np.linspace(t_low, t_crit * 0.9999, 80))
    dome = [(t, 0) for t in dome_t] + [(t, 1) for t in reversed(dome_t)]
    dome_x = [x("T", t, "Q", quality) for t, quality in dome]
    dome_y = [PropsSI("P", "T", t, "Q", 0, fluid) / 1e5 if kind == "PH" else t for t, _ in dome]
    critical = (
        x("T", t_crit, "D", constants["critical_density_kg_m3"]),
        p_crit / 1e5 if kind == "PH" else t_crit,
    )
    dome_x.insert(len(dome_t), critical[0])
    dome_y.insert(len(dome_t), critical[1])
    axes.plot(dome_x, dome_y, color="black", linewidth=1.5, label="saturation")
    if kind == "PH":
        # Isotherms: liquid and vapor branches joined by the boiling plateau.
        for t in np.linspace(t_low, 1.3 * t_crit, 7):
            pressures = np.geomspace(PropsSI("P", "T", t_low, "Q", 0, fluid) / 2, 2 * p_crit, 120)
            points = []
            for p in pressures:
                try:
                    points.append((x("T", t, "P", p), p / 1e5))
                except ValueError:
                    continue
            if t < t_crit:
                p_sat = PropsSI("P", "T", t, "Q", 0, fluid)
                points += [(x("T", t, "Q", 0), p_sat / 1e5), (x("T", t, "Q", 1), p_sat / 1e5)]
            points.sort(key=lambda point: (-point[1], point[0]))
            axes.plot(*zip(*points, strict=True), linewidth=0.8, label=f"{t:.0f} K")
        axes.set_yscale("log")
        axes.set(xlabel="Specific enthalpy (kJ/kg)", ylabel="Pressure (bar)")
    else:
        # Isobars: liquid and vapor branches joined by the boiling plateau.
        p_low = PropsSI("P", "T", t_low, "Q", 0, fluid)
        for p in np.geomspace(p_low, 2 * p_crit, 7):
            points = []
            for t in np.linspace(t_low, 1.5 * t_crit, 150):
                try:
                    points.append((x("T", t, "P", p), t))
                except ValueError:
                    continue
            if p < p_crit:
                t_sat = PropsSI("T", "P", p, "Q", 0, fluid)
                points += [(x("P", p, "Q", 0), t_sat), (x("P", p, "Q", 1), t_sat)]
            points.sort(key=lambda point: (point[1], point[0]))
            axes.plot(*zip(*points, strict=True), linewidth=0.8, label=f"{p / 1e5:.3g} bar")
        axes.set(xlabel="Specific entropy (kJ/(kg K))", ylabel="Temperature (K)")
    axes.set_title(fluid)
    axes.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1))
    figure.savefig(plot, dpi=150, bbox_inches="tight")
    plt.close(figure)
    return {"fluid": fluid, "kind": kind, **constants, "plot": plot}


def _constants(fluid: str) -> dict:
    return _props(
        {
            "critical_temperature_k": "Tcrit",
            "critical_pressure_pa": "pcrit",
            "critical_density_kg_m3": "rhocrit",
            "triple_point_temperature_k": "Ttriple",
            "molar_mass_kg_per_mol": "molar_mass",
        },
        fluid,
        [],
    )


def humid_air(
    dry_bulb_k: float,
    pressure_pa: float = 101325.0,
    relative_humidity: float | None = None,
    dew_point_k: float | None = None,
    wet_bulb_k: float | None = None,
    humidity_ratio: float | None = None,
) -> dict:
    """Psychrometrics of moist air from the dry-bulb temperature and one humidity input.

    Args:
        dry_bulb_k: Air temperature in K.
        pressure_pa: Total pressure in Pa.
        relative_humidity: 0 to 1.
        dew_point_k: Dew-point temperature in K.
        wet_bulb_k: Wet-bulb temperature in K.
        humidity_ratio: kg water per kg dry air.

    Returns:
        Relative humidity, humidity ratio, dew point, wet bulb, enthalpy and volume
        per kg of dry air, and the air's viscosity and thermal conductivity.
    """
    given = {
        "R": relative_humidity,
        "Tdp": dew_point_k,
        "Twb": wet_bulb_k,
        "W": humidity_ratio,
    }
    given = {key: value for key, value in given.items() if value is not None}
    if len(given) != 1:
        raise ValueError("Give one of relative_humidity, dew_point_k, wet_bulb_k, humidity_ratio.")
    ((key, value),) = given.items()
    outputs = {
        "relative_humidity": "R",
        "humidity_ratio": "W",
        "dew_point_k": "Tdp",
        "wet_bulb_k": "Twb",
        "enthalpy_j_per_kg_dry_air": "H",
        "volume_m3_per_kg_dry_air": "V",
        "viscosity_pa_s": "mu",
        "thermal_conductivity_w_m_k": "k",
    }
    result: dict[str, float | None] = {"dry_bulb_k": dry_bulb_k, "pressure_pa": pressure_pa}
    for name, output in outputs.items():
        try:
            result[name] = _number(
                _cp().HAPropsSI(output, "T", dry_bulb_k, "P", pressure_pa, key, value)
            )
        except ValueError as exc:
            raise ValueError(f"Not a valid humid-air state: {exc}") from exc
    return result


def fluids(search: str | None = None) -> dict:
    """Pure fluids and refrigerant blends, with aliases, constants, and model references.

    Args:
        search: Only fluids whose name, alias, CAS number, or formula contains this.

    Returns:
        For each fluid: aliases, CAS number, formula, critical and triple points,
        molar mass, and the references (BibTeX keys) of its equation of state,
        viscosity, and conductivity models; and predefined mixtures (natural gas
        samples, R4xx blends as true mixtures), usable by these names, e.g.
        "R407C.mix".
    """
    CP = _cp()
    names = sorted(CP.get_global_param_string("FluidsList").split(","), key=str.lower)
    mixtures = sorted(
        name
        for name in CP.get_global_param_string("predefined_mixtures").split(",")
        if name.endswith(".mix")
    )
    rows = {}
    for name in names:
        try:
            info = {
                "aliases": CP.get_fluid_param_string(name, "aliases"),
                "cas": CP.get_fluid_param_string(name, "CAS"),
                "formula": CP.get_fluid_param_string(name, "formula")
                .replace("_", "")
                .replace("{", "")
                .replace("}", ""),
            }
        except ValueError:
            info = {"aliases": "", "cas": "", "formula": ""}
        text = " ".join([name, *info.values()]).lower()
        if search and search.lower() not in text:
            continue
        references = {}
        for model in ("EOS", "VISCOSITY", "CONDUCTIVITY"):
            try:
                references[model.lower()] = CP.get_BibTeXKey(name, model)
            except ValueError:
                references[model.lower()] = None
        rows[name] = {**info, **_constants(name), "references": references}
    if search:
        mixtures = [name for name in mixtures if search.lower() in name.lower()]
        if not rows and not mixtures:
            raise ValueError(f"No fluid matches {search!r}.")
    return {"count": len(rows), "fluids": rows, "predefined_mixtures": mixtures}
