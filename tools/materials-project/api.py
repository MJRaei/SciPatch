"""The Materials Project database: search known materials, check stability, get structures.

Needs a free API key from https://next-gen.materialsproject.org/api (stored once
with `scipatch secret set MP_API_KEY`). Every result reports the database version,
because computed values change between releases.
"""

from __future__ import annotations

import contextlib
import os
import warnings

_KEY_URL = "https://next-gen.materialsproject.org/api"

_SEARCH_FIELDS = [
    "material_id", "formula_pretty", "symmetry", "nsites", "energy_above_hull",
    "formation_energy_per_atom", "band_gap", "is_stable", "density", "theoretical",
]  # fmt: skip
_DETAIL_FIELDS = [
    *_SEARCH_FIELDS, "energy_per_atom", "decomposes_to", "is_metal", "is_gap_direct",
    "is_magnetic", "ordering", "total_magnetization", "bulk_modulus", "shear_modulus",
    "volume", "database_IDs", "deprecated",
]  # fmt: skip


@contextlib.contextmanager
def _rester():
    """An authenticated client; a rejected key becomes a clear error message."""
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
                "The Materials Project rejected the API key. Check it at "
                f"{_KEY_URL} and store it again with 'scipatch secret set MP_API_KEY'."
            ) from exc
        raise


def _summary(doc) -> dict:
    symmetry = doc.symmetry
    return {
        "material_id": str(doc.material_id),
        "formula": doc.formula_pretty,
        "space_group_symbol": symmetry.symbol if symmetry else None,
        "space_group_number": symmetry.number if symmetry else None,
        "crystal_system": str(symmetry.crystal_system) if symmetry else None,
        "n_sites": doc.nsites,
        "energy_above_hull_ev_per_atom": doc.energy_above_hull,
        "formation_energy_ev_per_atom": doc.formation_energy_per_atom,
        "band_gap_ev": doc.band_gap,
        "is_stable": doc.is_stable,
        "density_g_cm3": doc.density,
        "theoretical": doc.theoretical,
    }


def _hull_order(material: dict) -> float:
    """Sort key: energy above the hull, unknown values last."""
    value = material["energy_above_hull_ev_per_atom"]
    return float("inf") if value is None else value


def search(
    formula: str | None = None,
    chemsys: str | None = None,
    elements: list[str] | None = None,
    stable_only: bool = False,
    max_energy_above_hull_ev: float | None = None,
    max_results: int = 20,
) -> dict:
    """Search the Materials Project for materials, lowest energy above the hull first.

    Give at least one of formula, chemsys, or elements.

    Args:
        formula: Reduced formula, e.g. "LiFePO4" (wildcards allowed, e.g. "*O3").
        chemsys: Chemical system with all and only these elements, e.g. "Li-Fe-P-O".
        elements: Materials containing at least these elements, e.g. ["Li", "Co"].
        stable_only: Only materials on the convex hull (energy above hull of 0).
        max_energy_above_hull_ev: Only materials at most this far above the hull, in
            eV/atom (0.05 is a common cutoff for possibly synthesizable materials).
        max_results: Maximum number of materials to return (1 to 200).

    Returns:
        The database version and, per material: Materials Project ID, formula, space
        group, number of sites, energy above hull and formation energy (eV/atom), band
        gap (eV), stability flag, density (g/cm³), and whether it is only theoretical.
    """
    if not (formula or chemsys or elements):
        raise ValueError("Give at least one of formula, chemsys, or elements.")
    if not 1 <= max_results <= 200:
        raise ValueError("max_results must be between 1 and 200.")
    criteria: dict = {"formula": formula, "chemsys": chemsys, "elements": elements}
    if stable_only:
        criteria["is_stable"] = True
    if max_energy_above_hull_ev is not None:
        criteria["energy_above_hull"] = (0.0, float(max_energy_above_hull_ev))
    with _rester() as rester:
        docs = rester.materials.summary.search(
            **{k: v for k, v in criteria.items() if v is not None},
            fields=_SEARCH_FIELDS,
            _sort_fields="energy_above_hull",
            num_chunks=1,
            chunk_size=max_results,
        )
        version = rester.get_database_version()
    materials = sorted((_summary(doc) for doc in docs), key=_hull_order)
    return {"database_version": version, "n_results": len(materials), "materials": materials}


def details(material_id: str) -> dict:
    """All key properties of one material, including what an unstable one decomposes into.

    Args:
        material_id: Materials Project ID, e.g. "mp-149".

    Returns:
        The database version and the material's formula, space group, energies
        (eV/atom), energy above hull and decomposition products, band gap (eV) and
        whether it is direct, magnetic ordering and total magnetization (μB per
        formula unit), bulk and shear moduli (GPa, Voigt-Reuss-Hill), density, volume,
        and identifiers in other databases (e.g. ICSD).
    """
    with _rester() as rester:
        docs = rester.materials.summary.search(material_ids=[material_id], fields=_DETAIL_FIELDS)
        version = rester.get_database_version()
    if not docs:
        raise ValueError(f"No material with ID {material_id} in the Materials Project.")
    doc = docs[0]
    result = _summary(doc)
    result.update(
        {
            "database_version": version,
            "energy_per_atom_ev": doc.energy_per_atom,
            "decomposes_to": [
                {"material_id": str(p.material_id), "formula": p.formula, "amount": p.amount}
                for p in doc.decomposes_to or []
            ],
            "is_metal": doc.is_metal,
            "is_gap_direct": doc.is_gap_direct,
            "magnetic_ordering": doc.ordering,
            "total_magnetization_mu_b": doc.total_magnetization,
            "bulk_modulus_vrh_gpa": (doc.bulk_modulus or {}).get("vrh"),
            "shear_modulus_vrh_gpa": (doc.shear_modulus or {}).get("vrh"),
            "volume_angstrom3": doc.volume,
            "database_ids": doc.database_IDs or {},
            "deprecated": doc.deprecated,
        }
    )
    return result


def get_structure(material_id: str, conventional: bool = True, output: str | None = None) -> dict:
    """Download a material's relaxed crystal structure as a CIF file.

    Args:
        material_id: Materials Project ID, e.g. "mp-149".
        conventional: Conventional standard cell (True) or primitive cell (False).
        output: File to write. Default: <material_id>.cif.

    Returns:
        The structure path, formula, number of sites, lattice parameters (Å, degrees),
        and the database version.
    """
    with _rester() as rester:
        structure = rester.get_structure_by_material_id(
            material_id, conventional_unit_cell=conventional
        )
        version = rester.get_database_version()
    output = output or f"{material_id}.cif"
    structure.to(filename=output)
    a, b, c = structure.lattice.abc
    alpha, beta, gamma = structure.lattice.angles
    return {
        "structure": output,
        "formula": structure.composition.reduced_formula,
        "n_sites": len(structure),
        "lattice": {
            "a_angstrom": a,
            "b_angstrom": b,
            "c_angstrom": c,
            "alpha_deg": alpha,
            "beta_deg": beta,
            "gamma_deg": gamma,
        },
        "database_version": version,
    }
