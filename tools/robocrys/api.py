"""Describe crystal structures in words with robocrystallographer.

robocrystallographer (Ganose and Jain, 2019) finds bonds with CrystalNN, names
coordination polyhedra and how they connect (corner, edge, or face sharing),
splits the structure into molecules, chains, layers, or frameworks, and matches
it to known mineral prototypes. Coordination polyhedra are also identified with
pymatgen's ChemEnv (continuous symmetry measures); where robocrystallographer
has no name for a polyhedron (trigonal prisms, as in MoS2), ChemEnv's is used.
"""

from __future__ import annotations

import functools
import logging
import warnings
from pathlib import Path
from typing import Literal

Format = Literal["raw", "unicode", "html", "latex"]

#: ChemEnv symbols for polyhedra that robocrystallographer's geometry
#: fingerprints cannot name, with the names used in descriptions.
CHEMENV_ONLY = {"T:6": ("trigonal prismatic", "trigonal prism", "trigonal prisms")}


@functools.cache
def _quiet() -> None:
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    from robocrys.util import util

    for name, single, plural in CHEMENV_ONLY.values():
        util.geometry_to_polyhedra.setdefault(name, single)
        util.polyhedra_plurals.setdefault(single, plural)


def _structure(path: str, oxidation_states: bool):
    from pymatgen.core import Structure

    file = Path(path)
    if not file.is_file():
        raise ValueError(f"Structure file {path!r} not found.")
    try:
        structure = Structure.from_file(file)
    except Exception as exc:
        raise ValueError(f"Could not read {file.name} as a crystal structure: {exc}") from exc
    note = None
    has_oxidation = any(hasattr(s, "oxi_state") for s in structure.composition.elements)
    if oxidation_states and not has_oxidation:
        try:  # as robocrystallographer's command line does
            structure.add_oxidation_state_by_guess(max_sites=-80)
        except ValueError:
            note = "Oxidation states could not be assigned; the description omits them."
    return structure, note


def _prepared(structure, symprec: float, conventional: bool):
    """The structure exactly as StructureCondenser analyses it (same site order)."""
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    structure = structure.get_sorted_structure()
    structure.translate_sites(range(structure.num_sites), [1, 1, 1])
    analyzer = SpacegroupAnalyzer(structure, symprec=symprec)
    if conventional:
        return analyzer.get_conventional_standard_structure()
    return analyzer.get_symmetrized_structure()


def _chemenv(structure, indices) -> dict[int, dict]:
    from pymatgen.analysis.chemenv.coordination_environments.chemenv_strategies import (
        SimplestChemenvStrategy,
    )
    from pymatgen.analysis.chemenv.coordination_environments.coordination_geometries import (
        AllCoordinationGeometries,
    )
    from pymatgen.analysis.chemenv.coordination_environments.coordination_geometry_finder import (
        LocalGeometryFinder,
    )
    from pymatgen.analysis.chemenv.coordination_environments.structure_environments import (
        LightStructureEnvironments,
    )

    finder = LocalGeometryFinder()
    finder.setup_structure(structure)
    environments = finder.compute_structure_environments(
        maximum_distance_factor=1.41, only_indices=list(indices), only_cations=False
    )
    light = LightStructureEnvironments.from_structure_environments(
        strategy=SimplestChemenvStrategy(), structure_environments=environments
    )
    geometries = AllCoordinationGeometries()
    result = {}
    for index in indices:
        found = light.coordination_environments[index]
        if not found:
            continue
        best = found[0]
        symbol = best["ce_symbol"]
        try:
            name = geometries.get_geometry_from_mp_symbol(symbol).name
        except LookupError:
            name = symbol
        result[index] = {
            "symbol": symbol,
            "name": name,
            "coordination_number": int(symbol.split(":")[1]) if ":" in symbol else None,
            "continuous_symmetry_measure": round(float(best["csm"]), 4),
        }
    return result


