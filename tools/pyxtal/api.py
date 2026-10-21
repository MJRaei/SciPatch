"""Crystal structure generation by symmetry with PyXtal.

Random crystals of a given composition in a chosen space group (atoms placed on
compatible Wyckoff positions, sensible interatomic distances), molecular crystals
from built-in molecules, SMILES, or files, Wyckoff tables and compatible space
groups. Generated structures are starting points: relax them (e.g. with
ml-potentials) and keep the lowest-energy ones for crystal structure prediction.
"""

from __future__ import annotations

import functools
import math
import warnings
from pathlib import Path


@functools.cache
def _quiet() -> None:
    warnings.filterwarnings("ignore")


def _group(space_group: int):
    from pyxtal.symmetry import Group

    if not 1 <= int(space_group) <= 230:
        raise ValueError("space_group must be between 1 and 230.")
    return Group(int(space_group))


def _composition(composition: dict[str, int]) -> tuple[list[str], list[int]]:
    if not composition:
        raise ValueError("Give at least one element with its number of atoms per cell.")
    species = list(composition)
    counts = [int(n) for n in composition.values()]
    if any(n <= 0 for n in counts):
        raise ValueError("Atom counts must be positive integers (atoms per conventional cell).")
    return species, counts


def _compatible(counts: list[int]) -> list[int]:
    from pyxtal.symmetry import Group

    return [number for number in range(1, 231) if Group(number).check_compatible(counts)[0]]


def _describe(crystal, file: str, symprec: float) -> dict:
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    structure = crystal.to_pymatgen()
    analyzer = SpacegroupAnalyzer(structure, symprec=symprec)
    sites = []
    for site in crystal.atom_sites:
        index = _site_index(structure, site.position)
        neighbors = structure.get_neighbors(structure[index], 8.0)
        nearest = min((n.nn_distance for n in neighbors), default=math.nan)
        shell = [n for n in neighbors if n.nn_distance <= 1.1 * nearest]
        sites.append(
            {
                "element": site.specie,
                "wyckoff": f"{site.wp.multiplicity}{site.wp.letter}",
                "site_symmetry": site.wp.get_site_symmetry_object().name,
                "position": [round(float(x), 5) for x in site.position],
                "nearest_neighbor_distance_angstrom": round(float(nearest), 4),
                "coordination": len(shell),
                "neighbors": sorted({str(n.specie) for n in shell}),
            }
        )
    lattice = structure.lattice
    crystal.to_file(file)
    return {
        "file": file,
        "space_group": crystal.group.number,
        "symbol": crystal.group.symbol,
        "space_group_found": analyzer.get_space_group_number(),
        "formula": structure.composition.reduced_formula,
        "atoms_in_cell": len(structure),
        "lattice": {
            "a": round(lattice.a, 4),
            "b": round(lattice.b, 4),
            "c": round(lattice.c, 4),
            "alpha": round(lattice.alpha, 3),
            "beta": round(lattice.beta, 3),
            "gamma": round(lattice.gamma, 3),
        },
        "volume_angstrom3": round(lattice.volume, 3),
        "density_g_cm3": round(float(structure.density), 4),
        "sites": sites,
    }


def _site_index(structure, position) -> int:
    import numpy as np

    distances = [
        structure.lattice.get_distance_and_image(site.frac_coords, np.asarray(position))[0]
        for site in structure
    ]
    return int(np.argmin(distances))


def random_crystals(
    composition: dict[str, int],
    space_group: int | None = None,
    count: int = 5,
    volume_factor: float = 1.1,
    seed: int = 1,
    prefix: str = "crystal",
) -> dict:
    """Random symmetric crystals of a composition, written as CIF files.

    Args:
        composition: Atoms per conventional cell, e.g. {"Na": 4, "Cl": 4} or
            {"Si": 8}; the counts must fit the multiplicities of the space group's
            Wyckoff positions (see compatible_space_groups).
        space_group: Space group number 1-230; default a random compatible group
            for each structure.
        count: Number of structures.
        volume_factor: Cell volume relative to the sum of atomic volumes (larger
            gives more open structures).
        seed: Random seed (structure i uses seed + i).
        prefix: CIF files are named <prefix>_1.cif, <prefix>_2.cif, ...

    Returns:
        For each structure: the CIF path, the intended space group and the one
        found by symmetry analysis, formula, lattice, volume, density, and each
        Wyckoff site with its site symmetry, coordinates, nearest-neighbour
        distance, and coordination. Structures are unrelaxed.
    """
    _quiet()
    from pyxtal import pyxtal

    species, counts = _composition(composition)
    if count < 1:
        raise ValueError("count must be at least 1.")
    choices = None
    if space_group is None:
        choices = _compatible(counts)
        if not choices:
            raise ValueError(f"No space group fits {composition} atoms per cell.")
    elif not _group(space_group).check_compatible(counts)[0]:
        raise ValueError(
            f"{composition} does not fit the Wyckoff multiplicities of space group "
            f"{space_group}; see compatible_space_groups."
        )
    import numpy as np

    rng = np.random.default_rng(seed)
    results, failures = [], 0
    for index in range(count):
        group = space_group or int(rng.choice(choices))
        crystal = pyxtal()
        try:
            crystal.from_random(3, group, species, counts, factor=volume_factor, seed=seed + index)
        except Exception:
            failures += 1
            continue
        if not crystal.valid:
            failures += 1
            continue
        results.append(_describe(crystal, f"{prefix}_{index + 1}.cif", 0.01))
    if not results:
        raise RuntimeError("PyXtal could not place the atoms; try a larger volume_factor.")
    return {"structures": results, "failed_attempts": failures}


