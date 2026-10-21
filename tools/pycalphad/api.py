"""Phase equilibria, solidification, and phase diagrams of alloys with pycalphad (CALPHAD).

Thermodynamic databases (TDB files) describe each phase's Gibbs energy; pycalphad
minimizes the total Gibbs energy to find which phases are stable, their amounts, and
their compositions. Published databases bundled with pycalphad can be named
(see database_info); any TDB file can be given as a path. Compositions are percent
of each alloying element, the rest being the balance element.
"""

from __future__ import annotations

import csv
import functools
import os
import warnings
from pathlib import Path
from typing import Any, Literal

import numpy as np

#: Published assessments in pycalphad's repository, by name.
DATABASES = {
    "COST507": (
        "COST507.tdb",
        "Light alloys, 29 elements (Al, Mg, Si, Cu, Fe, Ni, Ti, Zn, Li, ...): COST 507 "
        "round II (1999), I. Ansara, A. T. Dinsdale, M. H. Rand (eds.), COST 507: "
        "Thermochemical database for light metal alloys, vol. 2 (1998).",
    ),
    "Al-Fe": (
        "Al-Fe_sundman2009.tdb",
        "Al-Fe: B. Sundman et al., Acta Mater. 57, 2896 (2009).",
    ),
    "Al-Mg": ("Al-Mg_Zhong.tdb", "Al-Mg: NIMS Computational Phase Diagram Database (2008)."),
    "Al-Zn": ("alzn_mey.tdb", "Al-Zn: NIMS Computational Phase Diagram Database (2009)."),
    "Al-Ni": ("alni_dupin_2001.tdb", "Al-Ni: N. Dupin et al., Calphad 25, 279 (2001)."),
    "Cu-Mg": ("cumg.tdb", "Cu-Mg: NIMS Computational Phase Diagram Database (2008)."),
    "Pb-Sn": ("pbsn.tdb", "Pb-Sn (solders): NIMS Computational Phase Diagram Database (2011)."),
}
_LIQUID = "LIQUID"
_TOLERANCE = 1e-6
P_STANDARD = 101325.0


@functools.cache
def _database(name: str) -> Any:
    from pycalphad import Database

    if name in DATABASES:
        path = (
            Path(os.environ["MOTEL_SOURCE_DIR"]) / "pycalphad/tests/databases" / DATABASES[name][0]
        )
    else:
        path = Path(name)
        if not path.is_file():
            raise ValueError(
                f"{name!r} is neither a TDB file nor a bundled database ({', '.join(DATABASES)})."
            )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Database(str(path))


def _system(
    database: str, balance: str, composition: dict[str, float], basis: str
) -> tuple[Any, list[str], list[str], dict[Any, float]]:
    """Database, components, candidate phases, and mole-fraction conditions."""
    from pycalphad import variables as v
    from pycalphad.core.utils import filter_phases, unpack_species

    db = _database(database)
    known = {str(element) for element in db.elements} - {"/-", "VA"}
    elements = [balance.upper(), *(element.upper() for element in composition)]
    missing = [element for element in elements if element not in known]
    if missing:
        raise ValueError(
            f"{', '.join(missing)} not in this database; it has {', '.join(sorted(known))}."
        )
    if len(set(elements)) != len(elements):
        raise ValueError("The balance element must not also be in composition.")
    percents = {element.upper(): float(value) for element, value in composition.items()}
    if any(value < 0 for value in percents.values()) or sum(percents.values()) >= 100:
        raise ValueError("Alloying percentages must be positive and sum to less than 100.")
    if basis == "mass" and percents:
        masses = {element: db.refstates[element]["mass"] for element in elements}
        moles = v.get_mole_fractions(
            {v.W(element): value / 100 for element, value in percents.items()},
            v.Species(balance.upper()),
            masses,
        )
        fractions = {v.X(str(key.species.name)): float(value) for key, value in moles.items()}
    else:
        fractions = {v.X(element): value / 100 for element, value in percents.items()}
    components = [*sorted(set(elements)), "VA"]
    phases = filter_phases(db, unpack_species(db, components))
    return db, components, phases, fractions


def _solve(system: tuple[Any, list[str], list[str], dict[Any, float]], temperature: Any) -> Any:
    from pycalphad import equilibrium
    from pycalphad import variables as v

    db, components, phases, fractions = system
    conditions = {**fractions, v.T: temperature, v.P: P_STANDARD, v.N: 1}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return equilibrium(db, components, phases, conditions)


