"""Published synthesis recipes for inorganic materials, and routes from similar materials.

Wraps the data of SKY, the synthesis agent of github.com/hspark1212/synthesis-agent:
41,300 text-mined solid-state and sol-gel recipes (Kononova et al., Sci. Data 2019,
as served by the Materials Project) and Magpie composition features of 152,966
Materials Project entries. Composition similarity follows SKY's search (Magpie
features, standardized, Euclidean nearest neighbours); route suggestion follows
SKY's best-guess search, offline and one step deep. SKY's LLM agent is not used:
the calling agent does the reasoning. Everything runs without network access.
"""

from __future__ import annotations

import contextlib
import functools
import gzip
import json
import os
import statistics
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

import numpy as np

SynthesisType = Literal["any", "solid-state", "sol-gel"]
#: Hours per unit of the dataset's heating times.
_HOURS = {"h": 1.0, "hr": 1.0, "hrs": 1.0, "min": 1 / 60, "s": 1 / 3600, "day": 24.0, "days": 24.0}


def _assets() -> Path:
    return Path(os.environ["MOTEL_SOURCE_DIR"]) / "assets"


def _composition(formula: str) -> Any:
    from pymatgen.core import Composition

    try:
        composition = Composition(formula)
    except Exception as exc:  # pymatgen raises several types for bad formulas
        raise ValueError(f"{formula!r} is not a chemical formula (e.g. 'LiCoO2').") from exc
    if not composition.valid or composition.num_atoms == 0:
        raise ValueError(f"{formula!r} is not a chemical formula (e.g. 'LiCoO2').")
    return composition


@functools.cache
def _index() -> tuple[Any, Any, np.ndarray, np.ndarray]:
    """SKY's composition index: featurizer, fitted neighbour search, formulas, MP ids."""
    import h5py
    from matminer.featurizers.composition import ElementProperty
    from sklearn.neighbors import NearestNeighbors
    from sklearn.preprocessing import StandardScaler

    with h5py.File(_assets() / "embedding" / "mp_dataset_composition_magpie.h5", "r") as data:
        features = data["features"][:]
        formulas = data["formulas"][:].astype(str)
        material_ids = data["material_ids"][:].astype(str)
    scaler = StandardScaler().fit(features)
    search = NearestNeighbors(metric="euclidean").fit(scaler.transform(features))
    featurizer = ElementProperty.from_preset("magpie")
    return featurizer, (scaler, search), formulas, material_ids


def _key(composition: Any) -> str:
    """The same for any way of writing a composition (LiMn1.5Co0.5O4 = Li2CoMn3O8)."""
    fractions = composition.fractional_composition
    return " ".join(f"{element}{fractions[element]:.4f}" for element in sorted(fractions, key=str))


@functools.cache
def _recipes() -> tuple[list[dict[str, Any]], dict[str, list[int]], dict[str, str]]:
    """The recipes, their positions by target composition, and a formula for each."""
    from pymatgen.core import Composition

    with gzip.open(_assets() / "mp_synthesis_recipes.json.gz", "rt", encoding="utf-8") as handle:
        recipes = json.load(handle)
    parsed: dict[str, tuple[str, str] | None] = {}
    by_key: dict[str, list[int]] = defaultdict(list)
    written: dict[str, Counter[str]] = defaultdict(Counter)
    for position, recipe in enumerate(recipes):
        for target in recipe.get("targets_formula_s") or []:
            if target not in parsed:
                try:
                    composition = Composition(target)
                    parsed[target] = (_key(composition), composition.reduced_formula)
                except Exception:
                    parsed[target] = None
            if parsed[target]:
                key, formula = parsed[target]
                by_key[key].append(position)
                written[key][formula] += 1
    names = {key: counts.most_common(1)[0][0] for key, counts in written.items()}
    return recipes, by_key, names


def _features(formula: str) -> np.ndarray:
    """Standardized Magpie features of a formula, as in SKY's search."""
    featurizer, (scaler, _search), _formulas, _ids = _index()
    composition = _composition(formula)
    try:
        vector = np.array([featurizer.featurize(composition)], dtype=float)
    except Exception as exc:
        raise ValueError(f"No Magpie element data for an element of {formula!r}.") from exc
    if np.isnan(vector).any():
        raise ValueError(f"No Magpie element data for an element of {formula!r}.")
    return scaler.transform(vector)


