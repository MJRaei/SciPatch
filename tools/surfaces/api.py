"""Surfaces, adsorption sites, and nanoparticle shapes.

make_slab cuts a crystal along any Miller plane (pymatgen's SlabGenerator) and
lists the possible terminations; adsorption_sites finds top, bridge, and hollow
sites on a slab (fcc and hcp hollows told apart) and places adsorbates on them;
wulff_shape builds the equilibrium shape of a nanoparticle from surface
energies with WulffPack: free (Wulff), on a support (Winterbottom), or twinned
(decahedra and icosahedra), with an atomistic model.
"""

from __future__ import annotations

import functools
import math
import re
import warnings
from pathlib import Path
from typing import Literal

import numpy as np

ParticleKind = Literal["single_crystal", "winterbottom", "decahedron", "icosahedron"]
SiteKind = Literal["top", "bridge", "fcc_hollow", "hcp_hollow", "hollow", "fourfold_hollow"]

#: Adsorbates: ASE molecule name (or atom), binding atom index, and the atoms
#: listed from the binding atom upward.
ADSORBATES = {
    "H": ("H", 0),
    "C": ("C", 0),
    "N": ("N", 0),
    "O": ("O", 0),
    "S": ("S", 0),
    "OH": ("OH", 0),
    "CO": ("CO", 1),
    "NO": ("NO", 0),
    "H2O": ("H2O", 0),
    "NH3": ("NH3", 0),
    "CH3": ("CH3", 0),
}


@functools.cache
def _quiet() -> None:
    warnings.filterwarnings("ignore")


def _bulk(structure: str, lattice_constant: float | None):
    """Bulk crystal from a file, or from an element symbol (ASE reference crystal)."""
    _quiet()
    from pymatgen.core import Structure
    from pymatgen.io.ase import AseAtomsAdaptor

    path = Path(structure)
    if path.is_file():
        try:
            return Structure.from_file(path), path.name
        except Exception as exc:
            raise ValueError(f"Could not read {path.name} as a crystal structure: {exc}") from exc
    from ase.build import bulk
    from ase.data import atomic_numbers, reference_states

    symbol = structure.strip().capitalize()
    if symbol not in atomic_numbers:
        raise ValueError(f"{structure!r} is neither a structure file nor an element symbol.")
    state = reference_states[atomic_numbers[symbol]] or {}
    kind = state.get("symmetry")
    if kind not in ("fcc", "bcc", "hcp", "diamond", "sc"):
        raise ValueError(f"No simple reference crystal for {symbol}; give a structure file.")
    kwargs = {"a": lattice_constant} if lattice_constant else {}
    atoms = bulk(symbol, kind, cubic=kind in ("fcc", "bcc", "diamond", "sc"), **kwargs)
    return AseAtomsAdaptor.get_structure(
        atoms
    ), f"{symbol} ({kind}, a = {atoms.cell.lengths()[0]:.4f} Å)"


def _miller(text, size: int | None = None) -> tuple[int, ...]:
    """Miller indices from (1, 1, 1), [1, 1, 1], "111", "1 -1 0", or "-110"."""
    if isinstance(text, list | tuple):
        values = tuple(int(v) for v in text)
    else:
        cleaned = str(text).strip().strip("()[]{}")
        parts = (
            re.findall(r"-?\d+", cleaned)
            if re.search(r"[\s,]", cleaned)
            else re.findall(r"-?\d", cleaned)
        )
        values = tuple(int(v) for v in parts)
    if (size and len(values) != size) or not any(values):
        raise ValueError(f"Invalid Miller indices {text!r}.")
    return values


