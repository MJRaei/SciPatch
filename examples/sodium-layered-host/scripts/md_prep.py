"""Na0.5MX2 (O3) 4x4x1 supercells for MD, from a model's relaxed NaMX2."""
import sys, random
from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
SP, host, model = sys.argv[1:4]
s = Structure.from_file(f"{SP}/relax/out/{host}__full_O3__{model}.cif")
s = SpacegroupAnalyzer(s, symprec=0.1).get_conventional_standard_structure()
s.make_supercell([4, 4, 1])
na = [i for i, x in enumerate(s) if x.specie.symbol == "Na"]
random.seed(7); remove = random.sample(na, len(na) // 2)
s.remove_sites(remove)
fn = f"{SP}/md/{host}_Na0.5_{model}.cif"; s.to(filename=fn)
print(fn, s.composition, len(s), [round(v, 2) for v in s.lattice.abc])
