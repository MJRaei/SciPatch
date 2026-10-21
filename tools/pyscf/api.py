"""Ab initio quantum chemistry for molecules with PySCF: HF, DFT, MP2, CCSD(T), and TDDFT.

Molecules can be given as SMILES (a 3D structure is generated with RDKit), as a
structure file (XYZ, SDF/MOL, PDB), or as coordinates in Angstrom written
inline, e.g. "O 0 0 0; H 0 0.757 0.587; H 0 -0.757 0.587".
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

HARTREE_TO_EV = 27.211386245988
#: h*c in eV*nm, to turn excitation energies into wavelengths.
EV_NM = 1239.841984
CONV_TOL = 1e-10
_WAVEFUNCTION_METHODS = ("hf", "mp2", "ccsd", "ccsd(t)")
_METHOD_HINT = (
    "Use hf, mp2, ccsd, ccsd(t), or a DFT functional such as b3lyp, pbe, pbe0, "
    "wb97x, m06-2x, or tpss."
)


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #


def _atoms_from_input(molecule: str, seed: int) -> tuple[str, int | None, int | None]:
    """PySCF atom text (Angstrom), plus the charge and radical count when the input says so."""
    path = Path(molecule)
    if path.is_file():
        return _atoms_from_file(path)
    if re.search(r"\d", molecule) and re.search(r"\s", molecule.strip()):
        return molecule, None, None  # inline coordinates
    return _atoms_from_smiles(molecule, seed)


def _atoms_from_file(path: Path) -> tuple[str, int | None, int | None]:
    suffix = path.suffix.lower()
    if suffix == ".xyz":
        lines = path.read_text().splitlines()
        count = int(lines[0].split()[0])
        rows = [line.split()[:4] for line in lines[2 : 2 + count]]
        return "\n".join(" ".join(row) for row in rows), None, None
    from rdkit import Chem

    readers = {
        ".sdf": Chem.MolFromMolFile,
        ".mol": Chem.MolFromMolFile,
        ".pdb": Chem.MolFromPDBFile,
    }
    if suffix not in readers:
        raise ValueError(f"Unsupported file type '{suffix}': use XYZ, SDF/MOL, or PDB.")
    rdmol = readers[suffix](str(path), removeHs=False)
    if rdmol is None or rdmol.GetNumConformers() == 0:
        raise ValueError(f"Could not read 3D coordinates from {path.name}.")
    return _rdkit_atoms(rdmol), Chem.GetFormalCharge(rdmol), _radicals(rdmol)


def _atoms_from_smiles(smiles: str, seed: int) -> tuple[str, int | None, int | None]:
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem

    RDLogger.DisableLog("rdApp.*")
    rdmol = Chem.MolFromSmiles(smiles)
    if rdmol is None:
        raise ValueError(
            f"'{smiles}' is neither a file, nor coordinates, nor a valid SMILES string."
        )
    rdmol = Chem.AddHs(rdmol)
    parameters = AllChem.ETKDGv3()
    parameters.randomSeed = seed
    if AllChem.EmbedMolecule(rdmol, parameters) != 0:
        raise ValueError("Could not generate 3D coordinates for this molecule.")
    if AllChem.MMFFHasAllMoleculeParams(rdmol):
        AllChem.MMFFOptimizeMolecule(rdmol, maxIters=2000)
    return _rdkit_atoms(rdmol), Chem.GetFormalCharge(rdmol), _radicals(rdmol)


def _rdkit_atoms(rdmol: Any) -> str:
    positions = rdmol.GetConformer().GetPositions()
    return "\n".join(
        f"{atom.GetSymbol()} {x:.8f} {y:.8f} {z:.8f}"
        for atom, (x, y, z) in zip(rdmol.GetAtoms(), positions, strict=True)
    )


def _radicals(rdmol: Any) -> int:
    return sum(atom.GetNumRadicalElectrons() for atom in rdmol.GetAtoms())


def _build(
    molecule: str,
    basis: str,
    charge: int | None,
    unpaired_electrons: int | None,
    seed: int = 42,
) -> Any:
    from pyscf import gto
    from pyscf.data import elements

    atoms, input_charge, input_unpaired = _atoms_from_input(molecule, seed)
    charge = (input_charge or 0) if charge is None else charge
    unpaired = (input_unpaired or 0) if unpaired_electrons is None else unpaired_electrons
    try:
        symbols = [symbol for symbol, _ in gto.format_atom(atoms, unit="Angstrom")]
        electrons = sum(elements.charge(symbol) for symbol in symbols) - charge
    except Exception as exc:
        raise ValueError(f"Could not read the molecule: {exc}") from exc
    if unpaired < 0 or unpaired > electrons or (electrons - unpaired) % 2:
        raise ValueError(
            f"The molecule has {electrons} electrons (charge {charge}), which cannot have "
            f"{unpaired} unpaired electrons. An odd electron count needs an odd number, e.g. "
            "unpaired_electrons=1 for a radical; an even count needs 0 (singlet) or 2 (triplet)."
        )
    mol = gto.Mole()
    mol.atom = atoms
    mol.unit = "Angstrom"
    mol.basis = basis
    if basis.lower().startswith("def2"):
        mol.ecp = basis  # def2 basis sets use effective core potentials beyond Kr
    mol.charge = charge
    mol.spin = unpaired
    mol.verbose = 4  # SCF iterations go to the run's log
    try:
        mol.build()
    except (KeyError, RuntimeError, ValueError) as exc:
        raise ValueError(
            f"Could not set up basis set '{basis}' for {_formula(symbols)}: {exc}. Common "
            "names: sto-3g, 6-31g*, 6-311+g**, cc-pvdz, aug-cc-pvtz, def2-svp, def2-tzvp."
        ) from exc
    return mol


def _formula(symbols: list[str]) -> str:
    """Hill formula: C, then H, then the other elements alphabetically."""
    counts = Counter(symbols)
    order = (["C", "H"] if "C" in counts else []) + sorted(
        s for s in counts if not ("C" in counts and s in ("C", "H"))
    )
    return "".join(f"{s}{counts[s] if counts[s] > 1 else ''}" for s in order)


# --------------------------------------------------------------------------- #
# Methods
# --------------------------------------------------------------------------- #


def _check_method(method: str, allowed: tuple[str, ...] = _WAVEFUNCTION_METHODS) -> str:
    name = method.strip().lower()
    if name in _WAVEFUNCTION_METHODS:
        if name not in allowed:
            raise ValueError(
                f"Method '{method}' is not available here; use hf or a DFT functional."
            )
        return name
    from pyscf.dft import libxc

    try:
        libxc.parse_xc(name)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Unknown method '{method}'. {_METHOD_HINT}") from exc
    return name


def _mean_field(mol: Any, method: str) -> Any:
    """Converged HF (for wavefunction methods) or Kohn-Sham DFT; restricted for closed shells."""
    from pyscf import dft, scf

    if method in _WAVEFUNCTION_METHODS:
        mf = scf.RHF(mol) if mol.spin == 0 else scf.UHF(mol)
    else:
        mf = dft.RKS(mol) if mol.spin == 0 else dft.UKS(mol)
        mf.xc = method
    mf.conv_tol = CONV_TOL
    mf.max_cycle = 200
    mf.kernel()
    if not mf.converged:
        print("SCF did not converge with DIIS; retrying with a second-order solver.")
        mf = mf.newton()
        mf.kernel()
    if not mf.converged:
        raise RuntimeError(
            "The SCF did not converge. Check the charge and unpaired_electrons, try another "
            "starting geometry, or a smaller basis set first."
        )
    return mf


def _orbital_summary(mf: Any) -> dict[str, Any]:
    energies = np.asarray(mf.mo_energy).reshape(-1)
    occupied = np.asarray(mf.mo_occ).reshape(-1) > 0
    homo = float(energies[occupied].max()) * HARTREE_TO_EV
    lumo = float(energies[~occupied].min()) * HARTREE_TO_EV if (~occupied).any() else None
    _, charges = mf.mulliken_pop(verbose=0)
    dipole = mf.dip_moment(unit="Debye", verbose=0)
    return {
        "homo_ev": homo,
        "lumo_ev": lumo,
        "homo_lumo_gap_ev": None if lumo is None else lumo - homo,
        "dipole_debye": float(np.linalg.norm(dipole)),
        "dipole_vector_debye": [float(x) for x in dipole],
        "mulliken_charges": [float(q) for q in charges],
    }


def _describe(mol: Any, method: str, basis: str) -> dict[str, Any]:
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    return {
        "formula": _formula(symbols),
        "n_atoms": mol.natm,
        "charge": mol.charge,
        "unpaired_electrons": mol.spin,
        "method": method,
        "basis": basis,
        "n_basis_functions": mol.nao,
    }


def single_point(
    molecule: str,
    method: str = "b3lyp",
    basis: str = "def2-svp",
    charge: int | None = None,
    unpaired_electrons: int | None = None,
    frozen_core: bool = False,
    orbitals_file: str = "orbitals.molden",
) -> dict:
    """Compute the energy and electronic properties of a molecule at a fixed geometry.

    Args:
        molecule: SMILES (3D coordinates are generated), a structure file (XYZ,
            SDF/MOL, PDB), or inline coordinates in Angstrom such as
            "O 0 0 0; H 0 0.757 0.587; H 0 -0.757 0.587".
        method: "hf", "mp2", "ccsd", "ccsd(t)", or a DFT functional ("b3lyp",
            "pbe", "pbe0", "wb97x", "m06-2x", "tpss", ...).
        basis: Basis set, e.g. "sto-3g", "6-31g*", "cc-pvdz", "def2-svp", "def2-tzvp".
        charge: Total charge. Default: the formal charge in a SMILES or SDF/MOL file,
            otherwise 0.
        unpaired_electrons: Number of unpaired electrons (2S). Default: the radicals
            in a SMILES or SDF/MOL file, otherwise 0. Open shells use UHF/UKS.
        frozen_core: Keep core orbitals uncorrelated in MP2 and CCSD (all electrons
            are correlated by default).
        orbitals_file: Molden file with the orbitals, for viewing in e.g. Avogadro or Jmol.

    Returns:
        Total energy (Hartree and eV), the SCF energy, the correlation energy and
        (T) correction for MP2/CCSD, HOMO and LUMO energies and gap (eV, of the
        SCF reference), dipole moment (Debye), Mulliken charges, the number of
        basis functions, and the orbitals file.
    """
    method = _check_method(method)
    mol = _build(molecule, basis, charge, unpaired_electrons)
    mf = _mean_field(mol, method)
    energy = float(mf.e_tot)
    correlation = triples = None
    if method == "mp2":
        from pyscf import mp

        pt = mp.MP2(mf)
        if frozen_core:
            pt.set_frozen()
        correlation = float(pt.kernel()[0])
        energy = float(mf.e_tot) + correlation
    elif method in ("ccsd", "ccsd(t)"):
        from pyscf import cc

        coupled = cc.CCSD(mf)
        coupled.conv_tol = CONV_TOL
        if frozen_core:
            coupled.set_frozen()
        coupled.kernel()
        if not coupled.converged:
            raise RuntimeError("CCSD did not converge.")
        correlation = float(coupled.e_corr)
        energy = float(coupled.e_tot)
        if method == "ccsd(t)":
            triples = float(coupled.ccsd_t())
            energy += triples

    from pyscf.tools import molden

    molden.from_scf(mf, orbitals_file)
    return {
        **_describe(mol, method, basis),
        "energy_hartree": energy,
        "energy_ev": energy * HARTREE_TO_EV,
        "scf_energy_hartree": float(mf.e_tot),
        "correlation_energy_hartree": correlation,
        "triples_correction_hartree": triples,
        **_orbital_summary(mf),
        "orbitals_file": orbitals_file,
    }


def _optimize(mol: Any, method: str, max_steps: int) -> tuple[Any, bool, int]:
    from pyscf.geomopt.geometric_solver import GeometryOptimizer

    mf = _mean_field(mol, method)
    optimizer = GeometryOptimizer(mf)
    optimizer.max_cycle = max_steps
    optimizer.kernel()
    steps = len(getattr(optimizer, "energies", []) or []) or None
    return optimizer.mol, bool(optimizer.converged), steps


def optimize(
    molecule: str,
    method: str = "b3lyp",
    basis: str = "def2-svp",
    charge: int | None = None,
    unpaired_electrons: int | None = None,
    max_steps: int = 100,
    output: str = "optimized.xyz",
) -> dict:
    """Optimize a molecule's geometry (minimum energy structure) with HF or DFT.

    Args:
        molecule: SMILES, a structure file, or inline coordinates (see single_point).
        method: "hf" or a DFT functional.
        basis: Basis set, e.g. "def2-svp".
        charge: Total charge (default from SMILES/SDF, otherwise 0).
        unpaired_electrons: Number of unpaired electrons (default from SMILES/SDF, otherwise 0).
        max_steps: Maximum number of optimization steps.
        output: XYZ file for the optimized structure.

    Returns:
        Whether the optimization converged, the number of steps, the final energy
        (Hartree and eV), HOMO-LUMO gap, dipole moment, and the optimized structure path.
    """
    method = _check_method(method, allowed=("hf",))
    mol = _build(molecule, basis, charge, unpaired_electrons)
    final, converged, steps = _optimize(mol, method, max_steps)
    final.tofile(output, format="xyz")
    mf = _mean_field(final, method)
    return {
        **_describe(final, method, basis),
        "converged": converged,
        "steps": steps,
        "energy_hartree": float(mf.e_tot),
        "energy_ev": float(mf.e_tot) * HARTREE_TO_EV,
        **_orbital_summary(mf),
        "optimized_structure": output,
    }


def frequencies(
    molecule: str,
    method: str = "b3lyp",
    basis: str = "def2-svp",
    charge: int | None = None,
    unpaired_electrons: int | None = None,
    optimize_first: bool = True,
    temperature_k: float = 298.15,
    pressure_pa: float = 101325.0,
) -> dict:
    """Harmonic vibrational frequencies and thermochemistry from the analytic Hessian.

    Frequencies are only meaningful at a stationary point, so by default the
    geometry is optimized first (with the same method and basis).

    Args:
        molecule: SMILES, a structure file, or inline coordinates (see single_point).
        method: "hf" or a DFT functional.
        basis: Basis set, e.g. "def2-svp".
        charge: Total charge (default from SMILES/SDF, otherwise 0).
        unpaired_electrons: Number of unpaired electrons (default from SMILES/SDF, otherwise 0).
        optimize_first: Optimize the geometry before computing the Hessian.
        temperature_k: Temperature for thermochemistry, in K.
        pressure_pa: Pressure for thermochemistry, in Pa.

    Returns:
        Vibrational frequencies (cm⁻¹, imaginary ones negative), the number of
        imaginary frequencies, the electronic energy, zero-point energy, energy at
        0 K, enthalpy and Gibbs free energy (Hartree), entropy and heat capacity,
        and the optimized structure path if optimized.
    """
    from pyscf.hessian import thermo

    method = _check_method(method, allowed=("hf",))
    mol = _build(molecule, basis, charge, unpaired_electrons)
    structure = None
    if optimize_first:
        mol, converged, _ = _optimize(mol, method, 100)
        if not converged:
            raise RuntimeError("The geometry optimization before the frequencies did not converge.")
        structure = "optimized.xyz"
        mol.tofile(structure, format="xyz")
    mf = _mean_field(mol, method)
    hessian = mf.Hessian().kernel()
    harmonic = thermo.harmonic_analysis(mol, hessian)
    raw = np.asarray(harmonic["freq_wavenumber"])
    vibrations = [
        float(-abs(f.imag) if abs(f.imag) > abs(f.real) else f.real) for f in raw.astype(complex)
    ]
    properties = thermo.thermo(mf, harmonic["freq_au"], temperature_k, pressure_pa)
    value = lambda key: float(properties[key][0])  # noqa: E731 - (value, unit) pairs
    return {
        **_describe(mol, method, basis),
        "frequencies_cm1": vibrations,
        "imaginary_frequencies": sum(1 for f in vibrations if f < 0),
        "energy_hartree": float(mf.e_tot),
        "zero_point_energy_hartree": value("ZPE"),
        "energy_0k_hartree": value("E_0K"),
        "enthalpy_hartree": value("H_tot"),
        "free_energy_hartree": value("G_tot"),
        "entropy_hartree_per_k": value("S_tot"),
        "heat_capacity_hartree_per_k": value("Cv_tot"),
        "temperature_k": temperature_k,
        "pressure_pa": pressure_pa,
        "optimized_structure": structure,
    }


def excited_states(
    molecule: str,
    method: str = "b3lyp",
    basis: str = "def2-svp",
    charge: int | None = None,
    unpaired_electrons: int | None = None,
    n_states: int = 5,
    tda: bool = False,
    triplets: bool = False,
) -> dict:
    """Vertical excitation energies and oscillator strengths (UV-Vis) with TDDFT or TDHF.

    Args:
        molecule: SMILES, a structure file, or inline coordinates (see single_point).
        method: "hf" (TDHF/CIS) or a DFT functional (TDDFT). Range-separated
            functionals such as "wb97x" or "cam-b3lyp" describe charge-transfer
            states better.
        basis: Basis set; diffuse functions (e.g. "aug-cc-pvdz", "def2-svpd") matter
            for Rydberg and anionic states.
        charge: Total charge (default from SMILES/SDF, otherwise 0).
        unpaired_electrons: Number of unpaired electrons (default from SMILES/SDF, otherwise 0).
        n_states: Number of excited states.
        tda: Use the Tamm-Dancoff approximation (CIS for "hf").
        triplets: Singlet-to-triplet excitations instead of singlets (closed shells only).

    Returns:
        Excitation energies (eV) and wavelengths (nm), oscillator strengths, and
        whether each state converged.
    """
    method = _check_method(method, allowed=("hf",))
    if not 1 <= n_states <= 50:
        raise ValueError("n_states must be between 1 and 50.")
    mol = _build(molecule, basis, charge, unpaired_electrons)
    if triplets and mol.spin != 0:
        raise ValueError("triplets=True needs a closed-shell molecule (unpaired_electrons=0).")
    mf = _mean_field(mol, method)
    if tda:
        response = mf.TDA()
    elif method == "hf":
        response = mf.TDHF()
    else:
        response = mf.TDDFT()
    response.nstates = n_states
    if mol.spin == 0:
        response.singlet = not triplets
    response.kernel()
    energies = np.asarray(response.e) * HARTREE_TO_EV
    strengths = np.zeros_like(energies) if triplets else np.asarray(response.oscillator_strength())
    return {
        **_describe(mol, method, basis),
        "approximation": "TDA" if tda else ("TDHF" if method == "hf" else "TDDFT"),
        "spin": "triplet" if triplets else ("singlet" if mol.spin == 0 else "unrestricted"),
        "excitation_energies_ev": [float(e) for e in energies],
        "wavelengths_nm": [float(EV_NM / e) for e in energies],
        "oscillator_strengths": [float(f) for f in strengths],
        "converged": [bool(c) for c in np.atleast_1d(response.converged)],
    }
