"""Collect NEB profiles (energy vs reaction coordinate) from the extxyz bands."""
import glob, json, os, sys
import numpy as np
from ase.io import read
SP = sys.argv[1]; out = {}
for fn in sorted(glob.glob(f"{SP}/neb/*_*_*.extxyz")):
    host, lim, m = os.path.basename(fn)[:-7].split("_")
    if host == "ZrS2" and m == "orb" and os.path.getmtime(fn) < os.path.getmtime(f"{SP}/scripts/neb_na.py"):
        continue  # band from before the calculator fix
    ims = read(fn, ":")
    e = np.array([im.get_potential_energy() for im in ims]); e -= e[0]
    if np.allclose(e, 0): continue
    pos = np.array([im.get_positions() for im in ims])
    d = [0.0]
    for i in range(1, len(ims)):
        dv = ims[i].get_positions() - ims[i - 1].get_positions()
        dv = dv - np.round(dv @ np.linalg.inv(ims[0].cell.array)) @ ims[0].cell.array
        d.append(d[-1] + np.linalg.norm(dv))
    out[f"{host}|{lim}|{m}"] = dict(s=(np.array(d) / d[-1]).tolist(), E=e.tolist(), barrier=float(e.max()))
json.dump(out, open(f"{SP}/neb/profiles.json", "w"), indent=1)
for k, v in out.items(): print(k, round(v["barrier"], 3))
