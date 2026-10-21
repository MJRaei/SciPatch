"""Mass spectrometry calculations with pyOpenMS (OpenMS).

Exact masses and m/z values of molecules and peptides (with modifications),
isotope patterns, enzymatic digestion of proteins into peptides, theoretical
fragment-ion ladders for peptide identification, and summaries of mzML data files.
Peptides use one-letter codes with OpenMS modification notation, e.g.
"PEPTM(Oxidation)IDEC(Carbamidomethyl)K".
"""

from __future__ import annotations

import csv
import functools
import os
from pathlib import Path
from typing import Literal

PROTON_MASS = 1.007276466621  # u, CODATA 2018


@functools.cache
def _oms():
    os.environ.setdefault("OPENMS_DATA_PATH", "")
    import pyopenms

    return pyopenms


def _formula(text: str):
    try:
        formula = _oms().EmpiricalFormula(text)
    except Exception as exc:
        raise ValueError(f"Cannot read the formula {text!r}: {exc}") from exc
    if formula.getMonoWeight() <= 0:
        raise ValueError(f"Cannot read the formula {text!r}.")
    return formula


def _peptide(text: str):
    sequence = text.strip()
    try:
        peptide = _oms().AASequence.fromString(sequence)
    except Exception as exc:
        raise ValueError(f"Cannot read the peptide {text!r}: {exc}") from exc
    if peptide.size() == 0:
        raise ValueError("The peptide sequence is empty.")
    return peptide


def _one(formula: str | None, peptide: str | None):
    if (formula is None) == (peptide is None):
        raise ValueError("Give either a formula or a peptide.")
    if formula is not None:
        return _formula(formula), formula
    sequence = _peptide(peptide)
    return sequence.getFormula(), sequence.toString()


def mass(
    formula: str | None = None,
    peptide: str | None = None,
    charges: list[int] | None = None,
) -> dict:
    """Monoisotopic and average mass of a molecule or peptide, and its m/z values.

    Args:
        formula: Molecular formula, e.g. "C8H10N4O2" (isotopes as "(13)C2").
        peptide: Peptide in one-letter code with optional OpenMS modifications,
            e.g. "DRVYIHPF" or "PEPTM(Oxidation)IDEK".
        charges: Charge states for m/z, positive for [M+zH]z+ and negative for
            [M-zH]z- (default 1, 2, 3).

    Returns:
        The elemental formula, monoisotopic and average masses (Da), and m/z of each
        protonated or deprotonated ion.
    """
    composition, label = _one(formula, peptide)
    mono = composition.getMonoWeight()
    ions = []
    for z in charges or [1, 2, 3]:
        if z == 0:
            raise ValueError("Charges must be non-zero.")
        ions.append(
            {
                "charge": z,
                "ion": _ion_label(z),
                "mz": round((mono + z * PROTON_MASS) / abs(z), 6),
            }
        )
    return {
        "input": label,
        "formula": composition.toString(),
        "monoisotopic_mass_da": round(mono, 6),
        "average_mass_da": round(composition.getAverageWeight(), 5),
        "ions": ions,
    }


def _ion_label(z: int) -> str:
    sign = "+" if z > 0 else "-"
    count = str(abs(z)) if abs(z) > 1 else ""
    return f"[M{sign}{count}H]{count}{sign}"


def isotope_pattern(
    formula: str | None = None,
    peptide: str | None = None,
    charge: int = 0,
    resolution: Literal["fine", "coarse"] = "fine",
    min_abundance: float = 1e-4,
    table: str = "isotopes.csv",
    plot: str = "isotopes.png",
) -> dict:
    """Isotope distribution of a molecule or peptide from natural isotope abundances.

    Args:
        formula: Molecular formula (or give a peptide).
        peptide: Peptide sequence.
        charge: 0 for neutral masses, z for [M+zH]z+ m/z values.
        resolution: "fine" resolves isotopologues of nearly equal mass (e.g. 13C vs
            15N); "coarse" groups them by nominal mass (as seen at low resolution).
        min_abundance: Drop peaks below this fraction of the total.
        table: CSV of the peaks.
        plot: PNG stick spectrum.

    Returns:
        Peaks with mass or m/z, probability (fraction of all molecules), and
        intensity relative to the largest peak.
    """
    oms = _oms()
    composition, label = _one(formula, peptide)
    if resolution == "fine":
        generator = oms.FineIsotopePatternGenerator(min_abundance)
    else:
        generator = oms.CoarseIsotopePatternGenerator(50)
    distribution = composition.getIsotopeDistribution(generator)
    peaks = [(p.getMZ(), p.getIntensity()) for p in distribution.getContainer()]
    total = sum(i for _, i in peaks)
    peaks = [(m, i / total) for m, i in peaks if i / total >= min_abundance]
    top = max(i for _, i in peaks)
    rows = []
    for neutral, probability in peaks:
        value = (neutral + charge * PROTON_MASS) / abs(charge) if charge else neutral
        rows.append(
            {
                "mz" if charge else "mass_da": round(value, 6),
                "probability": round(probability, 6),
                "relative_intensity": round(probability / top, 6),
            }
        )
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _stick_plot(
        [(next(iter(r.values())), r["relative_intensity"]) for r in rows],
        f"{label}{f' ({charge:+d})' if charge else ''}",
        "m/z" if charge else "Mass (Da)",
        plot,
    )
    return {
        "input": label,
        "formula": composition.toString(),
        "peaks": rows,
        "table": table,
        "plot": plot,
    }


