"""Na hop barriers in layered MX2 by climbing-image NEB with the ml-potentials models.

Two limits: 'vac' = one Na vacancy in O3 NaMX2 (near full sodiation);
'dil' = one Na in the empty host (dilute). The hop goes between neighbouring
octahedral sites; the path is free to pass through the tetrahedral site.
usage: neb_na.py SP host model_short [limit]
"""
import sys, json, os, importlib.util
import numpy as np
from ase.io import read, write
from ase.mep import NEB
from ase.optimize import FIRE
from ase.constraints import FixAtoms

SP, host, ms = sys.argv[1:4]
limits = sys.argv[4].split(",") if len(sys.argv) > 4 else ["vac", "dil"]
MODELS = {"orb": "Orb-v3-conservative-inf-mpa", "mace": "MACE-MPA-0-medium",
          "chgnet": "CHGNet-0.3.0", "tensornet": "TensorNet-MatPES-PBE-2025.2"}
spec = importlib.util.spec_from_file_location("mlapi", os.path.expanduser("~/.scipatch/catalogs/scipatch/tools/ml-potentials/api.py"))
api = importlib.util.module_from_spec(spec); spec.loader.exec_module(api)
_inner = api._calculator(MODELS[ms], "float64" if ms == "mace" else "auto", "cpu")
from ase.calculators.calculator import Calculator, all_changes
class Fresh(Calculator):
    """Per-image wrapper: always re-evaluates the shared model on this image's atoms."""
    implemented_properties = ["energy", "free_energy", "forces"]
    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        _inner.reset()
        a = self.atoms.copy(); a.calc = _inner
        e = float(a.get_potential_energy()); f = a.get_forces().copy()
        self.results = {"energy": e, "free_energy": e, "forces": f}
calc = None
out = {}
os.makedirs(f"{SP}/neb", exist_ok=True)

def relax_fixed_cell(a, fmax=0.03, steps=400):
    a.calc = Fresh()
    FIRE(a, logfile=None).run(fmax=fmax, steps=steps)
    return a

def neighbours_in_plane(a, i, species="Na"):
    """Same-layer octahedral neighbours of site i: Na sites (or, if absent, translates by a/b vectors)."""
    return None

def run_neb(ini, fin, tag, nimg=5):
    images = [ini] + [ini.copy() for _ in range(nimg)] + [fin]
    for im in images: im.calc = Fresh()
    neb = NEB(images, climb=True)
    neb.interpolate(mic=True)
    opt = FIRE(neb, logfile=None)
    conv = opt.run(fmax=0.05, steps=400)
    for im in images: im.calc = Fresh()
    e = np.array([im.get_potential_energy() for im in images])
    write(f"{SP}/neb/{host}_{tag}_{ms}.extxyz", images)
    return dict(barrier_ev=float(e.max() - e[0]), asym_ev=float(e[-1] - e[0]), profile=(e - e[0]).tolist(), converged=bool(conv))

if "vac" in limits:
    # O3 NaMX2, conventional hex cell relaxed with this model, 3x3x1, remove one Na
    from pymatgen.core import Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from pymatgen.io.ase import AseAtomsAdaptor
    s = Structure.from_file(f"{SP}/relax/out/{host}__full_O3__{ms}.cif")
    s = SpacegroupAnalyzer(s, symprec=0.1).get_conventional_standard_structure(); s.make_supercell([3, 3, 1])
    na = [i for i, x in enumerate(s) if x.specie.symbol == "Na"]
    v = na[0]
    # nearest Na in the same layer
    d = [(s.get_distance(v, j), j) for j in na if j != v and abs(s[j].frac_coords[2] - s[v].frac_coords[2]) < 0.02]
    dmin, hop = min(d)
    base = s.copy(); base.remove_sites([v])
    ini = AseAtomsAdaptor.get_atoms(base)
    # final: the hopping Na moves into the vacancy
    fin_s = s.copy(); fin_s.remove_sites([hop])
    # reorder so the moving atom has the same index: in fin_s, site v holds the moved Na
    fin = AseAtomsAdaptor.get_atoms(fin_s)
    # map indices: ini has all sites except v; fin has all except hop. Build fin with ini ordering.
    idx_ini = [i for i in range(len(s)) if i != v]
    pos = s.cart_coords.copy(); pos[hop] = s[v].coords
    fin = ini.copy(); fin.positions = pos[idx_ini]
    ini = relax_fixed_cell(ini); fin = relax_fixed_cell(fin)
    out["vac"] = run_neb(ini, fin, "vac") | dict(hop_distance_A=float(dmin), natoms=len(ini))
    print(host, ms, "vac", json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in out["vac"].items() if k != "profile"}), flush=True)

if "dil" in limits:
    a = read(f"{SP}/relax/out/{host}__dilute__{ms}.cif")
    from pymatgen.core import Structure
    from pymatgen.io.ase import AseAtomsAdaptor
    s = AseAtomsAdaptor.get_structure(a)
    host_s = Structure.from_file(f"{SP}/relax/out/{host}__host__{ms}.cif")
    i_na = [i for i, x in enumerate(s) if x.specie.symbol == "Na"][0]
    # in-plane primitive translation of the host = supercell a / repeat count
    na_rep = round(s.lattice.a / host_s.lattice.a)
    shift = s.lattice.matrix[0] / na_rep
    ini = a.copy()
    fin = a.copy(); fin.positions[i_na] += shift; fin.wrap()
    ini = relax_fixed_cell(ini); fin = relax_fixed_cell(fin)
    out["dil"] = run_neb(ini, fin, "dil") | dict(hop_distance_A=float(np.linalg.norm(shift)), natoms=len(ini))
    print(host, ms, "dil", json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in out["dil"].items() if k != "profile"}), flush=True)
json.dump(out, open(f"{SP}/neb/{host}_{ms}.json", "w"), indent=1)
