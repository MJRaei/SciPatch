"""Pore geometry of porous materials (zeolites, MOFs, cages).

Pore sizes and channels come from Zeo++ (Voronoi decomposition of the structure
with atomic radii): the largest included sphere, the largest free sphere that can
travel through the pores (overall and along each axis), and the number and
dimensionality of channels a probe can traverse. Surface area and pore volume are
computed here by Monte Carlo with the same radii (Zeo++'s own area and volume
routines abort for some structures and probe sizes in the available builds).
"""

from __future__ import annotations

import functools
import itertools
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

import numpy as np

Radii = Literal["ccdc", "iza"]
RADII_FILE = Path(__file__).with_name("ccdc_radii.json")
AVOGADRO = 6.02214076e23


@functools.cache
def _ccdc() -> dict[str, float]:
    return json.loads(RADII_FILE.read_text(encoding="utf-8"))["radii_angstrom"]


def _network() -> str:
    for folder in (Path(sys.prefix) / "bin", Path(sys.prefix) / "Library" / "bin"):
        found = shutil.which("network", path=str(folder))
        if found:
            return found
    raise RuntimeError("The Zeo++ program 'network' was not found in this environment.")


def _read(structure: str):
    import warnings

    import ase.io

    path = Path(structure)
    if not path.is_file():
        raise ValueError(f"Structure file {structure!r} not found.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            atoms = ase.io.read(path)
    except Exception as exc:
        raise ValueError(f"Could not read {path.name} as a crystal structure: {exc}") from exc
    if len(atoms) == 0 or not atoms.pbc.all():
        raise ValueError(f"{path.name} has no periodic structure.")
    return atoms


def _radii(atoms, radii: Radii | dict[str, float]) -> dict[str, float]:
    elements = sorted(set(atoms.get_chemical_symbols()))
    if radii == "iza":  # IZA convention: T and O atoms are hard spheres of 2.7 Angstrom diameter
        return {element: 1.35 for element in elements}
    table = dict(_ccdc())
    if isinstance(radii, dict):
        table.update(radii)
    elif radii != "ccdc":
        raise ValueError("radii must be 'ccdc', 'iza', or a mapping of element to radius.")
    missing = [element for element in elements if element not in table]
    if missing:
        raise ValueError(f"No radius for {', '.join(missing)}; pass radii={{...}} for them.")
    return {element: float(table[element]) for element in elements}


def _zeopp(atoms, table: dict[str, float], probe: float) -> tuple[list[float], int, int]:
    import ase.io

    with tempfile.TemporaryDirectory(prefix="zeopp-") as scratch:
        folder = Path(scratch)
        ase.io.write(folder / "input.cif", atoms)
        (folder / "radii.rad").write_text("".join(f"{e} {r}\n" for e, r in table.items()))
        args = [
            _network(),
            "-ha",
            "-r",
            "radii.rad",
            "-resex",
            "out.res",
            "-chan",
            f"{probe:g}",
            "out.chan",
            "input.cif",
        ]
        completed = subprocess.run(args, cwd=folder, capture_output=True, text=True, check=False)
        res, chan = folder / "out.res", folder / "out.chan"
        if completed.returncode != 0 or not res.is_file():
            tail = "\n".join((completed.stdout + completed.stderr).splitlines()[-8:])
            raise RuntimeError(f"Zeo++ failed (exit {completed.returncode}):\n{tail}")
        values = [float(v) for v in res.read_text().split()[1:10]]
        match = re.search(r"(\d+) channels identified of dimensionality ([\d ]*)", chan.read_text())
        dims = [int(d) for d in match.group(2).split()] if match else []
        return values, int(match.group(1)) if match else 0, max(dims) if dims else 0


def _blocked(points, tree, image_radii, max_radius, own=None) -> np.ndarray:
    """True for points inside any (probe-expanded) atom sphere."""
    k = 32
    while True:
        k = min(k, len(image_radii))
        distances, indices = tree.query(points, k=k, distance_upper_bound=max_radius)
        valid = np.isfinite(distances)
        safe = np.where(valid, indices, 0)
        inside = valid & (distances < image_radii[safe] - 1e-9)
        if own is not None:
            inside &= safe != own[:, None]
        if k == len(image_radii) or not valid[:, -1].any():
            return inside.any(axis=1)
        k *= 2


def _monte_carlo(atoms, table, probe, samples_per_atom, volume_samples, seed) -> dict:
    from scipy.spatial import cKDTree

    rng = np.random.default_rng(seed)
    cell = atoms.cell.array
    volume = abs(np.linalg.det(cell))
    expanded = np.array([table[s] for s in atoms.get_chemical_symbols()]) + probe
    max_radius = float(expanded.max())
    widths = [
        volume / np.linalg.norm(np.cross(cell[(i + 1) % 3], cell[(i + 2) % 3])) for i in range(3)
    ]
    reach = [math.ceil(max_radius / w) + 1 for w in widths]
    offsets = np.array(list(itertools.product(*[range(-n, n + 1) for n in reach]))) @ cell
    positions = atoms.get_positions(wrap=True)
    image_positions = (positions[None, :, :] + offsets[:, None, :]).reshape(-1, 3)
    image_radii = np.tile(expanded, len(offsets))
    central = int(np.flatnonzero((offsets == 0).all(axis=1))[0]) * len(atoms)
    tree = cKDTree(image_positions)

    area = 0.0
    if max_radius > 0:
        for index, radius in enumerate(expanded):
            if radius <= 0:
                continue
            directions = rng.normal(size=(samples_per_atom, 3))
            directions /= np.linalg.norm(directions, axis=1)[:, None]
            points = positions[index] + radius * directions
            own = np.full(samples_per_atom, central + index)
            free = ~_blocked(points, tree, image_radii, max_radius, own)
            area += 4 * math.pi * radius**2 * free.mean()
    points = rng.random((volume_samples, 3)) @ cell
    fraction = (
        1.0 - _blocked(points, tree, image_radii, max(max_radius, 1e-9)).mean()
        if max_radius > 0
        else 1.0
    )
    mass_g = atoms.get_masses().sum() / AVOGADRO
    return {
        "area_a2": area,
        "fraction": float(fraction),
        "volume_a3": volume,
        "mass_g": mass_g,
    }


def pore_geometry(
    structure: str,
    probe_radius: float = 1.86,
    radii: Radii | dict[str, float] = "ccdc",
    samples_per_atom: int = 500,
    volume_samples: int = 200000,
    seed: int = 1,
) -> dict:
    """Pore sizes, channels, surface area, and pore volume of a framework.

    Args:
        structure: CIF (or other crystal file ASE reads) of the framework, with
            guests and solvent removed.
        probe_radius: Probe radius in Angstrom for channels, surface area, and
            volume (1.86 for N2, as used by many MOF databases; 1.4 water; 1.2 small
            molecules; 0 for the geometric pore volume).
        radii: "ccdc" (Zeo++'s default CCDC van der Waals radii), "iza" (every atom a
            1.35 Angstrom hard sphere, the IZA convention for zeolite frameworks), or
            a mapping of element to radius (others keep their CCDC radii).
        samples_per_atom: Monte Carlo points on each atom's surface.
        volume_samples: Monte Carlo points in the cell for the pore volume.
        seed: Random seed.

    Returns:
        Largest included sphere (Di), largest free sphere (Df, the pore-limiting
        diameter), and largest included sphere along the free path (Dif), overall
        and along a, b, and c (Angstrom); the number and dimensionality of channels
        the probe can travel through; surface area reachable by the probe
        (Angstrom2 per cell, m2/cm3, m2/g); pore volume available to the probe
        centre (fraction and cm3/g); cell volume, density, and the radii used.
    """
    if probe_radius < 0 or samples_per_atom < 10 or volume_samples < 100:
        raise ValueError("probe_radius must be >= 0, with at least 10 and 100 samples.")
    atoms = _read(structure)
    table = _radii(atoms, radii)
    (di, df, dif, df_a, df_b, df_c, *_), channels, dimensionality = _zeopp(
        atoms, table, probe_radius
    )
    mc = _monte_carlo(atoms, table, probe_radius, samples_per_atom, volume_samples, seed)
    return {
        "structure": Path(structure).name,
        "formula": atoms.get_chemical_formula(),
        "radii_angstrom": table,
        "largest_included_sphere_angstrom": round(di, 4),
        "largest_free_sphere_angstrom": round(df, 4),
        "largest_included_sphere_along_free_path_angstrom": round(dif, 4),
        "free_sphere_along_angstrom": {
            "a": round(df_a, 4),
            "b": round(df_b, 4),
            "c": round(df_c, 4),
        },
        "probe_radius_angstrom": probe_radius,
        "channels": channels,
        "channel_dimensionality": dimensionality,
        "surface_area": {
            "angstrom2_per_cell": round(mc["area_a2"], 3),
            "m2_per_cm3": round(mc["area_a2"] / mc["volume_a3"] * 1e4, 3),
            "m2_per_g": round(mc["area_a2"] * 1e-20 / mc["mass_g"], 3),
        },
        "pore_volume": {
            "fraction": round(mc["fraction"], 5),
            "cm3_per_g": round(mc["fraction"] * mc["volume_a3"] * 1e-24 / mc["mass_g"], 5),
        },
        "cell_volume_angstrom3": round(mc["volume_a3"], 3),
        "density_g_cm3": round(mc["mass_g"] / (mc["volume_a3"] * 1e-24), 5),
    }
