"""Gas adsorption in porous materials (zeolites, MOFs) with RASPA3 Monte Carlo.

Grand-canonical Monte Carlo (GCMC) gives adsorption isotherms and mixture
uptakes; Widom insertion gives Henry coefficients. Gases use the TraPPE models;
silicalite (MFI) and any all-silica zeolite CIF use TraPPE-zeo, the bundled MOFs
the framework parameters of the RASPA3 examples, and any other CIF file UFF
Lennard-Jones parameters with the partial charges written in the CIF, if any.
Lorentz-Berthelot mixing, 12 Angstrom cutoff with analytic tail corrections,
Ewald summation for charges.
"""

from __future__ import annotations

import csv
import functools
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

UFF = Path(__file__).with_name("uff.json")
#: Van der Waals cutoff (Angstrom); the simulation box is at least twice this wide in
#: every direction.
CUTOFF = 12.0
PA_PER_BAR = 1e5
TRAPPE = (
    "TraPPE: J. J. Potoff, J. I. Siepmann, AIChE J. 47, 1676 (2001) for CO2 and N2; "
    "M. G. Martin, J. I. Siepmann, J. Phys. Chem. B 102, 2569 (1998) for methane"
)
#: TraPPE pseudo-atoms: element, mass, charge (e), epsilon/k_B (K), sigma (Angstrom).
#: N_com is the massless charge site at the centre of N2.
PSEUDO_ATOMS = {
    "C_co2": ("C", 12.0107, 0.70, 27.0, 2.80),
    "O_co2": ("O", 15.9994, -0.35, 79.0, 3.05),
    "N_n2": ("N", 14.00674, -0.482, 36.0, 3.31),
    "N_com": ("N", 0.0, 0.964, 0.0, 1.0),
    "CH4": ("C", 16.04246, 0.0, 148.0, 3.73),
}
#: Rigid molecules: critical temperature (K), critical pressure (Pa), and acentric
#: factor for the Peng-Robinson fugacity; then pseudo-atoms and positions (Angstrom).
MOLECULES = {
    "CO2": (304.1282, 7377300.0, 0.22394, [("O_co2", 1.16), ("C_co2", 0.0), ("O_co2", -1.16)]),
    "N2": (126.192, 3395800.0, 0.0372, [("N_n2", 0.55), ("N_com", 0.0), ("N_n2", -0.55)]),
    "methane": (190.564, 4599200.0, 0.01142, [("CH4", 0.0)]),
}
ALIASES = {
    "co2": "CO2",
    "carbon dioxide": "CO2",
    "n2": "N2",
    "nitrogen": "N2",
    "ch4": "methane",
    "methane": "methane",
}
CHARGE_TAGS = ("_atom_site_charge", "_atom_site_partial_charge", "_atom_type_partial_charge")
#: All-silica zeolites: charge (e), epsilon/k_B (K), sigma (Angstrom). UFF overbinds them.
TRAPPE_ZEO = {"O": (-0.75, 53.0, 3.30), "Si": (1.50, 22.0, 2.30)}
TRAPPE_ZEO_SOURCE = (
    "TraPPE-zeo: P. Bai, M. Tsapatsis, J. I. Siepmann, J. Phys. Chem. C 117, 24375 (2013)"
)


@dataclass(frozen=True)
class Bundled:
    example: str
    cif: str
    about: str
    #: Replaces the example's framework parameters: name -> (charge, epsilon_k, sigma).
    parameters: dict[str, tuple[float, float, float]] | None = None
    source: str | None = None


