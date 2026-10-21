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
motel add tools/chgnet
```

This downloads about 1 GB (mostly PyTorch). Then try
`motel run chgnet predict structure=tools/chgnet/tests/data/mp-18767-LiMnO2.cif`,
or ask your AI app to *relax LiMnO₂ with CHGNet and report the Mn magnetic moments*.

## `pymatgen-diffusion/`: turning an analysis library into a tool

[pymatgen-analysis-diffusion](https://github.com/materialsvirtuallab/pymatgen-analysis-diffusion)
computes diffusivities, conductivities, and activation energies from MD
trajectories (Deng et al., *Chem. Mater.* 2017). It was onboarded because an
agent analyzing a CHGNet MD run had to write its own MSD scripts: work that is
not recorded in Motel and not reusable. Now it's two tool calls.

1. `motel onboard https://github.com/materialsvirtuallab/pymatgen-analysis-diffusion --ref v2025.11.14 --name pymatgen-diffusion`
2. Two capabilities were exposed: `analyze_trajectory` (MSD, diffusivity,
   conductivity, Haven ratio, plot) and `arrhenius_fit` (activation energy,
   extrapolation to room temperature). Any ASE-readable trajectory works, so it
   chains directly with CHGNet's `molecular_dynamics`, which reports the
   `frame_interval_fs` this tool needs.
3. The upstream tests check a preprocessed LGPS run, not a trajectory file. To
   test this tool's own path, that run was rebuilt as a trajectory
   ([tests/data](pymatgen-diffusion/tests/data/README.md)); the golden test
   reproduces the upstream values (D = 1.1608e-6 cm²/s, 74.165 mS/cm, Haven
   ratio 0.3185), as does the exact Arrhenius test.
4. The analysis reports how many ions actually hopped and warns when none did,
   so a vibration-only run is never mistaken for a diffusivity.

```bash
motel add tools/pymatgen-diffusion
```

## Featured tools

The tools in [`src/motel/catalog/`](../src/motel/catalog) (`ase-emt`,
`rdkit-descriptors`) are also complete examples. They wrap PyPI packages
instead of a git repository, and they install by name: `motel add ase-emt`.
