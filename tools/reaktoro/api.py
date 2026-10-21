"""Aqueous and geochemical equilibrium with Reaktoro and the PHREEQC databases.

Speciation of natural waters, brines, and process waters (pH, ionic strength,
species, saturation indices), and equilibrium with minerals and gases (solubility,
dissolution and precipitation, open systems such as water in contact with air).
Activity models follow PHREEQC for each database (Debye-Hückel/WATEQ/Davies), or
Pitzer equations for concentrated brines.
"""

from __future__ import annotations

import csv
import functools
import math
from typing import Literal

Database = Literal["phreeqc", "wateq4f", "minteq.v4", "llnl", "pitzer"]

#: Common analytes -> the master species they are added as. Concentrations of
#: "HCO3" or "C" are total dissolved inorganic carbon; "SO4" or "S" total sulfate.
MASTER = {
    "Ca": "Ca+2",
    "Mg": "Mg+2",
    "Na": "Na+",
    "K": "K+",
    "Sr": "Sr+2",
    "Ba": "Ba+2",
    "Li": "Li+",
    "Fe": "Fe+2",
    "Mn": "Mn+2",
    "Al": "Al+3",
    "Zn": "Zn+2",
    "Cu": "Cu+2",
    "Pb": "Pb+2",
    "Cd": "Cd+2",
    "Cl": "Cl-",
    "F": "F-",
    "Br": "Br-",
    "SO4": "SO4-2",
    "S": "SO4-2",
    "HCO3": "HCO3-",
    "C": "HCO3-",
    "NO3": "NO3-",
    "NH4": "NH4+",
    "SiO2": "H4SiO4",
    "Si": "H4SiO4",
    "B": "H3BO3",
    "PO4": "H2PO4-",
}
UNITS = {"mol/kg": 1.0, "mmol/kg": 1e-3, "mg/kg": None, "mg/L": None}
#: Moles of each mineral put in contact with 1 kg of water (as in PHREEQC's examples).
EXCESS_MOL = 1.0


@functools.cache
def _database(name: str):
    import reaktoro as rkt

    file = {
        "phreeqc": "phreeqc.dat",
        "wateq4f": "wateq4f.dat",
        "minteq.v4": "minteq.v4.dat",
        "llnl": "llnl.dat",
        "pitzer": "pitzer.dat",
    }.get(name)
    if file is None:
        raise ValueError(
            f"Unknown database {name!r}; choose phreeqc, wateq4f, minteq.v4, llnl, or pitzer."
        )
    return rkt.PhreeqcDatabase(file)


def _species_names(name: str) -> set[str]:
    return {species.name() for species in _database(name).species()}


def _amounts(
    solutes: dict[str, float], units: str, density_kg_l: float, database: str
) -> dict[str, float]:
    """Moles of each master species per kg of water."""
    import reaktoro as rkt

    if units not in UNITS:
        raise ValueError(f"Unknown units {units!r}; use one of {', '.join(UNITS)}.")
    names = _species_names(database)
    amounts: dict[str, float] = {}
    for key, value in solutes.items():
        if value < 0:
            raise ValueError(f"Concentration of {key} is negative.")
        species = MASTER.get(key, key)
        if species not in names:
            raise ValueError(
                f"{key!r} is not an analyte or a species of the {database} database; use e.g. "
                f"{', '.join(list(MASTER)[:12])}, ..."
            )
        if UNITS[units] is not None:
            moles = value * UNITS[units]
        else:
            formula = key if key in MASTER else species
            grams_per_mol = rkt.ChemicalFormula(formula).molarMass() * 1000
            mg_per_kg = value / density_kg_l if units == "mg/L" else value
            moles = mg_per_kg / 1000 / grams_per_mol
        amounts[species] = amounts.get(species, 0.0) + moles
    return amounts


def _elements(species: list[str], database: str) -> list[str]:
    db = _database(database)
    symbols = {"H", "O"}
    for name in species:
        symbols.update(element.symbol() for element, _ in db.species().get(name).elements())
    return sorted(symbols)


