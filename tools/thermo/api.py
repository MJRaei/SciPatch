"""Chemical engineering thermodynamics with thermo, chemicals, and fluids.

Properties of about 20,000 pure chemicals (constants and temperature-dependent
correlations from critically evaluated compilations), vapor-liquid equilibrium of
mixtures with UNIFAC, Peng-Robinson, or Raoult's law (flash, bubble and dew
points, T-x-y diagrams and azeotropes), and single-phase pipe flow (friction
factor and pressure drop). SI units throughout.
"""

from __future__ import annotations

import csv
import functools
import itertools
import math
import warnings
from typing import Literal

Model = Literal["UNIFAC", "UNIFAC-Dortmund", "Peng-Robinson", "ideal"]
ATM = 101325.0
#: Mole fraction used for the pure-component ends of a binary diagram.
PURE = 1e-6


@functools.cache
def _quiet() -> None:
    warnings.filterwarnings("ignore")


def _number(value, digits: int = 6) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return float(f"{value:.{digits}g}") if math.isfinite(value) else None


def _cas(name: str) -> str:
    from chemicals.identifiers import CAS_from_any

    try:
        return CAS_from_any(name)
    except Exception as exc:
        raise ValueError(
            f"Unknown chemical {name!r}; give a name, CAS number, formula, SMILES, or InChI."
        ) from exc


def chemical(name: str, temperature_k: float = 298.15, pressure_pa: float = ATM) -> dict:
    """Identity, constants, and properties of a pure chemical at a temperature and pressure.

    Args:
        name: Common name, CAS number, formula, SMILES, or InChI (e.g. "ethanol",
            "64-17-5", "toluene", "CCO").
        temperature_k: Temperature in K.
        pressure_pa: Pressure in Pa.

    Returns:
        Name, CAS, formula, SMILES, InChIKey, molar mass; critical temperature,
        pressure, and volume, acentric factor, normal boiling and melting points,
        triple point; and at the given state: phase, density, heat capacity,
        viscosity, thermal conductivity, vapor pressure, enthalpy of
        vaporization, surface tension, and the Prandtl number. Properties without
        data or outside their correlation's range are null.
    """
    _quiet()
    from thermo import Chemical

    cas = _cas(name)
    try:
        c = Chemical(cas, T=temperature_k, P=pressure_pa)
    except Exception as exc:
        raise ValueError(f"No property data for {name} at this state: {exc}") from exc
    return {
        "name": c.name,
        "cas": c.CAS,
        "formula": c.formula,
        "smiles": c.smiles,
        "inchi_key": c.InChI_Key,
        "molar_mass_g_per_mol": _number(c.MW),
        "critical_temperature_k": _number(c.Tc),
        "critical_pressure_pa": _number(c.Pc),
        "critical_volume_m3_per_mol": _number(c.Vc),
        "acentric_factor": _number(c.omega),
        "normal_boiling_point_k": _number(c.Tb),
        "melting_point_k": _number(c.Tm),
        "triple_point_temperature_k": _number(c.Tt),
        "state": {
            "temperature_k": temperature_k,
            "pressure_pa": pressure_pa,
            "phase": {"l": "liquid", "g": "gas", "s": "solid"}.get(c.phase, c.phase),
            "density_kg_m3": _number(c.rho),
            "cp_j_per_kg_k": _number(c.Cp),
            "viscosity_pa_s": _number(c.mu),
            "thermal_conductivity_w_m_k": _number(c.k),
            "vapor_pressure_pa": _number(c.Psat),
            "enthalpy_of_vaporization_j_per_kg": _number(c.Hvap),
            "surface_tension_n_m": _number(c.sigma),
            "prandtl": _number(c.Pr),
        },
    }


