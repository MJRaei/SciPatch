"""Explaining a metallicity model with crystal counterfactuals, from CLUE.

Wraps CLUE, Crystal Learning for Understandable Explanations (E. Patyukova,
github.com/epatyukova/llm2025-hackathon-CLUE, 2025 LLM Hackathon): a random-forest
classifier of metallic versus non-metallic crystals (trained on JARVIS-DFT with
matminer composition and structure features and SOAP descriptors), a crystal
similarity combining the element mover's distance, orbit-matched SOAP
descriptors, and volume per atom, and a search of the Materials Project for
counterfactuals: similar compounds the model classifies the other way. CLUE asks
GPT-4.1-mini to explain the differences; here the calling agent does that, for
example with robocrystallographer descriptions of the counterfactuals.
"""

from __future__ import annotations

import functools
import os
import sys
import warnings
from pathlib import Path

import numpy as np

WEIGHTS = {"composition": 0.3, "structure": 0.5, "volume": 0.2}  # CLUE's defaults


@functools.cache
def _source() -> Path:
    warnings.filterwarnings("ignore")
    root = Path(os.environ["MOTEL_SOURCE_DIR"])
    code = str(root / "clue")
    if code not in sys.path:
        sys.path.insert(0, code)
    return root


@functools.cache
def _model():
    import pickle

    # CLUE's trained model, from the pinned commit of its repository.
    with open(_source() / "data" / "RF_is_metal.pkl", "rb") as handle:
        return pickle.load(handle)  # noqa: S301


def _structure(path: str):
    from pymatgen.core import Structure

    file = Path(path)
    if not file.is_file():
        raise ValueError(f"Structure file {path!r} not found.")
    try:
        return Structure.from_file(file)
    except Exception as exc:
        raise ValueError(f"Could not read {file.name} as a crystal structure: {exc}") from exc


def _features(structures) -> np.ndarray:
    """CLUE's 404 features: matminer composition and structure features and SOAP."""
    import pandas as pd
    from models import matminer_composition_features, matminer_structure_features, soap_features

    frame = pd.DataFrame(
        {"formula": [s.formula for s in structures], "structure": list(structures)}
    )
    composition = matminer_composition_features(
        frame, ["ElementProperty", "Stoichiometry", "ValenceOrbital"]
    )
    structure = matminer_structure_features(frame, ["GlobalSymmetryFeatures", "DensityFeatures"])
    return np.concatenate([composition, structure, soap_features(frame)], axis=1)


def _predict(structures) -> tuple[np.ndarray, np.ndarray]:
    model = _model()
    features = _features(structures)
    labels = model.predict(features)
    metal_column = list(model.classes_).index(1)
    return labels, model.predict_proba(features)[:, metal_column]


def predict_metallicity(structure: str) -> dict:
    """Is a crystal metallic? CLUE's random-forest prediction.

    Args:
        structure: Crystal structure file (CIF, POSCAR, ...).

    Returns:
        The prediction (metal or non-metal), the fraction of the forest's 100
        trees voting "metal", the reduced formula, and the model's reported test
        performance.
    """
    _source()
    crystal = _structure(structure)
    labels, votes = _predict([crystal])
    return {
        "structure": Path(structure).name,
        "formula": crystal.composition.reduced_formula,
        "is_metal": bool(labels[0] == 1),
        "prediction": "metal" if labels[0] == 1 else "non-metal",
        "metal_vote_fraction": round(float(votes[0]), 4),
        "model": "random forest (100 trees) on matminer and SOAP features, "
        "trained on JARVIS-DFT 3D",
        "reported_test_performance": {"accuracy": 0.92, "matthews_corrcoef": 0.81, "f1": 0.94},
    }


def _similarities(sample, candidates) -> list[dict]:
    """CLUE's three similarities of each candidate to the sample (unscaled composition term)."""
    import pandas as pd
    from distance import structure_similarity, volume_similarity
    from ElMD import ElMD

    frame = pd.DataFrame({"structure": list(candidates)})
    frame = volume_similarity(sample, frame, lam_vol=2.0)
    frame = structure_similarity(sample, frame)
    elmd = ElMD(sample.formula, metric="mod_petti")
    distances = [float(elmd.elmd(c.formula)) for c in candidates]
    return [
        {
            "composition_distance_elmd": round(d, 5),
            "volume_similarity": round(float(v), 5),
            "structure_similarity": round(float(s), 5),
        }
        for d, v, s in zip(
            distances, frame["vol_similarity"], frame["struct_similarity"], strict=True
        )
    ]


