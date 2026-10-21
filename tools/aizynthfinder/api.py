"""Retrosynthesis planning with AiZynthFinder: synthesis routes from purchasable compounds.

A neural network trained on reaction templates from US patents (USPTO) proposes
disconnections; a Monte Carlo tree search combines them into routes that end in
compounds of a stock. The default stock is the 17.4 million purchasable compounds
of ZINC (April 2020); add your own inventory as SMILES.
"""

from __future__ import annotations

import functools
import json
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np

DATA = Path(sys.prefix) / "share" / "aizynthfinder"


def _config(ring_breaker: bool) -> dict:
    """A fresh configuration (AiZynthFinder consumes the dictionary it is given)."""
    expansion = {"uspto": [str(DATA / "uspto_model.onnx"), str(DATA / "uspto_templates.csv.gz")]}
    if ring_breaker:
        expansion["ringbreaker"] = [
            str(DATA / "uspto_ringbreaker_model.onnx"),
            str(DATA / "uspto_ringbreaker_templates.csv.gz"),
        ]
    return {"expansion": expansion, "filter": {"uspto": str(DATA / "uspto_filter_model.onnx")}}


@functools.cache
def _quiet() -> None:
    warnings.filterwarnings("ignore")
    from rdkit import RDLogger

    RDLogger.DisableLog("rdApp.*")


def _molecule(smiles: str) -> Any:
    _quiet()
    from aizynthfinder.chem import Molecule
    from rdkit import Chem

    if not smiles or Chem.MolFromSmiles(smiles) is None:
        raise ValueError(f"Could not parse the SMILES {smiles!r}.")
    return Molecule(smiles=smiles, sanitize=True)


def _stock_query(keys: np.ndarray) -> Any:
    from aizynthfinder.context.stock.queries import StockQueryMixin

    class SortedInchiKeys(StockQueryMixin):
        """Membership by binary search in a sorted array of InChIKeys."""

        def __len__(self) -> int:
            return len(keys)

        def __contains__(self, mol: Any) -> bool:
            key = mol.inchi_key.encode()
            index = int(np.searchsorted(keys, key))
            return index < len(keys) and keys[index] == key

    return SortedInchiKeys()


@functools.cache
def _zinc() -> np.ndarray:
    return np.load(DATA / "zinc_stock_inchikeys.npy", mmap_mode="r")


def _custom_keys(custom_stock: list[str] | str | None) -> np.ndarray | None:
    if custom_stock is None:
        return None
    if isinstance(custom_stock, str):
        lines = Path(custom_stock).read_text(encoding="utf-8").splitlines()
        smiles = [line.split()[0] for line in lines if line.strip() and not line.startswith("#")]
    else:
        smiles = list(custom_stock)
    keys = {_molecule(text).inchi_key.encode() for text in smiles}
    return np.array(sorted(keys), dtype="S27")


def _load_stock(stock: Any, use_zinc: bool, custom: np.ndarray | None) -> list[str]:
    selected = []
    if use_zinc:
        stock.load(_stock_query(_zinc()), "zinc")
        selected.append("zinc")
    if custom is not None:
        stock.load(_stock_query(custom), "custom")
        selected.append("custom")
    if not selected:
        raise ValueError("Use the ZINC stock, a custom stock, or both.")
    stock.select(selected)
    return selected


def _availability(stock: Any, mol: Any) -> list[str]:
    return [key for key in stock.selection or [] if mol in stock[key]]


def _reaction(reaction: Any) -> dict:
    metadata = reaction.metadata
    probability = metadata.get("policy_probability")
    return {
        "product": reaction.mol.smiles,
        "reactants": [mol.smiles for mol in reaction.reactants[0]],
        "reaction_smiles": reaction.reaction_smiles(),
        "policy_probability": None if probability is None else round(float(probability), 4),
        "template_occurrences": metadata.get("library_occurence"),
    }


