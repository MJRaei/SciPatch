"""Docking scored by machine-learned interatomic potentials, with UMA-Dock.

Wraps UMA-Dock (M. Cafiero, github.com/MauricioCafiero/UMADock, a 2025 LLM
Hackathon project): a binding site is cut from a protein structure around a
crystal ligand (residues within a cutoff, repaired and protonated by PDBFixer,
termini capped with ACE/NME, charge from AMBER ff14SB), ligand conformers from
RDKit are placed in it at random and scored with a machine-learned potential, the
best pose of each conformer is optimized with the residues' alpha carbons fixed,
and the interaction energy is combined with the ligand's strain and desolvation
energies into an electronic binding energy. Scorers: AIMNet2 (default; organic
elements) or MACE-OMOL-0. Meta's UMA, UMA-Dock's default, needs gated weights and
is not included. A patch fills short gaps between selected residues, whose caps
otherwise overlap, and a guard keeps AIMNet2's neighbour lists complete when it
switches between the ligand, the site, and the complex.
"""

from __future__ import annotations

import functools
import json
import os
import random
import re
import sys
import warnings
from pathlib import Path
from typing import Literal

import numpy as np

Model = Literal["aimnet2", "mace-omol"]
AIMNET2_ELEMENTS = {"H", "B", "C", "N", "O", "F", "Si", "P", "S", "Cl", "As", "Se", "Br", "I"}


@functools.cache
def _source() -> Path:
    warnings.filterwarnings("ignore")
    code = Path(os.environ["MOTEL_SOURCE_DIR"]) / "code"
    if str(code) not in sys.path:
        sys.path.insert(0, str(code))
    return code


@functools.cache
def _guard_aimnet_neighbor_list() -> None:
    """Keep AIMNet2's neighbour lists complete.

    aimnet 0.2.0 shrinks its neighbour-list buffer after a small system (the ligand)
    and expects an overflow error for a larger one, but nvalchemi-toolkit-ops 0.5 on
    the CPU only reports the full neighbour count and returns truncated lists: the
    complex then gets wrong energies and forces (55 eV off for paracetamol in
    SULT1A3) and its optimization diverges. Retry with a buffer that fits.
    """
    from aimnet.calculators import calculator as module

    neighbor_list = module.AdaptiveNeighborList
    original = neighbor_list.__call__

    def complete(self, *args, **kwargs):
        while True:
            nbmat, counts, shifts = original(self, *args, **kwargs)
            needed = int(counts.max().item()) if counts.numel() else 0
            if needed <= nbmat.shape[-1]:
                return nbmat, counts, shifts
            self.max_neighbors = self._round_to_16(int(needed / self.target_utilization) + 1)

    neighbor_list.__call__ = complete


def _pdb_file(pdb: str, folder: Path) -> Path:
    path = Path(pdb)
    if path.is_file():
        return path
    if re.fullmatch(r"[0-9][A-Za-z0-9]{3}", pdb):
        import urllib.request

        target = folder / f"{pdb.upper()}.pdb"
        try:
            urllib.request.urlretrieve(f"https://files.rcsb.org/download/{pdb.upper()}.pdb", target)
        except Exception as exc:
            raise ValueError(f"Could not download PDB entry {pdb} from the RCSB: {exc}") from exc
        return target
    raise ValueError(f"{pdb!r} is neither a PDB file nor a PDB id.")


