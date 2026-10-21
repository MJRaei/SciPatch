"""Chemical thermodynamics and kinetics with Cantera.

Equilibrium compositions, adiabatic flame temperatures, laminar flame speeds,
ignition delays, and species properties for gas mixtures, with detailed
reaction mechanisms (GRI-Mech 3.0 for natural gas by default, or any Cantera
YAML mechanism file). Mixtures are written as "CH4:1, O2:2, N2:7.52" (mole
ratios); temperatures in K, pressures in atm.
"""

from __future__ import annotations

import functools
from typing import Any, Literal

import numpy as np

AIR = "O2:1, N2:3.76"
Constant = Literal["TP", "HP", "UV", "SP"]


@functools.cache
def _load(mechanism: str) -> Any:
    import cantera as ct

    try:
        return ct.Solution(mechanism)
    except ct.CanteraError as exc:
        raise ValueError(
            f"Could not load mechanism '{mechanism}': use a Cantera YAML file, or a built-in "
            "one such as gri30.yaml (natural gas), h2o2.yaml (hydrogen), or nasa_gas.yaml "
            "(thermodynamics only, many species)."
        ) from exc


def _fresh(mechanism: str) -> Any:
    """An independent copy of the mechanism (the cached one is never modified)."""
    import cantera as ct

    _load(mechanism)  # validates once, with a clear error
    return ct.Solution(mechanism)


def _check_species(gas: Any, *mixtures: str) -> None:
    names = set(gas.species_names)
    for mixture in mixtures:
        for part in mixture.split(","):
            name = part.split(":")[0].strip()
            if name and name not in names:
                close = [s for s in gas.species_names if s.upper() == name.upper()]
                hint = f" Did you mean {close[0]}?" if close else ""
                raise ValueError(
                    f"Species '{name}' is not in the mechanism ({len(names)} species).{hint}"
                )


def _set(
    gas: Any,
    fuel: str,
    oxidizer: str,
    phi: float,
    temperature_k: float,
    pressure_atm: float,
) -> None:
    import cantera as ct

    if phi <= 0 or temperature_k <= 0 or pressure_atm <= 0:
        raise ValueError("Equivalence ratio, temperature, and pressure must be positive.")
    _check_species(gas, fuel, oxidizer)
    gas.TP = temperature_k, pressure_atm * ct.one_atm
    gas.set_equivalence_ratio(phi, fuel, oxidizer)


def _major(gas: Any, top: int, threshold: float = 1e-6) -> dict[str, float]:
    order = np.argsort(gas.X)[::-1][:top]
    return {gas.species_names[i]: float(gas.X[i]) for i in order if gas.X[i] > threshold}


def adiabatic_flame_temperature(
    fuel: str,
    oxidizer: str = AIR,
    equivalence_ratio: float | list[float] = 1.0,
    temperature_k: float = 298.15,
    pressure_atm: float = 1.0,
    mechanism: str = "gri30.yaml",
    plot: str = "flame_temperature.png",
) -> dict:
    """Adiabatic flame temperature and equilibrium products at constant pressure.

    Args:
        fuel: Fuel mixture, e.g. "CH4:1", "H2:1", or "CH4:0.9, H2:0.1".
        oxidizer: Oxidizer mixture; default air as "O2:1, N2:3.76".
        equivalence_ratio: Equivalence ratio (1 = stoichiometric, < 1 lean), or a
            list of ratios for a scan (then a plot is written).
        temperature_k: Temperature of the unburned mixture, K.
        pressure_atm: Pressure, atm.
        mechanism: Cantera mechanism (species and their thermodynamics).
        plot: PNG of temperature vs equivalence ratio, for a scan.

    Returns:
        For each equivalence ratio: the adiabatic flame temperature (K) and the
        main equilibrium products (mole fractions); the plot path for a scan.
    """
    ratios = equivalence_ratio if isinstance(equivalence_ratio, list) else [equivalence_ratio]
    gas = _fresh(mechanism)
    results = []
    for phi in ratios:
        _set(gas, fuel, oxidizer, float(phi), temperature_k, pressure_atm)
        gas.equilibrate("HP")
        results.append({
            "equivalence_ratio": float(phi),
            "temperature_k": float(gas.T),
            "products": _major(gas, 8),
        })  # fmt: skip
    output: dict[str, Any] = {"mechanism": mechanism, "results": results}
    if len(results) > 1:
        phis = [r["equivalence_ratio"] for r in results]
        temperatures = [r["temperature_k"] for r in results]
        _plot(phis, temperatures, "equivalence ratio", "adiabatic flame temperature (K)", plot)
        output["plot"] = plot
    return output


