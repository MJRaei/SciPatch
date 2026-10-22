"""Self-assembly conditions of peptides, from the most similar peptides with known conditions.

Wraps the curated data of peptide-agent (github.com/ndharms/peptide-agent): 989
records of peptide self-assembly (sequence, terminal groups, morphology, pH,
concentration, temperature, solvent, time) from SAPdb (Mathur et al., Comput. Biol.
Med. 2021) and published summaries. peptide-agent retrieves similar records for an
LLM that proposes conditions; here the retrieval ranks by sequence similarity and
the calling agent does the reasoning. Everything runs offline.

Sequences use one-letter amino-acid codes; lowercase letters are D-amino acids.
"""

from __future__ import annotations

import csv
import functools
import os
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Literal

Morphology = Literal["fiber", "sphere", "aggregate", "none"]

_SEQUENCE = re.compile(r"^[A-Za-z]+$")
#: The data's spellings of the same group or solvent.
_SAME = {
    "acetylation": "Acetylated",
    "amidation": "Amidated",
    "h2o": "water",
    "hepes": "HEPES",
    "ehylacetate": "ethyl acetate",
    "ethyl acetate": "ethyl acetate",
}


def _canonical(text: str) -> str:
    text = text.strip()
    return _SAME.get(text.lower(), text)


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _ph(text: str) -> tuple[float, float] | None:
    """A pH value or range ("7", "2–5") as (low, high)."""
    numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return None
    return min(numbers), max(numbers)


