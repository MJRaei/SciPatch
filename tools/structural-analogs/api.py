"""Materials with the same crystal structure type, from the Materials Project, for analogies.

Wraps the analog search of mp-property-analogies (github.com/ahaibel/mp-property-analogies):
Materials Project entries with the reference's anonymous formula (e.g. ABC3) and space
group are compared with pymatgen's StructureMatcher, ignoring the elements (ltol 0.35,
stol 0.6, angle tolerance 10°), and kept when they match with a normalized RMS
displacement of at most 0.3 (looser matches can be another structure type: zinc blende
matches rock salt at 0.43). The project then asked an LLM
to estimate the reference's properties from its analogs; here the calling agent does
that. Needs MP_API_KEY.
"""

from __future__ import annotations

import contextlib
import os
import statistics
import warnings
from collections.abc import Iterator
from typing import Any

# The project's matching settings (mp_structural_analogs.py).
LENGTH_TOLERANCE = 0.35
SITE_TOLERANCE = 0.6
ANGLE_TOLERANCE = 10.0
_KEY_URL = "https://next-gen.materialsproject.org/api"
_FIELDS = [
    "material_id", "formula_pretty", "formula_anonymous", "structure", "symmetry",
    "band_gap", "formation_energy_per_atom", "energy_above_hull", "is_stable",
    "volume", "nsites", "theoretical",
]  # fmt: skip


@contextlib.contextmanager
def _rester() -> Iterator[Any]:
    """An authenticated Materials Project client; a rejected key becomes a clear error."""
    from mp_api.client import MPRester

    warnings.filterwarnings("ignore")
    key = os.environ.get("MP_API_KEY")
    if not key:
        raise ValueError(f"MP_API_KEY is not set. Get a free key at {_KEY_URL}.")
    try:
        with MPRester(api_key=key, mute_progress_bars=True) as rester:
            yield rester
    except Exception as exc:
        if "401" in str(exc) or "403" in str(exc):
            raise ValueError(
                f"The Materials Project rejected the API key. Check it at {_KEY_URL} and "
                "store it again with 'scipatch secret set MP_API_KEY'."
            ) from exc
        raise


def _properties(doc: Any) -> dict[str, Any]:
    return {
        "material_id": str(doc.material_id),
        "formula": doc.formula_pretty,
        "band_gap_ev": doc.band_gap,
        "formation_energy_ev_per_atom": doc.formation_energy_per_atom,
        "energy_above_hull_ev_per_atom": doc.energy_above_hull,
        "is_stable": doc.is_stable,
        "volume_per_atom_angstrom3": round(doc.volume / doc.nsites, 4) if doc.nsites else None,
        "experimentally_known": None if doc.theoretical is None else not doc.theoretical,
    }


def _kinship(reference: list[Any], composition: Any) -> int:
    """How many of the reference's elements the analog has, or replaces by one of the same group."""
    elements = composition.elements
    return sum(
        any(element == mine or element.group == mine.group for element in elements)
        for mine in reference
    )


def _stability(analog: dict[str, Any]) -> float:
    value = analog["energy_above_hull_ev_per_atom"]
    return float("inf") if value is None else value


def _spread(values: list[float]) -> dict[str, float] | None:
    values = [value for value in values if value is not None]
    if not values:
        return None
    return {
        "median": round(statistics.median(values), 4),
        "min": min(values),
        "max": max(values),
        "materials": len(values),
    }


