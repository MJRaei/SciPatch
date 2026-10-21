# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Tool collection in `tools/`: CHGNet, MACE, phonopy, phono3py,
  pymatgen-diffusion, pymatgen-structure, Materials Project, GPAW, Quantum
  ESPRESSO, matcalc, xTB, CREST, PySCF, RDKit, OpenMM, Cantera, LAMMPS, Open
  Babel, MDAnalysis, OVITO, and AutoDock Vina, each with golden tests against
  upstream test suites, reference databases, or established physics, and a CI
  workflow that rebuilds changed tools from scratch.
- Catalogs: `motel catalog add <git-url>` adds a collection of tools; install
  them by name with `motel add <name>`.
- `motel freeze` pins the exact package versions a tool was tested with
  (`requirements.lock`, applied as constraints).
- Secrets for tools that call online services; each tool receives only the
  secrets it declares, which can name what they are and where to get one.
  `motel add` asks for missing keys (hidden), the dashboard has a Keys page, and
  when a run in an AI app needs a missing key, the user enters it on a one-time
  page on their computer, so keys never pass through the chat. Apps that support
  MCP URL elicitation (2025-11-25 and 2026-07-28) open the page themselves and the
  run continues once the key is saved; others show the link. Without a terminal,
  `motel secret set` opens the page in the browser, for agents that use the
  command line.
- conda tools no longer need a working conda: Motel downloads a pinned
  micromamba (checked against its SHA-256) into `~/.motel/bin` the first time a
  conda tool is built, and prefers it to plain conda (`MOTEL_SYSTEM_CONDA=1`
  opts out). `motel doctor` reports which one is used.
- Golden tests can require secrets (skipped when missing) or require a clear
  error (`raises:`) for inputs outside a tool's validity.
- Arguments are checked against each function's types before a run starts.
- Progress for running jobs: `get_run`, `motel runs show`, and the dashboard show
  the elapsed time and the tool's latest printed lines (`latest_output`). Tool
  output is now line-buffered, so it appears while the job runs.
- Example `pymatgen-diffusion`: diffusivity, conductivity, and Arrhenius analysis
  of MD trajectories, with golden tests reproducing the upstream test suite.
- CHGNet example: MD prints progress and reports `n_frames` and
  `frame_interval_fs`; guidance on `fmax` for cell relaxation.

### Fixed

- conda environments use only the channels in the manifest (`--override-channels`),
  so a user's own conda configuration cannot change or slow down a tool's environment.
- Golden tests resolve lists of file paths in their arguments, as runs do.

- Reinstalling from a checkout (`./install.sh`, `uv tool install .`) could reuse a
  stale cached build when only source files changed.

## [0.1.0] - 2026-10-18

First release.

### Added

- Tool package format (`motel.yaml` + `api.py` + `SKILL.md`), with pinned
  sources, replayable patches, per-function settings, shared data kinds, validity
  limits, and golden tests.
- Isolated environments per tool with uv or conda; a stdlib-only runtime shim
  that runs in any environment with Python 3.8+.
- MCP gateway with constant-size discovery tools (`find_tools`,
  `describe_tool`, `run_tool`, `get_run`, `cancel_run`, `search_history`,
  `list_tools`).
- Run history with provenance, result caching by input content, and background
  runs that outlive the request.
- Agent Skills: `motel`, `motel-onboard`, and one generated skill per tool, kept
  in sync for connected apps.
- One-command connection to Claude Desktop, Claude Code, Codex, Cursor, and
  Gemini CLI.
- `motel onboard`: prepares a workspace and hands a repository to a coding agent.
- Local dashboard (`motel ui`) with forms generated from function schemas.
- Featured tools: `ase-emt` (materials) and `rdkit-descriptors` (chemistry).
- Guided setup (`motel setup`), health checks (`motel doctor`), and installers
  for macOS/Linux and Windows.
