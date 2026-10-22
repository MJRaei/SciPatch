# Tool package format

A tool package is a folder:

```text
my-tool/
├── scipatch.yaml       required: the manifest
├── api.py           required: the functions (name set by `entrypoint`)
├── SKILL.md         recommended: usage notes for agents
├── references/      optional: extra documents copied into the agent skill
├── patches/         optional: *.patch / *.diff applied to the source, in name order
├── tests/data/      optional: input files for golden tests
└── requirements.txt / environment.yml   optional, if referenced from scipatch.yaml
```

`scipatch new <name>` creates this skeleton; `scipatch check <folder>` validates it.

## `scipatch.yaml`

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
maturity: published        # established, published, or experimental (the default)

golden:
  - name: reproduces the paper's value for silicon
    function: relax
    args: {structure: tests/data/Si.cif}
    expect:
      lattice_a_angstrom: {approx: 5.47, abs: 0.05}
    reference: <exact source of the number>
    against: paper             # kind of reference, see below
    timeout: 900
```

### Identity

| Field | Meaning |
|---|---|
| `schema` | Manifest format version (currently 1). |
| `name` | Lowercase letters, digits, and single hyphens; at most 48 characters. Used for folders, commands, and the skill name `scipatch-<name>`. |
| `version` | Version of this package (your wrapper), not of the upstream code. |
| `title`, `summary`, `description` | Shown to people and agents. The summary is searched; make it specific. |
| `domains`, `tags` | Search keywords. |

### `source`

Where the scientific code comes from. Leave it out for tools that only use PyPI
packages (like the featured `ase-emt`).

| Field | Meaning |
|---|---|
| `repo` | Git URL (https, ssh, or a local `file://` path). |
| `ref` | Branch, tag, or commit, **required** with `repo`. Prefer a commit or tag so rebuilds are identical; `scipatch new` and `scipatch onboard` pin the commit for you. |
| `subdirectory` | Install from this subfolder of the repository. |
| `install` | Install the checkout into the environment (editable). Set `false` for repositories that are not pip-installable; at run time, the checkout's path is in the `SCIPATCH_SOURCE_DIR` environment variable. |
| `paper`, `citation`, `license`, `homepage` | Shown with every result, so users can cite correctly. |

### `environment`

