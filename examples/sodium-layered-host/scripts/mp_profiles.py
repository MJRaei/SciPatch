"""Thermodynamic sodiation profiles of hosts from Materials Project formation energies."""
import json, glob, os, sys
from pymatgen.core import Composition, Element
from pymatgen.analysis.phase_diagram import PhaseDiagram, PDEntry
SP = sys.argv[1]
recs = {}
for fn in glob.glob(f"{SP}/mp/chemsys/*.json") + glob.glob(f"{SP}/mp/*.json"):
    try: d = json.load(open(fn))
    except Exception: continue
    if d.get("status") != "succeeded": continue
    for m in d["result"].get("materials", []):
        recs[m["material_id"]] = m
def entries_for(els):
    els = set(els); out = [PDEntry(Composition(e), 0.0, name=e) for e in els]
    for m in recs.values():
        c = Composition(m["formula"])
        if set(str(e) for e in c.elements) <= els and len(c.elements) > 1:
            out.append(PDEntry(c, m["formation_energy_ev_per_atom"] * c.num_atoms, name=f"{m['formula']}[{m['material_id']}{'' if not m['theoretical'] else ',th'}]"))
    return out
hosts = {"TiS2": "Na-Ti-S", "ZrS2": "Na-Zr-S", "ZrSe2": "Na-Zr-Se", "HfS2": "Na-Hf-S", "TiSe2": "Na-Ti-Se",
         "NbS2": "Na-Nb-S", "VS2": "Na-V-S", "MoS2": "Na-Mo-S", "ZrNCl": "Na-Zr-N-Cl", "TiNCl": "Na-Ti-N-Cl",
         "CrSBr": "Na-Cr-S-Br", "FeOCl": "Na-Fe-O-Cl", "FeSe": "Na-Fe-Se", "MnPS3": "Na-Mn-P-S"}
out = {}
for h, cs in hosts.items():
    pd = PhaseDiagram(entries_for(cs.split("-")))
    comp = Composition(h)
    host_e = min((e for e in pd.all_entries if e.composition.reduced_composition == comp.reduced_composition), key=lambda e: e.energy_per_atom, default=None)
    ehull = pd.get_e_above_hull(host_e) if host_e else None
    prof = pd.get_element_profile(Element("Na"), comp)
    steps = []
    for p in prof:
        steps.append(dict(V=round(-p["chempot"], 3), x_na=round(p["evolution"], 3), reaction=str(p["reaction"])))
    out[h] = dict(ehull=ehull, steps=steps)
    print(f"\n== {h}  (MP E_hull of host = {ehull:.3f} eV/atom)")
    for s in steps: print(f"   V={s['V']:6.3f}  Na/fu={s['x_na']:6.3f}  {s['reaction']}")
json.dump(out, open(f"{SP}/mp/mp_profiles.json", "w"), indent=1)