def _condense(structure, symprec: float, conventional: bool):
    from robocrys import StructureCondenser

    condenser = StructureCondenser(use_conventional_cell=conventional, symprec=symprec)
    data = condenser.condense_structure(structure)
    for component in data["components"].values():
        if component.get("orientation") is not None:
            component["orientation"] = tuple(int(i) for i in component["orientation"])
    data["dimensionality"] = int(data["dimensionality"])
    for component in data["components"].values():
        component["dimensionality"] = int(component["dimensionality"])
    prepared = _prepared(structure, symprec, conventional)
    # ChemEnv polyhedra are meaningful for polyhedron-forming (cation) sites only.
    polyhedral = [i for i, site in data["sites"].items() if site["poly_formula"]]
    chemenv = _chemenv(prepared, polyhedral) if polyhedral else {}
    corrected = []
    for index, site in data["sites"].items():
        found = chemenv.get(index)
        if not found or found["symbol"] not in CHEMENV_ONLY:
            continue
        if (
            found["coordination_number"] == len(site["nn"])
            and found["continuous_symmetry_measure"] < 2
        ):
            name = CHEMENV_ONLY[found["symbol"]][0]
            site["geometry"] = {
                "type": name,
                "likeness": 1 - found["continuous_symmetry_measure"] / 10,
            }
            corrected.append(index)
    return data, chemenv, corrected, prepared


def describe(
    structure: str,
    oxidation_states: bool = True,
    symmetry_labels: bool = True,
    bond_length_decimals: int = 2,
    conventional_cell: bool = True,
    symprec: float = 0.01,
    fmt: Format = "unicode",
) -> dict:
    """A text description of a crystal structure, with its key facts.

    Args:
        structure: Crystal structure file (CIF, POSCAR, pymatgen JSON, ...).
        oxidation_states: Guess oxidation states (bond valence) when the file has
            none, and mention them (e.g. Sn4+).
        symmetry_labels: Number inequivalent sites of an element (Sn(1), Sn(2)).
        bond_length_decimals: Decimal places for bond lengths.
        conventional_cell: Analyse the conventional standard cell.
        symprec: Symmetry tolerance in Angstrom.
        fmt: "unicode" (P4₂/mnm, Sn⁴⁺), "raw" (P4_2/mnm, Sn4+), "html", or "latex".

    Returns:
        The description; formula; mineral prototype (exact match, or the
        closest with its fingerprint distance); space group; crystal system;
        dimensionality (0 molecules, 1 chains, 2 layers, 3 framework); the
        components (formula, dimensionality, layer orientation as Miller
        indices, molecule name, count); van der Waals layering; and notes.
    """
    _quiet()
    from robocrys import StructureDescriber

    if not 0 <= bond_length_decimals <= 6:
        raise ValueError("bond_length_decimals must be between 0 and 6.")
    loaded, note = _structure(structure, oxidation_states)
    data, _, corrected, _ = _condense(loaded, symprec, conventional_cell)
    describer = StructureDescriber(
        describe_oxidation_states=oxidation_states,
        describe_symmetry_labels=symmetry_labels,
        bond_length_decimal_places=bond_length_decimals,
        fmt=fmt,
        return_parts=False,
    )
    text = describer.describe(data)
    mineral = data["mineral"]
    counts: dict[int, int] = {}
    for index in data["component_makeup"]:
        counts[index] = counts.get(index, 0) + 1
    components = [
        {
            "formula": data["components"][index]["formula"],
            "dimensionality": data["components"][index]["dimensionality"],
            "orientation": data["components"][index]["orientation"],
            "molecule_name": data["components"][index]["molecule_name"],
            "count": count,
        }
        for index, count in counts.items()
    ]
    notes = [note] if note else []
    if corrected:
        notes.append(
            "Polyhedra named by ChemEnv (no robocrystallographer name): "
            + ", ".join(sorted({data["sites"][i]["element"] for i in corrected}))
        )
    heterostructure = data["vdw_heterostructure_info"]
    return {
        "description": text,
        "formula": data["formula"],
        "mineral": {
            "name": mineral["type"],
            "exact_match": mineral["distance"] == -1,
            "fingerprint_distance": None if mineral["distance"] == -1 else mineral["distance"],
            "same_number_of_species": mineral["n_species_type_match"],
        }
        if mineral["type"]
        else None,
        "space_group": data["spg_symbol"],
        "crystal_system": data["crystal_system"],
        "dimensionality": data["dimensionality"],
        "components": components,
        "van_der_waals_layers": {
            "repeating_unit": list(heterostructure["repeating_unit"]),
            "repetitions": int(heterostructure["num_repetitions"]),
            "intercalants": list(heterostructure["intercalant_formulas"]),
        }
        if heterostructure
        else None,
        "notes": notes,
    }