def similarity(structure_a: str, structure_b: str) -> dict:
    """CLUE's similarity between two crystal structures.

    Args:
        structure_a: First crystal structure file.
        structure_b: Second crystal structure file.

    Returns:
        Composition distance (element mover's distance on the modified Pettifor
        scale; 0 for the same composition) and similarity exp(-distance);
        structure similarity (symmetry-orbit SOAP descriptors matched across
        species, 0-1); volume-per-atom similarity exp(-|dV|/2 Angstrom3); and
        their weighted total (0.3, 0.5, 0.2).
    """
    _source()
    a, b = _structure(structure_a), _structure(structure_b)
    values = _similarities(a, [b])[0]
    composition = float(np.exp(-values["composition_distance_elmd"]))
    total = (
        WEIGHTS["composition"] * composition
        + WEIGHTS["structure"] * values["structure_similarity"]
        + WEIGHTS["volume"] * values["volume_similarity"]
    )
    return {
        "a": a.composition.reduced_formula,
        "b": b.composition.reduced_formula,
        **values,
        "composition_similarity": round(composition, 5),
        "total_similarity": round(total, 5),
        "weights": WEIGHTS,
    }


def counterfactuals(
    structure: str,
    top: int = 10,
    neighbours: int = 5,
    output_dir: str = "counterfactuals",
) -> dict:
    """Similar Materials Project compounds that the model classifies the other way.

    Candidates are Materials Project compounds (the most stable structure of each
    formula) made only of the sample's elements and their nearest neighbours on
    CLUE's element scale; each is classified, and those with the opposite
    prediction are ranked by CLUE's total similarity to the sample (the
    composition term scaled by the largest distance among candidates, as in
    CLUE). Needs a Materials Project API key; can take several minutes.

    Args:
        structure: Crystal structure file of the sample.
        top: Number of counterfactuals to return (and write as CIF).
        neighbours: Elements added per sample element as substitution candidates.
        output_dir: Folder for the counterfactuals' CIF files.

    Returns:
        The sample's prediction and, for each counterfactual: Materials Project
        id, formula, prediction, the similarity components and total, energy
        above hull, formation energy, and CIF file; plus the number of candidates
        considered.
    """
    _source()
    from distance import (
        composition_similarity,
        structure_similarity,
        total_similarity,
        volume_similarity,
    )

    key = os.environ.get("MP_API_KEY")
    if not key:
        raise ValueError("A Materials Project API key is needed (MP_API_KEY).")
    if not 1 <= top <= 50 or not 1 <= neighbours <= 10:
        raise ValueError("top must be 1-50 and neighbours 1-10.")
    sample = _structure(structure)
    label, vote = _predict([sample])
    frame = _mp_candidates(sample, key, neighbours)
    if frame.empty:
        raise ValueError("The Materials Project has no candidates for these elements.")
    frame = composition_similarity(sample, frame)
    frame = volume_similarity(sample, frame, lam_vol=2.0)
    frame = structure_similarity(sample, frame)
    frame = total_similarity(frame, w_comp=0.3, w_struct=0.5, w_vol=0.2)
    labels, votes = _predict(list(frame["structure"]))
    frame["predicted"] = labels
    frame["metal_vote"] = votes
    opposite = (
        frame[frame["predicted"] != label[0]]
        .sort_values("total_similarity", ascending=False)
        .head(top)
    )
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for _, row in opposite.iterrows():
        cif = folder / f"{row['id']}_{row['structure'].composition.reduced_formula}.cif"
        row["structure"].to(filename=str(cif))
        rows.append(
            {
                "material_id": str(row["id"]),
                "formula": row["structure"].composition.reduced_formula,
                "prediction": "metal" if row["predicted"] == 1 else "non-metal",
                "metal_vote_fraction": round(float(row["metal_vote"]), 4),
                "total_similarity": round(float(row["total_similarity"]), 5),
                "composition_similarity": round(float(row["comp_similarity"]), 5),
                "structure_similarity": round(float(row["struct_similarity"]), 5),
                "volume_similarity": round(float(row["vol_similarity"]), 5),
                "energy_above_hull_ev_per_atom": float(row["energy_above_hull"]),
                "formation_energy_ev_per_atom": float(row["form_energy"]),
                "cif": str(cif),
            }
        )
    return {
        "sample": {
            "formula": sample.composition.reduced_formula,
            "prediction": "metal" if label[0] == 1 else "non-metal",
            "metal_vote_fraction": round(float(vote[0]), 4),
        },
        "candidates_considered": len(frame),
        "counterfactuals": rows,
        "next_step": "Compare the sample with the counterfactuals (e.g. robocrys.describe on "
        "each CIF) to explain what the model's decision depends on.",
    }