@functools.cache
def _records() -> list[dict[str, Any]]:
    folder = Path(os.environ["SCIPATCH_SOURCE_DIR"]) / "data"
    records, seen = [], set()
    for name in ("train_split.csv", "test_split.csv"):
        with open(folder / name, encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                sequence = row["PEPTIDE_CODE"].replace(" ", "")
                if not _SEQUENCE.match(sequence):
                    continue
                reference = row["Reference"].strip()
                doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", reference)
                is_doi = doi.startswith("10.")
                record = {
                    "sequence": sequence,
                    "n_terminal": _canonical(row["N-terminal"]),
                    "c_terminal": _canonical(row["C-terminal"]),
                    "morphology": row["Morphology"].strip().lower() or "none",
                    "ph": _ph(row["PH"]),
                    "concentration_mg_ml": _number(row["CONCENTRATION_mg ml"]),
                    "temperature_c": _number(row["TEMPERATURE_C"]),
                    "solvent": _canonical(row["SOLVENT"]) or None,
                    "time_min": _number(row["Time (min)"]),
                    "reference": f"https://doi.org/{doi}" if is_doi else reference,
                }
                key = tuple(record.items())
                if key not in seen:  # the data repeats some records
                    seen.add(key)
                    records.append(record)
    return records


def _distance(a: str, b: str) -> int:
    """Edit (Levenshtein) distance between two sequences."""
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def _similarity(a: str, b: str) -> float:
    """1 for identical sequences, 0 for nothing in common (1 - distance / longer length)."""
    return 1 - _distance(a, b) / max(len(a), len(b))


def _check(sequence: str) -> str:
    sequence = sequence.replace(" ", "")
    if not _SEQUENCE.match(sequence):
        raise ValueError(
            f"{sequence!r} is not a peptide sequence in one-letter codes (e.g. 'FF', 'KLVFFAE')."
        )
    return sequence


def _ranked(
    sequence: str, morphology: str, n_terminal: str, c_terminal: str
) -> list[dict[str, Any]]:
    """Records, most similar first; terminal groups that match the query break ties."""
    wanted = {"n_terminal": _canonical(n_terminal), "c_terminal": _canonical(c_terminal)}
    rows = []
    for record in _records():
        if morphology != "any" and record["morphology"] != morphology:
            continue
        same_ends = sum(
            wanted[key] == "any" or record[key].lower() == wanted[key].lower() for key in wanted
        )
        rows.append((_similarity(sequence, record["sequence"]), same_ends, record))
    rows.sort(key=lambda row: (-row[0], -row[1], row[2]["sequence"]))
    return [
        {**record, "similarity": round(similarity, 3), "terminal_groups_match": same_ends == 2}
        for similarity, same_ends, record in rows
    ]


def _view(record: dict[str, Any]) -> dict[str, Any]:
    ph = record["ph"]
    return {
        **record,
        "ph": None if ph is None else (ph[0] if ph[0] == ph[1] else f"{ph[0]:g}-{ph[1]:g}"),
    }


def similar_peptides(
    sequence: str,
    morphology: Literal["any", "fiber", "sphere", "aggregate", "none"] = "any",
    n_terminal: str = "any",
    c_terminal: str = "any",
    count: int = 10,
) -> dict:
    """Peptides with known self-assembly conditions most similar to a sequence.

    Args:
        sequence: Peptide in one-letter codes, e.g. "FF" or "KLVFFAE" (lowercase = D).
        morphology: Only records with this outcome: "fiber", "sphere", "aggregate",
            "none" (no assembly reported), or "any".
        n_terminal: N-terminal group to prefer, e.g. "Free", "Fmoc", "Boc",
            "Acetylated", or "any".
        c_terminal: C-terminal group to prefer, e.g. "Free", "Amidated", "Methoxy",
            or "any".
        count: How many records to return.

    Returns:
        Records, most similar first: sequence, terminal groups, morphology, pH,
        concentration in mg/mL, temperature in °C, solvent, time in minutes, the
        reference (a DOI link, or the record number of the source compilation), and
        similarity (1 = same sequence; 1 - edit distance / longer length).
    """
    if count < 1:
        raise ValueError("count must be at least 1.")
    ranked = _ranked(_check(sequence), morphology, n_terminal, c_terminal)
    return {"sequence": sequence, "matches": [_view(record) for record in ranked[:count]]}


def _spread(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "median": round(statistics.median(values), 3),
        "min": min(values),
        "max": max(values),
        "records": len(values),
    }


def suggest_conditions(
    sequence: str,
    morphology: Morphology = "fiber",
    n_terminal: str = "Free",
    c_terminal: str = "Free",
    neighbors: int = 10,
) -> dict:
    """Conditions to try for a peptide to self-assemble into a morphology, from similar peptides.

    Summarizes the conditions of the most similar peptides that formed the target
    morphology (records with the same terminal groups come first among equally
    similar sequences).

    Args:
        sequence: Peptide in one-letter codes (lowercase = D-amino acid).
        morphology: Target outcome: "fiber", "sphere", "aggregate", or "none".
        n_terminal: N-terminal group of the peptide, e.g. "Free", "Fmoc", "Boc".
        c_terminal: C-terminal group of the peptide, e.g. "Free", "Amidated".
        neighbors: How many similar records to summarize.

    Returns:
        pH, concentration (mg/mL), temperature (°C), and time (min) as median, range,
        and number of records; solvents by count; how similar the records are; and
        the records themselves with their references.
    """
    if neighbors < 1:
        raise ValueError("neighbors must be at least 1.")
    records = _ranked(_check(sequence), morphology, n_terminal, c_terminal)[:neighbors]
    if not records:
        raise ValueError(f"The data has no records with morphology {morphology!r}.")
    middles = [(record["ph"][0] + record["ph"][1]) / 2 for record in records if record["ph"]]
    solvents = Counter(record["solvent"] for record in records if record["solvent"])
    return {
        "sequence": sequence,
        "morphology": morphology,
        "ph": _spread(middles),
        "concentration_mg_ml": _spread(
            [r["concentration_mg_ml"] for r in records if r["concentration_mg_ml"] is not None]
        ),
        "temperature_c": _spread(
            [r["temperature_c"] for r in records if r["temperature_c"] is not None]
        ),
        "time_min": _spread([r["time_min"] for r in records if r["time_min"] is not None]),
        "solvents": [{"solvent": name, "records": n} for name, n in solvents.most_common()],
        "similarity": {
            "best": records[0]["similarity"],
            "worst": records[-1]["similarity"],
            "same_sequence": sum(r["similarity"] == 1 for r in records),
        },
        "records": [_view(record) for record in records],
    }
