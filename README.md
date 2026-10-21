# Motel

**Turn research code into tools that any AI agent can find, run, and remember.**

You find a promising paper with code. Setting it up takes an afternoon. A month
later you set up another one, and another, until you have a dozen separate
installations that know nothing about each other, each with its own quirks,
interface, and forgotten fixes.

Motel gives every research repository its own *room*, an isolated environment
where it works exactly as tested, and checks them all in at **one front desk**.
Your AI assistant (Claude, Codex, Gemini, Cursor, ...) can then find the right
tool for a question, run it, combine it with others, and remember every result.
Motel is built for science, with materials science and chemistry first.

```text
  You: "Is this structure stable? What's its lattice constant?"
        │
        ▼
  Your AI app (Claude Desktop, Claude Code, Codex, Gemini CLI, Cursor)
        │  finds, reads, and runs tools through one connection
        ▼
  ┌─────────────────────── Motel ────────────────────────┐
  │  front desk:  search · descriptions · run · results   │
  │                                                       │
  │  room: ml-potentials   room: gpaw   room: rdkit  ...  │  ← each with its own environment
  │                                                       │
  │  guest book:  every run, its inputs, outputs, and     │  ← memory and provenance
  │               the exact tool version                  │
  └───────────────────────────────────────────────────────┘
```

## What you get

- **One place for all your research tools.** Each tool runs in its own
  environment, so tools with conflicting requirements live side by side.
- **Works with every major AI app.** One command connects Claude Desktop, Claude
  Code, Codex, Gemini CLI, or Cursor, through the Model Context Protocol (MCP)
  and the Agent Skills standard (`SKILL.md`).
- **Repositories become tools with your AI agent's help.** `motel onboard <url>`
  hands a repository to your coding agent with step-by-step instructions: install
  it, wrap its key capabilities, and reproduce a number from the paper.
- **Results you can trust and cite.** Each tool carries golden tests that check
  it reproduces known results, plus stated validity limits and citations. Every
  run records the exact tool version and source commit.
- **Mature tools first.** Each tool is *established*, *published*, or
  *experimental*, backed by evidence Motel checks. Agents prefer established
  tools and are told to cross-check results from experimental ones, such as a
  small lab's code without a paper.
- **A memory.** Ask about something you computed last week; identical calls are
  answered instantly from the history instead of being recomputed.
- **No terminal required for daily use.** `motel ui` opens a dashboard with a
  form for every tool, generated automatically.

## Quick start

**1. Install** (macOS or Linux; Windows: see [Getting started](docs/getting-started.md)).
From a copy of this repository:

```bash
./install.sh
```

The script installs [uv](https://docs.astral.sh/uv/) if needed (it manages
Python for you), installs Motel, and starts the guided setup.

**2. Set up.** If the installer didn't already start it, run:

```bash
motel setup
```

It checks your computer, connects the AI apps it finds, and offers to install
an example tool. Restart your AI app afterwards.

**3. Ask.** In your AI app, try:

> *Use my Motel tools to find the equilibrium lattice constant and bulk modulus of copper.*

The assistant finds the `ase-emt` tool, reads its instructions, runs it, and
reports the result with its limitations and citation.

## Adding tools

| You have | Run | What happens |
|---|---|---|
| A featured tool | `motel add ase-emt`, or just ask your AI app | Installs and verifies it (`motel catalog` lists them); AI apps suggest and install catalog tools on first use, after asking you |
| A collection of tools | `motel catalog add <git-url>`, then `motel add <name>` | Adds a lab's or community collection; install its tools by name |
| A research repository | `motel onboard https://github.com/org/repo --paper <doi>` | Your coding agent turns it into a tool, guided by Motel |
| A ready tool package | `motel add ./folder` or `motel add <git-url>` | Installs and verifies it |

Built in: **ase-emt** (fast approximate simulations of metals) and
**rdkit-descriptors** (molecular properties from SMILES). The [tool
collection](tools/README.md) adds, for materials, **ML potentials** (Orb, MACE,
CHGNet, and MatGL in one tool: relaxation, MD, elastic and thermal properties,
model comparison), **GPAW** and **Quantum ESPRESSO** (DFT for crystals),
**LAMMPS** (classical MD), **OVITO** (crystal structure, defects, dislocations),
**phonopy** (phonons and stability), **phono3py** (thermal conductivity),
**pymatgen-diffusion** (ion transport from MD), **pymatgen-structure**
(symmetry, supercells, XRD), **synthesis recipes** (precursors and temperatures
from papers, routes for new materials), **doping knowledge** (what papers report
about doping layered materials), and the **Materials Project** database; and for
chemistry, **PySCF** (ab initio quantum chemistry), **xTB** (fast semiempirical
quantum chemistry), **CREST** (conformers, protomers, tautomers), **RDKit**
(cheminformatics), **Open Babel** (chemical file formats, force fields),
**OpenMM** (molecular dynamics), **MDAnalysis** (trajectory analysis), **NMR
mixtures** (mole fractions from crude 1H NMR), **AutoDock Vina** (docking),
**peptide assembly** (self-assembly conditions from similar peptides), and
**Cantera** (combustion chemistry and thermodynamics). Every tool reproduces
published or upstream-tested values before it installs.

Onboarding needs a coding agent, such as [Claude Code](https://claude.com/claude-code),
Codex, or Gemini CLI. See [Turning a repository into a tool](docs/onboarding.md),
and [tools](tools/README.md) for real repositories turned into tools (the
universal ML potentials, and pymatgen-analysis-diffusion for diffusivities
and activation energies), with golden tests that reproduce the values in their
own test suites.

## Using tools without an AI app

```bash
motel ui                                         # dashboard in your browser
motel find "lattice constant"                    # search all tools
motel info ase-emt                               # parameters, notes, limits, citation
motel run ase-emt equation_of_state element=Cu   # run a function
motel runs                                       # history of runs
```

Add `--json` to any of these for machine-readable output (agents use this).

## Learn more

- [Getting started](docs/getting-started.md): installation on each system, and connecting each app
- [Concepts](docs/concepts.md): how Motel works, and why
- [Turning a repository into a tool](docs/onboarding.md)
- [Tool package format](docs/tool-format.md): `motel.yaml`, `api.py`, golden tests, patches
- [Connecting AI apps](docs/connecting-apps.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Contributing](CONTRIBUTING.md)

## Safety

Onboarding and installing tools runs code from the repositories you choose, on
your computer, just like installing them by hand. Only add code you trust.
Motel's servers listen only on your own computer (`127.0.0.1`), and the dashboard
requires a per-session token. API keys are stored only on your computer, given
only to the tools that declare them, and entered on a local page rather than in
the chat, so they never reach the AI model. Motel only ever edits its own entry in your AI
apps' configuration files, and makes a backup first.

## Status

Motel is early (version 0.1). Environments are built with uv or conda; Docker
and HPC (Slurm) backends are planned. Feedback and contributions are welcome.

## License

[MIT](LICENSE)