def _flasher(names: list[str], model: Model):
    _quiet()
    from thermo import (
        PRMIX,
        CEOSGas,
        CEOSLiquid,
        ChemicalConstantsPackage,
        FlashVL,
        GibbsExcessLiquid,
        IdealGas,
    )
    from thermo.interaction_parameters import IPDB
    from thermo.unifac import DOUFIP2016, DOUFSG, UFIP, UFSG, UNIFAC

    cas = [_cas(name) for name in names]
    if len(set(cas)) != len(cas):
        raise ValueError("Each component must be a different chemical.")
    constants, properties = ChemicalConstantsPackage.from_IDs(cas)
    zs = [1.0 / len(cas)] * len(cas)
    T, P = 300.0, ATM
    if model == "Peng-Robinson":
        try:
            kijs = IPDB.get_ip_asymmetric_matrix("ChemSep PR", constants.CASs, "kij")
        except Exception:
            kijs = [[0.0] * len(cas) for _ in cas]
        eos = {"Tcs": constants.Tcs, "Pcs": constants.Pcs, "omegas": constants.omegas, "kijs": kijs}
        gas = CEOSGas(PRMIX, eos, HeatCapacityGases=properties.HeatCapacityGases, T=T, P=P, zs=zs)
        liquid = CEOSLiquid(
            PRMIX, eos, HeatCapacityGases=properties.HeatCapacityGases, T=T, P=P, zs=zs
        )
    else:
        GE = None
        if model in ("UNIFAC", "UNIFAC-Dortmund"):
            dortmund = model == "UNIFAC-Dortmund"
            groups = constants.UNIFAC_Dortmund_groups if dortmund else constants.UNIFAC_groups
            missing = [name for name, group in zip(names, groups, strict=True) if not group]
            if missing:
                raise ValueError(f"No {model} groups for {', '.join(missing)}; use Peng-Robinson.")
            GE = UNIFAC.from_subgroups(
                T=T,
                xs=zs,
                chemgroups=groups,
                version=1 if dortmund else 0,
                interaction_data=DOUFIP2016 if dortmund else UFIP,
                subgroups=DOUFSG if dortmund else UFSG,
            )
        liquid = GibbsExcessLiquid(
            VaporPressures=properties.VaporPressures,
            HeatCapacityGases=properties.HeatCapacityGases,
            VolumeLiquids=properties.VolumeLiquids,
            GibbsExcessModel=GE,
            equilibrium_basis="Psat",
            caloric_basis="Psat",
            T=T,
            P=P,
            zs=zs,
        )
        gas = IdealGas(HeatCapacityGases=properties.HeatCapacityGases, T=T, P=P, zs=zs)
    return FlashVL(constants, properties, liquid=liquid, gas=gas), constants


def _fractions(components: dict[str, float]) -> tuple[list[str], list[float]]:
    if len(components) < 2:
        raise ValueError("Give at least two components with their mole fractions.")
    if any(x < 0 for x in components.values()) or sum(components.values()) <= 0:
        raise ValueError("Mole fractions must be non-negative and not all zero.")
    total = sum(components.values())
    return list(components), [x / total for x in components.values()]


def flash(
    components: dict[str, float],
    temperature_k: float | None = None,
    pressure_pa: float | None = ATM,
    vapor_fraction: float | None = None,
    model: Model = "UNIFAC",
) -> dict:
    """Vapor-liquid equilibrium of a mixture at two of temperature, pressure, vapor fraction.

    Bubble point: vapor_fraction=0 with a pressure (or temperature); dew point:
    vapor_fraction=1.

    Args:
        components: Overall mole fractions by chemical, e.g. {"ethanol": 0.4,
            "water": 0.6}; normalized to sum to 1.
        temperature_k: Temperature in K.
        pressure_pa: Pressure in Pa (set to null when giving temperature and
            vapor fraction).
        vapor_fraction: Molar vapor fraction, 0 to 1.
        model: "UNIFAC" (activity coefficients from functional groups; polar and
            non-ideal liquids at low pressure), "UNIFAC-Dortmund", "Peng-Robinson"
            (equation of state; hydrocarbons, gases, high pressure), or "ideal"
            (Raoult's law).

    Returns:
        Temperature, pressure, vapor fraction, the phases present, and the
        composition of each phase with K values (y/x).
    """
    names, zs = _fractions(components)
    given = {
        k: v
        for k, v in {"T": temperature_k, "P": pressure_pa, "VF": vapor_fraction}.items()
        if v is not None
    }
    if len(given) != 2:
        raise ValueError("Give exactly two of temperature_k, pressure_pa, and vapor_fraction.")
    if "VF" in given and not 0 <= given["VF"] <= 1:
        raise ValueError("vapor_fraction must be between 0 and 1.")
    flasher, _ = _flasher(names, model)
    try:
        state = flasher.flash(zs=zs, **given)
    except Exception as exc:
        raise ValueError(f"The flash did not converge: {exc}") from exc
    gas = state.gas.zs if state.gas is not None else None
    liquid = state.liquid0.zs if state.liquid0 is not None else None
    phases = {}
    for index, name in enumerate(names):
        x = liquid[index] if liquid else None
        y = gas[index] if gas else None
        phases[name] = {
            "overall": round(zs[index], 6),
            "liquid": None if x is None else round(x, 6),
            "vapor": None if y is None else round(y, 6),
            "k_value": round(y / x, 5) if x and y else None,
        }
    return {
        "model": model,
        "temperature_k": _number(state.T),
        "pressure_pa": _number(state.P),
        "vapor_fraction": _number(state.VF),
        "phases_present": [p for p, z in (("liquid", liquid), ("vapor", gas)) if z],
        "components": phases,
    }


