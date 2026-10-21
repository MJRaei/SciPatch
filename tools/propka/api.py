"""Protein pKa values and protonation states with PROPKA 3.

PROPKA predicts the pKa of every titratable group in a protein structure (Asp,
Glu, His, Cys, Tyr, Lys, Arg, termini, and ligand groups) from empirical
desolvation, hydrogen-bond, and charge-charge terms, and from them the charge,
isoelectric point, and pH-dependent folding free energy of the protein.
"""

from __future__ import annotations

import csv
import functools
import logging
import re
import tempfile
import urllib.request
from pathlib import Path

#: PROPKA's pKa for cysteines in disulfide bonds (they do not titrate).
DISULFIDE_PKA = 99.0
#: Residue types reported as acids (negative when deprotonated); the rest are bases.
ACIDS = {"ASP", "GLU", "C-", "CYS", "TYR"}
ONE_LETTER = {"D": "ASP", "E": "GLU", "H": "HIS", "C": "CYS", "Y": "TYR", "K": "LYS", "R": "ARG"}


@functools.cache
def _quiet() -> None:
    logging.disable(logging.WARNING)


def _run(structure: str, keep_hetero: bool):
    _quiet()
    import propka.run

    path = Path(structure)
    if not path.is_file():
        raise ValueError(f"Structure file {structure!r} not found; use fetch_pdb for a PDB ID.")
    if path.suffix.lower() not in (".pdb", ".pqr", ".ent"):
        raise ValueError("PROPKA reads PDB (.pdb, .ent) or PQR files.")
    with tempfile.TemporaryDirectory() as folder:
        source = path
        if not keep_hetero:  # waters, ions, and ligands
            source = Path(folder) / f"{path.stem}{path.suffix}"
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            source.write_text("".join(x for x in lines if not x.startswith("HETATM")), "utf-8")
        try:
            return propka.run.single(str(source), optargs=["--quiet"], write_pka=False)
        except Exception as exc:
            raise ValueError(f"PROPKA could not read {path.name}: {exc}") from exc


def _groups(molecule, chains: list[str] | None) -> list:
    conformation = molecule.conformations["AVR"]
    order = molecule.version.parameters.write_out_order
    selected = []
    for residue_type in order:
        for group in conformation.groups:
            if group.residue_type != residue_type or group.coupled_titrating_group:
                continue
            if chains and group.atom.chain_id not in chains:
                continue
            selected.append(group)
    return selected


def _charge(group, ph: float) -> float:
    if group.residue_type in ACIDS:
        return -1.0 / (1.0 + 10 ** (group.pka_value - ph))
    return 1.0 / (1.0 + 10 ** (ph - group.pka_value))


def _key(text: str) -> tuple[str, int, str | None]:
    """Parse "GLU 35 A", "Glu35", "E35:A", or "N+ 1 A" into (type, number, chain)."""
    match = re.match(r"^\s*([A-Za-z+\-]+)\s*:?\s*(-?\d+)\s*:?\s*([A-Za-z0-9]?)\s*$", text)
    if not match:
        raise ValueError(f"Cannot read the residue {text!r}; write e.g. 'GLU 35 A' or 'E35'.")
    kind, number, chain = match.groups()
    kind = kind.upper()
    kind = ONE_LETTER.get(kind, kind)
    return kind, int(number), chain or None


def protein_pka(
    structure: str,
    ph: float = 7.0,
    chains: list[str] | None = None,
    experimental: dict[str, float] | None = None,
    keep_hetero: bool = False,
    table: str = "pka.csv",
) -> dict:
    """pKa and charge of every titratable group of a protein at a given pH.

    Args:
        structure: PDB or PQR file (crystal or model structure; hydrogens are not
            needed). Use fetch_pdb to download one by PDB ID.
        ph: pH at which to report charges and protonation.
        chains: Only report these chains (default all).
        experimental: Measured pKa values to compare with, e.g. {"GLU 35 A": 6.2,
            "D52": 3.68}.
        keep_hetero: Keep HETATM records (ligands, ions, waters) so that bound
            ligands affect the pKa values and their own groups are reported. By
            default they are removed: PROPKA can mistype small ions (e.g. it treats
            nitrate as an amine).
        table: CSV with every group.

    Returns:
        For each group: residue, chain, number, predicted pKa, model (unperturbed)
        pKa and the shift, how buried it is (%), its average charge at `ph`, and
        whether it is mostly protonated (cysteines in disulfide bonds are listed
        separately, as they do not titrate); the net charge at `ph` and the
        isoelectric point (folded and unfolded); groups whose pKa is shifted by
        more than 1.5 units; and, with `experimental`, the per-group differences
        and their RMS.
    """
    molecule = _run(structure, keep_hetero)
    groups = _groups(molecule, chains)
    if not groups:
        raise ValueError("No titratable groups found (check the chain identifiers).")
    rows = []
    disulfides = []
    for group in groups:
        if group.residue_type == "CYS" and group.pka_value >= DISULFIDE_PKA:
            disulfides.append(" ".join(group.label.split()))
            continue
        rows.append(
            {
                "residue": group.residue_type,
                "number": int(group.atom.res_num),
                "chain": group.atom.chain_id,
                "label": " ".join(group.label.split()),
                "pka": round(float(group.pka_value), 2),
                "model_pka": round(float(group.model_pka), 2),
                "shift": round(float(group.pka_value - group.model_pka), 2),
                "buried_percent": round(float(group.buried) * 100, 0),
                "charge_at_ph": round(_charge(group, ph), 3),
                "protonated_at_ph": bool(group.pka_value > ph),
                "ligand": group.atom.type == "hetatm",
            }
        )
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    conformation = molecule.conformations["AVR"]
    unfolded, folded = conformation.calculate_charge(molecule.version.parameters, ph=ph)
    pi_folded, pi_unfolded = molecule.get_pi()
    result = {
        "groups": rows,
        "ph": ph,
        "net_charge_folded": round(float(folded), 2),
        "net_charge_unfolded": round(float(unfolded), 2),
        "pi_folded": round(float(pi_folded), 2),
        "pi_unfolded": round(float(pi_unfolded), 2),
        "strongly_shifted": [r["label"] for r in rows if abs(r["shift"]) > 1.5],
        "disulfide_cysteines": disulfides,
        "table": table,
    }
    if experimental:
        result["comparison"] = _compare(rows, experimental)
    return result


