---
name: motel-onboard
description: >-
  Turn a scientific code repository (and its paper) into a Motel tool package that
  people and AI agents can run reliably: an isolated environment, typed functions,
  golden tests that reproduce published numbers, and usage notes. Use when the user
  wants to set up, wrap, onboard, package, or add a GitHub/GitLab repository or a
  paper's code to Motel, or when a folder contains ONBOARDING.md.
---

# Onboard a repository into Motel

You are turning research code into a **tool package**: a folder containing

| File | Purpose |
|---|---|
| `motel.yaml` | manifest: source, environment, exposed functions, validity, golden tests |
| `api.py` | typed, documented Python functions: the tool's capabilities |
| `SKILL.md` | usage notes for agents (Motel adds function signatures itself) |
| `patches/` | fixes to the upstream code, re-applied on every rebuild |
| `tests/data/` | small input files for golden tests |

Motel builds an isolated environment from the manifest, runs the functions in it,
exposes them to every connected agent, and records every run.

**Where to work:** the current folder if it contains `ONBOARDING.md` (the upstream
code is in `source/`). Otherwise create a package with
`motel new <name> --repo <url> [--paper <doi>]` and work in that folder.

## Principles

- **Few, useful capabilities.** Expose the 1 to 5 things a scientist wants from this
  code, not its internal API.
- **Reproduce, don't assume.** At least one golden test must reproduce a number
  from the paper or from the repository's own documented example.
- **Never lose a fix.** Every edit to `source/` becomes a patch
  (`motel patch save . -m "why"`); rebuilds start from the pinned commit.
- **Be honest about limits.** `validity` says when results must not be trusted.
- **Ask about science, decide about plumbing.** Ask the user before choosing a
  model, method, functional, or dataset. Fix installation problems yourself.

## Steps

### 1. Understand the code

Read the README, the paper's abstract and methods (if available), examples,
notebooks, tests, and command-line entry points in `source/`. Then tell the user,
briefly:

- what the code computes and for which systems;
- the 1 to 5 functions you plan to expose (name, inputs, outputs, units);
- heavy requirements: GPU, model weights, licensed software, compiled code, long
  runtimes, credentials.

Wait for confirmation if anything is ambiguous.

### 2. Make the environment build

Edit `environment` in `motel.yaml` (see [references/manifest.md](references/manifest.md)):

- `manager: uv` for PyPI-only dependencies; `manager: conda` for conda-forge
  binaries (OpenMM, xtb, RDKit builds with extras, ...).
- `python`: a version the repository supports.
- `source.install: true` installs the repository itself (editable). If it is not
  installable, set it to `false` and add what it needs to `packages`; `api.py`
  can then import from `source/` by adding it to `sys.path`.
- Model weights or data → `post_install` commands.
- API keys → list their names under `environment.secrets` (e.g. `[MP_API_KEY]`)
  and say in the usage notes where to get one; the user stores them with
  `motel secret set NAME`. Never write a key into a file. Golden tests that need
  a key declare it with `requires: [NAME]`.

Run `motel check . --skip-tests` and iterate until it builds. On failure, read the
error and `.motel/build.log`. Typical fixes:

| Symptom | Fix |
|---|---|
| compiler / missing system library | switch to `manager: conda` and add the library |
| version conflict (NumPy 2, torch, CUDA) | pin it in `environment.packages` |
| bug in the upstream code | edit `source/`, then `motel patch save . -m "fix ..."` |
| `ImportError` in `api.py` | add the package to `environment.packages` |

### 3. Reproduce something before wrapping

Run the repository's own example inside the environment, e.g.

```bash
motel exec . -- python source/examples/quickstart.py
```

Find one number the paper reports (a table entry, an energy, an error metric) or
the README prints, and reproduce it. This becomes the golden test. The
repository's own test suite is often the best source: look for asserted values
such as `pytest.approx(-7.36769)` next to an example input file. If those tests
use preprocessed data rather than the input your function takes (say, saved
displacements instead of a trajectory), convert that data into your input
format once, keep the conversion script in `tests/data/`, and reproduce the
same numbers through your function. If nothing is
reproducible on this machine (for example, it needs a cluster), say so and
reproduce the documented example instead.