MP_SUMMARY = "https://api.materialsproject.org/materials/summary/"


def _mp_get(key: str, params: dict) -> list[dict]:
    import time

    import requests

    for attempt in range(4):
        try:
            response = requests.get(
                MP_SUMMARY, headers={"X-API-KEY": key}, params=params, timeout=120
            )
        except requests.RequestException as exc:
            if attempt == 3:
                raise RuntimeError(f"The Materials Project could not be reached: {exc}") from exc
            time.sleep(2 * (attempt + 1))
            continue
        if response.status_code in (401, 403):
            raise ValueError("The Materials Project rejected the API key (MP_API_KEY).")
        if response.status_code in (429, 502, 503, 504) and attempt < 3:
            time.sleep(2 * (attempt + 1))
            continue
        response.raise_for_status()
        return response.json()["data"]
    return []


def _mp_candidates(sample, key: str, neighbours: int):
    """CLUE's candidate list (mp_crystals.get_list_of_crystals_from_mp), queried directly.

    Same selection: compounds containing a sample element and made only of the sample's
    elements and their nearest neighbours on CLUE's element scale, keeping the lowest
    formation energy entry of each formula. (CLUE's pinned mp-api cannot read the
    Materials Project's current material ids.)
    """
    import heapq

    import pandas as pd
    from distance import pettifor_scale
    from pymatgen.core import Structure

    def closest(element: str) -> list[str]:  # mp_crystals.get_closest_elements
        if element not in pettifor_scale:
            return []
        target = pettifor_scale[element]
        pairs = [(abs(v - target), e) for e, v in pettifor_scale.items() if e != element]
        return [e for _, e in heapq.nsmallest(neighbours, pairs, key=lambda x: x[0])]

    elements = [e.symbol for e in sample.composition.elements]  # without oxidation states
    allowed = set()
    for element in elements:
        allowed.update([element, *closest(element)])
    fields = "material_id,formula_pretty,elements,formation_energy_per_atom,energy_above_hull"
    docs: dict[str, dict] = {}
    for element in elements:
        skip = 0
        while True:
            params = {"elements": element, "deprecated": "false", "_fields": fields}
            page = _mp_get(key, {**params, "_limit": 1000, "_skip": skip})
            for doc in page:
                if set(doc["elements"]) <= allowed:
                    docs.setdefault(doc["material_id"], doc)
            if len(page) < 1000:
                break
            skip += 1000
    best: dict[str, dict] = {}
    for doc in docs.values():
        formula = doc["formula_pretty"]
        energy = doc.get("formation_energy_per_atom")
        if energy is None:
            continue
        if formula not in best or energy < best[formula]["formation_energy_per_atom"]:
            best[formula] = doc
    ids = sorted(best[f]["material_id"] for f in best)
    structures = {}
    for start in range(0, len(ids), 100):
        chunk = ",".join(ids[start : start + 100])
        params = {"material_ids": chunk, "_fields": "material_id,structure", "_limit": 100}
        for doc in _mp_get(key, params):
            structures[doc["material_id"]] = Structure.from_dict(doc["structure"])
    rows = [
        {
            "id": best[f]["material_id"],
            "formula": f,
            "structure": structures[best[f]["material_id"]],
            "energy_above_hull": best[f].get("energy_above_hull"),
            "form_energy": best[f]["formation_energy_per_atom"],
        }
        for f in sorted(best)
        if best[f]["material_id"] in structures
    ]
    columns = ["id", "formula", "structure", "energy_above_hull", "form_energy"]
    return pd.DataFrame(rows, columns=columns)
