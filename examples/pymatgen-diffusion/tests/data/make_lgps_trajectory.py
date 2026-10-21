"""Rebuild upstream's preprocessed LGPS AIMD run (DiffusionAnalyzer.json) as a trajectory."""
import json, sys
import numpy as np
from ase.io import write
from pymatgen.core import Structure
from pymatgen.io.ase import AseAtomsAdaptor

source, target = sys.argv[1], sys.argv[2]
data = json.load(open(source))
structure = Structure.from_dict(data["structure"])
displacements = np.array(data["displacements"])  # (sites, frames, 3), cumulative, Cartesian
frames = []
for t in range(displacements.shape[1]):
    atoms = AseAtomsAdaptor.get_atoms(structure)
    atoms.set_positions(structure.cart_coords + displacements[:, t, :])
    frames.append(atoms)
write(target, frames, format="extxyz")
print(f"wrote {len(frames)} frames of {len(structure)} atoms ({structure.composition.reduced_formula})")