def equilibrium(
    mixture: str,
    temperature_k: float = 298.15,
    pressure_atm: float = 1.0,
    constant: Constant = "TP",
    mechanism: str = "gri30.yaml",
    top: int = 12,
) -> dict:
    """Chemical equilibrium of a gas mixture.

    Args:
        mixture: Initial composition as mole ratios, e.g. "CO2:1, H2:1".
        temperature_k: Temperature, K (the initial temperature unless constant is "TP").
        pressure_atm: Pressure, atm.
        constant: Properties held fixed: "TP" (temperature and pressure; default),
            "HP" (adiabatic at constant pressure), "UV" (adiabatic, constant volume),
            or "SP" (isentropic).
        mechanism: Cantera mechanism.
        top: Number of species to report.

    Returns:
        Final temperature (K), pressure (atm), density (kg/m^3), mean molar mass
        (g/mol), and the most abundant species (mole fractions).
    """
    import cantera as ct

    gas = _fresh(mechanism)
    _check_species(gas, mixture)
    gas.TPX = temperature_k, pressure_atm * ct.one_atm, mixture
    gas.equilibrate(constant)
    return {
        "mechanism": mechanism,
        "constant": constant,
        "temperature_k": float(gas.T),
        "pressure_atm": float(gas.P / ct.one_atm),
        "density_kg_m3": float(gas.density),
        "mean_molar_mass_g_mol": float(gas.mean_molecular_weight),
        "mole_fractions": _major(gas, top, threshold=1e-12),
    }


def flame_speed(
    fuel: str,
    oxidizer: str = AIR,
    equivalence_ratio: float = 1.0,
    temperature_k: float = 298.15,
    pressure_atm: float = 1.0,
    mechanism: str = "gri30.yaml",
    transport: Literal["mixture-averaged", "multicomponent"] = "mixture-averaged",
    width_m: float = 0.03,
    profile: str = "flame_profile.csv",
    plot: str = "flame_profile.png",
) -> dict:
    """Laminar burning velocity of a premixed flame (freely propagating, 1D).

    Args:
        fuel: Fuel mixture, e.g. "CH4:1".
        oxidizer: Oxidizer mixture; default air.
        equivalence_ratio: Equivalence ratio.
        temperature_k: Unburned gas temperature, K.
        pressure_atm: Pressure, atm.
        mechanism: Cantera mechanism with kinetics and transport data (gri30.yaml
            for natural gas, h2o2.yaml for hydrogen).
        transport: "mixture-averaged" (default) or "multicomponent" (slower, more exact).
        width_m: Width of the computational domain, m.
        profile: CSV with position, temperature, velocity, and major species.
        plot: PNG of the temperature and heat release profile.

    Returns:
        Laminar burning velocity (m/s), burned gas temperature (K), thermal flame
        thickness (m), number of grid points, and the profile and plot paths.
    """
    import cantera as ct

    gas = _fresh(mechanism)
    if not gas.transport_model or gas.transport_model == "none":
        raise ValueError(f"Mechanism {mechanism} has no transport data; flames need it.")
    _set(gas, fuel, oxidizer, equivalence_ratio, temperature_k, pressure_atm)
    flame = ct.FreeFlame(gas, width=width_m)
    flame.set_refine_criteria(ratio=3, slope=0.06, curve=0.12)
    flame.transport_model = "mixture-averaged"
    print("Solving the mixture-averaged flame...", flush=True)
    flame.solve(loglevel=0, auto=True)
    if transport == "multicomponent":
        print("Refining with multicomponent transport...", flush=True)
        flame.transport_model = "multicomponent"
        flame.solve(loglevel=0)
    z, temperature = flame.grid, flame.T
    thickness = (temperature[-1] - temperature[0]) / np.max(np.gradient(temperature, z))
    reported = ("CH4", "H2", "O2", "H2O", "CO2", "CO", "OH", "NO")
    species = [s for s in reported if s in gas.species_names]
    columns = {"z_m": z, "temperature_k": temperature, "velocity_m_s": flame.velocity}
    columns |= {f"X_{s}": flame.X[gas.species_index(s)] for s in species}
    _write_csv(columns, profile)
    _plot(z * 1000, temperature, "position (mm)", "temperature (K)", plot)
    return {
        "mechanism": mechanism,
        "transport": transport,
        "laminar_flame_speed_m_s": float(flame.velocity[0]),
        "burned_temperature_k": float(temperature[-1]),
        "flame_thickness_m": float(thickness),
        "grid_points": len(z),
        "profile": profile,
        "plot": plot,
    }


