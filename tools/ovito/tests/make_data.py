"""Write the ideal crystals and defects in tests/data (not run by Motel).

Usage: python make_data.py OUT_DIR
"""

import sys

import numpy as np
from ase.build import bulk
from ase.io import write
from ase.lattice.cubic import FaceCenteredCubic

A_CU = 3.615


def main(out: str) -> None:
    perfect = bulk("Cu", "fcc", a=A_CU, cubic=True).repeat((4, 4, 4))
    write(f"{out}/Cu_fcc.xyz", perfect)
    # One vacancy: atom 0 removed.
    write(f"{out}/Cu_fcc_vacancy.xyz", perfect[1:])
    # A Frenkel pair: atom 0 moved to an octahedral interstitial site far from its site.
    frenkel = perfect.copy()
    frenkel.positions[0] = np.array([1.52, 1.5, 1.5]) * A_CU
    write(f"{out}/Cu_frenkel.xyz", frenkel)
    write(f"{out}/Fe_bcc.xyz", bulk("Fe", "bcc", a=2.8553, cubic=True).repeat((4, 4, 4)))
    write(f"{out}/Mg_hcp.xyz", bulk("Mg", "hcp", a=3.21, c=3.21 * np.sqrt(8 / 3)).repeat((4, 4, 3)))
    write(f"{out}/Si_diamond.xyz", bulk("Si", "diamond", a=5.431, cubic=True).repeat((3, 3, 3)))
    # Straight screw dislocation in fcc Cu (Volterra displacement field): line along
    # z = [1-10], Burgers vector b = a/2 [1-10], periodic along the line only.
    crystal = FaceCenteredCubic(
        "Cu",
        directions=[[1, 1, -2], [1, 1, 1], [1, -1, 0]],
        size=(8, 6, 4),
        latticeconstant=A_CU,
        pbc=(False, False, True),
    )
    center = crystal.cell.lengths()[:2] / 2 + np.array([0.13, 0.17])  # between atoms
    theta = np.arctan2(*(crystal.positions[:, [1, 0]] - center).T)
    crystal.positions[:, 2] += A_CU / np.sqrt(2) * theta / (2 * np.pi)
    crystal.wrap()
    write(f"{out}/Cu_screw_dislocation.xyz", crystal)


if __name__ == "__main__":
    main(sys.argv[1])