def _stick_plot(points: list[tuple[float, float]], title: str, xlabel: str, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(6.5, 3.5))
    for x, y in points:
        axes.vlines(x, 0, y)
    axes.set(xlabel=xlabel, ylabel="Relative intensity", title=title, ylim=(0, 1.05))
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def digest(
    protein: str,
    enzyme: str = "Trypsin",
    missed_cleavages: int = 0,
    min_length: int = 1,
    max_length: int = 100,
    table: str = "peptides.csv",
) -> dict:
    """Enzymatic digestion of a protein into peptides (in silico).

    Args:
        protein: Protein sequence (one-letter code) or a FASTA file (the first
            entry is used).
        enzyme: Protease name, e.g. "Trypsin" (after K/R, not before P),
            "Trypsin/P", "Lys-C", "Arg-C", "Asp-N", "Glu-C", "Chymotrypsin"; see
            enzymes().
        missed_cleavages: Maximum missed cleavage sites per peptide.
        min_length: Shortest peptide to keep.
        max_length: Longest peptide to keep.
        table: CSV of the peptides.

    Returns:
        Peptides in order with start and end positions (1-based), length,
        missed cleavages, monoisotopic mass, and m/z of the 2+ ion.
    """
    oms = _oms()
    sequence = _protein_sequence(protein)
    if enzyme not in _enzyme_names():
        raise ValueError(f"Unknown enzyme {enzyme!r}; see enzymes().")
    digestion = oms.ProteaseDigestion()
    digestion.setEnzyme(enzyme)
    digestion.setMissedCleavages(int(missed_cleavages))
    peptides: list = []
    digestion.digest(oms.AASequence.fromString(sequence), peptides, min_length, max_length)
    # Cleavage sites: the ends of the fully cleaved peptides (except the protein's end).
    complete: list = []
    digestion.setMissedCleavages(0)
    digestion.digest(oms.AASequence.fromString(sequence), complete, 1, len(sequence))
    sites, position = [], 0
    for piece in complete:  # returned from N- to C-terminus
        position += piece.size()
        sites.append(position)
    rows = []
    for peptide in peptides:
        text = peptide.toUnmodifiedString()
        start = _position(sequence, text, rows)
        mono = peptide.getMonoWeight()
        rows.append(
            {
                "peptide": text,
                "start": start,
                "end": start + len(text) - 1,
                "length": len(text),
                "missed_cleavages": sum(start <= site < start + len(text) - 1 for site in sites),
                "monoisotopic_mass_da": round(mono, 5),
                "mz_2plus": round((mono + 2 * PROTON_MASS) / 2, 5),
            }
        )
    rows.sort(key=lambda r: (r["start"], r["length"]))
    if rows:
        with open(table, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return {"enzyme": enzyme, "protein_length": len(sequence), "peptides": rows, "table": table}


def _protein_sequence(protein: str) -> str:
    path = Path(protein)
    if path.suffix.lower() in (".fasta", ".fa", ".faa") and path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
        body = []
        for line in lines[1:] if lines and lines[0].startswith(">") else lines:
            if line.startswith(">"):
                break
            body.append(line.strip())
        protein = "".join(body)
    sequence = "".join(protein.split()).upper()
    if not sequence.isalpha():
        raise ValueError("A protein sequence contains letters only (or give a FASTA file).")
    return sequence


def _position(sequence: str, peptide: str, earlier: list[dict]) -> int:
    used = {(r["peptide"], r["start"]) for r in earlier}
    start = sequence.find(peptide)
    while start >= 0 and (peptide, start + 1) in used:
        start = sequence.find(peptide, start + 1)
    return start + 1


@functools.cache
def _enzyme_names() -> list[str]:
    names: list = []
    _oms().ProteaseDB().getAllNames(names)
    return sorted(n.decode() if isinstance(n, bytes) else n for n in names)


def enzymes() -> dict:
    """Proteases available for digest.

    Returns:
        The enzyme names.
    """
    return {"enzymes": _enzyme_names()}


def fragment_ions(
    peptide: str,
    max_charge: int = 1,
    ion_types: list[Literal["a", "b", "c", "x", "y", "z"]] | None = None,
    neutral_losses: bool = False,
    table: str = "fragments.csv",
) -> dict:
    """Theoretical fragment ions of a peptide (for matching MS/MS spectra).

    Args:
        peptide: Peptide sequence with optional modifications.
        max_charge: Highest fragment charge.
        ion_types: Ion series (default b and y, as in CID/HCD spectra; c and z for
            ETD).
        neutral_losses: Also add water and ammonia losses.
        table: CSV of the ions.

    Returns:
        Each ion with its name (e.g. "y3++"), series, number, charge, and m/z,
        sorted by m/z.
    """
    oms = _oms()
    sequence = _peptide(peptide)
    kinds = ion_types or ["b", "y"]
    generator = oms.TheoreticalSpectrumGenerator()
    parameters = generator.getParameters()
    for kind in "abcxyz":
        parameters.setValue(f"add_{kind}_ions", "true" if kind in kinds else "false")
    parameters.setValue("add_losses", "true" if neutral_losses else "false")
    parameters.setValue("add_metainfo", "true")
    generator.setParameters(parameters)
    spectrum = oms.MSSpectrum()
    generator.getSpectrum(spectrum, sequence, 1, int(max_charge))
    names = [n.decode() if isinstance(n, bytes) else n for n in spectrum.getStringDataArrays()[0]]
    rows = []
    for name, peak in zip(names, spectrum, strict=True):
        series = name[0]
        number = "".join(ch for ch in name[1:] if ch.isdigit())
        rows.append(
            {
                "ion": name,
                "series": series,
                "number": int(number) if number else None,
                "charge": name.count("+") or 1,
                "mz": round(peak.getMZ(), 5),
            }
        )
    rows.sort(key=lambda r: r["mz"])
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"peptide": sequence.toString(), "ions": rows, "table": table}