def prepare_site(
    pdb: str,
    ligand_resname: str,
    chain: str | None = None,
    cutoff_angstrom: float = 4.0,
    ph: float = 7.0,
    fill_gaps: int = 2,
    keep_metals: bool = True,
    constrain_metals: bool = False,
    name: str = "site",
    output_dir: str = "site",
) -> dict:
    """Cut a capped, protonated binding-site cluster from a protein structure.

    Args:
        pdb: PDB file, or a PDB id to download from the RCSB (e.g. "2A3R").
        ligand_resname: Residue name of the crystal ligand that defines the site.
        chain: Chain of the ligand copy to use (needed for oligomers).
        cutoff_angstrom: Residues with a heavy atom within this distance of the
            ligand are kept.
        ph: pH for protonation and charges.
        fill_gaps: Also keep the residues in gaps of up to this many residues
            between kept ones, instead of capping both sides (the caps would
            overlap). 0 reproduces UMA-Dock's original selection.
        keep_metals: Keep structural metal ions near the ligand (as +2 ions).
        constrain_metals: Hold kept metal ions fixed during optimization.
        name: Site name.
        output_dir: Folder for the cluster (XYZ, capped PDB) and site file (JSON).

    Returns:
        The site file to pass to dock, the cluster's atoms, net charge, spin, the
        residues kept, the fixed alpha-carbon atoms, and the shortest interatomic
        distance (a check for overlapping atoms).
    """
    _source()
    from UMADock import prep_binding_site as prep

    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    pdb_path = _pdb_file(pdb, folder)
    if not 2.0 <= cutoff_angstrom <= 8.0:
        raise ValueError("cutoff_angstrom must be between 2 and 8.")
    try:
        site = prep.prepare_binding_site(
            str(pdb_path),
            ligand_resname,
            cutoff=cutoff_angstrom,
            ph=ph,
            name=name,
            output_dir=str(folder),
            chain=chain,
            keep_metals=keep_metals,
            constrain_metals=constrain_metals,
            fill_gaps=fill_gaps,
        )
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Binding-site preparation failed: {exc}") from exc
    import ase.io

    cluster = ase.io.read(site["file_location"])
    distances = cluster.get_all_distances()
    np.fill_diagonal(distances, np.inf)
    capped = folder / f"{name}_capped.pdb"
    record = {
        **site,
        "file_location": Path(site["file_location"]).name,  # next to this file
        "pdb": pdb_path.name,
        "ligand_resname": ligand_resname,
        "chain": chain,
        "cutoff_angstrom": cutoff_angstrom,
        "ph": ph,
        "fill_gaps": fill_gaps,
        "elements": sorted(set(cluster.get_chemical_symbols())),
    }
    site_file = folder / f"{name}.json"
    site_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {
        "site": str(site_file),
        "cluster_xyz": site["file_location"],
        "capped_pdb": str(capped),
        "atoms": site["size"],
        "charge": site["charge"],
        "spin": site["spin"],
        "residues": site["residues"],
        "fixed_atoms": len(site["constraints"]),
        "min_interatomic_distance_angstrom": round(float(distances.min()), 4),
        "overlapping_pairs_below_0_9_angstrom": int((distances < 0.9).sum() // 2),
    }


def dock(
    smiles: str,
    site: str,
    model: Model = "aimnet2",
    conformers: int = 3,
    tries: int = 100,
    criteria: Literal["distance", "energy"] = "distance",
    seed: int = 1,
    output_dir: str = "dock",
) -> dict:
    """Dock a molecule into a prepared site and estimate its binding energy.

    For each RDKit conformer, poses are placed at random around the site centre
    (kept if their centre is within 5 Angstrom of it), scored with the potential,
    and the best (closest to the centre, or lowest in energy) is optimized with the
    site's alpha carbons fixed. The binding energy is the optimized interaction
    energy plus the ligand's strain and desolvation energies.

    Args:
        smiles: The molecule (neutral, closed shell).
        site: Site file from prepare_site.
        model: "aimnet2" (fast; H, B, C, N, O, F, Si, P, S, Cl, As, Se, Br, I only)
            or "mace-omol" (MACE-OMOL-0, 89 elements, much slower on a CPU;
            Academic Software License, non-commercial).
        conformers: Number of ligand conformers.
        tries: Random placements per conformer.
        criteria: Pose choice for optimization: "distance" or "energy".
        seed: Random seed for conformers and placements.
        output_dir: Folder for poses and the optimized complexes.

    Returns:
        For each conformer: optimized interaction, strain, desolvation, and
        binding energies (kcal/mol; negative is favourable) and the optimized
        complex file; the best conformer and its binding energy; and the scorer.
    """
    _source()
    import torch
    import UMADock.UMADock as ud

    record = json.loads(Path(site).read_text(encoding="utf-8")) if Path(site).is_file() else None
    if record is None:
        raise ValueError(f"Site file {site!r} not found; create it with prepare_site.")
    if model == "aimnet2":
        outside = sorted(set(record.get("elements", [])) - AIMNET2_ELEMENTS)
        if outside:
            raise ValueError(
                f"AIMNet2 cannot model {', '.join(outside)} in the site; use model='mace-omol'."
            )
    if not 1 <= conformers <= 9 or not 10 <= tries <= 2000:  # file names hold one digit
        raise ValueError("conformers must be 1-9 and tries 10-2000.")
    from rdkit import Chem

    if Chem.MolFromSmiles(smiles) is None:
        raise ValueError(f"Invalid SMILES {smiles!r}.")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if model == "aimnet2":
        _guard_aimnet_neighbor_list()
    calculator = ud.build_calculator(model, device=device)
    generator = ud.conformers(smiles, conformers)
    generator.get_confs(use_random=True)
    generator.get_XYZ_strings()
    fragments = generator.prep_XYZ_docking()
    bs = {k: record[k] for k in ("name", "charge", "spin", "constraints", "size")}
    cluster = Path(record["file_location"])
    bs["file_location"] = str(cluster if cluster.is_absolute() else Path(site).parent / cluster)
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    docking = ud.UMA_Dock(fragments, tries, calculator, bs, output_dir=str(folder))
    docking.dock()
    interaction, binding = docking.post_process(criteria=criteria)
    rows = []
    for index, (ie, be) in enumerate(zip(interaction, binding, strict=True)):
        if be == -1:
            rows.append({"conformer": index, "pose_found": False})
            continue
        optimized = sorted(
            (folder / "opt_files").glob(f"{bs['name']}_w_conf_{index}*_OPTIMIZED.xyz")
        )
        rows.append(
            {
                "conformer": index,
                "pose_found": True,
                "interaction_kcal_mol": round(float(ie), 3),
                "strain_kcal_mol": round(float(docking.strain_energies[index]), 3),
                "desolvation_kcal_mol": round(float(docking.desolvation_energies[index]), 3),
                "binding_kcal_mol": round(float(be), 3),
                "complex_xyz": str(optimized[0]) if optimized else None,
            }
        )
    found = [r for r in rows if r["pose_found"]]
    if not found:
        raise RuntimeError("No pose landed in the site; increase tries or conformers.")
    best = min(found, key=lambda r: r["binding_kcal_mol"])
    return {
        "smiles": smiles,
        "site": record["name"],
        "model": model,
        "device": device,
        "conformers": rows,
        "best_conformer": best["conformer"],
        "best_binding_kcal_mol": best["binding_kcal_mol"],
        "best_complex_xyz": best["complex_xyz"],
    }