def _check_names(names: list[str], database: str, kind: str) -> None:
    known = _species_names(database)
    missing = [name for name in names if name not in known]
    if missing:
        raise ValueError(
            f"Unknown {kind} {', '.join(missing)} in the {database} database; see minerals()."
        )


def _aqueous_phase(elements: list[str], database: str):
    import reaktoro as rkt

    phase = rkt.AqueousPhase(rkt.speciate(" ".join(elements)))
    if database == "pitzer":
        phase.set(rkt.ActivityModelPitzer())
    else:
        phase.set(rkt.ActivityModelPhreeqc(_database(database)))
    return phase


def _round(value: float, digits: int = 6) -> float | None:
    value = float(value)
    return float(f"{value:.{digits}g}") if math.isfinite(value) else None


def _describe(state, system, top: int) -> dict:
    import reaktoro as rkt

    props = rkt.AqueousProps(state)
    chemical = rkt.ChemicalProps(state)
    aqueous = [
        s.name() for s in system.species() if s.aggregateState() == rkt.AggregateState.Aqueous
    ]
    rows = []
    for name in aqueous:
        if name == "H2O":
            continue
        molality = float(props.speciesMolality(name))
        activity = float(chemical.speciesActivity(name))
        rows.append((molality, name, activity))
    rows.sort(reverse=True)
    species = [
        {
            "species": name,
            "molality": _round(molality),
            "activity": _round(activity),
            "log_gamma": _round(math.log10(activity / molality), 4)
            if molality > 0 and activity > 0
            else None,
        }
        for molality, name, activity in rows[:top]
    ]
    indices = {}
    for species_object in props.saturationSpecies():
        name = species_object.name()
        indices[name] = _round(float(props.saturationIndex(name)), 4)
    minerals = {k: v for k, v in sorted(indices.items()) if not k.endswith("(g)")}
    gases = {k: v for k, v in sorted(indices.items()) if k.endswith("(g)")}
    elements = {
        element.symbol(): _round(float(props.elementMolality(element.symbol())))
        for element in system.elements()
        if element.symbol() not in ("H", "O", "Z")
    }
    return {
        "temperature_c": _round(float(state.temperature()) - 273.15, 6),
        "pH": _round(float(props.pH()), 6),
        "ionic_strength_mol_per_kg": _round(float(props.ionicStrength())),
        "water_activity": _round(float(chemical.speciesActivity("H2O"))),
        "element_molalities": elements,
        "species": species,
        "saturation_indices": minerals,
        "gas_saturation_indices": gases,
    }


