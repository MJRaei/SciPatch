"""Recreate the files in tests/data (not run by SciPatch; kept so the data can be checked).

Usage: python make_data.py ADK_DIR OUT_DIR, where ADK_DIR holds adk.psf and
adk_dims.dcd from MDAnalysisTests 2.10.0 (testsuite/MDAnalysisTests/data).
"""

import sys

import MDAnalysis as mda
import numpy as np
from ase.build import bulk


def main(source: str, out: str) -> None:
    # Frames 0, 49 and 97 of the AdK transition used by MDAnalysis's RMSD tests.
    adk = mda.Universe(f"{source}/adk.psf", f"{source}/adk_dims.dcd")
    adk.trajectory[0]
    adk.atoms.write(f"{out}/adk.pdb")
    with mda.Writer(f"{out}/adk_3frames.dcd", adk.atoms.n_atoms) as writer:
        for _ in adk.trajectory[[0, 49, 97]]:
            writer.write(adk.atoms)
    # Perfect fcc copper, 4x4x4 conventional cells (256 atoms).
    bulk("Cu", "fcc", a=3.615, cubic=True).repeat((4, 4, 4)).write(f"{out}/Cu_fcc_4x4x4.pdb")
    # 3D random walk: each frame (1 ps) every particle moves +-1 Angstrom along x, y, z,
    # so MSD(t) = 3 t exactly in expectation and D = 0.5 Angstrom^2/ps.
    rng = np.random.default_rng(2026)
    n, frames = 100, 501
    steps = rng.choice([-1.0, 1.0], size=(frames - 1, n, 3))
    positions = np.concatenate([np.zeros((1, n, 3)), np.cumsum(steps, axis=0)]) + 50.0
    walk = mda.Universe.empty(n, trajectory=True)
    walk.add_TopologyAttr("names", ["Ar"] * n)
    walk.add_TopologyAttr("types", ["Ar"] * n)
    walk.add_TopologyAttr("resnames", ["AR"])
    walk.atoms.write(f"{out}/random_walk.pdb")
    with mda.Writer(f"{out}/random_walk.dcd", n, dt=1.0) as writer:
        for frame in positions:
            walk.atoms.positions = frame
            writer.write(walk.atoms)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
