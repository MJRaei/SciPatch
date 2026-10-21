# Concepts

Motel solves one problem: research code is valuable but scattered. Each
repository needs its own setup, has its own interface, and knows nothing about
the others, so as your collection grows it becomes harder to use, not easier.

Motel's answer has four parts.

## 1. A tool package: one repository, made reliable

A **tool package** is a small folder that describes how to use one piece of
research code:

```text
chgnet/
├── motel.yaml        manifest: source, environment, functions, validity, golden tests
├── api.py            typed Python functions: the tool's capabilities
├── SKILL.md          usage notes for AI agents
├── patches/          fixes to the upstream code, re-applied on every rebuild
└── tests/data/       small input files for golden tests
```

The package does not contain the research code itself. It **pins** it (a git
URL plus an exact commit), so the tool can be rebuilt identically anywhere. Fixes
needed to make the code work are kept as patch files rather than lost in a local
checkout.

`api.py` is the only file that touches the research code. It exposes a handful
of functions with type hints and docstrings. Motel reads those to generate
everything else: the command line, the MCP interface, the dashboard forms, and
the agent skill. All of them come from one source of truth, so they cannot drift
apart.

**Golden tests** call functions with known inputs and check the outputs,
ideally against a number published in the paper. They run every time the tool
is built, so "installed" means "reproduces known results", not just "imports
without errors". The manifest's **validity** text says when results should not
be trusted.

## 2. Rooms: isolated environments

Every tool gets its own environment, built with uv (PyPI packages) or conda
(conda-forge packages). Tools that need different versions of NumPy, PyTorch, or
anything else live side by side. Conda environments are created with your own
micromamba or mamba if you have one, otherwise with a micromamba that Motel
downloads once, checks against a pinned checksum, and keeps in `~/.motel/bin`;
your own conda installation and settings are never touched. Set
`MOTEL_SYSTEM_CONDA=1` to use your conda instead. Only the channels in the tool's
manifest are used, so a tool's environment is the same on every computer.

Each tool's `motel.lock` pins its packages for Linux, macOS, and Windows, and says
where it cannot be installed. On Windows, a tool that exists only for Linux is
built and run inside WSL (the Windows Subsystem for Linux) with exactly its
locked Linux packages: the environment lives on the Linux side, and the tool
reads and writes files on Windows through `/mnt/c/...`. Paths are translated both
ways, and secrets reach the Linux process as environment variables, never on a
command line.

Motel never imports tool code into its own process. To call a function it starts
the tool's own Python interpreter with a tiny standard-library-only *shim*, which
imports `api.py`, calls the function, and writes the result as JSON. This is why
one Motel can host tools that would never coexist in one environment, including
tools that need old Python versions (3.8+).

```text
Motel process                         tool environment (its own Python)
─────────────                         ─────────────────────────────────
run_tool("chgnet", "relax", {...})
  └─ writes request.json ───────────► python -I shim.py call request.json
                                        └─ import api; api.relax(...)
     reads response.json ◄────────────  └─ writes response.json
```

Each run happens in its own folder (`~/.motel/runs/<run-id>/`), which holds the
output files, the tool's printed output (`stdout.log`, `stderr.log`), and the
request and response.

## 3. One front desk: the MCP gateway

AI apps connect to Motel through the Model Context Protocol (MCP), the open
standard for giving AI models tools. Motel runs **one** MCP server for all your
tools, with a fixed set of operations:

| Operation | Purpose |
|---|---|
| `search_history` | find earlier runs (check before computing again) |
| `find_tools` | search all functions by plain-language description; also suggests matching tools from catalogs that are not installed yet |
| `list_tools` | everything installed |
| `describe_tool` | parameters with units, usage notes, validity, citation |
| `install_tool` | install a suggested tool, after the user agrees (runs in the background; call again until it is ready) |
| `run_tool` | run a function; long jobs continue in the background |
| `get_run`, `cancel_run` | collect or stop a background run |

Registering every function as its own MCP tool would flood the model's context
as your collection grows. With a search-then-describe-then-run pattern, ten
tools and three hundred tools cost the same.

The same operations are available on the command line (`motel find`,
`motel info`, `motel run`, `motel runs`) with `--json` output, and in the
dashboard (`motel ui`).

**Skills** complement MCP. Motel installs Agent Skills (`SKILL.md` files) into
the apps that support them: one that teaches the workflow above, one per tool
(generated from its manifest and functions), and `motel-onboard`, which teaches
a coding agent how to turn a repository into a tool package. Agents read only
each skill's one-line description until a task needs it, so many skills cost
little context.

## 4. A memory: the run history

Every run is recorded in `~/.motel/motel.db`: the tool and its version, the
source commit, the exact arguments, the result, output files, timing, and any
error. This gives you:

- **Provenance**: any number can be traced to the exact code and inputs that
  produced it.
- **Caching**: an identical call (same tool build, same arguments, same input
  file *contents*) is answered from the history instantly.
- **Recall**: "what did I compute last week?" is a search, not a re-run.

## Long-running jobs

All runs start in the background in their own process group. A caller decides
how long to wait. If the run is still going when the wait ends, it keeps running
and can be collected later by its run id. A quick calculation and a multi-hour
simulation therefore work the same way, and an AI app's request never times out
while a job runs. Functions marked `long_running` in the manifest always return
immediately with a run id.

## Onboarding: where AI agents fit

Turning arbitrary research code into a reliable tool needs judgment: which
capabilities matter, why an install fails, which published number to reproduce.
Motel leaves those decisions to a coding agent (Claude Code, Codex, Gemini CLI)
guided by the `motel-onboard` skill. Motel itself provides the deterministic
parts: scaffolding (`motel new`), building and checking (`motel check`),
recording fixes (`motel patch save`), and installing (`motel add`). See
[Turning a repository into a tool](onboarding.md).

## Design principles

- **Plain files over hidden state.** Tools are folders, state is JSON, history is
  SQLite. You can inspect, back up, or share all of it.
- **Reproducible by default.** Pinned commits, recorded patches, golden tests,
  and per-run provenance.
- **Honest results.** Validity limits travel with every tool, and agents are
  instructed to report them.
- **Safe with your files.** Motel edits only its own entries in apps'
  configuration files, backs them up first, and never touches skills it did not
  create.
