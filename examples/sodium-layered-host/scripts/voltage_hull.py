"""Na_xZrS2 voltage profile (convex hull over orderings) and ML phase stability vs Na-Zr-S phases, per model."""
import json, sys, glob, os
import numpy as np
from pymatgen.core import Structure, Composition
from pymatgen.analysis.phase_diagram import PhaseDiagram, PDEntry
SP = sys.argv[1]; host = sys.argv[2] if len(sys.argv) > 2 else "ZrS2"
res = {}
for fn in glob.glob(f"{SP}/relax/results*.json"): res.update(json.load(open(fn)))
models = ["orb", "mace", "chgnet", "tensornet"]
def E(m, name):
    r = res.get(f"{m}|{name}")
    if not r or r["status"] != "succeeded": return None
    s = Structure.from_file(r["relaxed_structure"]); return r["final_energy_ev"], s
out = {}
for m in models:
    na = E(m, "Na_bcc"); h = E(m, f"{host}__host")
    if not na or not h: continue
    eNa = na[0] / len(na[1]); eH = h[0] / h[1].composition.get_reduced_composition_and_factor()[1]
    pts = {0.0: ("host_O1", eH)}
    for stk in ("O1", "O3"):
        f = E(m, f"{host}__full_{stk}")
        if f:
            nfu = f[1].composition["Zr" if "Zr" in host else f[1].composition.elements[0].symbol]
            e = f[0] / f[1].composition["Na"]
            if 1.0 not in pts or e < pts[1.0][1]: pts[1.0] = (f"full_{stk}", e)
    configs = []
    for k, r in res.items():
        mm, name = k.split("|")
        if mm != m or not name.startswith(f"{host}enum_") or r["status"] != "succeeded": continue
        s = Structure.from_file(r["relaxed_structure"]); c = s.composition
        nM = sum(v for el, v in c.items() if el.symbol not in ("Na", "S", "Se"))
        x = c["Na"] / nM; e = r["final_energy_ev"] / nM
        configs.append((x, e, name))
        if x not in pts or e < pts[x][1]: pts[x] = (name, e)
    xs = sorted(pts)
    # formation energy relative to host and NaMX2 end members
    e0, e1 = pts[0.0][1], pts[1.0][1]
    ef = {x: pts[x][1] - (1 - x) * e0 - x * e1 for x in xs}
    # lower convex hull
    hull = [0.0]
    for x in xs[1:]:
        hull.append(x)
        while len(hull) >= 3:
            x1, x2, x3 = hull[-3:]
            if (ef[x2] - ef[x1]) * (x3 - x1) >= (ef[x3] - ef[x1]) * (x2 - x1): hull.pop(-2)
            else: break
    steps = []
    for a, b in zip(hull[:-1], hull[1:]):
        V = -((pts[b][1] - pts[a][1]) - (b - a) * eNa) / (b - a)
        steps.append(dict(x0=a, x1=b, V=V))
    Vavg = -((e1 - e0) - eNa)
    allcfg = [dict(x=x, ef=e - (1 - x) * e0 - x * e1, name=n) for x, e, n in configs]
    out[m] = dict(steps=steps, V_avg=Vavg, hull=hull, ef={str(k): v for k, v in ef.items()}, configs=allcfg, ends=dict(x0=pts[0.0][0], x1=pts[1.0][0]))
    print(m, "Vavg=%.3f" % Vavg, " ".join(f"[{s['x0']:.2f}-{s['x1']:.2f}: {s['V']:.3f} V]" for s in steps), "| ends:", pts[1.0][0])
    # ML phase diagram Na-Zr-S using the same model for every phase
    if "Zr" in host:
        phases = ["Na2S", "ZrS", "Zr3S4c", "Zr3S4", "Na2ZrS3", "Zr2S", "ZrS3", "Zr", "Na19Zr11S30"]
        ents = [PDEntry(Composition("Na"), eNa, name="Na"), PDEntry(Composition("ZrS2"), e0, name="ZrS2")]
        ents.append(PDEntry(Composition("NaZrS2"), e1, name="NaZrS2(ML)"))
        for p in phases:
            r = E(m, p)
            if r: ents.append(PDEntry(r[1].composition, r[0], name=p))
        # sulfur reference: take from the hull of S-rich side is not needed for Na-ZrS2 tie line; add S via ZrS3 only
        try:
            pd = PhaseDiagram(ents + [PDEntry(Composition("S"), min(e.energy_per_atom for e in ents) * 0 + 0, name="S_dummy")]) if False else None
        except Exception: pd = None
        # Stability of NaZrS2 against the other phases: compute decomposition energy with a hull built from all but S (use reaction energies)
        from pymatgen.analysis.phase_diagram import PhaseDiagram as PD
        # add elemental S as a high-energy placeholder so the hull is defined (S-free tie lines unaffected)
        Ssrc = E(m, "ZrS3")
        # S chemical potential bounded by ZrS2/ZrS3 coexistence: mu_S = E(ZrS3) - E(ZrS2)
        muS = (Ssrc[0] / Ssrc[1].composition.get_reduced_composition_and_factor()[1] - e0) if Ssrc else 0.0
        ents2 = ents + [PDEntry(Composition("S"), muS + 0.3, name="S_ref(upper bound)")]
        try: pd = PD(ents2)
        except ValueError as err:
            print("   phase diagram skipped:", err); continue
        target = [e for e in ents2 if e.name == "NaZrS2(ML)"][0]
        dec, ehull = pd.get_decomp_and_phase_separation_energy(target)
        out[m]["NaZrS2_ehull_eV_atom"] = ehull
        out[m]["NaZrS2_decomp"] = {e.name: round(a, 3) for e, a in dec.items()}
        print("   NaZrS2 E_hull(ML) = %.3f eV/atom; decomposes to %s" % (ehull, out[m]["NaZrS2_decomp"]))
json.dump(out, open(f"{SP}/relax/voltage_{host}.json", "w"), indent=1)