@functools.cache
def _targets() -> tuple[list[str], Any]:
    """Recipe targets with Magpie features, and a neighbour search over them.

    Featurizing the 53,000 targets takes about a minute, so the features are
    saved in the tool's environment the first time (the install's golden test
    does this).
    """
    from pymatgen.core import Composition
    from sklearn.neighbors import NearestNeighbors

    _recipe_list, by_key, names = _recipes()
    keys = sorted(by_key)
    cache = Path(sys.prefix) / "share" / "synthesis-recipes" / "recipe-targets-magpie-v2.npz"
    features = None
    with contextlib.suppress(OSError, KeyError, ValueError):
        saved = np.load(cache, allow_pickle=False)
        if saved["keys"].tolist() == keys:
            features = saved["features"]
    if features is None:
        featurizer = _index()[0]
        print(f"Indexing {len(keys)} recipe targets (once)", flush=True)
        features = np.full((len(keys), len(featurizer.feature_labels())), np.nan)
        for row, key in enumerate(keys):
            with warnings.catch_warnings(), contextlib.suppress(Exception):
                warnings.simplefilter("ignore")
                features[row] = featurizer.featurize(Composition(names[key]))
            if row and row % 10000 == 0:
                print(f"  {row}/{len(keys)}", flush=True)
        with contextlib.suppress(OSError):
            cache.parent.mkdir(parents=True, exist_ok=True)
            partial = cache.with_name(f"{cache.stem}.{os.getpid()}.npz")
            np.savez_compressed(partial, keys=np.array(keys), features=features)
            os.replace(partial, cache)
    usable = ~np.isnan(features).any(axis=1)
    scaler = _index()[1][0]
    search = NearestNeighbors(metric="euclidean").fit(scaler.transform(features[usable]))
    return [key for key, keep in zip(keys, usable, strict=True) if keep], search


def _neighbours(formula: str, depth: int) -> list[dict[str, Any]]:
    """Distinct formulas nearest to ``formula``, with their distance and MP entries."""
    _featurizer, (_scaler, search), formulas, material_ids = _index()
    distances, positions = search.kneighbors(_features(formula), n_neighbors=depth)
    grouped: dict[str, dict[str, Any]] = {}
    for distance, position in zip(distances[0], positions[0], strict=True):
        name = str(formulas[position])
        entry = grouped.setdefault(name, {"formula": name, "distance": float(distance), "ids": []})
        entry["ids"].append(str(material_ids[position]))
    return list(grouped.values())


def similar_materials(formula: str, count: int = 10) -> dict:
    """Materials Project compositions most similar to a formula, and which have recipes.

    Args:
        formula: Chemical formula, e.g. "LiCoO2" or "Ba0.9Sr0.1TiO3".
        count: How many distinct formulas to return.

    Returns:
        The reduced formula and, nearest first, similar formulas with their distance
        (standardized Magpie features; 0 means the same composition), up to five
        Materials Project ids each, and how many published recipes they have.
    """
    if count < 1:
        raise ValueError("count must be at least 1.")
    reduced = _composition(formula).reduced_formula
    similar = []
    for entry in _neighbours(formula, depth=min(50 * count, 5000))[:count]:
        similar.append(
            {
                "formula": entry["formula"],
                "distance": round(entry["distance"], 4),
                "material_ids": entry["ids"][:5],
                "entries": len(entry["ids"]),
                "recipes": len(_recipes_for(_key(_composition(entry["formula"])), "any")),
            }
        )
    return {"formula": reduced, "similar": similar}


def _quantity(values: list[dict[str, Any]], scale: dict[str, float]) -> float | None:
    """The first value of a text-mined condition in the target unit (°C or hours)."""
    for value in values:
        numbers = value.get("values") or [value.get("max_value")]
        unit = (value.get("units") or "").strip()
        if not numbers or numbers[0] is None:
            continue
        if unit in scale:
            return round(float(numbers[0]) * scale[unit], 3)
        if unit == "K" and "°C" in scale:
            return round(float(numbers[0]) - 273.15, 1)
    return None