| Field | Meaning |
|---|---|
| `manager` | `uv` (default; PyPI) or `conda` (conda-forge plus PyPI). |
| `python` | Python version, e.g. `"3.11"`. Quote it in YAML. |
| `packages` | PyPI requirement strings, e.g. `["numpy<2", "torch==2.5.1"]`. |
| `requirements` | Path to a requirements file in the package. |
| `conda_packages`, `channels`, `conda_file` | Conda only. |
| `platforms` | Platforms the tool supports, if fewer than its packages allow: `linux-64`, `linux-aarch64`, `osx-arm64`, `osx-64`, `win-64`. Usually left out; `scipatch freeze` finds where the packages exist. |
| `post_install` | Shell commands run in the activated environment after installing (e.g. downloading model weights). |
| `variables` | Environment variables set for every run. |
| `secrets` | Secrets the tool needs, such as API keys: names (`[MP_API_KEY]`) or, better, objects with `name`, `description`, and `url` (where to get one), so SciPatch can ask for them clearly. Each tool receives only the secrets it declares, as environment variables. See [API keys](#api-keys). |

The environment is rebuilt only when something that affects it changes: this
section, the source commit, the patches, the lock file, or the referenced files.

#### Different packages on different platforms

Any entry of `packages` or `conda_packages` can end with a
[PEP 508 environment marker](https://packaging.python.org/en/latest/specifications/dependency-specifiers/#environment-markers),
so it is installed only where it applies:

```yaml
environment:
  manager: conda
  conda_packages: ["openmm=8.6.1", "ambertools=23.3; sys_platform != 'win32'"]
  packages: ["ovito==3.16.1.post1; sys_platform == 'darwin'",
             "ovito==3.16.1; sys_platform != 'darwin'"]
```

Useful markers: `sys_platform` (`linux`, `darwin`, `win32`), `platform_machine`
(`x86_64`, `arm64`, `aarch64`, `AMD64`), `python_version`. A function that needs
a package missing on some platform should say so in its error message.

#### API keys

```yaml
environment:
  secrets:
    - name: MP_API_KEY
      description: Materials Project API key
      url: https://next-gen.materialsproject.org/api
```

Read the key with `os.environ["MP_API_KEY"]` in `api.py`. Keys never go into
tool packages, run records, or the chat with an AI app. A user can provide one:

- when installing: `scipatch add` asks for it, hidden, with the `url`;
- on the **Keys** page of the dashboard (`scipatch ui`);
- from a run in an AI app: if the key is missing, the app gets a one-time link
  to a page on the user's computer where they enter it (apps that support MCP
  URL elicitation open it themselves);
- from a terminal: `scipatch secret set MP_API_KEY` asks for it, hidden. Run by an
  AI agent (no terminal to type in), the same command opens the page in the
  user's browser instead and waits until they have entered the key.

An environment variable with the same name takes precedence, which suits CI.

### `scipatch.lock`

The exact packages a tool was tested with, for every platform, written by
`scipatch freeze` after `scipatch check` passes:

- the platform you tested on gets the packages of that working environment;
- Linux (x86-64 and ARM), macOS (Apple silicon and Intel), and Windows are
  resolved without installing anything: conda packages by a dry-run solve for
  that platform, PyPI packages by uv using only prebuilt wheels (pure-Python
  packages published only as source are allowed). The tested versions are kept
  wherever they exist; otherwise the lock says which versions differ;
- a platform where a package does not exist, or would have to be compiled, is
  marked unavailable with the reason, e.g. "conda-forge has no Windows build of
  crest =2.12".

Builds install exactly the locked conda packages and use the locked PyPI
versions as constraints. On a platform marked unavailable, `scipatch add` stops at
once with the reason, `scipatch catalog` shows the tool as not installable there.
`scipatch info` lists where a tool runs. On Windows, a tool with
Linux packages but no Windows ones is built and run inside WSL with its locked
Linux packages; write such tools so they need nothing
but their environment and the files they are given.

The lock also records how much disk space the environment took on the
platform it was tested on, so people and agents know the download size before
installing.

The lock records a hash of the environment section; when you change the
requested packages, it is out of date and is not applied until you test and
freeze again. Freeze every tool you share, so others build what you tested.
Older packages may still have a `requirements.lock` (one list of PyPI versions);
it is applied as before until the next `scipatch freeze` replaces it.

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
| `resources` | What this function needs, if it differs from the tool (see `resources` below). |
| `params.<name>` | `kind`, `unit`, `description` for a parameter. |
| `outputs.<key>` | `kind`, `unit`, `description` for a key of the returned dict. |

**Kinds** name what a value *is*, so agents can chain tools: `structure` (CIF,
POSCAR, extended XYZ path), `molecule` (SMILES or SDF/MOL/XYZ path),
`trajectory`, `spectrum`, `table`, `image`, `file`, `directory`. Relative paths
in parameters with a file-like kind are resolved from the caller's folder.

### `resources`

What the tool needs from the computer. Leave it out when a CPU, a little memory,
and no internet connection are enough.

```yaml
resources:
  gpu: optional            # none (default) | optional (faster with one) | required
  gpu_types: [cuda]        # cuda (NVIDIA, the default) and/or mps (Apple silicon)
  gpu_memory_gb: 16        # GPU memory it needs
  memory_gb: 8             # memory (RAM) recommended for typical inputs
  network: false           # true if it calls a web service
functions:
  train:
    resources: {gpu: required, memory_gb: 32}   # a function can need more (or less)
```

SciPatch compares this with the computer (`scipatch doctor` shows what it found):

- A tool that **requires** a GPU the computer lacks is not installed (catalogs
  and agents see why); a function that requires one is refused with the reason
  before it starts, and its golden tests are skipped there.
- Short memory, a GPU smaller than needed, and needing the internet are shown
  to agents and people (`describe_tool`, `scipatch info`) before they run anything.
- Each run is told which device to use in the environment variable
  `SCIPATCH_DEVICE`: `cuda`, `mps`, or `cpu`. Tools that require a GPU always get
  one; tools that are only faster with one use it when the user allows it
  (`scipatch config gpu on`), and the CPU otherwise. Golden tests run on the CPU
  unless the tool requires a GPU, so their values stay reproducible.

### `validity`

Plain text: the training data or level of theory, supported elements or
chemistries, known failure modes. Agents are instructed to respect it and repeat
the relevant caveats.

### `maturity`

How much evidence backs the tool's results. Agents see the level with the
evidence behind it (`describe_tool`, `scipatch info`); search ranks
better-established tools first among similar matches; and experimental tools
carry a caution telling agents to say so and cross-check key numbers with
better-established tools.

| Level | Meaning | Needs |
|---|---|---|
| `established` | Mature, widely used community code | `source.paper` (its publication or citable software record) and a golden test with `against: independent` or `against: exact` |
| `published` | Research code from a publication, less widely tested | `source.paper` and a golden test with `against` set to `independent`, `exact`, `paper`, or `upstream-tests` |
| `experimental` (default) | Little outside validation, e.g. a small project without a publication | nothing |

The manifest is refused when the evidence for its level is missing. Whether code
is "widely used" cannot be checked automatically: whoever adds a tool to a
catalog decides, and `established` should not be claimed for a project only its
authors use. On their own computer, users can lower a level (never raise it)
with `scipatch maturity <tool> <level>`.

### `golden`

| Field | Meaning |
|---|---|
| `name` | What the test shows. |
| `function`, `args` | The call. Relative file paths are resolved from the package folder; paths starting with `source/` refer to the tool's source checkout (`source.repo`), so tests can use the project's own example files wherever the checkout lives. |
| `expect` | Checks, keyed by a dotted path into the result (`energy`, `forces.0.2`; `.` is the whole result). |
| `reference` | Where the expected values come from. Never invent one. |
| `against` | The kind of reference: `independent` (experiment, a reference database, or another program), `paper` (the tool's own publication), `upstream-tests` (the project's own test suite or documentation), `exact` (an analytical result, a sum or conservation rule, symmetry, or a count), or `regression` (output of this tool or its example, which catches changes but not errors). It backs the tool's `maturity` and is summarized for agents. Not used with `raises`. |
| `timeout` | Seconds (default 900). |
| `requires` | Secrets the test needs, e.g. `[MP_API_KEY]`. Without them the test is skipped, not failed, so the tool still installs. |
| `raises` | Text the call's error message must contain: the test passes only if the call *fails* this way. Use it to prove that inputs outside the tool's validity are refused, e.g. `raises: "no reliable parameters for Fe"`. |
| `quick` | Also run when the tool is installed. Mark one fast test (seconds) that exercises the main computation; `scipatch add` runs only the quick tests (all of them if none is marked), while `scipatch check`, `scipatch test`, and `scipatch add --all-tests` run every test. |
| `platforms` | Run only on these platforms (e.g. `[linux-64, osx-arm64, osx-64]`), for tests that need a package some platform lacks. Elsewhere the test is skipped. Pair it with a test for the other platforms that checks the function explains what is missing. |

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

Golden tests run on every build. A failing test stops `scipatch add` unless you pass
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
  return their relative paths; SciPatch returns them as absolute paths.
- Raise `ValueError` with a clear message for bad input. The message is shown
  to the user and the agent.
- A `device` parameter should default to `"auto"`, meaning the device SciPatch
  chose: `os.environ.get("SCIPATCH_DEVICE", "cpu")`. Then the user's GPU setting
  applies, and golden tests stay on the CPU.
- No prompts, windows, or `plt.show()`. Printing is fine; it goes to the run's
  log. While a long job runs, its latest printed lines are shown to agents and
  users (`latest_output`), so print progress such as `step 120/5000`.

## `SKILL.md`

Usage notes in the [Agent Skills](https://agentskills.io/specification) format.
SciPatch combines them with the manifest and function signatures into the skill
`scipatch-<name>` that it installs for your agents.

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
signatures in the body; SciPatch adds them.
