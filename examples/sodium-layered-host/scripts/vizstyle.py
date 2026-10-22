"""Shared chart style: reference palette (light), thin marks, hairline solid grid."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
SURF = "#fcfcfb"; INK = "#0b0b0b"; INK2 = "#52514e"; MUTED = "#8a8984"; GRID = "#e6e5e0"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MODEL_ORDER = ["orb", "mace", "chgnet", "tensornet"]
MODEL_LABEL = {"orb": "Orb-v3", "mace": "MACE-MPA-0", "chgnet": "CHGNet 0.3", "tensornet": "TensorNet-MatPES"}
MODEL_COLOR = dict(zip(MODEL_ORDER, SERIES[:4]))
MODEL_MARKER = {"orb": "o", "mace": "s", "chgnet": "D", "tensornet": "^"}
def setup():
    plt.rcParams.update({
        "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
        "axes.edgecolor": GRID, "axes.linewidth": 0.8, "axes.labelcolor": INK2,
        "axes.titlecolor": INK, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.labelsize": 9.5, "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "grid.linestyle": "-",
        "axes.spines.top": False, "axes.spines.right": False,
        "legend.frameon": False, "legend.fontsize": 8.5, "text.color": INK,
        "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "lines.linewidth": 2, "lines.solid_capstyle": "round",
    })