def _phase_fractions(result: Any) -> list[dict[str, float]]:
    """Per temperature: phase name -> fraction of atoms (summing composition sets)."""
    names = result.Phase.values.reshape(-1, result.Phase.shape[-1])
    amounts = result.NP.values.reshape(-1, result.NP.shape[-1])
    rows = []
    for row_names, row_amounts in zip(names, amounts, strict=True):
        row: dict[str, float] = {}
        for name, amount in zip(row_names, row_amounts, strict=True):
            if name and not np.isnan(amount) and amount > _TOLERANCE:
                row[str(name)] = row.get(str(name), 0.0) + float(amount)
        rows.append(row)
    return rows


def _liquid(
    system: tuple[Any, list[str], list[str], dict[Any, float]], temperature: float
) -> float:
    return _phase_fractions(_solve(system, temperature))[0].get(_LIQUID, 0.0)


def _bisect(
    system: tuple[Any, list[str], list[str], dict[Any, float]],
    low: float,
    high: float,
    above: Any,
) -> float:
    """Temperature (to 0.05 K) between low and high where ``above(liquid fraction)`` turns true."""
    while high - low > 0.05:
        middle = (low + high) / 2
        if above(_liquid(system, middle)):
            high = middle
        else:
            low = middle
    return round(float(low + high) / 2, 2)


def equilibrium(
    database: str,
    balance: str,
    composition: dict[str, float],
    temperature_k: float,
    basis: Literal["mass", "mole"] = "mass",
) -> dict:
    """Stable phases of an alloy at a temperature: their amounts and compositions.

    Args:
        database: A bundled database name ("COST507", "Al-Fe", "Pb-Sn", ...; see
            database_info) or the path of a TDB file.
        balance: The majority element, e.g. "AL".
        composition: Percent of each alloying element, e.g. {"SI": 7, "MG": 0.3}.
        temperature_k: Temperature in K (pressure is 1 atm).
        basis: Whether composition is mass percent (wt%) or mole percent (at%).

    Returns:
        Each stable phase with its fraction (of atoms) and composition in mole
        percent, and the molar Gibbs energy of the alloy in J/mol.
    """
    system = _system(database, balance, composition, basis)
    result = _solve(system, temperature_k)
    components = [c for c in system[1] if c != "VA"]
    names = result.Phase.values.reshape(-1)
    amounts = result.NP.values.reshape(-1)
    contents = result.X.values.reshape(len(names), -1)
    phases = []
    for name, amount, content in zip(names, amounts, contents, strict=True):
        if name and not np.isnan(amount) and amount > _TOLERANCE:
            phases.append(
                {
                    "phase": str(name),
                    "fraction": round(float(amount), 6),
                    "composition_mole_percent": {
                        element: round(float(x) * 100, 4)
                        for element, x in zip(components, content, strict=True)
                    },
                }
            )
    phases.sort(key=lambda phase: -phase["fraction"])
    return {
        "temperature_k": temperature_k,
        "phases": phases,
        "stable_phases": [phase["phase"] for phase in phases],
        "gibbs_energy_j_per_mol": float(result.GM.values.reshape(-1)[0]),
    }