def retrosynthesis(
    target: str,
    max_routes: int = 5,
    iteration_limit: int = 100,
    time_limit_s: float = 120.0,
    max_steps: int = 6,
    ring_breaker: bool = False,
    custom_stock: list[str] | str | None = None,
    use_zinc: bool = True,
    image_prefix: str = "route",
    routes_file: str = "routes.json",
) -> dict:
    """Plan synthesis routes from purchasable starting materials (multi-step retrosynthesis).

    Args:
        target: SMILES of the molecule to make.
        max_routes: Number of best routes to return.
        iteration_limit: Monte Carlo tree search iterations; more explores more
            disconnections.
        time_limit_s: Stop searching after this many seconds.
        max_steps: Longest route considered (reactions from the target down).
        ring_breaker: Also use the ring-breaker policy, which proposes
            ring-forming reactions (useful for heterocycles and fused rings).
        custom_stock: Your own available compounds: SMILES, or a path to a text
            file with one SMILES per line.
        use_zinc: Count the 17.4 million ZINC purchasable compounds as available.
        image_prefix: Route images are written to <prefix>_1.png, <prefix>_2.png, ...
        routes_file: JSON file with the full route trees (AiZynthFinder format).

    Returns:
        Whether a route ending entirely in available compounds was found, search
        statistics, and the routes ranked by score: for each, whether it is solved,
        the number of steps, the starting materials and where they are available,
        the reactions in forward order (starting materials first) with the
        template network's probability and how often the template occurs in the
        patent data, and an image path.
    """
    if max_routes < 1 or iteration_limit < 1 or max_steps < 1 or time_limit_s <= 0:
        raise ValueError(
            "max_routes, iteration_limit, max_steps, and time_limit_s must be positive."
        )
    target_mol = _molecule(target)
    custom = _custom_keys(custom_stock)
    from aizynthfinder.aizynthfinder import AiZynthFinder
    from aizynthfinder.analysis.utils import RouteSelectionArguments

    finder = AiZynthFinder(configdict=_config(ring_breaker))
    _load_stock(finder.stock, use_zinc, custom)
    finder.expansion_policy.select(["uspto", "ringbreaker"] if ring_breaker else ["uspto"])
    finder.filter_policy.select("uspto")
    search = finder.config.search
    search.iteration_limit = iteration_limit
    search.time_limit = time_limit_s
    search.max_transforms = max_steps
    finder.target_smiles = target_mol.smiles
    started = time.time()
    finder.prepare_tree()
    finder.tree_search()
    finder.build_routes(RouteSelectionArguments(nmin=max_routes, nmax=max_routes))
    statistics = finder.extract_statistics()
    print(f"Search finished in {time.time() - started:.1f} s", flush=True)

    collection = finder.routes
    images = collection.make_images() if len(collection) else []
    routes = []
    for index, tree in enumerate(collection.reaction_trees[:max_routes]):
        image = f"{image_prefix}_{index + 1}.png"
        images[index].save(image)
        routes.append(
            {
                "rank": index + 1,
                "score": round(float(collection.scores[index]["state score"]), 4),
                "solved": bool(tree.is_solved),
                "steps": len(list(tree.reactions())),
                "starting_materials": [
                    {"smiles": mol.smiles, "available_in": _availability(finder.stock, mol)}
                    for mol in tree.leafs()
                ],
                "reactions": [_reaction(reaction) for reaction in reversed(list(tree.reactions()))],
                "image": image,
            }
        )
    with open(routes_file, "w", encoding="utf-8") as handle:
        json.dump(collection.dicts[:max_routes], handle, indent=1)
    return {
        "target": target_mol.smiles,
        "solved": bool(statistics["is_solved"]),
        "search_time_s": round(float(statistics["search_time"]), 2),
        "first_solution_time_s": round(float(statistics["first_solution_time"]), 2)
        if statistics["is_solved"]
        else None,
        "iterations": statistics["profiling"]["iterations"],
        "routes_found": statistics["number_of_routes"],
        "solved_routes_found": statistics["number_of_solved_routes"],
        "routes": routes,
        "routes_file": routes_file,
    }


def single_step(
    target: str,
    max_suggestions: int = 10,
    ring_breaker: bool = False,
    custom_stock: list[str] | str | None = None,
) -> dict:
    """Possible immediate precursors of a molecule (one retrosynthetic step).

    Args:
        target: SMILES of the product.
        max_suggestions: Number of distinct precursor sets to return.
        ring_breaker: Also use the ring-breaker policy (ring-forming reactions).
        custom_stock: Your own available compounds (SMILES, or a file with one
            SMILES per line), reported next to ZINC availability.

    Returns:
        Suggestions ranked by the template network: precursors with where they
        are available, the reaction SMILES, the template probability, the
        feasibility estimated by the filter network (0 to 1), and how often the
        template occurs in the patent data.
    """
    if max_suggestions < 1:
        raise ValueError("max_suggestions must be positive.")
    target_mol = _molecule(target)
    custom = _custom_keys(custom_stock)
    from aizynthfinder.aizynthfinder import AiZynthExpander
    from aizynthfinder.context.stock import Stock

    expander = AiZynthExpander(configdict=_config(ring_breaker))
    expander.expansion_policy.select(["uspto", "ringbreaker"] if ring_breaker else ["uspto"])
    expander.filter_policy.select("uspto")
    stock = Stock()
    _load_stock(stock, True, custom)
    suggestions = []
    for group in expander.do_expansion(target_mol.smiles, return_n=max_suggestions):
        best = max(group, key=lambda r: r.metadata.get("policy_probability", 0.0))
        row = _reaction(best)
        feasibility = best.metadata.get("feasibility")
        suggestions.append(
            {
                "precursors": [
                    {"smiles": mol.smiles, "available_in": _availability(stock, mol)}
                    for mol in best.reactants[0]
                ],
                "reaction_smiles": row["reaction_smiles"],
                "policy_probability": row["policy_probability"],
                "feasibility": None if feasibility is None else round(float(feasibility), 3),
                "template_occurrences": row["template_occurrences"],
            }
        )
    return {"target": target_mol.smiles, "suggestions": suggestions}


def in_stock(molecules: list[str], custom_stock: list[str] | str | None = None) -> dict:
    """Which molecules are purchasable (ZINC, April 2020) or in your own stock.

    Args:
        molecules: SMILES to look up.
        custom_stock: Your own available compounds (SMILES, or a file with one
            SMILES per line).

    Returns:
        For each molecule: canonical SMILES, InChIKey, and the stocks it is in.
    """
    from aizynthfinder.context.stock import Stock

    stock = Stock()
    _load_stock(stock, True, _custom_keys(custom_stock))
    rows = []
    for text in molecules:
        mol = _molecule(text)
        rows.append(
            {
                "smiles": mol.smiles,
                "inchi_key": mol.inchi_key,
                "available_in": _availability(stock, mol),
            }
        )
    return {"molecules": rows, "zinc_compounds": len(_zinc())}