def _compare(rows: list[dict], experimental: dict[str, float]) -> dict:
    found = []
    missing = []
    for text, measured in experimental.items():
        kind, number, chain = _key(text)
        kind = {"NTERM": "N+", "N-TERM": "N+", "CTERM": "C-", "C-TERM": "C-"}.get(kind, kind)
        match = [
            r
            for r in rows
            if r["residue"] == kind
            and r["number"] == number
            and (chain is None or r["chain"] == chain)
        ]
        if not match:
            missing.append(text)
            continue
        row = match[0]
        found.append(
            {
                "group": row["label"],
                "predicted": row["pka"],
                "measured": measured,
                "difference": round(row["pka"] - measured, 2),
            }
        )
    errors = [entry["difference"] for entry in found]
    return {
        "groups": found,
        "not_found": missing,
        "rmsd": round((sum(e * e for e in errors) / len(errors)) ** 0.5, 3) if errors else None,
        "max_abs_difference": round(max(abs(e) for e in errors), 2) if errors else None,
    }


def charge_curve(
    structure: str,
    ph_min: float = 0.0,
    ph_max: float = 14.0,
    step: float = 0.25,
    keep_hetero: bool = False,
    table: str = "charge_curve.csv",
    plot: str = "charge_curve.png",
) -> dict:
    """Net charge and folding free energy of a protein versus pH.

    Args:
        structure: PDB or PQR file.
        ph_min: Lowest pH.
        ph_max: Highest pH.
        step: pH step.
        keep_hetero: Keep ligands, ions, and waters (see protein_pka).
        table: CSV with pH, charge (folded and unfolded), and folding free energy.
        plot: PNG of charge and folding free energy versus pH.

    Returns:
        Isoelectric points (folded and unfolded), the pH of maximum stability and
        the folding free energy there (kcal/mol, relative to the neutral reference),
        the pH range where folding is favourable, and the file paths.
    """
    if not ph_min < ph_max or step <= 0:
        raise ValueError("Need ph_min < ph_max and a positive step.")
    molecule = _run(structure, keep_hetero)
    grid = [ph_min, ph_max, step]
    charges = molecule.get_charge_profile(grid=grid)
    profile, optimum, _, stable = molecule.get_folding_profile(grid=tuple(grid))
    rows = [
        {
            "ph": round(ph, 4),
            "charge_unfolded": round(q_unfolded, 3),
            "charge_folded": round(q_folded, 3),
            "folding_free_energy_kcal_mol": round(energy, 3),
        }
        for (ph, q_unfolded, q_folded), (_, energy) in zip(charges, profile, strict=True)
    ]
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _plot(rows, Path(structure).stem, plot)
    pi_folded, pi_unfolded = molecule.get_pi()
    return {
        "pi_folded": round(float(pi_folded), 2),
        "pi_unfolded": round(float(pi_unfolded), 2),
        "most_stable_ph": None if optimum[0] is None else round(float(optimum[0]), 2),
        "folding_free_energy_at_optimum_kcal_mol": round(float(optimum[1]), 2),
        "stable_ph_range": [None if v is None else round(float(v), 2) for v in stable],
        "table": table,
        "plot": plot,
    }


def _plot(rows: list[dict], title: str, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, (top, bottom) = plt.subplots(2, 1, figsize=(6.5, 6), sharex=True)
    ph = [r["ph"] for r in rows]
    top.plot(ph, [r["charge_folded"] for r in rows], label="folded")
    top.plot(ph, [r["charge_unfolded"] for r in rows], label="unfolded", linestyle="--")
    top.axhline(0, color="grey", linewidth=0.8)
    top.set(ylabel="Net charge (e)", title=title)
    top.legend()
    bottom.plot(ph, [r["folding_free_energy_kcal_mol"] for r in rows])
    bottom.set(xlabel="pH", ylabel="Folding free energy (kcal/mol)")
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def fetch_pdb(pdb_id: str, file: str | None = None) -> dict:
    """Download a structure from the RCSB Protein Data Bank in PDB format.

    Args:
        pdb_id: Four-character PDB ID, e.g. "2LZT".
        file: Where to save it (default <ID>.pdb).

    Returns:
        The file path, title, and experimental method.
    """
    code = pdb_id.strip().upper()
    if not re.fullmatch(r"[0-9][A-Z0-9]{3}", code):
        raise ValueError(f"{pdb_id!r} is not a PDB ID (four characters, e.g. 2LZT).")
    target = file or f"{code}.pdb"
    url = f"https://files.rcsb.org/download/{code}.pdb"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(
            f"Could not download {code} (very large entries exist only as mmCIF): {exc}"
        ) from exc
    Path(target).write_text(text, encoding="utf-8")
    title = " ".join(line[10:].strip() for line in text.splitlines() if line.startswith("TITLE"))
    method = next(
        (line[10:].strip() for line in text.splitlines() if line.startswith("EXPDTA")), ""
    )
    return {"file": target, "pdb_id": code, "title": title, "method": method}
