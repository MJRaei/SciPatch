"""Local crystal structure, point defects, and dislocations in atomistic models with OVITO.

Reads LAMMPS dump and data files, extended XYZ, POSCAR/XDATCAR, CFG, GROMACS,
PDB and more (multi-frame files are trajectories); other formats are read with
ASE. Lengths are in Angstrom.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Literal

import numpy as np

Method = Literal["adaptive_cna", "ptm", "cna", "ackland_jones", "diamond"]
Frames = Literal["all", "first", "last"]
Lattice = Literal["fcc", "bcc", "hcp", "cubic_diamond", "hexagonal_diamond"]
#: Dislocation length per volume, Angstrom^-2 to m^-2.
PER_ANGSTROM2_TO_PER_M2 = 1e20


def _pipeline(path: str):
    from ovito.io import import_file
    from ovito.pipeline import Pipeline, StaticSource

    if not Path(path).is_file():
        raise ValueError(f"No such file: {path}")
    try:
        return import_file(path)
    except Exception as ovito_error:
        try:
            from ase.io import read
            from ovito.io.ase import ase_to_ovito

            return Pipeline(source=StaticSource(data=ase_to_ovito(read(path))))
        except Exception:
            raise ValueError(f"Could not read {path}: {ovito_error}") from ovito_error


def _frames(pipeline, frames: Frames) -> list[int]:
    n = pipeline.num_frames
    return {"all": list(range(n)), "first": [0], "last": [n - 1]}[frames]


def _modifier(method: str, rmsd_cutoff: float):
    from ovito.modifiers import (
        AcklandJonesModifier,
        CommonNeighborAnalysisModifier,
        IdentifyDiamondModifier,
        PolyhedralTemplateMatchingModifier,
    )

    if method == "adaptive_cna":
        return CommonNeighborAnalysisModifier(
            mode=CommonNeighborAnalysisModifier.Mode.AdaptiveCutoff
        )
    if method == "cna":
        return CommonNeighborAnalysisModifier(
            mode=CommonNeighborAnalysisModifier.Mode.IntervalCutoff
        )
    if method == "ptm":
        ptm = PolyhedralTemplateMatchingModifier(rmsd_cutoff=rmsd_cutoff)
        for name in ("SC", "ICO", "CUBIC_DIAMOND", "HEX_DIAMOND", "GRAPHENE"):
            ptm.structures[getattr(PolyhedralTemplateMatchingModifier.Type, name)].enabled = True
        return ptm
    if method == "ackland_jones":
        return AcklandJonesModifier()
    if method == "diamond":
        return IdentifyDiamondModifier()
    raise ValueError(f"Unknown method {method}.")


def _type_names(data) -> dict[int, str]:
    prop = data.particles["Structure Type"]
    return {t.id: t.name for t in prop.types}


def _write_csv(path: str, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def structure_types(
    structure: str,
    method: Method = "adaptive_cna",
    frames: Frames = "all",
    rmsd_cutoff: float = 0.1,
    output: str = "structure_types.xyz",
    table: str = "structure_types.csv",
) -> dict:
    """Identify the local crystal structure of every atom (FCC, BCC, HCP, ICO, diamond, ...).

    Args:
        structure: Structure or trajectory file (LAMMPS dump/data, extended XYZ,
            POSCAR/XDATCAR, CFG, ...).
        method: "adaptive_cna" (default; adaptive common neighbor analysis, FCC/
            HCP/BCC/ICO), "ptm" (polyhedral template matching; most robust at
            high temperature, also simple cubic, diamond and graphene),
            "cna" (fixed cutoff), "ackland_jones" (bond angles), or "diamond"
            (cubic and hexagonal diamond, with first and second neighbors).
        frames: For trajectories, analyze "all" frames, the "first", or the "last".
        rmsd_cutoff: PTM only: largest deviation from an ideal template (0 = no limit).
        output: Extended XYZ of the last analyzed frame with each atom's structure type.
        table: CSV with the count of each structure type in each frame.

    Returns:
        Counts and fractions of each structure type in the last analyzed frame,
        the fraction of the main type over the frames (listed up to 1000), and the
        output files.
    """
    from ovito.io import export_file

    pipeline = _pipeline(structure)
    pipeline.modifiers.append(_modifier(method, rmsd_cutoff))
    rows, history, names, analyzed = [], [], {}, []
    for frame in _frames(pipeline, frames):
        data = pipeline.compute(frame)
        names = _type_names(data)
        counts = np.bincount(np.asarray(data.particles["Structure Type"]), minlength=max(names) + 1)
        rows.append([frame, *(int(counts[i]) for i in sorted(names))])
        history.append(counts)
        analyzed.append((frame, data, counts))
    frame, data, counts = analyzed[-1]
    n = int(data.particles.count)
    labelled = {names[i]: int(counts[i]) for i in sorted(names) if counts[i] or names[i] == "Other"}
    _write_csv(table, ["frame", *(names[i] for i in sorted(names))], rows)
    export_file(
        pipeline,
        output,
        "xyz",
        columns=["Particle Type", "Position.X", "Position.Y", "Position.Z", "Structure Type"],
        frame=frame,
    )
    main = max(labelled, key=labelled.get)
    main_id = next(i for i, name in names.items() if name == main)
    return {
        "method": method,
        "n_atoms": n,
        "n_frames_analyzed": len(rows),
        "counts": labelled,
        "fractions": {name: count / n for name, count in labelled.items()},
        "main_structure": main,
        "main_fraction_by_frame": [float(c[main_id] / c.sum()) for c in history]
        if len(history) <= 1000
        else None,
        "output": output,
        "table": table,
    }


def point_defects(
    structure: str,
    reference: str,
    frames: Frames = "all",
    output: str = "defects.csv",
) -> dict:
    """Count vacancies and interstitials relative to a perfect reference crystal (Wigner-Seitz).

    Each atom is assigned to the nearest site of the reference; empty sites are
    vacancies and extra atoms on a site are interstitials. Used for radiation
    damage cascades, diffusion mechanisms, and defect evolution.

    Args:
        structure: Structure or trajectory file with the damaged crystal.
        reference: Perfect crystal with the same cell (e.g. the first frame).
        frames: For trajectories, "all", "first", or "last".
        output: CSV of vacancy and interstitial counts per frame.

    Returns:
        Vacancies, interstitials, and Frenkel pairs in the last analyzed frame;
        positions of up to 100 vacancy and interstitial sites; counts per frame
        (listed up to 1000 frames); and the output file.
    """
    from ovito.modifiers import WignerSeitzAnalysisModifier

    pipeline = _pipeline(structure)
    analysis = WignerSeitzAnalysisModifier(output_displaced=False)
    analysis.reference = _pipeline(reference).source
    pipeline.modifiers.append(analysis)
    rows, analyzed = [], []
    for frame in _frames(pipeline, frames):
        data = pipeline.compute(frame)
        analyzed.append(data)
        rows.append(
            [
                frame,
                int(data.attributes["WignerSeitz.vacancy_count"]),
                int(data.attributes["WignerSeitz.interstitial_count"]),
            ]
        )
    data = analyzed[-1]
    occupancy = np.asarray(data.particles["Occupancy"])
    sites = np.asarray(data.particles.positions)
    _write_csv(output, ["frame", "vacancies", "interstitials"], rows)
    vacancies, interstitials = rows[-1][1], rows[-1][2]
    return {
        "n_sites": len(occupancy),
        "vacancies": vacancies,
        "interstitials": interstitials,
        "frenkel_pairs": min(vacancies, interstitials),
        "vacancy_sites": sites[occupancy == 0][:100].round(4).tolist(),
        "interstitial_sites": sites[occupancy > 1][:100].round(4).tolist(),
        "by_frame": rows if len(rows) <= 1000 else None,
        "output": output,
    }


def dislocations(
    structure: str,
    lattice: Lattice = "fcc",
    frame: int = -1,
    output: str = "dislocations.ca",
) -> dict:
    """Extract dislocation lines and their Burgers vectors (dislocation extraction algorithm, DXA).

    Args:
        structure: Structure or trajectory file of a crystal with the given lattice.
        lattice: Crystal structure of the material: "fcc", "bcc", "hcp",
            "cubic_diamond", or "hexagonal_diamond".
        frame: Trajectory frame to analyze (default: the last).
        output: Crystal Analysis (.ca) file with the dislocation lines, for OVITO
            or ParaView.

    Returns:
        Total dislocation line length (Angstrom) and density (m^-2), length per
        Burgers vector family (e.g. 1/2<110> perfect and 1/6<112> Shockley partials
        in fcc), and up to 100 segments with their Burgers vector (in lattice
        units, and in Angstrom in the simulation frame), length, character angle
        (0 = screw, 90 = edge), and whether they are loops or infinite lines.
    """
    from ovito.io import export_file
    from ovito.modifiers import DislocationAnalysisModifier

    structures = {
        "fcc": DislocationAnalysisModifier.Lattice.FCC,
        "bcc": DislocationAnalysisModifier.Lattice.BCC,
        "hcp": DislocationAnalysisModifier.Lattice.HCP,
        "cubic_diamond": DislocationAnalysisModifier.Lattice.CubicDiamond,
        "hexagonal_diamond": DislocationAnalysisModifier.Lattice.HexagonalDiamond,
    }
    pipeline = _pipeline(structure)
    n = pipeline.num_frames
    if not -n <= frame < n:
        raise ValueError(f"frame must be within the {n} frames.")
    pipeline.modifiers.append(
        DislocationAnalysisModifier(input_crystal_structure=structures[lattice])
    )
    data = pipeline.compute(frame % n)
    attributes = data.attributes
    total = float(attributes["DislocationAnalysis.total_line_length"])
    volume = float(abs(np.linalg.det(np.asarray(data.cell)[:, :3])))
    families = {
        key.split("DislocationAnalysis.length.", 1)[1]: float(value)
        for key, value in attributes.items()
        if key.startswith("DislocationAnalysis.length.") and value > 0
    }
    segments = []
    for segment in data.dislocations.segments[:100]:
        points = np.asarray(segment.points)
        burgers = np.asarray(segment.spatial_burgers_vector)
        steps = np.diff(points, axis=0)
        lengths = np.linalg.norm(steps, axis=1)
        cosines = np.abs(steps @ burgers) / np.maximum(lengths * np.linalg.norm(burgers), 1e-12)
        mean_cos = float((cosines * lengths).sum() / max(lengths.sum(), 1e-12))
        segments.append(
            {
                "burgers_vector": [round(float(v), 4) for v in segment.true_burgers_vector],
                "burgers_vector_angstrom": [round(float(v), 4) for v in burgers],
                "burgers_magnitude_angstrom": float(np.linalg.norm(burgers)),
                "length_angstrom": float(segment.length),
                "character_deg": float(np.degrees(np.arccos(min(mean_cos, 1.0)))),
                "is_loop": bool(segment.is_loop),
                "is_infinite_line": bool(segment.is_infinite_line),
            }
        )
    export_file(pipeline, output, "ca", frame=frame % n)
    return {
        "lattice": lattice,
        "n_segments": len(data.dislocations.segments),
        "total_line_length_angstrom": total,
        "dislocation_density_per_m2": total / volume * PER_ANGSTROM2_TO_PER_M2 if volume else None,
        "length_by_family_angstrom": families,
        "segments": segments,
        "crystalline_fraction": 1
        - float(attributes.get("DislocationAnalysis.counts.OTHER", 0))
        / max(int(data.particles.count), 1),
        "output": output,
    }