def _primitive_miller(conventional, primitive, hkl) -> tuple[int, int, int]:
    """Miller indices of the same planes in the primitive cell's basis."""
    transform = primitive.lattice.matrix @ np.linalg.inv(conventional.lattice.matrix)
    values = transform @ np.asarray(hkl, dtype=float)
    scale = next(
        d for d in range(1, 13) if np.allclose(values * d, np.round(values * d), atol=1e-6)
    )
    indices = np.round(values * scale).astype(int)
    divisor = math.gcd(*map(int, np.abs(indices)))
    return tuple(int(v) for v in indices // divisor)


def _oriented(slab):
    """The slab with c perpendicular to the surface and along z (a along x)."""
    from pymatgen.core import Lattice, Structure

    slab = slab.get_orthogonal_c_slab()
    lattice = Lattice.from_parameters(*slab.lattice.parameters)
    return Structure(lattice, slab.species, slab.frac_coords, site_properties=slab.site_properties)


def _write(structure, path: str) -> None:
    from ase.io import write
    from pymatgen.io.ase import AseAtomsAdaptor

    atoms = AseAtomsAdaptor.get_atoms(structure)
    fmt = (
        "vasp"
        if Path(path).suffix.lower() in (".vasp", ".poscar")
        or Path(path).name.upper() in ("POSCAR", "CONTCAR")
        else None
    )
    write(path, atoms, format=fmt)


def _formula(structure, indices) -> str:
    from collections import Counter

    from pymatgen.core import Composition

    return Composition(Counter(structure[i].species_string for i in indices)).reduced_formula


def _layers(z: np.ndarray, tolerance: float = 0.3) -> list[list[int]]:
    order = np.argsort(-z)
    layers: list[list[int]] = []
    for i in order:
        if layers and abs(z[layers[-1][0]] - z[i]) < tolerance:
            layers[-1].append(int(i))
        else:
            layers.append([int(i)])
    return layers


def make_slab(
    structure: str,
    miller: list[int] | str,
    layers: int = 4,
    vacuum_angstrom: float = 15.0,
    supercell: list[int] | None = None,
    termination: int = 0,
    symmetric: bool = False,
    lattice_constant: float | None = None,
    output: str = "slab.vasp",
) -> dict:
    """Cut a crystal into a slab along a Miller plane.

    Args:
        structure: Bulk crystal file (CIF, POSCAR, ...), or an element symbol for
            its reference crystal (e.g. "Cu", "Fe", "Ru").
        miller: Miller indices of the surface in the conventional cell, e.g.
            [1, 1, 1] or "110".
        layers: Number of atomic layers (planes of the given orientation).
        vacuum_angstrom: Vacuum thickness between periodic images.
        supercell: In-plane repetition, e.g. [2, 2] (default [1, 1], the smallest
            surface cell).
        termination: Which termination to write (see terminations in the result).
        symmetric: Make both surfaces equivalent (removing atoms if needed).
        lattice_constant: With an element symbol, the lattice constant a in
            Angstrom (default: ASE's reference value).
        output: Slab file (.vasp for POSCAR, .cif, .xyz, .extxyz, ...), with the
            surface normal along z and the top surface facing +z.

    Returns:
        Interlayer spacing, surface cell area (Angstrom2) and lattice, number of
        atoms and layers, thickness, composition and polarity, the possible
        terminations, and the atoms in the top layer.
    """
    _quiet()
    from pymatgen.core.surface import SlabGenerator
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    if layers < 1 or vacuum_angstrom < 0:
        raise ValueError("layers must be at least 1 and vacuum_angstrom non-negative.")
    bulk, name = _bulk(structure, lattice_constant)
    analyzer = SpacegroupAnalyzer(bulk, symprec=0.01)
    conventional = analyzer.get_conventional_standard_structure()
    primitive = analyzer.get_primitive_standard_structure()
    hkl = _miller(miller, 3)
    prim_hkl = _primitive_miller(conventional, primitive, hkl)
    generator = SlabGenerator(
        primitive,
        prim_hkl,
        min_slab_size=layers,
        min_vacuum_size=vacuum_angstrom,
        in_unit_planes=True,
        center_slab=True,
        primitive=True,
        lll_reduce=True,
    )
    slabs = generator.get_slabs(symmetrize=symmetric)
    if not slabs:
        raise ValueError("No slab could be built for this orientation (try symmetric=false).")
    if not 0 <= termination < len(slabs):
        raise ValueError(f"termination must be 0-{len(slabs) - 1}.")
    spacing = float(primitive.lattice.d_hkl(prim_hkl))
    terminations = []
    for i, slab in enumerate(slabs):
        oriented = _oriented(slab)
        z = oriented.cart_coords[:, 2]
        groups = _layers(z)
        terminations.append(
            {
                "index": i,
                "atoms": len(slab),
                "top_layer": _formula(oriented, groups[0]),
                "bottom_layer": _formula(oriented, groups[-1]),
                "symmetric": bool(slab.is_symmetric()),
                "polar": bool(slab.is_polar()),
            }
        )
    chosen = _oriented(slabs[termination])
    reps = list(supercell or [1, 1])
    if len(reps) != 2 or min(reps) < 1:
        raise ValueError("supercell must be two positive integers, e.g. [2, 2].")
    chosen.make_supercell([reps[0], reps[1], 1])
    z = chosen.cart_coords[:, 2]
    groups = _layers(z)
    a, b = chosen.lattice.matrix[0], chosen.lattice.matrix[1]
    area = float(np.linalg.norm(np.cross(a, b)))
    _write(chosen, output)
    return {
        "bulk": name,
        "miller": list(hkl),
        "interlayer_spacing_angstrom": round(spacing, 5),
        "surface_area_angstrom2": round(area, 5),
        "area_per_surface_cell_angstrom2": round(area / (reps[0] * reps[1]), 5),
        "surface_lattice": {
            "a_angstrom": round(float(np.linalg.norm(a)), 5),
            "b_angstrom": round(float(np.linalg.norm(b)), 5),
            "gamma_deg": round(float(chosen.lattice.gamma), 3),
        },
        "atoms": len(chosen),
        "layers": len(groups),
        "atoms_per_layer": [len(g) for g in groups],
        "thickness_angstrom": round(float(z.max() - z.min()), 4),
        "vacuum_angstrom": round(float(chosen.lattice.c - (z.max() - z.min())), 4),
        "formula": chosen.composition.reduced_formula,
        "terminations": terminations,
        "termination": termination,
        "top_layer_atoms": sorted(groups[0]),
        "output": output,
    }


def _surface_frame(structure):
    """Surface atoms (top layer), the layer below, and the in-plane cell."""
    z = structure.cart_coords[:, 2]
    groups = _layers(z, tolerance=0.5)
    if len(groups) < 2:
        raise ValueError("The slab needs at least two atomic layers (surface normal along z).")
    return groups[0], groups[1], groups[2] if len(groups) > 2 else []


def _lateral(points: np.ndarray, origin: np.ndarray, cell2d: np.ndarray) -> np.ndarray:
    """In-plane distances from origin to points and their periodic images."""
    shifts = np.array([i * cell2d[0] + j * cell2d[1] for i in range(-2, 3) for j in range(-2, 3)])
    images = (points[:, None, :] + shifts[None, :, :]).reshape(-1, 2)
    return np.linalg.norm(images - origin, axis=1)


def _classify(structure, site: np.ndarray, top, second, third) -> tuple[str, int, float]:
    coords = structure.cart_coords
    cell2d = structure.lattice.matrix[:2, :2]
    distances = _lateral(coords[top, :2], site[:2], cell2d)
    nearest = float(distances.min())
    if nearest < 0.3:
        return "top", 1, nearest
    count = int(np.sum(distances < nearest * 1.08 + 0.05))
    if count == 2:
        return "bridge", 2, nearest
    if count == 3:
        below = _lateral(coords[second, :2], site[:2], cell2d).min() if second else np.inf
        if below < 0.5:
            return "hcp_hollow", 3, nearest
        deeper = _lateral(coords[third, :2], site[:2], cell2d).min() if third else np.inf
        return ("fcc_hollow" if deeper < 0.5 else "hollow"), 3, nearest
    if count >= 4:
        return "fourfold_hollow", count, nearest
    return "hollow", count, nearest


def _adsorbate(name: str):
    from ase.build import molecule

    key = name.strip()
    match = {k.lower(): k for k in ADSORBATES}.get(key.lower())
    if match is None:
        raise ValueError(f"Unknown adsorbate {name!r}; choose from {', '.join(ADSORBATES)}.")
    formula, binding = ADSORBATES[match]
    if formula in ("H", "C", "N", "O", "S"):
        return [formula], np.zeros((1, 3))
    atoms = molecule(formula)
    positions = atoms.positions - atoms.positions[binding]
    rest = np.delete(positions, binding, axis=0)
    direction = rest.mean(axis=0)
    norm = np.linalg.norm(direction)
    if norm > 1e-8:  # rotate so the molecule points up (+z) from the binding atom
        direction /= norm
        axis = np.cross(direction, [0, 0, 1.0])
        sin, cos = np.linalg.norm(axis), float(np.dot(direction, [0, 0, 1.0]))
        if sin > 1e-8:
            axis /= sin
            k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
            rotation = np.eye(3) + sin * k + (1 - cos) * k @ k
            positions = positions @ rotation.T
        elif cos < 0:
            positions = -positions
    symbols = list(atoms.get_chemical_symbols())
    order = [binding] + [i for i in range(len(symbols)) if i != binding]
    return [symbols[i] for i in order], positions[order]


def adsorption_sites(
    slab: str,
    adsorbate: str | None = None,
    site: SiteKind | None = None,
    height_angstrom: float = 1.5,
    symmetry_reduce: bool = True,
    output: str = "slab_adsorbate.vasp",
) -> dict:
    """Adsorption sites on the top surface of a slab, and adsorbate placement.

    Args:
        slab: Slab file with the surface normal along z (e.g. from make_slab).
        adsorbate: Optionally place this on a site: H, C, N, O, S, OH, CO (C-down),
            NO, H2O, NH3, or CH3, bound through its first atom and pointing up.
        site: Site type for the adsorbate: top, bridge, fcc_hollow, hcp_hollow,
            hollow, or fourfold_hollow (default: the first site found).
        height_angstrom: Height of the binding atom above the top atomic layer.
        symmetry_reduce: List only symmetry-distinct sites.
        output: Slab-with-adsorbate file (when adsorbate is given).

    Returns:
        Each site: type (top; bridge; fcc or hcp 3-fold hollow, told apart by
        whether an atom lies directly below in the second layer; 4-fold hollow),
        number of surface atoms around it, their lateral distance, and its
        Cartesian position; the counts per type; and, with an adsorbate, the file
        and the distance from the binding atom to the nearest surface atom.
    """
    _quiet()
    from pymatgen.analysis.adsorption import AdsorbateSiteFinder
    from pymatgen.core import Structure

    path = Path(slab)
    if not path.is_file():
        raise ValueError(f"Slab file {slab!r} not found.")
    structure = Structure.from_file(path)
    top, second, third = _surface_frame(structure)
    surface_z = float(structure.cart_coords[top, 2].mean())
    finder = AdsorbateSiteFinder(structure, mi_vec=[0, 0, 1], height=0.5)
    found = finder.find_adsorption_sites(
        distance=0.0,
        symm_reduce=0.01 if symmetry_reduce else 0,
        positions=["ontop", "bridge", "hollow"],
    )
    sites = []
    seen = set()
    for position in found["all"]:
        kind, count, lateral = _classify(structure, np.asarray(position), top, second, third)
        key = (kind, round(lateral, 2))
        if symmetry_reduce and key in seen:
            continue
        seen.add(key)
        point = np.array([position[0], position[1], surface_z])
        sites.append(
            {
                "type": kind,
                "surface_neighbours": count,
                "lateral_distance_angstrom": round(lateral, 4),
                "position_angstrom": [round(float(v), 4) for v in point],
            }
        )
    order = ["top", "bridge", "fcc_hollow", "hcp_hollow", "hollow", "fourfold_hollow"]
    sites.sort(key=lambda s: (order.index(s["type"]), s["lateral_distance_angstrom"]))
    counts = {kind: sum(1 for s in sites if s["type"] == kind) for kind in order}
    result = {
        "slab": path.name,
        "surface_atoms_per_cell": len(top),
        "sites": sites,
        "counts": {k: v for k, v in counts.items() if v},
    }
    if adsorbate:
        candidates = [s for s in sites if site is None or s["type"] == site]
        if not candidates:
            raise ValueError(
                f"No {site} site on this surface; available: {', '.join(result['counts'])}."
            )
        chosen = candidates[0]
        symbols, positions = _adsorbate(adsorbate)
        anchor = np.array(chosen["position_angstrom"]) + np.array([0.0, 0.0, height_angstrom])
        combined = structure.copy()
        for symbol, offset in zip(symbols, positions, strict=True):
            combined.append(symbol, anchor + offset, coords_are_cartesian=True)
        distances = [combined.get_distance(len(structure), i) for i in top]
        _write(combined, output)
        result["adsorbate"] = {
            "name": adsorbate,
            "site": chosen,
            "height_angstrom": height_angstrom,
            "nearest_surface_atom_distance_angstrom": round(float(min(distances)), 4),
            "output": output,
        }
    return result


def wulff_shape(
    surface_energies: dict,
    structure: str = "Au",
    kind: ParticleKind = "single_crystal",
    natoms: int = 1000,
    interface_energy: float | None = None,
    interface_direction: list[int] | str = "111",
    twin_energy: float | None = None,
    lattice_constant: float | None = None,
    output: str = "particle.xyz",
    plot: str = "particle.png",
) -> dict:
    """Equilibrium nanoparticle shape from surface energies (Wulff construction).

    Args:
        surface_energies: Surface energy per orientation, e.g. {"111": 1.28,
            "100": 1.42, "110": 1.53} (any consistent unit, e.g. J/m2), with Miller
            indices of the conventional cell (four indices for hexagonal).
        structure: Element symbol of a reference crystal (e.g. "Au", "Pt") or a
            bulk structure file.
        kind: "single_crystal" (Wulff), "winterbottom" (particle on a support),
            "decahedron" or "icosahedron" (twinned; fcc only).
        natoms: Approximate number of atoms (sets the size).
        interface_energy: Winterbottom: interface energy to the support minus the
            support's surface energy (same units; negative wets the support).
        interface_direction: Winterbottom: facet in contact with the support.
        twin_energy: Decahedron or icosahedron: twin boundary energy.
        lattice_constant: With an element symbol, the lattice constant a.
        output: Atomistic model of the particle (.xyz, .extxyz, .cif, ...).
        plot: PNG of the shape.

    Returns:
        Area fraction of each facet family (and the interface), average surface
        energy, volume (Angstrom3), surface area, number of corners, the number
        of atoms in the atomistic model, and the files.
    """
    _quiet()
    from pymatgen.io.ase import AseAtomsAdaptor

    if not surface_energies:
        raise ValueError("Give at least one surface energy.")
    energies = {}
    for key, value in surface_energies.items():
        indices = _miller(key)
        if len(indices) not in (3, 4):
            raise ValueError(f"Invalid Miller indices {key!r}.")
        if float(value) <= 0:
            raise ValueError("Surface energies must be positive.")
        energies[indices] = float(value)
    bulk, name = _bulk(structure, lattice_constant)
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    primitive = AseAtomsAdaptor.get_atoms(
        SpacegroupAnalyzer(bulk).get_primitive_standard_structure()
    )
    if natoms < 10:
        raise ValueError("natoms must be at least 10.")
    import wulffpack

    try:
        if kind == "single_crystal":
            particle = wulffpack.SingleCrystal(
                energies, primitive_structure=primitive, natoms=natoms
            )
        elif kind == "winterbottom":
            if interface_energy is None:
                raise ValueError("A Winterbottom particle needs interface_energy.")
            particle = wulffpack.Winterbottom(
                energies,
                interface_direction=_miller(interface_direction),
                interface_energy=interface_energy,
                primitive_structure=primitive,
                natoms=natoms,
            )
        else:
            if twin_energy is None:
                raise ValueError(f"A {kind} needs twin_energy.")
            cls = wulffpack.Decahedron if kind == "decahedron" else wulffpack.Icosahedron
            particle = cls(
                energies, twin_energy=twin_energy, primitive_structure=primitive, natoms=natoms
            )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"WulffPack could not build the particle: {exc}") from exc
    fractions = {
        ("".join(str(i) for i in key) if isinstance(key, tuple) else str(key)): round(float(v), 8)
        for key, v in particle.facet_fractions.items()
        if v > 1e-10
    }
    atoms = particle.atoms
    from ase.io import write

    write(output, atoms)
    _plot(particle, plot)
    return {
        "structure": name,
        "kind": kind,
        "facet_fractions": dict(sorted(fractions.items(), key=lambda kv: -kv[1])),
        "average_surface_energy": round(float(particle.average_surface_energy), 8),
        "volume_angstrom3": round(float(particle.volume), 4),
        "area_angstrom2": round(float(particle.area), 4),
        "number_of_corners": int(particle.number_of_corners),
        "atoms_in_model": len(atoms),
        "formula": atoms.get_chemical_formula(),
        "output": output,
        "plot": plot,
    }


def _plot(particle, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    figure = plt.figure(figsize=(4.5, 4.5))
    axis = figure.add_subplot(projection="3d")
    shown = [key for key, value in particle.facet_fractions.items() if value > 1e-10]
    palette = plt.get_cmap("tab10").colors
    colors = {key: palette[i % len(palette)] for i, key in enumerate(shown)}
    particle.make_plot(axis, colors=colors)
    handles = [
        Patch(color=color, label="".join(str(i) for i in key) if isinstance(key, tuple) else key)
        for key, color in colors.items()
    ]
    axis.legend(handles=handles, loc="upper left")
    axis.set_axis_off()
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)
