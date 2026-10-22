"""Run ml-potentials relaxations through SciPatch with a small parallel queue.
usage: queue.py results.json jobs.json [max_parallel]"""
import json, subprocess, sys, time, os
res_path, jobs_path = sys.argv[1], sys.argv[2]
maxp = int(sys.argv[3]) if len(sys.argv) > 3 else 3
jobs = json.load(open(jobs_path))
res = json.load(open(res_path)) if os.path.exists(res_path) else {}
pending = [j for j in jobs if j["key"] not in res or res[j["key"]].get("status") != "succeeded"]
running = {}
def already_running(j):
    out = subprocess.run(["scipatch", "runs", "--tool", "ml-potentials", "--json"], capture_output=True, text=True).stdout
    try: d = json.loads(out)
    except Exception: return None
    runs = d if isinstance(d, list) else d.get("runs", [])
    for r in runs:
        if r.get("status") == "running" and r.get("arguments", {}).get("output") == j["output"]:
            return r["run_id"]
    return None
def start(j):
    rid = already_running(j)
    if rid: return rid
    args = dict(structure=j["structure"], model=j["model"], fmax=j.get("fmax", 0.02),
                steps=j.get("steps", 800), relax_cell=j.get("relax_cell", True), output=j["output"])
    out = subprocess.run(["scipatch", "run", "ml-potentials", "relax", "--args", json.dumps(args),
                          "--background", "--json"], capture_output=True, text=True)
    d = json.loads(out.stdout)
    if d.get("status") == "succeeded":  # cached
        return d
    return d["run_id"]
while pending or running:
    while pending and len(running) < maxp:
        j = pending.pop(0); r = start(j)
        if isinstance(r, dict):
            res[j["key"]] = dict(status="succeeded", run_id=r["run_id"], **{k: r["result"].get(k) for k in ("final_energy_ev", "converged", "steps", "lattice", "relaxed_structure")}, natoms=j.get("natoms"))
            json.dump(res, open(res_path, "w"), indent=1); continue
        running[r] = j
    time.sleep(3)
    for rid in list(running):
        d = json.loads(subprocess.run(["scipatch", "runs", "show", rid, "--json"], capture_output=True, text=True).stdout)
        if d["status"] in ("running", "queued", "pending"): continue
        j = running.pop(rid); r = d.get("result") or {}
        res[j["key"]] = dict(status=d["status"], run_id=rid, error=(d.get("error") or "")[:300] if d["status"] != "succeeded" else None,
                             **{k: r.get(k) for k in ("final_energy_ev", "converged", "steps", "lattice", "relaxed_structure")})
        json.dump(res, open(res_path, "w"), indent=1)
        print(time.strftime("%H:%M:%S"), j["key"], d["status"], r.get("final_energy_ev"), r.get("converged"), d.get("duration_seconds"), flush=True)
print("ALL DONE", flush=True)