FRAMEWORKS = {
    "MFI": Bundled(
        "basic/12_mc_henry_coefficient_of_co2_n2_methane_in_mfi",
        "MFI_SI",
        "Silicalite-1, the all-silica form of zeolite ZSM-5 (MFI), with 10-ring channels "
        "of about 5.5 Angstrom. Structure: H. van Koningsveld, H. van Bekkum, J. C. Jansen, "
        "Acta Cryst. B43, 127 (1987).",
        TRAPPE_ZEO,
        TRAPPE_ZEO_SOURCE,
    ),
    "Cu-BTC": Bundled(
        "basic/11_mc_adsorption_of_co2_in_cu_btc",
        "Cu-BTC",
        "HKUST-1, copper benzene-1,3,5-tricarboxylate MOF (dehydrated, with open copper "
        "sites and small tetrahedral pockets). Structure: S. S.-Y. Chui et al., Science "
        "283, 1148 (1999).",
    ),
    "IRMOF-1": Bundled(
        "non_basic/1_mc_adsorption_binary_mixture_co2_ch4_in_irmof_1",
        "IRMOF-1",
        "MOF-5: Zn4O clusters linked by terephthalate into large cubic cages. Structure: "
        "M. Eddaoudi et al., Science 295, 469 (2002).",
    ),
    "CALF-20": Bundled(
        "density_grids/6_mc_adsorption_of_co2_in_calf_20_split_density_equitable_binning",
        "CALF-20",
        "Zinc 1,2,4-triazolate oxalate MOF made for CO2 capture from flue gas (J.-B. Lin "
        "et al., Science 374, 1464 (2021)); partial charges from REPEAT.",
    ),
}


@functools.cache
def _share() -> Path:
    for root in (Path(sys.prefix), Path(sys.prefix) / "Library"):
        if (root / "share" / "raspa3" / "examples").is_dir():
            return root / "share" / "raspa3"
    raise RuntimeError("RASPA3's example files were not found in this environment.")


@functools.cache
def _executable() -> str:
    folders = (Path(sys.prefix) / "bin", Path(sys.prefix) / "Library" / "bin")
    found = shutil.which("raspa3", path=os.pathsep.join(map(str, folders))) or shutil.which(
        "raspa3"
    )
    if not found:
        raise RuntimeError("The raspa3 program was not found in this environment.")
    return found


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pseudo_atom(name: str, element: str, mass: float, charge: float, framework: bool) -> dict:
    return {
        "name": name,
        "framework": framework,
        "print_to_output": mass > 0,
        "element": element,
        "print_as": element if mass > 0 else "-",
        "mass": mass,
        "charge": charge,
    }


def _lennard_jones(name: str, epsilon_k: float, sigma: float, source: str) -> dict:
    return {
        "name": name,
        "type": "lennard-jones",
        "parameters": [epsilon_k, sigma],
        "source": source,
    }


def _molecule(name: str) -> dict:
    critical_t, critical_p, acentric, sites = MOLECULES[name]
    return {
        "CriticalTemperature": critical_t,
        "CriticalPressure": critical_p,
        "AcentricFactor": acentric,
        "Type": "rigid",
        "pseudoAtoms": [[atom, [0.0, 0.0, z]] for atom, z in sites],
    }


def _adsorbate(name: str) -> str:
    key = ALIASES.get(name.strip().lower())
    if key is None:
        raise ValueError(f"Unknown adsorbate {name!r}; choose CO2, N2, or methane.")
    return key


def _charged(adsorbate: str) -> bool:
    return any(PSEUDO_ATOMS[atom][2] for atom, _ in MOLECULES[adsorbate][3])


@dataclass
class Framework:
    """A framework ready to copy into a RASPA3 working directory."""

    name: str
    cif_text: str
    atoms: list[dict]
    pairs: list[dict]
    cell: tuple[float, ...]
    force_field: str
    charges: str
    charges_from: str = "PseudoAtoms"

    @property
    def unit_cells(self) -> list[int]:
        """Unit cells per direction so the box is at least two cutoffs wide."""
        return [max(1, math.ceil(2 * CUTOFF / width)) for width in _widths(self.cell)]

    def write(self, folder: Path, adsorbates: list[str]) -> None:
        atoms = [
            _pseudo_atom(name, element, mass, charge, False)
            for name, (element, mass, charge, _, _) in PSEUDO_ATOMS.items()
        ]
        pairs = [
            _lennard_jones(name, epsilon, sigma, "TraPPE")
            for name, (_, _, _, epsilon, sigma) in PSEUDO_ATOMS.items()
        ]
        field = {
            "MixingRule": "Lorentz-Berthelot",
            "TruncationMethod": "truncated",
            "TailCorrections": True,
            "PseudoAtoms": self.atoms + atoms,
            "SelfInteractions": self.pairs + pairs,
        }
        (folder / "force_field.json").write_text(json.dumps(field, indent=1), encoding="utf-8")
        (folder / f"{self.name}.cif").write_text(self.cif_text, encoding="utf-8")
        for name in adsorbates:
            (folder / f"{name}.json").write_text(json.dumps(_molecule(name)), encoding="utf-8")