def structural_analogs(
    material_id: str | None = None,
    structure: str | None = None,
    count: int = 30,
    max_rms: float = 0.3,
) -> dict:
    """Materials Project compounds with the same crystal structure type, and their properties.

    Give either a Materials Project ID or a structure file (for a material that is not
    in the database). Candidates share the reference's anonymous formula and space
    group; they count as analogs when pymatgen's StructureMatcher maps one structure
    onto the other with the elements ignored.

    Args:
        material_id: Materials Project ID of the reference, e.g. "mp-22862" (NaCl).
        structure: Structure file of the reference (CIF, POSCAR, extended XYZ).
        count: How many analogs to return, best first.
        max_rms: Largest RMS displacement, normalized by (volume per site)^(1/3), for a
            match to count; looser matches are often a different structure type.

    Returns:
        The reference (formula, anonymous formula, space group, and its properties if it
        is in the database); the number of candidates compared and of analogs; the
        analogs, best first: the closest structural matches and, among those, the ones
        with the most of the reference's elements or same-group replacements (kinship),
        then the most stable. Each has its ID, formula, RMS displacement normalized by
        (volume per site)^(1/3), band gap in eV, formation energy and energy above the
        hull in eV/atom, stability, volume per atom, and whether it is known from
        experiment. Also the median and range of each property over all analogs, and
        the database version.
    """
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    if (material_id is None) == (structure is None):
        raise ValueError("Give either material_id or structure (one of them).")
    if count < 1:
        raise ValueError("count must be at least 1.")
    local = None
    if structure is not None:
        try:
            local = Structure.from_file(structure)
        except Exception as exc:
            raise ValueError(f"Could not read a crystal structure from {structure}.") from exc
    with _rester() as rester:
        version = rester.get_database_version()
        if local is not None:
            analyzer = SpacegroupAnalyzer(local, symprec=0.01, angle_tolerance=5)
            reference_structure = local
            anonymous = local.composition.anonymized_formula
            space_group = analyzer.get_space_group_number()
            reference: dict[str, Any] = {
                "formula": local.composition.reduced_formula,
                "space_group_symbol": analyzer.get_space_group_symbol(),
            }
        else:
            docs = rester.materials.summary.search(material_ids=[material_id], fields=_FIELDS)
            if not docs:
                raise ValueError(f"No Materials Project material {material_id!r}.")
            doc = docs[0]
            reference_structure = doc.structure
            anonymous = doc.formula_anonymous
            space_group = doc.symmetry.number
            reference = {**_properties(doc), "space_group_symbol": doc.symmetry.symbol}
        reference.update({"anonymous_formula": anonymous, "space_group_number": space_group})
        print(f"Fetching {anonymous} compounds in space group {space_group}", flush=True)
        candidates = rester.materials.summary.search(
            formula=anonymous, spacegroup_number=space_group, fields=_FIELDS
        )
    matcher = StructureMatcher(
        ltol=LENGTH_TOLERANCE,
        stol=SITE_TOLERANCE,
        angle_tol=ANGLE_TOLERANCE,
        primitive_cell=True,
        scale=True,
        attempt_supercell=True,
    )
    reference_elements = reference_structure.composition.elements
    analogs, compared, loose = [], 0, 0
    for number, doc in enumerate(candidates, 1):
        if number % 100 == 0:
            print(f"compared {number}/{len(candidates)}", flush=True)
        if str(doc.material_id) == material_id or doc.structure is None:
            continue
        compared += 1
        found = None
        with contextlib.suppress(Exception):  # the matcher fails on some odd cells
            found = matcher.get_rms_anonymous(reference_structure, doc.structure)
        if found is None or found[0] is None:  # not the same structure type
            continue
        if found[0] > max_rms:
            loose += 1
            continue
        kinship = _kinship(reference_elements, doc.structure.composition)
        analogs.append({**_properties(doc), "rms": round(float(found[0]), 4), "kinship": kinship})
    # Among equally good structural matches: chemically closest, then most stable, first.
    analogs.sort(
        key=lambda analog: (
            round(analog["rms"], 2),
            -analog["kinship"],
            _stability(analog),
            analog["material_id"],
        )
    )
    return {
        "reference": reference,
        "candidates": compared,
        "loose_matches_left_out": loose,
        "analogs_found": len(analogs),
        "formulas": [analog["formula"] for analog in analogs[:count]],
        "analogs": analogs[:count],
        "properties": {
            key: _spread([analog[key] for analog in analogs])
            for key in (
                "band_gap_ev",
                "formation_energy_ev_per_atom",
                "energy_above_hull_ev_per_atom",
                "volume_per_atom_angstrom3",
            )
        },
        "database_version": version,
    }