### 4. Write `api.py`

Follow [references/api-guidelines.md](references/api-guidelines.md). Essentials:

- One public function per capability; helpers start with `_`.
- Type hints on every parameter and the return value; a one-line summary and an
  `Args:` section with **units**.
- Inputs are plain values and file paths (`str`). Outputs are JSON-friendly dicts
  with units in key names (`energy_ev_per_atom`). Large outputs go to files in the
  current directory, returned as paths.
- Declare shared data kinds in `motel.yaml` so agents can chain tools:
  `functions.<fn>.params.<param>.kind` is one of `structure`, `molecule`,
  `trajectory`, `spectrum`, `table`, `image`, `file`, `directory`.
- Cache loaded models with `functools.lru_cache`. No prompts, GUIs, or plot
  windows (save figures to files).
- Mark functions slower than about a minute `long_running: true`.

Run `motel check .` after each change. It lists every function with its
signature, plus warnings for missing type hints or docs: fix them all.

### 5. Add golden tests

```yaml
golden:
  - name: reproduces the published formation energy of the test structure
    function: predict
    args: {structure: tests/data/example.cif}
    expect:
      formation_energy_ev_per_atom: {approx: <published value>, abs: <tolerance>}
    reference: <exact source, e.g. "Paper, Table 2, row 3">
```

Copy the input files into `tests/data/` (golden tests must not point into
`source/`, which lives elsewhere once the tool is installed). Set the tolerance
from the precision the paper reports; explain unusual tolerances in `reference`. Never invent a
reference: if a number comes from running the documented example (not from the
paper), say exactly that. Matchers: `approx`
(with `rel`/`abs`), `equals`, `min`, `max`, `contains`, `length`, `exists`, `type`.

### 6. Document

- `motel.yaml`: `summary`, `domains`, `tags`, `validity`, `source.citation`,
  `source.license`, `source.paper`.
- `SKILL.md` frontmatter `description`: what the tool does **and when to use it**,
  with the words a user would say. Agents choose tools by this text.
- `SKILL.md` body: workflows (including chaining with other tools), parameter
  advice, interpretation of outputs, pitfalls. Don't repeat the signatures.

### 7. Verify and install

```bash
motel freeze .          # pin the exact package versions you tested (requirements.lock)
motel check . --clean   # rebuild from the pinned repo + patches + lock; golden tests must pass
motel add .             # install into Motel (use --link while still iterating)
motel run <name> <function> key=value --json
```

Finish with a short report to the user: the functions exposed, golden test
results, patches and why they were needed, and the caveats.

## Command reference

| Command | Purpose |
|---|---|
| `motel new NAME --repo URL [--ref REF] [--paper DOI]` | scaffold a package |
| `motel check DIR [--clean] [--skip-tests]` | build, inspect functions, run golden tests |
| `motel exec DIR -- CMD ...` | run a command inside the package's environment |
| `motel patch save DIR -m "why"` | save edits in `DIR/source` as a patch file |
| `motel freeze DIR` | pin tested package versions into `requirements.lock` |
| `motel add DIR [--link] [--force]` | install the package |
| `motel info NAME` | what agents will see |
| `motel run NAME FUNCTION k=v --json` | try a function |

## Done when

- [ ] `motel check . --clean` passes, including at least one golden test that
      reproduces a published or documented number
- [ ] every exposed function has type hints and documented arguments with units
- [ ] `summary`, `validity`, `citation`, and `license` are filled in
- [ ] the `SKILL.md` description says when to use the tool
- [ ] all edits to `source/` are saved as patches
- [ ] package versions are pinned with `motel freeze .`
- [ ] the tool is installed (`motel add .`) and a test call succeeds
