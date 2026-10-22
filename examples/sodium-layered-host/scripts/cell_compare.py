"""Hard-carbon || NVPF (Chayambuka2022, PyBaMM) vs the same cell with a ZrS2 negative electrode.

The ZrS2 electrode replaces only the negative-electrode active material: OCP from the
ML voltage profile, c_max from the ZrS2 density, solid diffusivity from MD, areal capacity
matched to the hard-carbon electrode (same N/P), same porosity, particle size, and kinetics.
usage: cell_compare.py SP inputs.json
"""
import sys, json
import numpy as np
import pybamm
SP, inp = sys.argv[1], json.load(open(sys.argv[2]))
F = 96485.33
def base():
    return pybamm.ParameterValues("Chayambuka2022")
def run(p, c_rate, vmin, vmax):
    model = pybamm.lithium_ion.DFN()
    exp = pybamm.Experiment([f"Discharge at {c_rate}C until {vmin} V"])
    sim = pybamm.Simulation(model, parameter_values=p, experiment=exp)
    sol = sim.solve()
    t = sol["Time [h]"].entries; V = sol["Voltage [V]"].entries
    Q = sol["Discharge capacity [A.h]"].entries
    E = np.trapezoid(V, Q)
    return dict(Q_Ah=float(Q[-1]), E_Wh=float(E), Vavg=float(E / Q[-1]), V=V.tolist(), Q=Q.tolist())
out = {}
# --- hard carbon baseline
p = base(); cap_nom = p["Nominal cell capacity [A.h]"]
out["HC"] = {str(c): run(p, c, 2.0, 4.2) for c in inp["c_rates"]}
# areal capacity of the HC electrode (A h / m2)
L_n = p["Negative electrode thickness [m]"]; eps_n = p["Negative electrode active material volume fraction"]
cmax_hc = p["Maximum concentration in negative electrode [mol.m-3]"]
sto0_hc = p["Initial concentration in negative electrode [mol.m-3]"] / cmax_hc
Qa_hc = L_n * eps_n * cmax_hc * F / 3600
# --- ZrS2 electrode
x_pts = np.array(inp["ocp_x"]); v_pts = np.array(inp["ocp_V"])
cmax_z = inp["rho_kg_m3"] / inp["M_kg_mol"] * inp["x_max"]
def zrs2_ocp(sto):
    return pybamm.Interpolant(x_pts, v_pts, sto, "ZrS2_ocp")
def zrs2_D(sto, T):
    Ea = inp["Ea_eV"] * F
    return inp["D300_m2_s"] * pybamm.exp(-Ea / 8.314 * (1 / T - 1 / 298.15))
q = base()
L_z = Qa_hc / (eps_n * cmax_z * F / 3600)
q.update({
    "Negative electrode OCP [V]": zrs2_ocp,
    "Negative particle diffusivity [m2.s-1]": zrs2_D,
    "Maximum concentration in negative electrode [mol.m-3]": cmax_z,
    "Initial concentration in negative electrode [mol.m-3]": sto0_hc * cmax_z,
    "Negative electrode thickness [m]": L_z,
    "Lower voltage cut-off [V]": inp["vmin_zrs2"],
    "Open-circuit voltage at 0% SOC [V]": inp["vmin_zrs2"],
    "Open-circuit voltage at 100% SOC [V]": 4.2,
})
out["ZrS2"] = {str(c): run(q, c, inp["vmin_zrs2"], 4.2) for c in inp["c_rates"]}
out["notes"] = dict(Qa_mAh_cm2=Qa_hc / 10, L_hc_um=L_n * 1e6, L_zrs2_um=L_z * 1e6, cmax_zrs2=cmax_z, sto0=sto0_hc)
json.dump(out, open(f"{SP}/pybamm/cell_compare.json", "w"))
for k in ("HC", "ZrS2"):
    for c, r in out[k].items():
        print(k, c, "C: Q=%.3f mAh  E=%.2f mWh  Vavg=%.3f V" % (r["Q_Ah"] * 1e3, r["E_Wh"] * 1e3, r["Vavg"]))
print(out["notes"])