def _recipe_view(recipe: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for operation in recipe.get("operations") or []:
        conditions = operation.get("conditions") or {}
        step: dict[str, Any] = {"operation": operation.get("token") or operation.get("type")}
        temperature = _quantity(conditions.get("heating_temperature") or [], {"°C": 1.0})
        if temperature is not None:
            step["temperature_c"] = temperature
        duration = _quantity(conditions.get("heating_time") or [], _HOURS)
        if duration is not None:
            step["time_h"] = duration
        if conditions.get("heating_atmosphere"):
            step["atmosphere"] = conditions["heating_atmosphere"]
        steps.append(step)
    doi = recipe.get("doi")
    return {
        "doi": doi,
        "url": f"https://doi.org/{doi}" if doi else None,
        "synthesis_type": recipe.get("synthesis_type"),
        "precursors": sorted(set(recipe.get("precursors_formula_s") or [])),
        "reaction": recipe.get("reaction_string"),
        "steps": steps,
    }


def _summary(views: list[dict[str, Any]]) -> dict[str, Any]:
    sets = Counter(" + ".join(view["precursors"]) for view in views if view["precursors"])
    temperatures = [
        max(step["temperature_c"] for step in view["steps"] if "temperature_c" in step)
        for view in views
        if any("temperature_c" in step for step in view["steps"])
    ]
    summary: dict[str, Any] = {
        "common_precursors": [{"precursors": key, "recipes": n} for key, n in sets.most_common(5)],
    }
    if temperatures:
        summary["highest_temperature_c"] = {
            "median": statistics.median(temperatures),
            "min": min(temperatures),
            "max": max(temperatures),
            "recipes": len(temperatures),
        }
    return summary


def _recipes_for(key: str, synthesis_type: str) -> list[dict[str, Any]]:
    """Distinct recipes for a composition, most common precursors first."""
    recipes, by_key, _names = _recipes()
    views, seen = [], set()
    for position in by_key.get(key, []):
        view = _recipe_view(recipes[position])
        if synthesis_type != "any" and view["synthesis_type"] != synthesis_type:
            continue
        key = (view["doi"], tuple(view["precursors"]), view["reaction"])
        if key not in seen:
            seen.add(key)
            views.append(view)
    counts = Counter(" + ".join(view["precursors"]) for view in views)
    views.sort(key=lambda view: (-counts[" + ".join(view["precursors"])], view["doi"] or ""))
    return views


def recipes(formula: str, synthesis_type: SynthesisType = "any", limit: int = 10) -> dict:
    """Published synthesis recipes for an inorganic material, with a summary.

    Recipes are text-mined from papers: precursors, the balanced reaction, and steps
    with temperatures, times, and atmospheres. Matching is by composition, however
    it is written (LiMn1.5Co0.5O4 = Li2CoMn3O8), so doped variants (e.g.
    Ba0.98La0.02SnO3 for BaSnO3) are separate: suggest_routes finds them.

    Args:
        formula: Chemical formula of the target, e.g. "LiCoO2".
        synthesis_type: "solid-state", "sol-gel", or "any".
        limit: How many individual recipes to return (the summary covers all).

    Returns:
        The number of recipes (by synthesis type), the most common precursor sets,
        the range of the highest heating temperature in °C, and up to ``limit``
        recipes (DOI and link, precursors, reaction, steps with temperature_c and
        time_h), most common precursor sets first.
    """
    composition = _composition(formula)
    views = _recipes_for(_key(composition), synthesis_type)
    return {
        "formula": composition.reduced_formula,
        "total": len(views),
        "by_type": dict(Counter(view["synthesis_type"] for view in views)),
        **_summary(views),
        "recipes": views[: max(limit, 0)],
    }


def suggest_routes(formula: str, count: int = 5, synthesis_type: SynthesisType = "any") -> dict:
    """Synthesis routes for a material from the most similar materials with published recipes.

    For a material without recipes of its own, the nearest compositions that have
    recipes (including doped and non-stoichiometric ones) suggest precursors and
    temperatures to start from; the element changes say what to adapt. A material
    with recipes is its own first route.

    Args:
        formula: Chemical formula of the target, e.g. "LiNi0.8Co0.1Mn0.1O2".
        count: How many source materials to suggest.
        synthesis_type: "solid-state", "sol-gel", or "any".

    Returns:
        For each source material, nearest first: its formula, composition distance,
        number of recipes, most common precursor sets, highest-temperature range in °C,
        the elements to add or remove relative to it, and its two most typical recipes.
    """
    if count < 1:
        raise ValueError("count must be at least 1.")
    target = _composition(formula)
    target_elements = {str(element) for element in target.elements}
    keys, search = _targets()
    names = _recipes()[2]
    depth = min(len(keys), 50 * count)
    distances, positions = search.kneighbors(_features(formula), n_neighbors=depth)
    routes = []
    for distance, position in zip(distances[0], positions[0], strict=True):
        views = _recipes_for(keys[position], synthesis_type)
        if not views:
            continue
        source = names[keys[position]]
        source_elements = {str(element) for element in _composition(source).elements}
        routes.append(
            {
                "source": source,
                "distance": round(float(distance), 4),
                "recipes": len(views),
                **_summary(views),
                "add_elements": sorted(target_elements - source_elements),
                "remove_elements": sorted(source_elements - target_elements),
                "examples": views[:2],
            }
        )
        if len(routes) == count:
            break
    return {"formula": target.reduced_formula, "routes": routes}
