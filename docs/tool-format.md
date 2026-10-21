# Tool package format

A tool package is a folder:

```text
my-tool/
├── motel.yaml       required: the manifest
├── api.py           required: the functions (name set by `entrypoint`)
├── SKILL.md         recommended: usage notes for agents
├── references/      optional: extra documents copied into the agent skill
├── patches/         optional: *.patch / *.diff applied to the source, in name order
├── tests/data/      optional: input files for golden tests
└── requirements.txt / environment.yml   optional, if referenced from motel.yaml
```

`motel new <name>` creates this skeleton; `motel check <folder>` validates it.

## `motel.yaml`

```yaml
schema: 1
name: chgnet                       # required
version: 0.1.0
title: CHGNet universal potential
summary: >-                        # required, 10-400 characters
  Relax crystal structures and predict energies, forces, and magnetic moments
  with the CHGNet universal machine-learning interatomic potential.
description: null
domains: [materials]
tags: [ml-potential, relaxation]
authors: []

source:
  repo: https://github.com/CederGroupHub/chgnet
  ref: <tag or commit>             # required when repo is set
  subdirectory: null
  install: true
  paper: https://doi.org/10.1038/s42256-023-00716-3
  citation: "Deng et al., Nat. Mach. Intell. 5, 1031 (2023)"
  license: <SPDX id>
  homepage: null

environment:
  manager: uv                      # uv | conda
  python: "3.11"
  packages: []
  requirements: null
  conda_packages: []               # conda only
  channels: [conda-forge]          # conda only
  conda_file: null                 # conda only
  post_install: []
  variables: {}

entrypoint: api

functions:                         # optional
  relax:
    long_running: false
    cache: true
    timeout: null
    params:
      structure: {kind: structure}
      fmax: {unit: eV/Å}
    outputs:
      energy_ev_per_atom: {unit: eV/atom}

validity: >-
  When results can and cannot be trusted.

golden:
  - name: reproduces the paper's value for silicon
    function: relax
    args: {structure: tests/data/Si.cif}
    expect:
      lattice_a_angstrom: {approx: 5.47, abs: 0.05}
    reference: <exact source of the number>
    timeout: 900
```

### Identity

| Field | Meaning |
|---|---|
| `schema` | Manifest format version (currently 1). |
| `name` | Lowercase letters, digits, and single hyphens; at most 48 characters. Used for folders, commands, and the skill name `motel-<name>`. |
| `version` | Version of this package (your wrapper), not of the upstream code. |
| `title`, `summary`, `description` | Shown to people and agents. The summary is searched; make it specific. |
| `domains`, `tags` | Search keywords. |

### `source`

Where the scientific code comes from. Leave it out for tools that only use PyPI
packages (like the featured `ase-emt`).

| Field | Meaning |
|---|---|
| `repo` | Git URL (https, ssh, or a local `file://` path). |
| `ref` | Branch, tag, or commit, **required** with `repo`. Prefer a commit or tag so rebuilds are identical; `motel new` and `motel onboard` pin the commit for you. |
| `subdirectory` | Install from this subfolder of the repository. |
| `install` | Install the checkout into the environment (editable). Set `false` for repositories that are not pip-installable; at run time, the checkout's path is in the `MOTEL_SOURCE_DIR` environment variable. |
| `paper`, `citation`, `license`, `homepage` | Shown with every result, so users can cite correctly. |

### `environment`

| Field | Meaning |
|---|---|
| `manager` | `uv` (default; PyPI) or `conda` (conda-forge plus PyPI). |
| `python` | Python version, e.g. `"3.11"`. Quote it in YAML. |
| `packages` | PyPI requirement strings, e.g. `["numpy<2", "torch==2.5.1"]`. |
| `requirements` | Path to a requirements file in the package. |
| `conda_packages`, `channels`, `conda_file` | Conda only. |
| `post_install` | Shell commands run in the activated environment after installing (e.g. downloading model weights). |
| `variables` | Environment variables set for every run. |

The environment is rebuilt only when something that affects it changes: this
section, the source commit, the patches, or the referenced files.

### `functions`

Leave it out to expose every public function of the entry-point module (all
functions not starting with `_`, defined in that module, or listed in its
`__all__`). Give a list (`functions: [relax, predict]`) or a mapping to expose
only some, with settings:

| Setting | Meaning |
|---|---|
| `long_running` | Calls return immediately with a run id; agents poll for the result. |
| `cache` | Reuse results of identical calls (default `true`; turn off for stochastic functions without a seed). |
| `timeout` | Seconds. |
| `params.<name>` | `kind`, `unit`, `description` for a parameter. |
| `outputs.<key>` | `kind`, `unit`, `description` for a key of the returned dict. |

**Kinds** name what a value *is*, so agents can chain tools: `structure` (CIF,
POSCAR, extended XYZ path), `molecule` (SMILES or SDF/MOL/XYZ path),
`trajectory`, `spectrum`, `table`, `image`, `file`, `directory`. Relative paths
in parameters with a file-like kind are resolved from the caller's folder.

### `validity`

Plain text: the training data or level of theory, supported elements or
chemistries, known failure modes. Agents are instructed to respect it and repeat
the relevant caveats.

### `golden`

| Field | Meaning |
|---|---|
| `name` | What the test shows. |
| `function`, `args` | The call. Relative file paths are resolved from the package folder. |
| `expect` | Checks, keyed by a dotted path into the result (`energy`, `forces.0.2`; `.` is the whole result). |
| `reference` | Where the expected values come from. Never invent one. |
| `timeout` | Seconds (default 900). |

Each check is a literal (numbers are compared to within about 1e-9) or a matcher:

| Matcher | Passes when |
|---|---|
| `{approx: x, rel: r, abs: a}` | the value is within tolerance (default `rel: 0.01` when neither is given) |
| `{equals: v}` | the value equals `v` exactly |
| `{min: a}`, `{max: b}` | the value is within bounds (inclusive) |
| `{contains: v}` | a string contains `v`, or a list contains the item `v` |
| `{length: n}` | `len(value) == n` |
| `{exists: true}` | the value is a path to an existing file |
| `{type: t}` | JSON type: `number`, `integer`, `string`, `boolean`, `array`, `object`, `null` |

Golden tests run on every build. A failing test stops `motel add` unless you pass
`--allow-failing-tests`, in which case the tool is marked as failing its tests
everywhere it appears.

## `api.py`

```python
"""One line about the tool."""

from __future__ import annotations

from typing import Literal


def relax(
    structure: str,
    fmax: float = 0.05,
    optimizer: Literal["bfgs", "fire"] = "bfgs",
    output: str = "relaxed.cif",
) -> dict:
    """Relax a crystal structure.

    Args:
        structure: Path to the input structure (CIF, POSCAR, or extended XYZ).
        fmax: Force convergence threshold in eV/Å.
        optimizer: Optimization algorithm.
        output: File to write the relaxed structure to.

    Returns:
        Final energy per atom (eV/atom), steps taken, and the relaxed structure's path.
    """
    ...
```

- **Type hints** become the JSON Schema that agents, the CLI, and the dashboard
  use. Supported: `str`, `int`, `float`, `bool`, `list[...]`, `dict[str, ...]`,
  `Optional`/`X | None`, `Literal`, `Enum`, `pathlib.Path`, dataclasses,
  `TypedDict`, and `Annotated[str, {"kind": "structure", "unit": "Å"}]`.
- **Docstrings** (Google or NumPy style): the first line is the summary agents
  search; `Args:` describes each parameter, **with units**.
- **Inputs** are plain values and file paths. **Outputs** are JSON-friendly
  values (NumPy values, dataclasses, paths, and objects with
  `as_dict()`/`todict()` are converted automatically). Put units in key names.
- Write output files into the **current directory** (each run has its own) and
  return their relative paths; Motel returns them as absolute paths.
- Raise `ValueError` with a clear message for bad input. The message is shown
  to the user and the agent.
- No prompts, windows, or `plt.show()`. Printing is fine; it goes to the run's
  log.

## `SKILL.md`

Usage notes in the [Agent Skills](https://agentskills.io/specification) format.
Motel combines them with the manifest and function signatures into the skill
`motel-<name>` that it installs for your agents.

```markdown
---
name: chgnet
description: >-
  Relax crystal structures and predict energies with the CHGNet universal ML
  potential. Use for fast pre-relaxation, stability screening before DFT, or
  quick energy estimates for inorganic crystals.
---

## Recipes
- Stability screen: relax, then compare the energy with the Materials Project hull.

## Pitfalls
- Energies are PBE/PBE+U-like; compare only with compatible data.
```

The `description` decides when an agent picks the tool, so say what it does
**and when to use it**, using the words a user would. Don't repeat function
signatures in the body; Motel adds them.