def site_environments(
    structure: str,
    oxidation_states: bool = True,
    conventional_cell: bool = True,
    symprec: float = 0.01,
) -> dict:
    """Coordination environment of each symmetry-inequivalent site.

    Args:
        structure: Crystal structure file (CIF, POSCAR, pymatgen JSON, ...).
        oxidation_states: Guess oxidation states when the file has none.
        conventional_cell: Analyse the conventional standard cell.
        symprec: Symmetry tolerance in Angstrom.

    Returns:
        For each inequivalent site: element (with oxidation state), coordination
        number, neighbours with bond lengths (Angstrom), geometry from
        robocrystallographer with its likeness (0-1), for polyhedron-forming
        sites the ChemEnv polyhedron with its continuous symmetry measure (0 =
        ideal; below ~1 nearly ideal), the
        polyhedron formula, how many neighbouring polyhedra share a corner,
        edge, or face with it, and the metal-ligand-metal angles of corner- and
        edge-sharing connections (an octahedral tilt is 180° minus the corner
        angle).
    """
    _quiet()
    loaded, note = _structure(structure, oxidation_states)
    data, chemenv, corrected, prepared = _condense(loaded, symprec, conventional_cell)
    sites = []
    for index, site in data["sites"].items():
        neighbours = []
        for other, distances in data["distances"].get(index, {}).items():
            element = data["sites"][other]["element"]
            neighbours += [
                {"element": element, "distance_angstrom": round(float(d), 4)} for d in distances
            ]
        neighbours.sort(key=lambda n: n["distance_angstrom"])
        lengths = [n["distance_angstrom"] for n in neighbours]
        connectivity = {kind: len(members) for kind, members in site["nnn"].items()}
        angles = {}
        for by_kind in data["angles"].get(index, {}).values():
            for kind, values in by_kind.items():
                angles.setdefault(kind, []).extend(round(float(v), 2) for v in values)
        entry = {
            "index": int(index),
            "element": site["element"],
            "wyckoff_position": None,
            "coordination_number": len(site["nn"]),
            "neighbours": neighbours,
            "bond_length_angstrom": {
                "min": min(lengths),
                "mean": round(sum(lengths) / len(lengths), 4),
                "max": max(lengths),
            }
            if lengths
            else None,
            "geometry": site["geometry"]["type"],
            "geometry_likeness": round(float(site["geometry"]["likeness"]), 4),
            "geometry_from": "ChemEnv" if index in corrected else "robocrystallographer",
            "chemenv": chemenv.get(index),
            "polyhedron_formula": site["poly_formula"],
            "shared_with_neighbouring_polyhedra": {
                "corner": connectivity.get("corner", 0),
                "edge": connectivity.get("edge", 0),
                "face": connectivity.get("face", 0),
            },
            "connection_angles_deg": {kind: sorted(v) for kind, v in angles.items()},
        }
        sites.append(entry)
    _wyckoff(prepared, sites, symprec)
    return {
        "formula": data["formula"],
        "space_group": data["spg_symbol"],
        "sites": sites,
        "notes": [note] if note else [],
    }


def _wyckoff(structure, sites, symprec: float) -> None:
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    try:
        symmetrized = SpacegroupAnalyzer(structure, symprec=symprec).get_symmetrized_structure()
    except Exception:
        return
    for entry in sites:
        entry["wyckoff_position"] = symmetrized.wyckoff_symbols[
            next(
                i
                for i, group in enumerate(symmetrized.equivalent_indices)
                if entry["index"] in group
            )
        ]