def mzml_summary(file: str) -> dict:
    """Overview of an mzML data file: spectra, MS levels, retention time, and m/z ranges.

    Args:
        file: Path to an .mzML file.

    Returns:
        Number of spectra and chromatograms, spectra per MS level, total peaks,
        retention-time range (s), m/z range, total ion current, and the five most
        intense MS1 base peaks.
    """
    oms = _oms()
    path = Path(file)
    if not path.is_file():
        raise ValueError(f"File {file!r} not found.")
    experiment = oms.MSExperiment()
    try:
        oms.MzMLFile().load(str(path), experiment)
    except Exception as exc:
        raise ValueError(f"Could not read {path.name} as mzML: {exc}") from exc
    levels: dict[int, int] = {}
    times, low, high, tic, bases, count = [], [], [], 0.0, [], 0
    for spectrum in experiment:
        level = spectrum.getMSLevel()
        levels[level] = levels.get(level, 0) + 1
        times.append(spectrum.getRT())
        mz, intensity = spectrum.get_peaks()
        count += len(mz)
        if len(mz):
            low.append(float(mz.min()))
            high.append(float(mz.max()))
            tic += float(intensity.sum())
            if level == 1:
                top = int(intensity.argmax())
                bases.append((float(intensity[top]), float(mz[top]), spectrum.getRT()))
    bases.sort(reverse=True)
    return {
        "spectra": experiment.getNrSpectra(),
        "chromatograms": experiment.getNrChromatograms(),
        "spectra_per_ms_level": {str(k): v for k, v in sorted(levels.items())},
        "peaks": count,
        "retention_time_s": [round(min(times), 3), round(max(times), 3)] if times else None,
        "mz_range": [round(min(low), 4), round(max(high), 4)] if low else None,
        "total_ion_current": round(tic, 3),
        "top_ms1_base_peaks": [
            {"mz": round(m, 5), "intensity": round(i, 3), "retention_time_s": round(t, 3)}
            for i, m, t in bases[:5]
        ],
    }
