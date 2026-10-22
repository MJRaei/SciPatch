"""Build host, dilute-Na and fully sodiated structures for layered hosts."""
import sys, json, itertools
import numpy as np
from pymatgen.core import Structure, Lattice
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

SP = sys.argv[1]
H = f"{SP}/hosts"; OUT = f"{SP}/structs"
import os; os.makedirs(OUT, exist_ok=True)

def conventional(s):
    return SpacegroupAnalyzer(s, symprec=0.05).get_conventional_standard_structure()

def layer_height(lat):
    return lat.volume / np.linalg.norm(np.cross(lat.matrix[0], lat.matrix[1]))

def gaps(s, min_h=2.2):
    h = layer_height(s.lattice)
    zs = np.sort(np.mod(s.frac_coords[:, 2], 1.0))
    out = []
    for i in range(len(zs)):
        z0 = zs[i]; z1 = zs[(i + 1) % len(zs)] + (1.0 if i == len(zs) - 1 else 0.0)
        if (z1 - z0) * h >= min_h:
            out.append(((z0 + z1) / 2 % 1.0, (z1 - z0) * h))
    return out

def clearance_map(s, zmid, n=36):
    pts = np.array([[u / n, v / n, zmid] for u in range(n) for v in range(n)])
    d = s.lattice.get_all_distances(pts, s.frac_coords)
    return pts, d.min(axis=1)

def pick_sites(s, zmid, dmin=3.0, frac=0.88, nmax=None):
    pts, clr = clearance_map(s, zmid)
    order = np.argsort(-clr); cmax = clr[order[0]]
    chosen = []
    for i in order:
        if clr[i] < frac * cmax: break
        p = pts[i]
        if chosen and s.lattice.get_all_distances([p], chosen).min() < dmin: continue
        chosen.append(p)
        if nmax and len(chosen) >= nmax: break
    return chosen, cmax

def sodiate(s, nmax_per_gap=None, dmin=3.0):
    t = s.copy(); info = []
    for zmid, hgap in gaps(s):
        sites, cmax = pick_sites(s, zmid, dmin=dmin, nmax=nmax_per_gap)
        for p in sites: t.append("Na", p)
        info.append(dict(z=round(zmid, 3), gap_A=round(hgap, 2), n=len(sites), clearance_A=round(cmax, 2)))
    return t, info

def dilute(s, target_inplane=9.0, target_c=7.5, max_atoms=110):
    a, b, c = s.lattice.abc
    na = max(1, int(np.ceil(target_inplane / a))); nb = max(1, int(np.ceil(target_inplane / b)))
    nc = max(1, int(np.ceil(target_c / c)))
    while len(s) * na * nb * nc > max_atoms and (na > 1 or nb > 1):
        if na >= nb: na -= 1
        else: nb -= 1
    sc = s.copy(); sc.make_supercell([na, nb, nc])
    zmid, hgap = max(gaps(sc), key=lambda g: g[1])
    sites, cmax = pick_sites(sc, zmid, nmax=1)
    scn = sc.copy(); scn.append("Na", sites[0])
    return sc, scn, (na, nb, nc)

hosts = sys.argv[2].split(",")
summary = {}
for name in hosts:
    s = conventional(Structure.from_file(f"{H}/{name}.cif"))
    full, info = sodiate(s)
    sc, scn, rep = dilute(s)
    s.to(filename=f"{OUT}/{name}__host.cif")
    full.to(filename=f"{OUT}/{name}__full_O1.cif")
    sc.to(filename=f"{OUT}/{name}__sc.cif")
    scn.to(filename=f"{OUT}/{name}__dilute.cif")
    nfu = s.composition.get_reduced_composition_and_factor()[1]
    x = full.composition["Na"] / nfu
    summary[name] = dict(host_atoms=len(s), fu=nfu, gaps=info, x_full=round(x, 3), sc=rep, sc_atoms=len(sc))
    print(name, json.dumps(summary[name]))

# O3 (alpha-NaFeO2-type, R-3m) analogues of NaTiS2 for 1T MX2 hosts
tmpl = Structure.from_file(f"{H}/NaTiS2_O3.cif")
tmpl = SpacegroupAnalyzer(tmpl).get_conventional_standard_structure()
for name in hosts:
    s = conventional(Structure.from_file(f"{H}/{name}.cif"))
    sg = SpacegroupAnalyzer(s).get_space_group_symbol()
    if sg != "P-3m1" or len(s) != 3: continue
    comp = s.composition.reduced_composition
    M = [e for e in comp.elements if e.is_metal][0]; X = [e for e in comp.elements if not e.is_metal][0]
    t = tmpl.copy(); t.replace_species({"Ti": M.symbol, "S": X.symbol})
    a = s.lattice.a; ct = tmpl.lattice.c * (a / tmpl.lattice.a)
    t.lattice = Lattice.hexagonal(a, ct)
    t.to(filename=f"{OUT}/{name}__full_O3.cif")
    print(name, "O3 built", len(t))
json.dump(summary, open(f"{OUT}/summary.json", "w"), indent=1)
