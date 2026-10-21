"""Crystal structure tools: symmetry, standard cells, supercells, conversion, XRD, matching.

Built on pymatgen (with spglib for symmetry). Structures can be read from CIF,
POSCAR/CONTCAR, pymatgen JSON, extended XYZ, and other formats ASE understands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

#: Extensions written through ASE (pymatgen has no periodic XYZ writer).
_ASE_FORMATS = {".xyz": "extxyz", ".extxyz": "extxyz"}


def _read(path: str):
    """Read a structure with pymatgen, falling back to ASE for other formats."""
    from pymatgen.core import Structure

    try:
        return Structure.from_file(path)
    except Exception:  # noqa: BLE001 - try ASE's readers next
        from ase.io import read
        from pymatgen.io.ase import AseAtomsAdaptor

        try:
            return AseAtomsAdaptor.get_structure(read(path))
        except Exception as exc:
            raise ValueError(f"Could not read a crystal structure from {path}: {exc}") from exc


def _write(structure, path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in _ASE_FORMATS:
        from ase.io import write
        from pymatgen.io.ase import AseAtomsAdaptor

        write(path, AseAtomsAdaptor.get_atoms(structure), format=_ASE_FORMATS[suffix])
    else:
        structure.to(filename=path)
    return path


def _lattice(structure) -> dict:
    a, b, c = structure.lattice.abc
    alpha, beta, gamma = structure.lattice.angles
    return {
        "a_angstrom": round(a, 6),
        "b_angstrom": round(b, 6),
        "c_angstrom": round(c, 6),
        "alpha_deg": round(alpha, 4),
        "beta_deg": round(beta, 4),
        "gamma_deg": round(gamma, 4),
    }


def symmetry(
    structure: str,
    symprec: float = 0.01,
    angle_tolerance: float = 5.0,
    conventional_output: str = "conventional.cif",
    primitive_output: str = "primitive.cif",
) -> dict:
    """Find the space group and write the standard conventional and primitive cells.

    Args:
        structure: Path to a structure file (CIF, POSCAR, JSON, extended XYZ, ...).
        symprec: Distance tolerance for symmetry finding in Å. Use 0.1 for
            structures relaxed with loose settings or taken from MD.
        angle_tolerance: Angle tolerance in degrees.
        conventional_output: File for the standard conventional cell.
        primitive_output: File for the standard primitive cell.

    Returns:
        Reduced formula, space group symbol and number, crystal system, point
        group, the conventional cell's lattice parameters (Å, degrees), density
        (g/cm³), the symmetry-distinct sites with Wyckoff letters, and the paths
        of the written cells.
    """
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    crystal = _read(structure)
    analyzer = SpacegroupAnalyzer(crystal, symprec=symprec, angle_tolerance=angle_tolerance)
    conventional = analyzer.get_conventional_standard_structure()
    primitive = analyzer.get_primitive_standard_structure()
    symmetrized = analyzer.get_symmetrized_structure()
    sites = [
        {
            "element": group[0].species_string,
            "wyckoff": symbol,
            "multiplicity": len(group),
        }
        for group, symbol in zip(
            symmetrized.equivalent_sites, symmetrized.wyckoff_symbols, strict=True
        )
    ]
    return {
        "formula": crystal.composition.reduced_formula,
        "n_sites": len(crystal),
        "space_group_symbol": analyzer.get_space_group_symbol(),
        "space_group_number": analyzer.get_space_group_number(),
        "crystal_system": analyzer.get_crystal_system(),
        "point_group": analyzer.get_point_group_symbol(),
        "conventional_lattice": _lattice(conventional),
        "density_g_cm3": round(float(crystal.density), 5),
        "distinct_sites": sites,
        "conventional_cell": _write(conventional, conventional_output),
        "conventional_n_sites": len(conventional),
        "primitive_cell": _write(primitive, primitive_output),
        "primitive_n_sites": len(primitive),
    }


def make_supercell(
    structure: str,
    scaling: list[int] | None = None,
    output: str = "supercell.cif",
) -> dict:
    """Repeat a structure along its three lattice vectors.

    Args:
        structure: Path to a structure file.
        scaling: Repetitions along a, b, and c, e.g. [3, 2, 2]. Default [2, 2, 2].
        output: File for the supercell (format from the extension: .cif, .vasp or
            POSCAR, .json, .xyz/.extxyz, ...).

    Returns:
        Number of sites, formula, lattice parameters (Å, degrees), volume (Å³),
        and the supercell's path.
    """
    factors = scaling or [2, 2, 2]
    if len(factors) != 3 or any(int(f) != f or f < 1 for f in factors):
        raise ValueError("scaling must be three positive integers, e.g. [3, 2, 2].")
    crystal = _read(structure)
    crystal.make_supercell([int(f) for f in factors])
    return {
        "n_sites": len(crystal),
        "formula": crystal.composition.formula,
        "lattice": _lattice(crystal),
        "volume_angstrom3": round(float(crystal.volume), 6),
        "supercell": _write(crystal, output),
    }


def convert(structure: str, output: str) -> dict:
    """Convert a structure file to another format, chosen by the output's extension.

    Args:
        structure: Path to the input structure file.
        output: Output file: .cif, .vasp or POSCAR, .json (pymatgen), .xsf,
            .xyz or .extxyz (extended XYZ with the cell).

    Returns:
        The output path, formula, and number of sites.
    """
    crystal = _read(structure)
    return {
        "output": _write(crystal, output),
        "formula": crystal.composition.reduced_formula,
        "n_sites": len(crystal),
    }


def xrd_pattern(
    structure: str,
    wavelength: Literal["CuKa", "MoKa", "CoKa", "FeKa", "CrKa", "AgKa"] = "CuKa",
    two_theta_min: float = 0.0,
    two_theta_max: float = 90.0,
    min_intensity: float = 0.0,
    plot: str = "xrd.png",
    data: str = "xrd.csv",
) -> dict:
    """Simulate a powder X-ray diffraction pattern.

    Intensities include atomic scattering factors, the Lorentz-polarization factor,
    and multiplicities, scaled so the strongest peak is 100. No peak broadening,
    preferred orientation, or thermal (Debye-Waller) effects are included.

    Args:
        structure: Path to a structure file.
        wavelength: X-ray source (Kα, weighted average of Kα1 and Kα2).
        two_theta_min: Lower end of the 2θ range in degrees.
        two_theta_max: Upper end of the 2θ range in degrees.
        min_intensity: Leave out peaks weaker than this (0 to 100).
        plot: PNG file for the pattern.
        data: CSV file with every peak (2θ, intensity, d-spacing, hkl).

    Returns:
        The wavelength (Å), the peaks in order of increasing 2θ (2θ in degrees,
        relative intensity, d-spacing in Å, Miller indices), the number of peaks,
        and the plot and data paths.
    """
    import csv

    import matplotlib

    matplotlib.use("Agg")
    from pymatgen.analysis.diffraction.xrd import WAVELENGTHS, XRDCalculator

    if not 0 <= two_theta_min < two_theta_max <= 180:
        raise ValueError("Use 0 <= two_theta_min < two_theta_max <= 180 (degrees).")
    calculator = XRDCalculator(wavelength=wavelength)
    crystal = _read(structure)
    pattern = calculator.get_pattern(crystal, two_theta_range=(two_theta_min, two_theta_max))
    peaks = [
        {
            "two_theta": float(x),
            "intensity": float(y),
            "d_angstrom": float(d),
            "hkls": [list(item["hkl"]) for item in hkls],
        }
        for x, y, d, hkls in zip(pattern.x, pattern.y, pattern.d_hkls, pattern.hkls, strict=True)
        if y >= min_intensity
    ]
    with open(data, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["two_theta_deg", "intensity", "d_angstrom", "hkl"])
        for peak in peaks:
            hkl = " ".join("".join(map(str, h)) for h in peak["hkls"])
            writer.writerow([peak["two_theta"], peak["intensity"], peak["d_angstrom"], hkl])
    axes = calculator.get_plot(crystal, two_theta_range=(two_theta_min, two_theta_max))
    axes.figure.savefig(plot, dpi=150, bbox_inches="tight")
    matplotlib.pyplot.close(axes.figure)
    return {
        "wavelength_angstrom": WAVELENGTHS[wavelength],
        "n_peaks": len(peaks),
        "peaks": peaks[:200],
        "plot": plot,
        "data": data,
    }


def compare(
    structure_a: str,
    structure_b: str,
    length_tolerance: float = 0.2,
    site_tolerance: float = 0.3,
    angle_tolerance: float = 5.0,
) -> dict:
    """Check whether two structures are the same crystal (pymatgen StructureMatcher).

    Different cell choices, origins, and site orders are recognized as the same.

    Args:
        structure_a: Path to the first structure file.
        structure_b: Path to the second structure file.
        length_tolerance: Allowed fractional difference in lattice lengths.
        site_tolerance: Allowed site displacement, as a fraction of the average
            free length per atom, (V / n)^(1/3).
        angle_tolerance: Allowed difference in lattice angles in degrees.

    Returns:
        Whether they match, and if so the root-mean-square and largest site
        displacements, both as fractions of (V / n)^(1/3).
    """
    from pymatgen.analysis.structure_matcher import StructureMatcher

    matcher = StructureMatcher(
        ltol=length_tolerance, stol=site_tolerance, angle_tol=angle_tolerance
    )
    first, second = _read(structure_a), _read(structure_b)
    distances = matcher.get_rms_dist(first, second)
    if distances is None:
        return {"match": False, "rms_displacement": None, "max_displacement": None}
    rms, largest = distances
    return {
        "match": True,
        "rms_displacement": float(rms),
        "max_displacement": float(largest),
    }
