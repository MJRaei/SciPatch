# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Tool collection in `tools/`: ML potentials, phonopy, phono3py,
  pymatgen-diffusion, pymatgen-structure, Materials Project, GPAW, Quantum
  ESPRESSO, xTB, CREST, PySCF, RDKit, OpenMM, Cantera, LAMMPS, Open Babel,
  MDAnalysis, OVITO, AutoDock Vina, synthesis recipes (from the SKY hackathon
  agent), NMR mixture quantification (from the MixSense hackathon project),
  peptide self-assembly conditions (from peptide-agent), doping of layered
  materials from papers (from ARIA), structural analogs in the Materials Project
  (from mp-property-analogies), pycalphad, PyBaMM, RASPA3, AiZynthFinder,
  CoolProp, pvlib, Reaktoro, PROPKA, PyXtal, and thermo, each with golden tests
  against upstream test suites, reference databases, or established physics, and
  a CI workflow that rebuilds changed tools from scratch.
- Maturity levels: every tool is `established`, `published`, or `experimental`
  (the default), declared as `maturity` in `motel.yaml`, and refused when the
  evidence is missing (a publication, and golden tests whose new `against`
  field says what they are checked against: independent references, the paper,
  upstream tests, exact results, or the tool's own earlier output). Agents see
  the level with a one-line summary of the evidence in `find_tools`,
  `describe_tool`, and run results; search ranks better-established tools first
  among similar matches; experimental tools carry a caution that names
  better-established tools for cross-checks, also in their skills. `motel list`,
  `motel info`, `motel catalog`, and the dashboard show the level, and
  `motel maturity <tool> <level>` lowers it on your computer.
- Hardware needs: tools declare `resources` in `motel.yaml` (a GPU that is
  optional or required, GPU memory, memory, an internet connection), per
  function where they differ. Motel detects the computer's cores, memory, and
  GPUs (NVIDIA through `nvidia-smi`, Apple silicon), refuses to install a tool
  that requires a missing GPU and refuses such runs with the reason, and shows
  agents and people how each tool's needs fit this computer (`describe_tool`,
  `find_tools`, `motel info`, skills). Each run gets `MOTEL_DEVICE` (`cuda`,
  `mps`, or `cpu`); tools that are only faster on a GPU use it when the user
  allows it with the new `motel config gpu on`, and golden tests stay on the
  CPU. `motel doctor` shows the computer, and `motel.lock` records the
  environment's size, shown before installing.
- Onboarding: the agent proposes a maturity level for the user to confirm, says
  what each golden test is checked against, and reports anything in the code a
  user should know before running it (network access, writes outside the run
  folder, unexpected programs, obfuscated code).
- Catalogs: `motel catalog add <git-url>` adds a collection of tools; install
  them by name with `motel add <name>`.
- `motel freeze` pins the exact packages a tool was tested with and resolves it
  for every platform (Linux x86-64 and ARM, macOS Apple silicon and Intel,
  Windows) without installing anything, into `motel.lock`: exact conda packages
  and PyPI versions per platform, or the reason the tool cannot be installed
  there (e.g. "conda-forge has no Windows build of crest =2.12"). Builds install
  exactly the locked packages; on an unsupported platform `motel add` stops at
  once with the reason. `motel info` lists where a tool runs, and `motel catalog`
  marks tools that cannot be installed on this computer.
- Package entries, conda ones included, can carry PEP 508 environment markers
  (`"ambertools=23.3; sys_platform != 'win32'"`) to differ between platforms;
  `environment.platforms` restricts a tool to some platforms, and golden tests can
  run only on some (`platforms:`).
- Tools CI runs on Linux, macOS, and Windows, choosing for each tool the runners
  its `motel.lock` supports; Motel's own Windows tests are now required.
- On Windows, tools that exist only for Linux (CREST, GPAW, LAMMPS, Quantum
  ESPRESSO) are built and run inside WSL, as their own documentation recommends:
  the environment is created on the Linux side from exactly the locked Linux
  packages (with a checked micromamba), calls go through the usual shim with
  paths translated both ways and variables passed through `WSLENV` (secrets never
  on a command line), and cancelling a run stops its Linux processes. Without
  WSL, `motel add` explains how to set it up; `motel doctor`, `motel info`, and
  `motel catalog` show WSL support, and CI checks these tools on Windows in WSL.
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
- Install on first use: `find_tools` (and `motel find`) also suggest matching
  tools from catalogs that are not installed yet, with whether they can be
  installed on this computer; the new MCP operation `install_tool` installs one
  in the background (after the user agrees) and reports progress until it is
  ready, so users never need the command line to get a tool. `describe_tool` and
  `run_tool` on a catalog tool that is not installed say how to install it.
- Faster installs: `motel add` and `motel rebuild` run only the golden tests
  marked `quick: true` (seconds), or all of them if a tool marks none; the
  status says how many more `motel test` runs. `--all-tests` runs every test, as
  `motel check` and CI do. Every tool in `tools/` marks one quick test (OpenMM's
  install check drops from about 8 minutes to under a minute).
- Arguments are checked against each function's types before a run starts.
- Progress for running jobs: `get_run`, `motel runs show`, and the dashboard show
  the elapsed time and the tool's latest printed lines (`latest_output`). Tool
  output is now line-buffered, so it appears while the job runs.
- Example `pymatgen-diffusion`: diffusivity, conductivity, and Arrhenius analysis
  of MD trajectories, with golden tests reproducing the upstream test suite.
- ML potentials: MD prints progress and reports `n_frames` and
  `frame_interval_fs`; guidance on `fmax` for cell relaxation.

### Changed

- CHGNet, MACE, and matcalc are merged into one `ml-potentials` tool: Orb-v3
  (new, the default), MACE-MP/MPA, MACE-OFF, CHGNet, and MatGL's TensorNet and
  M3GNet share one environment and the same functions (energies, relaxation, MD,
  elastic constants, equation of state, thermal properties, formation energies),
  and `compare_models` relaxes a crystal with four model families to show how
  far they agree. Only models whose packages install together on Linux, macOS,
  and Windows are included: SevenNet and MatterSim need e3nn 0.5 (MACE pins
  0.4.4), and FAIRChem's PyTorch has no macOS (Apple silicon) build.
- Onboarding covers repositories with a user interface (Gradio, Streamlit, Dash,
  Flask, desktop programs): the tool calls the computation behind the
  interface, with its form fields as typed parameters and its plots, tables,
  and viewers as files and values, and leaves the interface packages out.
- `motel.lock` replaces `requirements.lock`; an existing `requirements.lock` is
  still applied until the next `motel freeze`.
- Tools on Windows: CHGNet (ML potentials, phonopy) installs from its prebuilt
  PyPI wheels (its source build needs a compiler); OVITO uses Python 3.13 (it
  has no Windows wheels for 3.12); OpenMM simulates biomolecules and water on
  Windows and explains that small molecules need AmberTools, which has no
  Windows build; AutoDock Vina runs the `vina` program on every platform (its
  Python bindings are Linux and macOS only), on Windows the official release's
  executable, checked at install.

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