def ignition_delay(
    fuel: str,
    oxidizer: str = AIR,
    equivalence_ratio: float = 1.0,
    temperature_k: float = 1200.0,
    pressure_atm: float = 1.0,
    mechanism: str = "gri30.yaml",
    reactor: Literal["constant-pressure", "constant-volume"] = "constant-pressure",
    max_time_s: float = 0.1,
    history: str = "ignition.csv",
    plot: str = "ignition.png",
) -> dict:
    """Autoignition delay of a homogeneous mixture in an adiabatic reactor.

    The delay is the time of the steepest temperature rise.

    Args:
        fuel: Fuel mixture, e.g. "H2:1" or "CH4:1".
        oxidizer: Oxidizer mixture; default air.
        equivalence_ratio: Equivalence ratio.
        temperature_k: Initial temperature, K.
        pressure_atm: Initial pressure, atm.
        mechanism: Cantera mechanism with kinetics.
        reactor: "constant-pressure" (default) or "constant-volume".
        max_time_s: Longest simulated time, s.
        history: CSV of time, temperature, pressure.
        plot: PNG of temperature vs time.

    Returns:
        The ignition delay (s; None if it did not ignite within max_time_s), the
        final temperature and the equilibrium temperature of the same mixture
        (K), their difference, and the history and plot paths.
    """
    import cantera as ct

    gas = _fresh(mechanism)
    _set(gas, fuel, oxidizer, equivalence_ratio, temperature_k, pressure_atm)
    target = _fresh(mechanism)
    target.TPX = gas.T, gas.P, gas.X
    target.equilibrate("HP" if reactor == "constant-pressure" else "UV")
    kind = ct.IdealGasConstPressureReactor if reactor == "constant-pressure" else ct.IdealGasReactor
    vessel = kind(gas)
    network = ct.ReactorNet([vessel])
    times, temperatures, pressures = [0.0], [vessel.T], [vessel.thermo.P]
    while network.time < max_time_s:
        network.step()
        times.append(network.time)
        temperatures.append(vessel.T)
        pressures.append(vessel.thermo.P)
        if vessel.T > target.T - 1 and network.time > 10 * times[1]:
            break
    t, temp = np.array(times), np.array(temperatures)
    slope = np.gradient(temp, t)
    ignited = temp.max() - temp[0] > 400
    delay = float(t[int(np.argmax(slope))]) if ignited else None
    pressure_atm_history = np.array(pressures) / ct.one_atm
    columns = {"time_s": t, "temperature_k": temp, "pressure_atm": pressure_atm_history}
    _write_csv(columns, history)
    _plot(t * 1000, temp, "time (ms)", "temperature (K)", plot)
    return {
        "mechanism": mechanism,
        "reactor": reactor,
        "ignition_delay_s": delay,
        "ignited": bool(ignited),
        "final_temperature_k": float(temp[-1]),
        "equilibrium_temperature_k": float(target.T),
        "final_minus_equilibrium_k": float(temp[-1] - target.T),
        "history": history,
        "plot": plot,
    }


def species_properties(
    species: list[str],
    temperatures_k: list[float],
    mechanism: str = "gri30.yaml",
) -> dict:
    """Thermodynamic properties of pure species (ideal gas, standard pressure).

    Args:
        species: Species names in the mechanism, e.g. ["N2", "CO2", "H2O"].
        temperatures_k: Temperatures in K.
        mechanism: Cantera mechanism; nasa_gas.yaml has many more species.

    Returns:
        For each species and temperature: heat capacity Cp and entropy S
        (J/mol/K), enthalpy H relative to the elements at 298.15 K and Gibbs
        energy G (kJ/mol).
    """
    gas = _fresh(mechanism)
    _check_species(gas, ",".join(species))
    rows = []
    for name in species:
        thermo = gas.species(name).thermo
        for temperature in temperatures_k:
            if not thermo.min_temp <= temperature <= thermo.max_temp:
                raise ValueError(
                    f"{name} is only parameterized from {thermo.min_temp:g} to "
                    f"{thermo.max_temp:g} K in {mechanism}."
                )
            # Cantera works per kmol: J/kmol/K and J/kmol.
            cp, h, s = thermo.cp(temperature), thermo.h(temperature), thermo.s(temperature)
            rows.append({
                "species": name,
                "temperature_k": float(temperature),
                "cp_j_mol_k": cp / 1000,
                "s_j_mol_k": s / 1000,
                "h_kj_mol": h / 1e6,
                "g_kj_mol": (h - temperature * s) / 1e6,
            })  # fmt: skip
    return {"mechanism": mechanism, "properties": rows}


def _write_csv(columns: dict[str, Any], path: str) -> None:
    data = np.column_stack([np.asarray(v, dtype=float) for v in columns.values()])
    np.savetxt(path, data, delimiter=",", header=",".join(columns), comments="")


def _plot(x: Any, y: Any, xlabel: str, ylabel: str, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(5.5, 3.8))
    axes.plot(x, y, marker="o" if len(x) < 30 else None)
    axes.set(xlabel=xlabel, ylabel=ylabel)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