def _widths(cell: tuple[float, ...]) -> list[float]:
    a, b, c, alpha, beta, gamma = cell
    alpha, beta, gamma = (math.radians(angle) for angle in (alpha, beta, gamma))
    vectors = np.array(
        [
            [a, 0, 0],
            [b * math.cos(gamma), b * math.sin(gamma), 0],
            [
                c * math.cos(beta),
                c * (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / math.sin(gamma),
                0,
            ],
        ]
    )
    vectors[2, 2] = math.sqrt(c**2 - vectors[2, 0] ** 2 - vectors[2, 1] ** 2)
    volume = abs(np.linalg.det(vectors))
    return [
        volume / float(np.linalg.norm(np.cross(vectors[(i + 1) % 3], vectors[(i + 2) % 3])))
        for i in range(3)
    ]


def _cif_cell(text: str) -> tuple[float, ...]:
    values = []
    for key in ("length_a", "length_b", "length_c", "angle_alpha", "angle_beta", "angle_gamma"):
        match = re.search(rf"^\s*_cell_{key}\s+([-\d.]+)", text, re.MULTILINE)
        if not match:
            raise ValueError(f"The CIF has no _cell_{key}.")
        values.append(float(match.group(1)))
    return tuple(values)


def _bundled(name: str) -> Framework:
    entry = FRAMEWORKS[name]
    folder = _share() / "examples" / entry.example
    field = _load(folder / "force_field.json")
    atoms = [atom for atom in field["PseudoAtoms"] if atom.get("framework")]
    names = {atom["name"] for atom in atoms}
    pairs = [pair for pair in field["SelfInteractions"] if pair["name"] in names]
    sources = sorted({str(pair.get("source", "")).strip() for pair in pairs} - {""})
    if entry.parameters:
        for atom in atoms:
            atom["charge"] = entry.parameters[atom["name"]][0]
        pairs = [
            _lennard_jones(atom, epsilon, sigma, entry.source or "")
            for atom, (_, epsilon, sigma) in entry.parameters.items()
        ]
        sources = [entry.source or ""]
    text = (folder / f"{entry.cif}.cif").read_text(encoding="utf-8")
    return Framework(
        name=entry.cif,
        cif_text=text,
        atoms=atoms,
        pairs=pairs,
        cell=_cif_cell(text),
        force_field="; ".join(sources),
        charges="from the force field" if any(a.get("charge") for a in atoms) else "none",
    )


def _from_cif(path: Path) -> Framework:
    import warnings

    import ase.io
    from ase.data import atomic_masses, atomic_numbers

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            structure = ase.io.read(path, format="cif", store_tags=True)
    except Exception as exc:
        raise ValueError(f"Could not read {path.name} as a CIF file: {exc}") from exc
    if len(structure) == 0 or not structure.pbc.all():
        raise ValueError(f"{path.name} has no periodic framework structure.")
    charges = None
    for tag in CHARGE_TAGS:
        if tag in structure.info:
            site = np.asarray(structure.info[tag], dtype=float)
            kinds = structure.arrays.get("spacegroup_kinds")
            charges = site[kinds] if kinds is not None else site
            break
    note = "none (the CIF has no partial charges)"
    if charges is not None and len(charges) == len(structure) and np.any(charges):
        net = float(charges.sum())
        charges = charges - net / len(charges)
        note = "from the CIF"
        if abs(net) > 1e-3:
            note += f" (net charge {net:+.3f} e spread evenly to make it neutral)"
    else:
        charges = np.zeros(len(structure))
    symbols = structure.get_chemical_symbols()
    elements = sorted(set(symbols))
    masses = {element: float(atomic_masses[atomic_numbers[element]]) for element in elements}
    if elements == ["O", "Si"]:
        atoms = [_pseudo_atom(e, e, masses[e], TRAPPE_ZEO[e][0], True) for e in elements]
        pairs = [_lennard_jones(e, *TRAPPE_ZEO[e][1:], TRAPPE_ZEO_SOURCE) for e in elements]
        force_field = f"{TRAPPE_ZEO_SOURCE} (all-silica zeolite)"
        note, charges_from = "TraPPE-zeo (Si +1.50 e, O -0.75 e)", "PseudoAtoms"
    else:
        uff = _load(UFF)["lennard_jones"]
        missing = sorted(set(elements) - set(uff))
        if missing:
            raise ValueError(f"No UFF parameters for {', '.join(missing)}.")
        atoms = [_pseudo_atom(e, e, masses[e], 0.0, True) for e in elements]
        pairs = [_lennard_jones(e, *uff[e], "UFF") for e in elements]
        force_field = "UFF (A. K. Rappé et al., J. Am. Chem. Soc. 114, 10024 (1992))"
        charges_from = "CIF_File"
    cell = tuple(float(value) for value in structure.cell.cellpar())
    lines = [
        "data_framework",
        *(
            f"_cell_{key} {value:.6f}"
            for key, value in zip(
                ("length_a", "length_b", "length_c", "angle_alpha", "angle_beta", "angle_gamma"),
                cell,
                strict=True,
            )
        ),
        "_symmetry_space_group_name_H-M 'P 1'",
        "_symmetry_Int_Tables_number 1",
        "loop_",
        "_symmetry_equiv_pos_as_xyz",
        " 'x,y,z'",
        "loop_",
        "_atom_site_label",
        "_atom_site_type_symbol",
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
        "_atom_site_charge",
    ]
    for symbol, (x, y, z), charge in zip(
        symbols, structure.get_scaled_positions(), charges, strict=True
    ):
        lines.append(f"{symbol} {symbol} {x:.6f} {y:.6f} {z:.6f} {charge:.6f}")
    return Framework(
        name="framework",
        cif_text="\n".join(lines) + "\n",
        atoms=atoms,
        pairs=pairs,
        cell=cell,
        force_field=force_field,
        charges=note,
        charges_from=charges_from,
    )


def _framework(framework: str) -> Framework:
    for name in FRAMEWORKS:
        if framework.strip().lower() == name.lower():
            return _bundled(name)
    path = Path(framework).expanduser()
    if path.suffix.lower() == ".cif" and path.is_file():
        return _from_cif(path)
    raise ValueError(
        f"Unknown framework {framework!r}; choose one of {', '.join(FRAMEWORKS)} "
        "(see materials) or give the path to a CIF file."
    )


def _component(name: str, mode: str, mole_fraction: float = 1.0) -> dict:
    if mode == "widom":
        return {"Name": name, "WidomProbability": 1.0, "CreateNumberOfMolecules": 0}
    component = {
        "Name": name,
        "MolFraction": mole_fraction,
        "TranslationProbability": 0.5,
        "ReinsertionProbability": 0.5,
        "SwapProbability": 1.0,
        "CreateNumberOfMolecules": 0,
    }
    if len(MOLECULES[name][3]) > 1:
        component["RotationProbability"] = 0.5
    return component


def _simulate(
    framework: Framework,
    components: list[dict],
    temperature_k: float,
    pressure_pa: float | None,
    cycles: int,
    initialization_cycles: int,
    seed: int,
) -> str:
    """Run RASPA3 once in a scratch folder and return its text output."""
    names = [component["Name"] for component in components]
    system = {
        "Type": "Framework",
        "Name": framework.name,
        "NumberOfUnitCells": framework.unit_cells,
        "ExternalTemperature": temperature_k,
        "ChargeMethod": "Ewald" if any(_charged(name) for name in names) else "None",
        "CutOffVDW": CUTOFF,
        "UseChargesFrom": framework.charges_from,
    }
    if pressure_pa is not None:
        system["ExternalPressure"] = pressure_pa
    simulation = {
        "SimulationType": "MonteCarlo",
        "NumberOfCycles": cycles,
        "NumberOfInitializationCycles": initialization_cycles,
        "PrintEvery": max(1, cycles // 5),
        "RandomSeed": seed,
        "Systems": [system],
        "Components": components,
    }
    with tempfile.TemporaryDirectory(prefix="raspa3-") as scratch:
        folder = Path(scratch)
        framework.write(folder, names)
        (folder / "simulation.json").write_text(json.dumps(simulation, indent=1), "utf-8")
        completed = subprocess.run(
            [_executable()], cwd=folder, capture_output=True, text=True, check=False
        )
        outputs = sorted((folder / "output").glob("output_*.txt"))
        if completed.returncode != 0 or not outputs:
            tail = "\n".join((completed.stdout + completed.stderr).splitlines()[-15:])
            raise RuntimeError(f"RASPA3 failed (exit code {completed.returncode}):\n{tail}")
        return outputs[0].read_text(encoding="utf-8", errors="replace")


_NUMBER = r"([-+0-9.eE]+|-?inf|nan)"


def _averages(text: str, label: str, unit: str) -> list[tuple[float, float]]:
    pattern = rf"{label}\s+{_NUMBER}\s+\+/-\s+{_NUMBER}\s+\[{re.escape(unit)}\]"
    return [(float(mean), float(error)) for mean, error in re.findall(pattern, text)]


def _loadings(text: str, names: list[str]) -> list[dict]:
    per_kg = _averages(text, r"Abs\. loading average", "mol/kg-framework")
    per_cell = _averages(text, r"Abs\. loading average", "molecules/uc")
    per_gram = _averages(text, r"Abs\. loading average", "mg/g-framework")
    coefficients = [float(x) for x in re.findall(rf"Fugacity coefficient:\s+{_NUMBER}", text)]
    section = text.partition("\nEnthalpy of adsorption\n")[2].partition("\nLoadingData\n")[0]
    enthalpies = dict(
        re.findall(
            rf"Component \d+ \[(\S+)\].*?Enthalpy of adsorption:[^\n]*\n"
            rf"\s*{_NUMBER}\s+\+/-\s+\S+\s+\[kJ/mol\]",
            section,
            re.DOTALL,
        )
    )
    if len(per_kg) < len(names):
        raise RuntimeError("RASPA3's output has no loadings; the run did not finish.")
    rows = []
    for index, name in enumerate(names):
        enthalpy = enthalpies.get(name)
        rows.append(
            {
                "adsorbate": name,
                "loading_mmol_per_g": round(per_kg[index][0], 5),
                "loading_error_mmol_per_g": round(per_kg[index][1], 5),
                "loading_molecules_per_cell": round(per_cell[index][0], 4),
                "loading_mg_per_g": round(per_gram[index][0], 4),
                "fugacity_coefficient": round(coefficients[index], 5)
                if index < len(coefficients)
                else None,
                "enthalpy_of_adsorption_kj_per_mol": None
                if enthalpy is None
                else round(float(enthalpy), 3),
            }
        )
    return rows


def _parallel(jobs: list, run) -> list:
    workers = max(1, min(len(jobs), os.cpu_count() or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, jobs))


def _check_runs(temperature_k: float, cycles: int, initialization_cycles: int) -> None:
    if temperature_k <= 0:
        raise ValueError("temperature_k must be positive.")
    if cycles < 1 or initialization_cycles < 0:
        raise ValueError("cycles must be at least 1 and initialization_cycles at least 0.")


def _about(framework: Framework) -> dict:
    return {
        "unit_cells": framework.unit_cells,
        "framework_force_field": framework.force_field,
        "framework_charges": framework.charges,
    }


def adsorption_isotherm(
    framework: str = "MFI",
    adsorbate: str = "methane",
    temperature_k: float = 298.0,
    pressures_bar: list[float] | None = None,
    cycles: int = 5000,
    initialization_cycles: int = 2000,
    seed: int = 42,
    table: str = "isotherm.csv",
    plot: str = "isotherm.png",
) -> dict:
    """Pure-gas adsorption isotherm by grand-canonical Monte Carlo (GCMC).

    Each pressure is a separate simulation; they run in parallel on the CPU cores.
    The gas-phase fugacity comes from the Peng-Robinson equation of state.

    Args:
        framework: A bundled framework ("MFI", "Cu-BTC", "IRMOF-1", "CALF-20"; see
            materials) or the path to a CIF file of the activated (solvent-free)
            framework.
        adsorbate: "CO2", "N2", or "methane".
        temperature_k: Temperature in K.
        pressures_bar: Pressures in bar (default 0.1, 0.5, 1, 2, 5, 10).
        cycles: Production Monte Carlo cycles per pressure; more cycles give
            smaller error bars and take longer.
        initialization_cycles: Equilibration cycles before averaging.
        seed: Random seed (each pressure uses seed + its index).
        table: CSV file for the isotherm.
        plot: PNG file for loading versus pressure.

    Returns:
        For each pressure: absolute loading in mmol/g (= mol/kg) with its error,
        molecules per unit cell, mg/g, the fugacity coefficient, and the enthalpy
        of adsorption in kJ/mol (negative; its magnitude is the isosteric heat);
        the number of unit cells simulated, the framework force field and charges,
        and the file paths.
    """
    name = _adsorbate(adsorbate)
    _check_runs(temperature_k, cycles, initialization_cycles)
    pressures = sorted(pressures_bar or [0.1, 0.5, 1.0, 2.0, 5.0, 10.0])
    if not pressures or pressures[0] <= 0:
        raise ValueError("pressures_bar must be positive.")
    built = _framework(framework)

    def run(job: tuple[int, float]) -> dict:
        index, pressure = job
        text = _simulate(
            built,
            [_component(name, "gcmc")],
            temperature_k,
            pressure * PA_PER_BAR,
            cycles,
            initialization_cycles,
            seed + index,
        )
        row = _loadings(text, [name])[0]
        print(f"{pressure:g} bar: {row['loading_mmol_per_g']:.4f} mmol/g", flush=True)
        return {"pressure_bar": pressure, **{k: v for k, v in row.items() if k != "adsorbate"}}

    points = _parallel(list(enumerate(pressures)), run)
    with open(table, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(points[0]))
        writer.writeheader()
        writer.writerows(points)
    _plot_isotherm(points, f"{name} in {framework} at {temperature_k:g} K", plot)
    return {
        "framework": framework,
        "adsorbate": name,
        "temperature_k": temperature_k,
        "points": points,
        **_about(built),
        "table": table,
        "plot": plot,
    }


def _plot_isotherm(points: list[dict], title: str, path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(6, 4))
    axes.errorbar(
        [p["pressure_bar"] for p in points],
        [p["loading_mmol_per_g"] for p in points],
        yerr=[p["loading_error_mmol_per_g"] for p in points],
        marker="o",
        capsize=3,
    )
    axes.set(xlabel="Pressure (bar)", ylabel="Absolute loading (mmol/g)", title=title)
    axes.set_ylim(bottom=0)
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def mixture_adsorption(
    framework: str,
    mole_fractions: dict[str, float],
    pressure_bar: float = 1.0,
    temperature_k: float = 298.0,
    cycles: int = 5000,
    initialization_cycles: int = 2000,
    seed: int = 42,
) -> dict:
    """Uptake of each gas from a mixture, and adsorption selectivities (GCMC).

    Args:
        framework: A bundled framework (see materials) or the path to a CIF file.
        mole_fractions: Gas-phase composition, e.g. {"CO2": 0.15, "N2": 0.85} for
            flue gas; normalized to sum to 1.
        pressure_bar: Total pressure in bar.
        temperature_k: Temperature in K.
        cycles: Production Monte Carlo cycles.
        initialization_cycles: Equilibration cycles before averaging.
        seed: Random seed.

    Returns:
        Per gas: gas mole fraction, absolute loading in mmol/g with its error,
        molecules per unit cell, and adsorbed mole fraction; the total loading;
        selectivities S(i/j) = (x_i/x_j)/(y_i/y_j) for each pair; the number of unit
        cells, and the framework force field and charges.
    """
    _check_runs(temperature_k, cycles, initialization_cycles)
    if pressure_bar <= 0:
        raise ValueError("pressure_bar must be positive.")
    gases: dict[str, float] = {}
    for gas, fraction in mole_fractions.items():
        if fraction <= 0:
            raise ValueError("Mole fractions must be positive.")
        gases[_adsorbate(gas)] = gases.get(_adsorbate(gas), 0.0) + fraction
    if len(gases) < 2:
        raise ValueError("Give at least two different gases; use adsorption_isotherm for one.")
    total = sum(gases.values())
    gases = {gas: fraction / total for gas, fraction in gases.items()}
    built = _framework(framework)
    text = _simulate(
        built,
        [_component(gas, "gcmc", fraction) for gas, fraction in gases.items()],
        temperature_k,
        pressure_bar * PA_PER_BAR,
        cycles,
        initialization_cycles,
        seed,
    )
    rows = _loadings(text, list(gases))
    loaded = sum(row["loading_mmol_per_g"] for row in rows)
    components = []
    for row in rows:
        components.append(
            {
                "adsorbate": row["adsorbate"],
                "gas_mole_fraction": round(gases[row["adsorbate"]], 6),
                "loading_mmol_per_g": row["loading_mmol_per_g"],
                "loading_error_mmol_per_g": row["loading_error_mmol_per_g"],
                "loading_molecules_per_cell": row["loading_molecules_per_cell"],
                "adsorbed_mole_fraction": round(row["loading_mmol_per_g"] / loaded, 5)
                if loaded
                else None,
            }
        )
    selectivity = {}
    for first, second in itertools.combinations(components, 2):
        ratio = first["loading_mmol_per_g"] * second["gas_mole_fraction"]
        base = second["loading_mmol_per_g"] * first["gas_mole_fraction"]
        selectivity[f"{first['adsorbate']}/{second['adsorbate']}"] = (
            round(ratio / base, 3) if base else None
        )
    return {
        "framework": framework,
        "pressure_bar": pressure_bar,
        "temperature_k": temperature_k,
        "components": components,
        "total_loading_mmol_per_g": round(loaded, 5),
        "selectivity": selectivity,
        **_about(built),
    }


def henry_coefficient(
    framework: str = "MFI",
    adsorbates: list[str] | None = None,
    temperature_k: float = 298.0,
    cycles: int = 5000,
    seed: int = 42,
) -> dict:
    """Henry coefficients (adsorption at infinite dilution) by Widom test-particle insertion.

    Faster than an isotherm, and the standard screening quantity: the slope of the
    isotherm at zero pressure. Ratios of Henry coefficients are the low-pressure
    selectivities.

    Args:
        framework: A bundled framework (see materials) or the path to a CIF file.
        adsorbates: Gases among "CO2", "N2", and "methane" (default all three).
        temperature_k: Temperature in K.
        cycles: Monte Carlo cycles (20 insertions each).
        seed: Random seed.

    Returns:
        Per gas: Henry coefficient in mol/kg/Pa and mmol/g/bar with its error, and
        the excess chemical potential in kJ/mol; the low-pressure selectivity
        K_i/K_j for each pair; the number of unit cells, and the framework force
        field and charges.
    """
    names = list(dict.fromkeys(_adsorbate(gas) for gas in adsorbates or ["CO2", "N2", "methane"]))
    _check_runs(temperature_k, cycles, 0)
    built = _framework(framework)

    def run(name: str) -> dict:
        text = _simulate(built, [_component(name, "widom")], temperature_k, None, cycles, 0, seed)
        henry = _averages(text, r"Average Henry coefficient:", "mol/kg/Pa")
        potential = _averages(text, r"Excess chemical potential:", "kJ/mol")
        if not henry:
            raise RuntimeError("RASPA3's output has no Henry coefficient; the run did not finish.")
        value, error = henry[0]
        print(f"{name}: {value:.4e} mol/kg/Pa", flush=True)
        return {
            "adsorbate": name,
            "henry_mol_per_kg_per_pa": float(f"{value:.5e}"),
            "henry_error_mol_per_kg_per_pa": float(f"{error:.3e}"),
            "henry_mmol_per_g_per_bar": round(value * PA_PER_BAR, 5),
            "excess_chemical_potential_kj_per_mol": round(potential[0][0], 4)
            if potential
            else None,
        }

    rows = _parallel(names, run)
    selectivity = {}
    for first, second in itertools.combinations(rows, 2):
        base = second["henry_mol_per_kg_per_pa"]
        selectivity[f"{first['adsorbate']}/{second['adsorbate']}"] = (
            round(first["henry_mol_per_kg_per_pa"] / base, 3) if base else None
        )
    return {
        "framework": framework,
        "temperature_k": temperature_k,
        "henry": rows,
        "selectivity": selectivity,
        **_about(built),
    }


def materials() -> dict:
    """Bundled frameworks and adsorbates, with their force fields and sources.

    Returns:
        For each bundled framework: what it is, the structure source, its force
        field, and the unit cells simulated; the adsorbate models; and how to use
        your own CIF file.
    """
    frameworks = {}
    for name, entry in FRAMEWORKS.items():
        built = _bundled(name)
        frameworks[name] = {"about": entry.about, **_about(built)}
    return {
        "frameworks": frameworks,
        "adsorbates": {"models": list(MOLECULES), "force_field": TRAPPE},
        "own_cif": (
            "Pass the path to a CIF file of the activated framework (solvent removed). "
            "All-silica zeolites (only Si and O) get TraPPE-zeo. Other frameworks get UFF "
            "Lennard-Jones parameters, with partial charges from _atom_site_charge in the "
            "CIF (e.g. CoRE MOF DDEC charges) or none."
        ),
    }
