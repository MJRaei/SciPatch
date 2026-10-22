"""Figure 3: simulated Cu-Ka powder XRD of ZrS2 (before) and NaZrS2 (after full sodiation)."""
import csv, sys, json
import numpy as np
sys.path.insert(0, sys.argv[1] + "/scripts")
from vizstyle import *
import matplotlib.pyplot as plt
SP = sys.argv[1]
def load(fn, hexcell=True):
    rows = list(csv.DictReader(open(fn)))
    pk = []
    for r in rows:
        tt = float(r[[k for k in r if "two" in k.lower()][0]]); I = float(r[[k for k in r if "intens" in k.lower()][0]])
        h = r[[k for k in r if "hkl" in k.lower()][0]]
        if pk and abs(pk[-1][0] - tt) < 0.02: pk[-1][1] += I
        else: pk.append([tt, I, h])
    m = max(p[1] for p in pk)
    return [(t, 100 * I / m, h) for t, I, h in pk]
def hk(h, rhombo=False):
    """Miller-Bravais string like '10-14' -> 3-index family label '(104)'."""
    import re
    v = [int(x) for x in re.findall(r"-?\d", h)]
    if len(v) != 4: return h
    fam = {(0, 0, 0): "00", (0, 1, 1): "10", (1, 1, 2): "11", (0, 2, 2): "20", (1, 2, 3): "21", (0, 3, 3): "30", (2, 2, 4): "22"}
    key = tuple(sorted(abs(x) for x in v[:3]))
    l = abs(v[3]); f = fam.get(key, "?")
    if rhombo and f in ("10", "20") and (-int(f[0]) + l) % 3 != 0:
        f = "0" + f[0]           # R-3m (hexagonal axes) condition -h + k + l = 3n
    return "(" + f + str(l) + ")"
H = sys.argv[2] if len(sys.argv) > 2 else "ZrS2"
CFG = {"ZrS2": ("ZrS2_before", "NaZrS2_after", "Before: 1T-ZrS2 (P-3m1), a = 3.662 Å, c = 5.82 Å (literature lattice)",
                "After: O3-NaZrS2 (R-3m), a = 3.675 Å, c = 20.62 Å (ML consensus, Orb-v3 cell)", "fig3_xrd.png"),
       "HfS2": ("HfS2_before", "NaHfS2_after", "Before: 1T-HfS2 (P-3m1), a = 3.625 Å, c = 5.846 Å (literature lattice)",
                "After: O3-NaHfS2 (R-3m), a ≈ 3.63 Å, c ≈ 20.6 Å (ML consensus, Orb-v3 cell)", "figS_xrd_HfS2.png")}[H]
before = load(f"{SP}/xrd/{CFG[0]}.csv"); after = load(f"{SP}/xrd/{CFG[1]}.csv")
setup()
fig, axs = plt.subplots(2, 1, figsize=(9.5, 5.6), sharex=True, gridspec_kw=dict(hspace=0.12))
tt = np.linspace(10, 80, 7000)
for ax, pk, col, title, rh in [(axs[0], before, SERIES[0], CFG[2], False),
                           (axs[1], after, SERIES[1], CFG[3], True)]:
    prof = sum(I * np.exp(-0.5 * ((tt - t) / 0.06) ** 2) for t, I, _ in pk)
    ax.plot(tt, prof, color=col, lw=1.4)
    ax.set_ylim(0, 118); ax.set_yticks([0, 50, 100]); ax.set_ylabel("Rel. intensity")
    ax.set_title(title, fontsize=9.5)
    for t, I, h in sorted(pk, key=lambda p: -p[1])[:6]:
        ax.text(t, I + 3, hk(h, rh), ha="center", fontsize=7.5, color=INK2)
    ax.grid(axis="x", visible=False)
# guide lines: ZrS2 (001) -> NaZrS2 (003)
for t, lab in [(before[0][0], ""), (after[0][0], "")]:
    for ax in axs: ax.axvline(t, color=GRID, lw=0.8, zorder=0)
axs[1].set_xlabel("2θ (degrees, Cu Kα, λ = 1.5418 Å)")
axs[1].set_xlim(10, 80)
fig.subplots_adjust(left=0.08, right=0.99, top=0.93, bottom=0.1)
fig.savefig(f"{SP}/plots/{CFG[4]}", dpi=200); print("saved")
