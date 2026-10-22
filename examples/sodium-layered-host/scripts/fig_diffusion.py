"""Figure 4: Na hop barriers (NEB, 4 ML models) and MD Arrhenius diffusivity for ZrS2."""
import json, sys
import numpy as np
sys.path.insert(0, sys.argv[1] + "/scripts")
from vizstyle import *
import matplotlib.pyplot as plt
SP = sys.argv[1]
P = json.load(open(f"{SP}/neb/profiles.json"))
setup()
fig, axs = plt.subplots(1, 3, figsize=(12, 4.2), gridspec_kw=dict(wspace=0.3))
for ax, lim, title in [(axs[0], "vac", "Vacancy hop in NaZrS2 (x ≈ 1)"), (axs[1], "dil", "Single Na hop in empty ZrS2")]:
    ref = P.get(f"TiS2|{lim}|orb")
    if ref:
        ax.plot(ref["s"], ref["E"], color=MUTED, lw=1.4, zorder=2, label=f"TiS2 reference, Orb-v3 ({ref['barrier']:.2f} eV)")
    for m in MODEL_ORDER:
        k = f"ZrS2|{lim}|{m}"
        if k in P:
            ax.plot(P[k]["s"], P[k]["E"], color=MODEL_COLOR[m], lw=2, marker=MODEL_MARKER[m], ms=5, mec=SURF, zorder=3,
                    label=f"{MODEL_LABEL[m]} ({P[k]['barrier']:.2f} eV)")
    ax.set_title(title); ax.set_xlabel("Reaction coordinate (normalized)"); ax.set_ylabel("Energy (eV)")
    ax.set_ylim(-0.03, 0.8); ax.legend(fontsize=7.5, loc="upper left")
ax = axs[2]
T = np.array([900, 1100, 1300]); D = np.array([6.366e-06, 2.0447e-05, 1.642e-05])
ax.scatter(1000 / T, D, s=40, color=SERIES[3], marker="^", edgecolor=SURF, zorder=4, label="MD, TensorNet, Na0.5ZrS2 (168 atoms)")
x = np.linspace(1000 / 1300, 1000 / 300, 50); kB = 8.617e-5
for Ea, D0, lab, col in [(0.257, 2.066e-4, "fit, 3 T: Ea = 0.26 ± 0.17 eV", SERIES[3]), (0.498, 3.900e-3, "fit, 900–1100 K: Ea = 0.50 eV", INK2)]:
    ax.plot(x, D0 * np.exp(-Ea / (kB * 1000 / x)), color=col, lw=1.4, zorder=3, label=lab)
ax.axhspan(2.6e-12, 2.0e-11, color="#f0efec", zorder=0)
ax.text(0.85, 3.2e-12, "hard carbon, solid-state D (Chayambuka 2022 parameter set)", ha="left", fontsize=7.5, color=INK2)
ax.axvline(1000 / 300, color=MUTED, lw=0.8)
ax.text(1000 / 300 - 0.04, 2e-13, "300 K", ha="right", fontsize=7.5, color=INK2)
ax.set_yscale("log"); ax.set_ylim(1e-13, 1e-4)
ax.set_xlabel("1000 / T (1/K)"); ax.set_ylabel("Na diffusivity (cm²/s)"); ax.set_title("Na diffusivity, MD + Arrhenius")
ax.legend(fontsize=7.2, loc="upper right")
fig.subplots_adjust(left=0.06, right=0.99, top=0.9, bottom=0.14)
fig.savefig(f"{SP}/plots/fig4_diffusion.png", dpi=200); print("saved")
