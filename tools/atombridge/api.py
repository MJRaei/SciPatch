"""From electron micrographs and papers to crystal lattices, with AtomBridge.

Wraps the image and structure analysis of AtomBridge (github.com/dpalmer-anl/AtomBridge,
a 2025 LLM Hackathon project): measuring the two in-plane lattice vectors of an
atomic-resolution STEM/TEM image (atom-column detection and neighbour-vector
clustering, with a Fourier-transform fallback), extracting figures and their
captions from a paper's PDF and flagging electron micrographs, and checking a
structure for atoms that are too close. AtomBridge's Gemini code generation and
Streamlit interface are left out; the calling agent builds structures from the
measured lattice.
"""

from __future__ import annotations

import functools
import os
import sys
import warnings
from pathlib import Path

import numpy as np


@functools.cache
def _source() -> Path:
    warnings.filterwarnings("ignore")
    root = Path(os.environ["MOTEL_SOURCE_DIR"])
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def measure_lattice(
    image: str,
    nm_per_pixel: float,
    crop: list[int] | None = None,
    cif: str | None = "lattice.cif",
) -> dict:
    """Two in-plane lattice vectors from an atomic-resolution STEM/TEM image.

    Args:
        image: Image file (PNG, JPEG, TIFF, ...) showing a periodic lattice of atom
            columns; bright columns on a dark background (HAADF-like) work best.
        nm_per_pixel: Image scale in nm per pixel (from the scale bar).
        crop: Region to analyse as [x, y, width, height] in pixels (default: the
            whole image). Choose a clean, periodic area.
        cif: Write a minimal CIF with the measured 2D cell (c = 10 Angstrom, one
            placeholder atom X) here; null to skip.

    Returns:
        Lattice lengths a and b (nm and Angstrom) and the angle gamma between them
        (degrees), the number of atom columns detected, the method (real-space
        neighbour clustering, or the Fourier-transform fallback), and an overlay
        image with the detected columns and vectors.
    """
    _source()
    from PIL import Image
    from src.stem_analysis import measure_lattice_vectors, minimal_cif_from_lattice

    path = Path(image)
    if not path.is_file():
        raise ValueError(f"Image file {image!r} not found.")
    if nm_per_pixel <= 0:
        raise ValueError("nm_per_pixel must be positive.")
    try:
        picture = Image.open(path).convert("L")
    except Exception as exc:
        raise ValueError(f"{path.name} is not an image file: {exc}") from exc
    if crop is not None:
        if len(crop) != 4 or crop[2] < 16 or crop[3] < 16:
            raise ValueError("crop must be [x, y, width, height] with at least 16 x 16 pixels.")
        x, y, width, height = (int(v) for v in crop)
        picture = picture.crop((x, y, x + width, y + height))
    working = Path(f"{path.stem}_analysed.png").resolve()
    picture.save(working)  # the overlay is written next to this copy
    try:
        result = measure_lattice_vectors(str(working), float(nm_per_pixel))
    except RuntimeError as exc:
        raise ValueError(f"{exc}. Try a larger, cleaner crop or check the scale.") from exc
    overlay = Path(result["overlay_path"])
    output = {
        "a_nm": round(result["a_nm"], 5),
        "b_nm": round(result["b_nm"], 5),
        "gamma_deg": round(result["gamma_deg"], 3),
        "a_angstrom": round(result["a_nm"] * 10, 4),
        "b_angstrom": round(result["b_nm"] * 10, 4),
        "columns_detected": result["n_atoms"],
        "method": "fourier_transform" if overlay.stem.endswith("_fft") else "real_space_clustering",
        "image_size_px": list(picture.size),
        "overlay": overlay.name,
    }
    if cif:
        minimal_cif_from_lattice(result["a_nm"], result["b_nm"], result["gamma_deg"], cif)
        output["cif"] = cif
    return output


def extract_figures(pdf: str, output_dir: str = "figures", only_micrographs: bool = False) -> dict:
    """Figures of a paper's PDF with their captions, flagging electron micrographs.

    Args:
        pdf: The paper's PDF.
        output_dir: Folder for the figure images (PNG, 300 dpi); panels are split
            into separate images when they can be segmented.
        only_micrographs: Return only figures flagged as STEM/TEM micrographs.

    Returns:
        For each figure: page, image file, bounding box on the page (points),
        caption (the text block just below), whether it looks like an electron
        micrograph (from caption and page keywords), and that keyword score;
        plus the counts.
    """
    _source()
    from src.figures import extract_figures_v2

    path = Path(pdf)
    if not path.is_file():
        raise ValueError(f"PDF file {pdf!r} not found.")
    try:
        figures = extract_figures_v2(str(path), out_dir=output_dir)
    except Exception as exc:
        raise ValueError(f"Could not read {path.name} as a PDF: {exc}") from exc
    rows = [
        {
            "page": figure.page_index + 1,
            "image": figure.image_path,
            "bbox": [round(float(v), 1) for v in figure.bbox],
            "caption": figure.caption,
            "micrograph": bool(figure.is_tem),
            "micrograph_score": int(figure.tem_score),
        }
        for figure in figures
        if figure.is_tem or not only_micrographs
    ]
    return {
        "pdf": path.name,
        "figures": rows,
        "count": len(rows),
        "micrographs": sum(1 for row in rows if row["micrograph"]),
    }


def check_structure(structure: str, cutoff_angstrom: float = 0.5) -> dict:
    """Check a structure for atoms that are too close (overlaps).

    Args:
        structure: Structure file ASE can read (CIF, POSCAR, XYZ, ...); periodic
            images are taken into account.
        cutoff_angstrom: Pairs closer than this are reported as overlaps.

    Returns:
        The minimum interatomic distance, the overlapping pairs (indices,
        elements, distance), whether the check passed, and the shortest distance
        for each pair of elements.
    """
    _source()
    from ase.io import read
    from src.structure_checks import distance_summary

    path = Path(structure)
    if not path.is_file():
        raise ValueError(f"Structure file {structure!r} not found.")
    try:
        atoms = read(path)
    except Exception as exc:
        raise ValueError(f"Could not read {path.name} as a structure: {exc}") from exc
    if len(atoms) < 2:
        raise ValueError("The structure needs at least two atoms.")
    summary = distance_summary(atoms, cutoff=cutoff_angstrom)
    distances = atoms.get_all_distances(mic=bool(atoms.pbc.any()))
    symbols = atoms.get_chemical_symbols()
    upper = np.triu_indices(len(atoms), k=1)
    pairs = [
        {
            "atoms": [int(i), int(j)],
            "elements": [symbols[i], symbols[j]],
            "distance_angstrom": round(float(distances[i, j]), 4),
        }
        for i, j in zip(*upper, strict=True)
        if distances[i, j] < cutoff_angstrom
    ]
    shortest: dict[str, float] = {}
    for i, j in zip(*upper, strict=True):
        key = "-".join(sorted((symbols[i], symbols[j])))
        shortest[key] = min(shortest.get(key, np.inf), float(distances[i, j]))
    return {
        "structure": path.name,
        "atoms": len(atoms),
        "min_distance_angstrom": round(float(summary["min_distance"]), 4),
        "overlapping_pairs": pairs,
        "passed": not pairs,
        "cutoff_angstrom": cutoff_angstrom,
        "shortest_by_elements_angstrom": {k: round(v, 4) for k, v in sorted(shortest.items())},
    }
