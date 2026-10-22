"""Figure 5: hard-carbon vs ZrS2 negative electrode in the same NVPF cell (PyBaMM DFN) + materials-level energy."""
import json, sys
import numpy as np
sys.path.insert(0, sys.argv[1] + "/scripts")
from vizstyle import *
import matplotlib.pyplot as plt
SP = sys.argv[1]
pe = json.load(open(f"{SP}/pybamm/cell_compare_pess.json")); op = json.load(open(f"{SP}/pybamm/cell_compare_opt.json"))
area_cm2 = 0.0254 * 100  # electrode 0.254 mm x 1 m in the Chayambuka2022 set = 2.54 cm2
HC, ZR = INK2, SERIES[1]
setup()
fig, axs = plt.subplots(1, 4, figsize=(13.5, 4.1), gridspec_kw=dict(width_ratios=[1.5, 1, 0.75, 0.75], wspace=0.42))
a = axs[0]
for d, col, lab in [(pe["HC"]["0.1"], HC, "Hard carbon || NVPF (Chayambuka 2022)"), (pe["ZrS2"]["0.1"], ZR, "ZrS2 || NVPF (same cathode, same N/P)")]:
    q = np.array(d["Q"]) * 1000 / area_cm2
    a.plot(q, d["V"], color=col, lw=2, label=f"{lab}: {d['Vavg']:.2f} V avg")
a.set_xlabel("Discharge capacity (mAh/cm²)"); a.set_ylabel("Cell voltage (V)"); a.set_title("C/10 discharge, PyBaMM DFN")
a.set_ylim(0.9, 4.3); a.legend(fontsize=7.5, loc="lower left")
b = axs[1]
rates = [0.1, 1, 2, 5]
for d, col, lab, mk in [(pe["HC"], HC, "Hard carbon", "o"), (pe["ZrS2"], ZR, "ZrS2, D(300 K) = 1.7e-11 cm²/s", "s"), (op["ZrS2"], SERIES[0], "ZrS2, D(300 K) = 1e-8 cm²/s", "D")]:
    e = [d[str(r)]["E_Wh"] / d["0.1"]["E_Wh"] * 100 for r in rates]
    b.plot(rates, e, color=col, lw=2, marker=mk, ms=6, mec=SURF, label=lab)
b.set_xscale("log"); b.set_xticks(rates); b.set_xticklabels(["0.1", "1", "2", "5"])
b.set_xlabel("C-rate"); b.set_ylabel("Energy retained (% of C/10)"); b.set_title("Rate (same cathode)")
b.legend(fontsize=7, loc="lower left")
# materials-level energy of the active pair (N/P = 1): NVPF 128 mAh/g, 3.17 g/cm3
Qc, rc = 128, 3.17
pairs = {"Hard carbon": dict(Q=300, rho=1.5, exp=1.0, V=pe["HC"]["0.1"]["Vavg"]),
         "ZrS2": dict(Q=172.5, rho=3.82, exp=1.19, V=pe["ZrS2"]["0.1"]["Vavg"])}
grav = {k: v["V"] / (1 / Qc + 1 / v["Q"]) for k, v in pairs.items()}
vol = {k: v["V"] / (1 / (Qc * rc) + v["exp"] / (v["Q"] * v["rho"])) for k, v in pairs.items()}
for ax, vals, yl, ttl in [(axs[2], grav, "Wh per kg of active material", "Specific energy"), (axs[3], vol, "Wh per L of active material", "Energy density")]:
    names = list(vals); ys = [vals[n] for n in names]
    ax.bar([0, 1], ys, width=0.6, color=[HC, ZR], edgecolor=SURF, linewidth=2)
    for i, y in enumerate(ys): ax.text(i, y * 1.02, f"{y:.0f}", ha="center", fontsize=8.5, color=INK)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["Hard\ncarbon", "ZrS2"]); ax.set_ylabel(yl); ax.set_title(ttl)
    ax.set_ylim(0, max(ys) * 1.18); ax.grid(axis="x", visible=False)
fig.text(0.01, 0.015, "Energy bars: cathode + anode active mass/volume only, N/P = 1, voltages from the C/10 simulations; HC 300 mAh/g at 1.5 g/cm³; ZrS2 172.5 mAh/g at 3.82 g/cm³ with +19% sodiation volume.", fontsize=7.5, color=INK2)
fig.subplots_adjust(left=0.05, right=0.99, top=0.9, bottom=0.2)
fig.savefig(f"{SP}/plots/fig5_cell.png", dpi=200)
print({k: round(v) for k, v in grav.items()}, {k: round(v) for k, v in vol.items()})
