"""Binding energies and average intercalation voltages from the ML relaxations."""
import json, sys, os, glob
import numpy as np
from pymatgen.core import Structure, Composition
SP = sys.argv[1]
res = {}
for fn in sorted(glob.glob(f"{SP}/relax/results*.json")):
    res.update(json.load(open(fn)))
models = ["orb", "mace", "chgnet", "tensornet"]
def get(m, name):
    r = res.get(f"{m}|{name}")
    if not r or r["status"] != "succeeded": return None
    f = r.get("relaxed_structure") or f"{SP}/relax/out/{name}__{m}.cif"
    s = Structure.from_file(f)
    return dict(E=r["final_energy_ev"], s=s, conv=r.get("converged"))
hosts = sorted({k.split("|")[1].split("__")[0] for k in res if "__host" in k})
table = {}
for h in hosts:
    row = {}
    for m in models:
        na = get(m, "Na_bcc"); host = get(m, f"{h}__host")
        if not na or not host: continue
        eNa = na["E"] / len(na["s"])
        hc = host["s"].composition
        nfu_h = hc.get_reduced_composition_and_factor()[1]
        e_fu = host["E"] / nfu_h; v_fu = host["s"].volume / nfu_h
        d = {}
        dil = get(m, f"{h}__dilute")
        if dil:
            nhost_atoms = len(dil["s"]) - 1
            e_host_sc = host["E"] * nhost_atoms / len(host["s"])
            d["Eb_dilute"] = dil["E"] - e_host_sc - eNa
            d["dil_conv"] = dil["conv"]
        best = None
        for stk in ("O1", "O3"):
            f = get(m, f"{h}__full_{stk}")
            if not f: continue
            c = f["s"].composition; nNa = c["Na"]
            nfu = Composition({el: amt for el, amt in c.items() if el.symbol != "Na"}).get_reduced_composition_and_factor()[1]
            dE = f["E"] - nfu * e_fu - nNa * eNa
            V = -dE / nNa; x = nNa / nfu
            vol = f["s"].volume / nfu
            # interlayer spacing per layer: cell height / number of gaps (from host)
            rec = dict(V=V, x=x, dvol_pct=100 * (vol / v_fu - 1), E_per_fu=(f["E"] - nNa * eNa) / nfu, conv=f["conv"])
            d[f"full_{stk}"] = rec
            if best is None or rec["E_per_fu"] < best[1]["E_per_fu"]: best = (stk, rec)
        if best:
            d["best_stacking"] = best[0]; d["V_avg"] = best[1]["V"]; d["x_full"] = best[1]["x"]; d["dvol_pct"] = best[1]["dvol_pct"]
        d["host_c"] = host["s"].lattice.c; d["host_vol_fu"] = v_fu
        row[m] = d
    table[h] = row
json.dump(table, open(f"{SP}/relax/analysis.json", "w"), indent=1, default=float)
print(f"{'host':8s} | " + " | ".join(f"{m:>9s}" for m in models) + " || Eb_dil mean±sd (eV) | Vavg mean±sd (V) | x | dV%")
for h, row in table.items():
    eb = [row[m]["Eb_dilute"] for m in models if m in row and "Eb_dilute" in row[m]]
    va = [row[m]["V_avg"] for m in models if m in row and "V_avg" in row[m]]
    dv = [row[m]["dvol_pct"] for m in models if m in row and "dvol_pct" in row[m]]
    xs = [row[m]["x_full"] for m in models if m in row and "x_full" in row[m]]
    cells = " | ".join(f"{row[m].get('Eb_dilute', float('nan')):+5.2f}/{row[m].get('V_avg', float('nan')):4.2f}" if m in row else f"{'-':>9s}" for m in models)
    print(f"{h:8s} | {cells} || {np.mean(eb) if eb else np.nan:+.2f}±{np.std(eb) if eb else np.nan:.2f} | {np.mean(va) if va else np.nan:.2f}±{np.std(va) if va else np.nan:.2f} | {xs[0] if xs else np.nan:.2f} | {np.mean(dv) if dv else np.nan:+.0f}")