def molecular_crystals(
    molecules: list[str],
    counts: list[int],
    space_group: int,
    count: int = 5,
    volume_factor: float = 1.1,
    seed: int = 1,
    prefix: str = "molecular",
) -> dict:
    """Random molecular crystals with molecules on general or special positions.

    Args:
        molecules: Each a built-in name (e.g. "H2O", "CH4", "benzene", "aspirin";
            see list_molecules), a SMILES string, or an .xyz file.
        counts: Molecules of each kind per conventional cell (e.g. [4] for Z = 4).
        space_group: Space group number, e.g. 14 (P2_1/c, the most common for
            organic crystals), 2, 19, 61, 4.
        count: Number of structures.
        volume_factor: Cell volume relative to the molecular volumes.
        seed: Random seed.
        prefix: CIF files are named <prefix>_1.cif, ...

    Returns:
        For each structure: CIF path, space group intended and found, formula,
        lattice, volume, and density. Structures are unrelaxed.
    """
    _quiet()
    from pyxtal import pyxtal

    if len(molecules) != len(counts) or not molecules:
        raise ValueError("Give one count per molecule.")
    group = _group(space_group).number
    resolved = [_molecule(text) for text in molecules]
    results, failures = [], 0
    for index in range(count):
        crystal = pyxtal(molecular=True)
        try:
            crystal.from_random(
                3,
                group,
                resolved,
                [int(n) for n in counts],
                factor=volume_factor,
                seed=seed + index,
            )
        except Exception as exc:
            if index == 0 and "compatib" in str(exc).lower():
                raise ValueError(
                    f"{counts} molecules do not fit space group {group}: {exc}"
                ) from exc
            failures += 1
            continue
        if not crystal.valid:
            failures += 1
            continue
        results.append(_describe_molecular(crystal, f"{prefix}_{index + 1}.cif"))
    if not results:
        raise RuntimeError("PyXtal could not pack the molecules; try a larger volume_factor.")
    return {"structures": results, "failed_attempts": failures}


@functools.cache
def _builtin_molecules() -> dict[str, str]:
    from pyxtal.molecule import molecule_collection

    return {name.lower(): name for name in molecule_collection}


def _molecule(text: str) -> str:
    if text.lower() in _builtin_molecules():
        return _builtin_molecules()[text.lower()]
    if Path(text).suffix.lower() in (".xyz", ".mol", ".pdb", ".sdf") and Path(text).is_file():
        return text
    from rdkit import Chem

    if Chem.MolFromSmiles(text) is None:
        raise ValueError(f"{text!r} is not a built-in molecule, a file, or a valid SMILES.")
    return f"{text}.smi"


def _describe_molecular(crystal, file: str) -> dict:
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    structure = crystal.to_pymatgen()
    crystal.to_file(file)
    lattice = structure.lattice
    return {
        "file": file,
        "space_group": crystal.group.number,
        "symbol": crystal.group.symbol,
        "space_group_found": SpacegroupAnalyzer(structure, symprec=0.01).get_space_group_number(),
        "formula": structure.composition.formula,
        "atoms_in_cell": len(structure),
        "lattice": {
            "a": round(lattice.a, 4),
            "b": round(lattice.b, 4),
            "c": round(lattice.c, 4),
            "alpha": round(lattice.alpha, 3),
            "beta": round(lattice.beta, 3),
            "gamma": round(lattice.gamma, 3),
        },
        "volume_angstrom3": round(lattice.volume, 3),
        "density_g_cm3": round(float(structure.density), 4),
    }


def wyckoff_positions(space_group: int) -> dict:
    """The Wyckoff positions of a space group (as in the International Tables).

    Args:
        space_group: Space group number 1-230.

    Returns:
        Hermann-Mauguin symbol, crystal lattice type, point group, whether the
        group is centrosymmetric, polar, and chiral (Sohncke), and each Wyckoff
        position with its multiplicity, letter, site symmetry, number of free
        coordinates, and first coordinate triplet.
    """
    _quiet()
    group = _group(space_group)
    positions = []
    for wp in group.Wyckoff_positions:
        positions.append(
            {
                "wyckoff": f"{wp.multiplicity}{wp.letter}",
                "multiplicity": wp.multiplicity,
                "letter": wp.letter,
                "site_symmetry": wp.get_site_symmetry_object().name,
                "free_coordinates": int(wp.get_dof()),
                "coordinates": wp.ops[0].as_xyz_str(),
            }
        )
    return {
        "space_group": group.number,
        "symbol": group.symbol,
        "lattice_type": group.lattice_type,
        "point_group": group.point_group,
        "centrosymmetric": bool(group.inversion),
        "polar": bool(group.polar),
        "chiral": bool(group.chiral),
        "positions": positions,
    }


def compatible_space_groups(composition: dict[str, int]) -> dict:
    """Space groups whose Wyckoff positions can hold a composition per conventional cell.

    Args:
        composition: Atoms per conventional cell, e.g. {"Ti": 2, "O": 4}.

    Returns:
        The compatible space group numbers and their count; try several
        multiples of the formula (Z = 1, 2, 4, ...) for crystal structure searches.
    """
    _quiet()
    _, counts = _composition(composition)
    groups = _compatible(counts)
    return {"composition": composition, "count": len(groups), "space_groups": groups}


def list_molecules() -> dict:
    """Built-in molecules PyXtal can place in molecular crystals by name.

    Returns:
        The molecule names.
    """
    _quiet()
    return {"molecules": sorted(_builtin_molecules().values(), key=str.lower)}