def speciate(
    solutes: dict[str, float],
    units: Literal["mol/kg", "mmol/kg", "mg/kg", "mg/L"] = "mol/kg",
    ph: float | None = None,
    temperature_c: float = 25.0,
    pressure_bar: float = 1.01325,
    density_kg_l: float = 1.0,
    database: Database = "phreeqc",
    top: int = 15,
) -> dict:
    """Speciation and mineral saturation of a water analysis (like a PHREEQC SOLUTION).

    Args:
        solutes: Concentrations by analyte, e.g. {"Ca": 40, "Mg": 10, "Na": 20,
            "Cl": 35, "SO4": 25, "HCO3": 150}. Analytes: Ca, Mg, Na, K, Sr, Ba, Li,
            Fe, Mn, Al, Zn, Cu, Pb, Cd, Cl, F, Br, SO4 (or S), HCO3 (or C, total
            inorganic carbon), NO3, NH4, SiO2 (or Si), B, PO4, or any species name of
            the database (e.g. "Fe+3").
        units: "mol/kg", "mmol/kg", "mg/kg", or "mg/L" (mass as the analyte written,
            e.g. SO4 as sulfate, SiO2 as silica, C as carbon).
        ph: Measured pH; without it the pH follows from charge balance, which needs
            a balanced analysis.
        temperature_c: Temperature in °C.
        pressure_bar: Pressure in bar.
        density_kg_l: Solution density, used to convert mg/L.
        database: "phreeqc" (default), "wateq4f" or "minteq.v4" (trace metals),
            "llnl" (wide temperature range), or "pitzer" (brines above ~1 mol/kg).
        top: Number of most abundant species to list.

    Returns:
        pH, ionic strength, water activity, element molalities, the most abundant
        species (molality, activity, log activity coefficient), saturation indices
        (log IAP/K; >0 supersaturated) of every mineral of the database that the
        water's elements can form, gas saturation indices (log partial pressure in
        atm in equilibrium with the water), and the charge balance error of the input.
    """
    import reaktoro as rkt

    amounts = _amounts(solutes, units, density_kg_l, database)
    db = _database(database)
    charges = {name: db.species().get(name).charge() for name in amounts}
    cations = sum(n * z for name, n in amounts.items() if (z := charges[name]) > 0)
    anions = -sum(n * z for name, n in amounts.items() if (z := charges[name]) < 0)
    error = 100 * (cations - anions) / (cations + anions) if cations + anions else 0.0
    if ph is None and abs(error) > 5:
        raise ValueError(
            f"The analysis is out of charge balance by {error:.1f}%; give the measured pH "
            "or correct the concentrations."
        )
    system = rkt.ChemicalSystem(db, _aqueous_phase(_elements(list(amounts), database), database))
    specs = rkt.EquilibriumSpecs(system)
    specs.temperature()
    specs.pressure()
    if ph is not None:
        specs.pH()
    conditions = rkt.EquilibriumConditions(specs)
    conditions.temperature(temperature_c, "celsius")
    conditions.pressure(pressure_bar, "bar")
    if ph is not None:
        conditions.pH(ph)
    state = rkt.ChemicalState(system)
    state.set("H2O", 1.0, "kg")
    for name, moles in amounts.items():
        state.add(name, moles, "mol")
    result = rkt.EquilibriumSolver(specs).solve(state, conditions)
    if not result.succeeded():
        raise RuntimeError("The speciation did not converge; check the analysis and the pH.")
    return {**_describe(state, system, top), "charge_balance_error_percent": round(error, 3)}


def mineral_equilibrium(
    minerals: list[str],
    solutes: dict[str, float] | None = None,
    units: Literal["mol/kg", "mmol/kg", "mg/kg", "mg/L"] = "mol/kg",
    gases: dict[str, float] | None = None,
    temperature_c: float = 25.0,
    pressure_bar: float = 1.01325,
    database: Database = "phreeqc",
    top: int = 10,
) -> dict:
    """Equilibrate 1 kg of water (with optional solutes) with minerals and fixed gas pressures.

    Each mineral starts at 1 mol and dissolves or precipitates to equilibrium, as in
    PHREEQC's EQUILIBRIUM_PHASES. Use it for solubility (e.g. gypsum, calcite,
    halite), for water in contact with air (e.g. {"CO2(g)": 0.00042}), or for scaling
    and dissolution in process waters.

    Args:
        minerals: Mineral names of the database, e.g. ["Calcite"], ["Gypsum",
            "Anhydrite"], ["Halite"] (see minerals()).
        solutes: Initial water composition (as in speciate); default pure water.
        units: Units of `solutes`.
        gases: Fixed partial pressures in bar (open system), e.g. {"CO2(g)": 0.00042}.
        temperature_c: Temperature in °C.
        pressure_bar: Total pressure in bar.
        database: As in speciate.
        top: Number of most abundant species to list.

    Returns:
        For each mineral (1 mol to start), millimoles dissolved into the 1 kg of
        water (negative when it precipitates) and whether any remains; the solution
        after equilibrium (pH, ionic strength, element molalities, species,
        saturation indices).
    """
    import reaktoro as rkt

    if not minerals and not gases:
        raise ValueError("Give at least one mineral or gas.")
    db = _database(database)
    _check_names(minerals, database, "mineral")
    gases = gases or {}
    _check_names(list(gases), database, "gas")
    amounts = _amounts(solutes or {}, units, 1.0, database)
    elements = _elements(list(amounts) + list(minerals) + list(gases), database)
    phases = [_aqueous_phase(elements, database)]
    if minerals:
        phases.append(rkt.MineralPhases(" ".join(minerals)))
    system = rkt.ChemicalSystem(db, *phases)
    specs = rkt.EquilibriumSpecs(system)
    specs.temperature()
    specs.pressure()
    for gas in gases:
        specs.fugacity(gas.removesuffix("(g)"))
    conditions = rkt.EquilibriumConditions(specs)
    conditions.temperature(temperature_c, "celsius")
    conditions.pressure(pressure_bar, "bar")
    for gas, pressure in gases.items():
        if pressure <= 0:
            raise ValueError(f"The partial pressure of {gas} must be positive.")
        conditions.fugacity(gas.removesuffix("(g)"), pressure, "bar")
    state = rkt.ChemicalState(system)
    state.set("H2O", 1.0, "kg")
    for name, moles in amounts.items():
        state.add(name, moles, "mol")
    for mineral in minerals:
        state.set(mineral, EXCESS_MOL, "mol")
    result = rkt.EquilibriumSolver(specs).solve(state, conditions)
    if not result.succeeded():
        raise RuntimeError("The equilibrium calculation did not converge.")
    transfers = {}
    for mineral in minerals:
        left = float(state.speciesAmount(mineral))
        transfers[mineral] = {
            "dissolved_mmol": _round((EXCESS_MOL - left) * 1000),
            "present": left > 1e-12,
        }
    return {"minerals": transfers, **_describe(state, system, top)}


