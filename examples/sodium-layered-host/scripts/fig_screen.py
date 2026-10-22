"""Figure 1: screening - Na binding (dilute) and average voltage per host, 4 ML models, plus MP decomposition onset."""
import json, sys
import numpy as np
sys.path.insert(0, sys.argv[1] + "/scripts")
from vizstyle import *
import matplotlib.pyplot as plt
SP = sys.argv[1]
t = json.load(open(f"{SP}/relax/analysis.json")); mp = json.load(open(f"{SP}/mp/mp_profiles.json"))
known = {"TiS2", "VS2", "NbS2", "MoS2"}            # Na phase in ICSD / heavily reported outside the KB
halide = {"ZrNCl", "HfNCl", "TiNCl", "FeOCl", "VOCl", "CrSBr"}
conv = {"FeSe", "MnPS3", "NiPS3"}
order = ["ZrS2", "HfS2", "ZrSe2", "TiSe2", "TiS2", "VS2", "NbS2", "MoS2", "FeSe", "MnPS3", "NiPS3", "CrSBr", "TiNCl", "ZrNCl", "HfNCl", "FeOCl", "VOCl"]
order = [h for h in order if h in t]
setup()
fig, axes = plt.subplots(1, 2, figsize=(10.5, 6.2), sharey=True, gridspec_kw=dict(wspace=0.08))
y = np.arange(len(order))[::-1]
for ax, key, title, xl in [(axes[0], "Eb_dilute", "Na binding, dilute limit", "E_bind vs Na metal (eV per Na)"),
                           (axes[1], "V_avg", "Average intercalation voltage", "V vs Na/Na+ (x = 0 to x_max)")]:
    for i, h in enumerate(order):
        vals = [t[h][m][key] for m in MODEL_ORDER if m in t[h] and key in t[h][m]]
        if vals:
            ax.plot([min(vals), max(vals)], [y[i]] * 2, color=GRID, lw=6, solid_capstyle="round", zorder=1)
        for m in MODEL_ORDER:
            if m in t[h] and key in t[h][m]:
                ax.scatter(t[h][m][key], y[i], s=34, marker=MODEL_MARKER[m], color=MODEL_COLOR[m], edgecolor=SURF, linewidth=1.2, zorder=3,
                           label=MODEL_LABEL[m] if i == 0 else None)
        if key == "V_avg" and h in mp:
            steps = mp[h]["steps"]; v_first = max(s["V"] for s in steps if s["x_na"] == 0) if any(s["x_na"] == 0 for s in steps) else None
            # first decomposition plateau = V of the x=0 row (host becomes unstable below it)
            if v_first is not None:
                ax.plot([v_first] * 2, [y[i] - 0.32, y[i] + 0.32], color=INK2, lw=1.6, zorder=2, label="Materials Project hull: first reaction with Na (known phases only)" if i == 0 else None)
    ax.set_title(title); ax.set_xlabel(xl)
    ax.grid(axis="y", visible=False)
axes[0].set_yticks(y)
labels = []
for h in order:
    tag = " · known Na" if h in known else (" · forms NaCl/NaBr" if h in halide else (" · converts" if h in conv else ""))
    labels.append(h.replace("2", "₂").replace("3", "₃") + tag)
axes[0].set_yticklabels(labels)
for tl, h in zip(axes[0].get_yticklabels(), order):
    tl.set_color(INK if h not in known | halide | conv else MUTED)
    if h == "ZrS2": tl.set_fontweight("bold")
axes[1].axvspan(0, 1.0, color="#f0efec", zorder=0); axes[1].text(0.05, y[0] + 0.55, "below 1 V", color=INK2, fontsize=8)
axes[1].set_xlim(0, 3.1); axes[0].set_xlim(-3.6, 0.0)
h_, l_ = axes[1].get_legend_handles_labels()
fig.legend(h_, l_, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.005))
fig.text(0.01, 0.965, "Screening 17 layered hosts not reported for Na in the knowledge base", ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.text(0.01, 0.928, "Each marker is one ML potential; grey bar = model spread. Grey names: Na phase already known outside the KB, or the host decomposes (NaCl/NaBr, Na2S/Na3FeSe3) before intercalating.", fontsize=8.5, color=INK2)
fig.subplots_adjust(left=0.15, right=0.99, top=0.86, bottom=0.15)
fig.savefig(f"{SP}/plots/fig1_screening.png", dpi=200)
print("saved")