def binary_vle(
    component1: str,
    component2: str,
    pressure_pa: float = ATM,
    model: Model = "UNIFAC",
    points: int = 41,
    table: str = "txy.csv",
    plot: str = "txy.png",
) -> dict:
    """T-x-y diagram of a binary mixture at constant pressure, and its azeotrope if any.

    Args:
        component1: First chemical; compositions are its mole fraction.
        component2: Second chemical.
        pressure_pa: Pressure in Pa.
        model: As in flash.
        points: Liquid compositions from 0 to 1.
        table: CSV with x1, y1, and the bubble temperature.
        plot: PNG of the T-x-y diagram.

    Returns:
        Pure-component boiling points at this pressure, the azeotrope (mole
        fraction of component 1, temperature, minimum- or maximum-boiling) or null,
        and the file paths.
    """
    if points < 5:
        raise ValueError("Use at least 5 points.")
    flasher, _ = _flasher([component1, component2], model)
    rows = []
    for index in range(points):
        # thermo's bubble-point flash fails for exactly pure ends; 1e-6 is pure enough.
        x = min(max(index / (points - 1), PURE), 1 - PURE)
        state = _bubble(flasher, pressure_pa, x)
        if state is not None:
            rows.append(
                {
                    "x1": round(x, 6),
                    "y1": round(state.gas.zs[0], 6),
                    "temperature_k": round(state.T, 4),
                }
            )
    if len(rows) < 3:
        raise ValueError("Bubble points could not be computed at this pressure.")
    azeotrope = _azeotrope(flasher, rows, pressure_pa)
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _plot_txy(rows, component1, component2, pressure_pa, azeotrope, plot)
    return {
        "model": model,
        "pressure_pa": pressure_pa,
        "boiling_point_k": {
            component1: rows[-1]["temperature_k"],
            component2: rows[0]["temperature_k"],
        },
        "azeotrope": azeotrope,
        "table": table,
        "plot": plot,
    }


def _bubble(flasher, pressure_pa: float, x: float):
    try:
        return flasher.flash(P=pressure_pa, VF=0, zs=[x, 1 - x])
    except Exception:  # an unconverged point is left out of the diagram
        return None


def _azeotrope(flasher, rows: list[dict], pressure_pa: float) -> dict | None:
    """Where y1 - x1 changes sign between pure-component ends, refine by bisection."""
    differences = [(r["x1"], r["y1"] - r["x1"]) for r in rows[1:-1]]
    for (x_a, d_a), (x_b, d_b) in itertools.pairwise(differences):
        if d_a == 0 or d_a * d_b < 0:
            low, high = x_a, x_b
            state = _bubble(flasher, pressure_pa, low)
            for _ in range(40):
                middle = (low + high) / 2
                trial = _bubble(flasher, pressure_pa, middle)
                if trial is None:  # the solver fails where y = x, i.e. at the azeotrope
                    break
                state = trial
                if (state.gas.zs[0] - middle) * d_a > 0:
                    low = middle
                else:
                    high = middle
            middle = (low + high) / 2
            if state is None:
                return None
            ends = (rows[0]["temperature_k"], rows[-1]["temperature_k"])
            kind = "minimum-boiling" if min(ends) > state.T else "maximum-boiling"
            return {"x1": round(middle, 4), "temperature_k": round(state.T, 3), "type": kind}
    return None


