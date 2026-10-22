# Contributing to SciPatch

Thanks for helping. This guide covers the development setup, the project
layout, and the conventions the code follows.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and git.

```bash
uv sync                          # creates .venv with SciPatch and the dev tools
uv run scipatch --help           # run the CLI from your checkout
uv run pre-commit install        # optional: run the checks on every commit
```

## Checks

```bash
uv run pytest                    # all tests (about 15 s)
uv run pytest -m "not integration"   # fast tests only, no environments built
uv run ruff check src tests      # lint
uv run ruff format src tests     # format
uv run mypy                      # strict type checking
```

Every pull request must pass all four; CI runs them on Linux and macOS with
Python 3.11 to 3.13.

Tests never touch your real configuration: each one gets its own temporary
`HOME` and `SCIPATCH_HOME`. Integration tests build real environments with uv from
packages that use only the standard library, so they also work offline once uv
has Python available.

## Project layout

```text
src/scipatch/
├── app.py            SciPatch facade: the one object behind the CLI, MCP, and dashboard
├── manifest.py       scipatch.yaml models and validation
├── registry.py       installed tools (folders) and their build state
├── installer.py      add / rebuild / check / test / patch
├── build.py          source → environment → introspection → golden tests
├── source.py         git checkouts and patches
├── environments/     uv and conda backends
├── runtime/
│   ├── shim.py       runs inside tool environments: stdlib only, Python 3.8+
│   ├── executor.py   launches the shim; process management
│   └── results.py    output paths and files
├── runs.py           run lifecycle: start, wait, cancel, cache
├── history.py        SQLite run history
├── search.py         BM25 search over tool functions
├── golden.py         golden-test matchers
├── skills.py         SKILL.md generation and syncing
├── clients.py        AI app integrations (config files)
├── onboarding.py     scaffolding and agent hand-off
├── gateway.py        MCP server
├── ui/               local dashboard
├── views.py          JSON shapes shared by MCP, CLI --json, and the dashboard
├── cli/              Typer commands
├── assets/           bundled skills and templates
└── catalog/          featured tool packages
```

## Conventions

- **Errors are for people.** Raise a `SciPatchError` subclass with a message that
  says what happened and a `hint` that says what to do. The CLI, MCP gateway, and
  dashboard all show both. Never show a traceback for an anticipated problem.
- **One source of truth.** Function signatures come from `api.py`; JSON views
  come from `views.py`; operations go through `app.SciPatch`. Interfaces stay thin.
- **The shim stays portable.** `runtime/shim.py` runs inside arbitrary tool
  environments: standard library only, Python 3.8 syntax at runtime (annotations
  are fine; they are never evaluated). `tests/test_integration.py` checks this
  against real 3.8 and 3.9 interpreters.
- **Never damage user files.** Edit only SciPatch's own entries in configuration
  files, back them up first, write atomically, and leave anything you cannot
  parse untouched.
- **Typed and documented.** `mypy --strict` passes; public functions have
  docstrings; comments explain *why*, not *what*.

## Adding an AI app

Subclass `AppIntegration` in `clients.py` (or `JsonMcpApp` if the app stores
MCP servers under `mcpServers` in a JSON file), add it to `APPS`, and add a test
in `tests/test_clients.py` that checks other settings in the file survive.

## Adding an environment backend

Subclass `EnvironmentBackend` in `environments/`, register it in
`environments/__init__.py`, and extend `Environment.manager` in `manifest.py`.
The backend only has to create an environment with a Python interpreter; the
runtime shim does the rest.

## Adding a tool to the collection

Tools live in [`tools/`](tools/README.md), one folder per tool. A new tool needs:

- golden tests whose `reference` says exactly where each expected value comes
  from (the paper, or the upstream test suite), and that pass with
  `scipatch check tools/<name> --clean`;
- a `validity` statement, a citation, and a license;
- pinned versions: run `scipatch freeze tools/<name>` after a passing build.

The two built-in tools in `src/scipatch/catalog/` ship inside SciPatch itself, so the
first-run demo needs nothing else; keep them small.

## Releasing

1. Update the version in `pyproject.toml` and add a section to `CHANGELOG.md`.
2. `uv build`, then check the wheel contains `assets/`, `catalog/`, and `ui/static/`.
3. Tag the release (`git tag v0.1.0`) and publish (`uv publish`).
