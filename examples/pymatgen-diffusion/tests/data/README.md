# Test data

`LGPS_600K_AIMD.extxyz.gz`: 1000 frames (20 fs apart) of a Li10GeP2S12 ab initio
MD run at 600 K. It was rebuilt from the preprocessed run that
pymatgen-analysis-diffusion's own test suite uses
(`tests/pymatgen/analysis/diffusion/DiffusionAnalyzer.json` at v2025.11.14), so
the golden test checks this tool against the values asserted there:

```bash
motel exec . -- python tests/data/make_lgps_trajectory.py \
    source/tests/pymatgen/analysis/diffusion/DiffusionAnalyzer.json \
    tests/data/LGPS_600K_AIMD.extxyz.gz
```