def _plot_txy(rows, name1, name2, pressure_pa, azeotrope, path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(6, 4.5))
    temperatures = [r["temperature_k"] for r in rows]
    axes.plot([r["x1"] for r in rows], temperatures, label="bubble (liquid)")
    axes.plot([r["y1"] for r in rows], temperatures, label="dew (vapor)")
    if azeotrope:
        axes.plot(azeotrope["x1"], azeotrope["temperature_k"], "ko", label="azeotrope")
    axes.set(
        xlabel=f"Mole fraction {name1}",
        ylabel="Temperature (K)",
        title=f"{name1} + {name2} at {pressure_pa / 1000:g} kPa",
        xlim=(0, 1),
    )
    axes.legend()
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def pipe_flow(
    diameter_m: float,
    length_m: float,
    volumetric_flow_m3_s: float | None = None,
    mass_flow_kg_s: float | None = None,
    roughness_m: float = 1.5e-6,
    fluid: str = "water",
    temperature_k: float = 293.15,
    pressure_pa: float = ATM,
    density_kg_m3: float | None = None,
    viscosity_pa_s: float | None = None,
) -> dict:
    """Pressure drop of a single-phase fluid in a straight round pipe (Darcy-Weisbach).

    Args:
        diameter_m: Inner diameter in m.
        length_m: Pipe length in m.
        volumetric_flow_m3_s: Flow in m3/s (give this or mass_flow_kg_s).
        mass_flow_kg_s: Flow in kg/s.
        roughness_m: Wall roughness in m (drawn tubing 1.5e-6, commercial steel
            4.5e-5, cast iron 2.6e-4).
        fluid: Chemical whose density and viscosity are used at the given state.
        temperature_k: Fluid temperature in K.
        pressure_pa: Fluid pressure in Pa.
        density_kg_m3: Override the density.
        viscosity_pa_s: Override the dynamic viscosity.

    Returns:
        Velocity, Reynolds number, flow regime, Darcy friction factor (64/Re when
        laminar, Colebrook equation when turbulent), pressure drop, and head loss.
    """
    _quiet()
    import fluids

    if diameter_m <= 0 or length_m <= 0:
        raise ValueError("diameter_m and length_m must be positive.")
    if density_kg_m3 is None or viscosity_pa_s is None:
        props = chemical(fluid, temperature_k, pressure_pa)["state"]
        density_kg_m3 = density_kg_m3 or props["density_kg_m3"]
        viscosity_pa_s = viscosity_pa_s or props["viscosity_pa_s"]
    if not density_kg_m3 or not viscosity_pa_s:
        raise ValueError(f"No density or viscosity for {fluid}; give them explicitly.")
    if (volumetric_flow_m3_s is None) == (mass_flow_kg_s is None):
        raise ValueError("Give either volumetric_flow_m3_s or mass_flow_kg_s.")
    flow = (
        volumetric_flow_m3_s if volumetric_flow_m3_s is not None else mass_flow_kg_s / density_kg_m3
    )
    area = math.pi * diameter_m**2 / 4
    velocity = flow / area
    reynolds = density_kg_m3 * velocity * diameter_m / viscosity_pa_s
    if reynolds < 2300:
        friction, regime = 64 / reynolds, "laminar"
    else:
        friction = fluids.friction_factor(
            Re=reynolds, eD=roughness_m / diameter_m, Method="Colebrook"
        )
        regime = "turbulent" if reynolds > 4000 else "transitional (turbulent correlation used)"
    drop = friction * length_m / diameter_m * density_kg_m3 * velocity**2 / 2
    return {
        "velocity_m_s": _number(velocity),
        "reynolds_number": _number(reynolds),
        "regime": regime,
        "friction_factor_darcy": _number(friction),
        "pressure_drop_pa": _number(drop),
        "head_loss_m": _number(drop / (density_kg_m3 * 9.80665)),
        "density_kg_m3": _number(density_kg_m3),
        "viscosity_pa_s": _number(viscosity_pa_s),
    }
