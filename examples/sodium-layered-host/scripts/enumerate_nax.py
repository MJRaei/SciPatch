"""Symmetry-distinct Na/vacancy orderings of Na_x MX2 in 2x2x2 supercells of the O1 and O3 cells."""
import sys, itertools, json, os
from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pymatgen.analysis.structure_matcher import StructureMatcher
SP, host = sys.argv[1], sys.argv[2]
out = f"{SP}/enum/{host}"; os.makedirs(out, exist_ok=True)
sm = StructureMatcher(ltol=0.1, stol=0.1, angle_tol=2, primitive_cell=False, scale=False)
manifest = []
for stk in ("O1", "O3"):
    s = Structure.from_file(f"{SP}/relax/out/{host}__full_{stk}__chgnet.cif")
    s = SpacegroupAnalyzer(s, symprec=0.1).get_primitive_standard_structure()
    assert s.composition["Na"] == 1, s.composition
    s.make_supercell([2, 2, 2])
    na_idx = [i for i, site in enumerate(s) if site.specie.symbol == "Na"]
    for nNa in (2, 4, 6):
        uniq = []
        for keep in itertools.combinations(na_idx, nNa):
            t = s.copy(); t.remove_sites([i for i in na_idx if i not in keep])
            if not any(sm.fit(t, u) for u in uniq): uniq.append(t)
        for k, t in enumerate(uniq):
            fn = f"{out}/{stk}_x{nNa/8:.2f}_{k}.cif"; t.to(filename=fn)
            manifest.append(dict(file=fn, stacking=stk, x=nNa / 8, natoms=len(t)))
        print(stk, nNa / 8, len(uniq), flush=True)
json.dump(manifest, open(f"{out}/manifest.json", "w"), indent=1)
