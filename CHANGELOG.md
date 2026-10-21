# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Progress for running jobs: `get_run`, `motel runs show`, and the dashboard show
  the elapsed time and the tool's latest printed lines (`latest_output`). Tool
  output is now line-buffered, so it appears while the job runs.
- Example `pymatgen-diffusion`: diffusivity, conductivity, and Arrhenius analysis
  of MD trajectories, with golden tests reproducing the upstream test suite.
- CHGNet example: MD prints progress and reports `n_frames` and
  `frame_interval_fs`; guidance on `fmax` for cell relaxation.

### Fixed

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
