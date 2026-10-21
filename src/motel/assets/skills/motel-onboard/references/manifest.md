# `motel.yaml` reference

Every field, with illustrative values (check real versions, licenses, and
numbers against the repository and paper you are wrapping):

```yaml
schema: 1                         # manifest format version
name: chgnet                      # lowercase, digits, hyphens; at most 48 characters
version: 0.1.0                    # version of this package (not of the upstream code)
title: CHGNet universal potential
summary: >-                       # 10 to 400 characters: what it computes, for what
  Relax crystal structures and predict energies, forces, and magnetic moments
  with the CHGNet universal machine-learning interatomic potential.
description: null                 # optional longer text
domains: [materials]              # broad fields
tags: [ml-potential, relaxation, energy, magmom]   # search keywords
authors: []

source:
  repo: https://github.com/CederGroupHub/chgnet   # git URL (optional)
  ref: v0.3.0                     # REQUIRED with repo: tag or commit, pinned
  subdirectory: null              # install from a subfolder of the repo
  install: true                   # pip-install the checkout (editable)
  paper: https://doi.org/10.1038/s42256-023-00716-3
  citation: "Deng et al., Nat. Mach. Intell. 5, 1031 (2023)"
  license: BSD-3-Clause

environment:
  manager: uv                     # uv (PyPI) | conda (conda-forge + PyPI)
  python: "3.11"
  packages: ["numpy<2"]           # PyPI requirement strings
  requirements: null              # or a requirements.txt in the package
  conda_packages: []              # conda only, e.g. ["openmm=8.1", "xtb"]
  channels: [conda-forge]         # conda only
  conda_file: null                # conda only: environment.yml in the package
  post_install: []                # shell commands run in the environment afterwards
  variables: {}                   # environment variables for every run
  secrets:                        # API keys, passed as environment variables
    - name: MP_API_KEY
      description: Materials Project API key
      url: https://next-gen.materialsproject.org/api   # where to get one

entrypoint: api                   # module that defines the functions

functions:                        # optional; omit to expose all public functions
  relax:
    long_running: false           # true: agents start it in the background
    cache: true                   # reuse results of identical calls
    timeout: null                 # seconds
    params:
      structure: {kind: structure}
      fmax: {unit: eV/Å}
    outputs:
      energy_ev_per_atom: {unit: eV/atom}

validity: >-
  Trained on Materials Project GGA/GGA+U relaxations. Compare energies only with
  MP-compatible data. Unreliable for elements or bonding environments absent
  from the training set; confirm critical results with DFT.

maturity: published               # established | published | experimental (default);
                                  # needs the evidence below, see "Maturity"

golden:
  - name: relaxes Si close to its PBE lattice constant
    function: relax
    args: {structure: tests/data/Si.cif}
    expect:
      lattice_a_angstrom: {approx: 5.47, abs: 0.05}
    reference: "<exact source of the number: paper table/figure, or documented example>"
    against: paper                # independent | paper | upstream-tests | exact | regression
    timeout: 900
  - name: refuses elements outside the training data   # inputs outside validity must fail
    function: relax
    args: {structure: tests/data/unsupported.cif}
    raises: "not supported"                              # text the error message must contain
```

Maturity: `established` (mature, widely used code) needs `source.paper` and a
golden test with `against: independent` or `exact`; `published` (research code
from a publication) needs `source.paper` and a test with `against` set to
`independent`, `exact`, `paper`, or `upstream-tests`; `experimental` needs
nothing. `against` says where expected values come from: `independent`
(experiment, a reference database, or another program), `paper` (the tool's own
publication), `upstream-tests` (the project's test suite or documentation),
`exact` (an analytical result, sum rule, symmetry, or count), or `regression`
(this tool's own earlier output). Refusal tests (`raises`) have no `against`.

Patches: every `*.patch` or `*.diff` file in `patches/` is applied to the
checkout in name order. Create them with `motel patch save . -m "reason"`.

Data kinds: `structure` (CIF, POSCAR, extended XYZ path), `molecule` (SMILES
string or SDF/MOL/XYZ path), `trajectory`, `spectrum`, `table` (CSV),
`image`, `file`, `directory`. Parameters with a file-like kind have relative
paths resolved from the caller's folder.

Golden matchers: a literal (exact; numbers to about 1e-9), or
`{approx: x, rel: 0.01, abs: 0.0}` (default rel 0.01), `{equals: v}`,
`{min: a}`, `{max: b}`, `{contains: v}`, `{length: n}`, `{exists: true}` (a file
path), `{type: number|integer|string|boolean|array|object|null}`. Keys are dotted
paths into the result (`forces.0.2`); `.` is the whole result.