def solidification(
    database: str,
    balance: str,
    composition: dict[str, float] | None = None,
    basis: Literal["mass", "mole"] = "mass",
    t_min_k: float = 300.0,
    t_max_k: float = 2000.0,
    step_k: float = 5.0,
    table: str = "phase_fractions.csv",
    plot: str = "phase_fractions.png",
) -> dict:
    """Liquidus and solidus of an alloy, and its phase fractions versus temperature.

    Equilibrium (lever-rule) solidification: phase fractions on a temperature grid,
    with the liquidus and solidus refined to 0.05 K.

    Args:
        database: A bundled database name or a TDB file path (see equilibrium).
        balance: The majority element, e.g. "AL" or "PB".
        composition: Percent of each alloying element, e.g. {"SI": 12.6}; empty for
            the pure element.
        basis: Whether composition is mass percent (wt%) or mole percent (at%).
        t_min_k: Lowest temperature in K.
        t_max_k: Highest temperature in K (must be above the liquidus).
        step_k: Temperature step of the table in K.
        table: CSV file for the phase fractions versus temperature.
        plot: PNG file for the phase fractions versus temperature.

    Returns:
        Liquidus and solidus in K (and °C), the freezing range, the phases at the
        lowest temperature, and the paths of the table and plot.
    """
    if not 0 < t_min_k < t_max_k:
        raise ValueError("Give 0 < t_min_k < t_max_k.")
    system = _system(database, balance, composition or {}, basis)
    temperatures = np.arange(t_min_k, t_max_k + step_k / 2, step_k)
    fractions = _phase_fractions(_solve(system, temperatures))
    liquid = np.array([row.get(_LIQUID, 0.0) for row in fractions])
    if liquid[-1] < 1 - _TOLERANCE:
        raise ValueError(f"The alloy is not fully liquid at {t_max_k} K; raise t_max_k.")
    liquidus = solidus = None
    partly_solid = np.nonzero(liquid < 1 - _TOLERANCE)[0]
    if len(partly_solid):
        i = partly_solid[-1]
        liquidus = _bisect(
            system, temperatures[i], temperatures[i + 1], lambda f: f >= 1 - _TOLERANCE
        )
    solid = np.nonzero(liquid <= _TOLERANCE)[0]
    if len(solid):
        i = solid[-1]
        solidus = _bisect(system, temperatures[i], temperatures[i + 1], lambda f: f > _TOLERANCE)
    phases = sorted({name for row in fractions for name in row})
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["temperature_k", *phases])
        for temperature, row in zip(temperatures, fractions, strict=True):
            writer.writerow([round(float(temperature), 3), *(row.get(p, 0.0) for p in phases)])
    _plot_fractions(temperatures, fractions, phases, plot)

    def celsius(kelvin: float | None) -> float | None:
        return None if kelvin is None else round(kelvin - 273.15, 2)

    return {
        "liquidus_k": liquidus,
        "solidus_k": solidus,
        "liquidus_c": celsius(liquidus),
        "solidus_c": celsius(solidus),
        "freezing_range_k": None
        if liquidus is None or solidus is None
        else round(liquidus - solidus, 2),
        "phases_at_t_min": {name: round(value, 4) for name, value in fractions[0].items()},
        "table": table,
        "plot": plot,
    }


def _plot_fractions(
    temperatures: np.ndarray, fractions: list[dict[str, float]], phases: list[str], path: str
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(7, 4))
    for phase in phases:
        axes.plot(temperatures, [row.get(phase, 0.0) for row in fractions], label=phase)
    axes.set(xlabel="Temperature (K)", ylabel="Phase fraction (atoms)", ylim=(-0.02, 1.02))
    axes.legend(fontsize=8)
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def phase_diagram(
    database: str,
    elements: list[str],
    t_min_k: float = 300.0,
    t_max_k: float = 2000.0,
    plot: str = "phase_diagram.png",
) -> dict:
    """Binary phase diagram (temperature versus composition) of two elements.

    Args:
        database: A bundled database name or a TDB file path (see equilibrium).
        elements: The two elements, e.g. ["AL", "SI"]; the x axis is the mole
            fraction of the second.
        t_min_k: Lowest temperature in K.
        t_max_k: Highest temperature in K.
        plot: PNG file for the diagram.

    Returns:
        The phases that appear and the plot's path.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pycalphad import binplot
    from pycalphad import variables as v

    if len(elements) != 2:
        raise ValueError("Give exactly two elements, e.g. ['AL', 'SI'].")
    first, second = (element.upper() for element in elements)
    db, components, phases, _ = _system(database, first, {second: 0.0}, "mole")
    conditions = {v.X(second): (0, 1, 0.01), v.T: (t_min_k, t_max_k, 5), v.P: P_STANDARD, v.N: 1}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        axes = binplot(db, components, phases, conditions)
    axes.set_title(f"{first}-{second} ({database})")
    axes.figure.savefig(plot, dpi=150, bbox_inches="tight")
    plt.close(axes.figure)
    labels = (
        sorted({text.get_text() for text in axes.get_legend().get_texts()})
        if axes.get_legend()
        else []
    )
    return {"elements": [first, second], "phases": labels, "plot": plot}


def database_info(database: str = "COST507") -> dict:
    """Elements and phases of a thermodynamic database, and the bundled databases.

    Args:
        database: A bundled database name or a TDB file path.

    Returns:
        The database's elements and phases, and every bundled database with its source.
    """
    db = _database(database)
    return {
        "elements": sorted(
            str(element) for element in db.elements if str(element) not in {"/-", "VA"}
        ),
        "phases": sorted(db.phases),
        "bundled": {name: source for name, (_file, source) in DATABASES.items()},
    }
