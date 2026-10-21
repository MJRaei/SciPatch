# Example tool packages

## `chgnet/`: a research repository turned into a tool

[CHGNet](https://github.com/CederGroupHub/chgnet) is a universal
machine-learning interatomic potential for crystals (Deng et al., *Nat. Mach.
Intell.* 2023). This package was produced by following the `motel-onboard`
skill, step by step:

1. `motel onboard https://github.com/CederGroupHub/chgnet --ref v0.4.2 --paper https://doi.org/10.1038/s42256-023-00716-3`
   pinned the release to commit `8d04abc` and prepared the workspace.
2. Reading the README, `pyproject.toml`, and the test suite showed three
   capabilities worth exposing: `predict` (energy, forces, stress, magnetic
   moments), `relax`, and `molecular_dynamics` (marked long-running). It also
   showed that the pretrained weights ship with the code, so nothing needs
   downloading.
3. `motel check . --skip-tests` built the environment (PyTorch, pymatgen, and
   CHGNet's compiled Cython extension) in under a minute. No patches were
   needed.
4. The repository's own test suite documents reference values for the bundled
   LiMnO₂ structure. Running the README example with `motel exec` reproduced
   them exactly before any wrapper code was written.
5. The golden tests in `motel.yaml` check those values and cite the exact test
   they come from. `motel check . --clean` passed, then `motel add .`.

Install it yourself with:

```bash
motel add examples/chgnet
```

This downloads about 1 GB (mostly PyTorch). Then try
`motel run chgnet predict structure=examples/chgnet/tests/data/mp-18767-LiMnO2.cif`,
or ask your AI app to *relax LiMnO₂ with CHGNet and report the Mn magnetic moments*.

## Featured tools

The tools in [`src/motel/catalog/`](../src/motel/catalog) (`ase-emt`,
`rdkit-descriptors`) are also complete examples. They wrap PyPI packages
instead of a git repository, and they install by name: `motel add ase-emt`.