def solubility_curve(
    mineral: str,
    t_min_c: float = 0.0,
    t_max_c: float = 100.0,
    points: int = 21,
    solutes: dict[str, float] | None = None,
    gases: dict[str, float] | None = None,
    database: Database = "phreeqc",
    table: str = "solubility.csv",
    plot: str = "solubility.png",
) -> dict:
    """Solubility of a mineral versus temperature (mmol dissolved per kg water).

    Args:
        mineral: Mineral name (see minerals()).
        t_min_c: Lowest temperature in °C.
        t_max_c: Highest temperature in °C.
        points: Number of temperatures.
        solutes: Background water composition in mol/kg (e.g. {"Na": 0.5, "Cl": 0.5}).
        gases: Fixed partial pressures in bar, e.g. {"CO2(g)": 0.00042}.
        database: As in speciate.
        table: CSV with temperature, solubility, and pH.
        plot: PNG of solubility versus temperature.

    Returns:
        Solubility and pH at each temperature, and the file paths.
    """
    if points < 2 or not t_min_c < t_max_c:
        raise ValueError("Need t_min_c < t_max_c and at least two points.")
    rows = []
    for index in range(points):
        temperature = t_min_c + (t_max_c - t_min_c) * index / (points - 1)
        result = mineral_equilibrium(
            [mineral], solutes, "mol/kg", gases, temperature, 1.01325, database, top=1
        )
        rows.append(
            {
                "temperature_c": round(temperature, 4),
                "solubility_mmol_per_kg": result["minerals"][mineral]["dissolved_mmol"],
                "pH": result["pH"],
            }
        )
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(6, 4))
    axes.plot(
        [r["temperature_c"] for r in rows], [r["solubility_mmol_per_kg"] for r in rows], marker="o"
    )
    axes.set(
        xlabel="Temperature (°C)", ylabel=f"{mineral} dissolved (mmol/kg water)", title=mineral
    )
    figure.savefig(plot, dpi=150, bbox_inches="tight")
    plt.close(figure)
    return {"mineral": mineral, "database": database, "points": rows, "table": table, "plot": plot}


def minerals(elements: list[str], database: Database = "phreeqc") -> dict:
    """Minerals and gases of a database made only of the given elements (plus H and O).

    Args:
        elements: Element symbols, e.g. ["Ca", "C"] or ["Ca", "Mg", "C", "S"].
        database: As in speciate.

    Returns:
        Mineral and gas names with their formulas.
    """
    import reaktoro as rkt

    db = _database(database)
    symbols = " ".join(sorted(set(elements) | {"H", "O"}))
    found = db.species().withElements(symbols)
    solids = {
        s.name(): s.formula().str() for s in found if s.aggregateState() == rkt.AggregateState.Solid
    }
    gases = {
        s.name(): s.formula().str() for s in found if s.aggregateState() == rkt.AggregateState.Gas
    }
    return {
        "database": database,
        "minerals": dict(sorted(solids.items())),
        "gases": dict(sorted(gases.items())),
    }
