"""Figure 2: NaxZrS2 voltage profile (4 ML models) vs hard-carbon OCP; formation-energy hull."""
import json, sys
import numpy as np
sys.path.insert(0, sys.argv[1] + "/scripts")
from vizstyle import *
import matplotlib.pyplot as plt
SP = sys.argv[1]
vz = json.load(open(f"{SP}/relax/voltage_ZrS2.json")); conv = json.load(open(f"{SP}/relax/conversion_ZrS2.json"))
ch = json.load(open(f"{SP}/pybamm/chayambuka_data.json"))
Q_ZRS2 = 26801.5 / 155.35          # mAh/g per Na per ZrS2
Q_HC = 14540 * 26.8015 / 1.5 / 1000  # mAh/g, c_max(Chayambuka) at an assumed 1.5 g/cm3 particle density
setup()
fig, (a, b) = plt.subplots(1, 2, figsize=(10.5, 4.6), gridspec_kw=dict(width_ratios=[1.6, 1], wspace=0.28))
# hard carbon
x, y = np.array(ch["U_n_data"][0]), np.array(ch["U_n_data"][1])
a.plot(x * Q_HC, y, color=INK2, lw=2, zorder=2)
a.text(62, 0.42, "Hard carbon\n(Chayambuka 2022 OCP;\nmass basis assumes 1.5 g/cm3)", color=INK2, fontsize=8, va="bottom")
for m in MODEL_ORDER:
    st = vz[m]["steps"]
    xs, ys = [], []
    for s in st:
        xs += [s["x0"] * Q_ZRS2, s["x1"] * Q_ZRS2]; ys += [s["V"], s["V"]]
    a.plot(xs, ys, color=MODEL_COLOR[m], lw=2, zorder=3, label=f"{MODEL_LABEL[m]}  (avg {vz[m]['V_avg']:.2f} V)")
vconv = max(max(conv[m]["V_to_Zr2S"], conv[m]["V_NaZrS2_to_ZrS_Na2S"]) for m in conv)
a.axhspan(0, vconv, color="#f0efec", zorder=0)
a.text(180, vconv + 0.04, f"below ~{vconv:.2f} V NaZrS2 converts\nto Zr2S + Na2S (all 4 models)", color=INK2, fontsize=8)
a.text(Q_ZRS2 * 0.02, 2.22, "NaxZrS2, x = 0 to 1 (hull of 2x2x2 orderings)", color=INK, fontsize=8.5, fontweight="bold")
a.set_xlim(0, 320); a.set_ylim(0, 2.45)
a.set_xlabel("Specific capacity (mAh/g of active material)"); a.set_ylabel("Voltage vs Na/Na+ (V)")
a.set_title("Sodiation voltage: ZrS2 vs hard carbon")
a.legend(loc="upper right", fontsize=8)
# formation energy hull
for m in MODEL_ORDER:
    cfg = vz[m]["configs"]
    b.scatter([c["x"] for c in cfg], [1000 * c["ef"] for c in cfg], s=22, marker=MODEL_MARKER[m], color=MODEL_COLOR[m], edgecolor=SURF, lw=1, alpha=0.9, zorder=3)
    hx = vz[m]["hull"]; hy = [1000 * vz[m]["ef"][str(v)] for v in hx]
    b.plot(hx, hy, color=MODEL_COLOR[m], lw=1.4, zorder=2, label=MODEL_LABEL[m])
b.axhline(0, color=INK2, lw=0.8)
b.set_xlabel("x in NaxZrS2"); b.set_ylabel("Formation energy (meV per ZrS2)")
b.set_title("Na/vacancy orderings and convex hull")
b.legend(loc="lower left", fontsize=8)
fig.subplots_adjust(left=0.07, right=0.99, top=0.9, bottom=0.12)
fig.savefig(f"{SP}/plots/fig2_voltage.png", dpi=200); print("saved")
