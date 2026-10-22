# Getting started

This guide takes you from nothing to asking your AI assistant to run a
scientific tool, in about ten minutes.

## 1. Install SciPatch

SciPatch needs [uv](https://docs.astral.sh/uv/), a small program that installs
Python and keeps each tool in its own environment. The installer sets it up for
you.

### macOS and Linux

Open a terminal in your copy of the SciPatch repository and run:

```bash
./install.sh
```

### Windows (experimental)

Open PowerShell in your copy of the SciPatch repository and run:

```powershell
powershell -ExecutionPolicy ByPass -File install.ps1
```

Most tools run natively on Windows. A few scientific codes have no Windows build
(CREST, GPAW, LAMMPS, Quantum ESPRESSO), and their own documentation recommends
WSL, the Windows Subsystem for Linux; SciPatch runs them there by itself, with the
same Linux packages it tests. To use them, set WSL up once: open PowerShell as
administrator, run `wsl --install`, restart, and finish setting up Ubuntu.
`scipatch doctor` shows whether WSL is ready.

### By hand

If you already use uv:

```bash
uv tool install --python 3.12 /path/to/scipatch     # a folder, a git URL, or "scipatch" from PyPI
uv tool update-shell                               # put 'scipatch' on your PATH
```

Open a **new** terminal afterwards so the `scipatch` command is found.

## 2. Run the guided setup

```bash
scipatch setup
```

The setup:

1. **Checks requirements**: uv and git. Anything missing is shown with the
   command that fixes it. You don't need conda: for tools that use conda
   packages, SciPatch downloads its own micromamba (and checks it) the first time
   one is installed.
2. **Connects your AI apps**: it finds Claude Desktop, Claude Code, Codex,
   Cursor, and Gemini CLI on your computer and asks before connecting each one.
3. **Offers an example tool**: `ase-emt`, which simulates simple metals in
   milliseconds. It is a good way to see everything working.

Then **restart your AI app** (quit Claude Desktop completely and open it again;
start a new session in the others).

## 3. Try it

Ask your assistant:

> *Use my SciPatch tools to find the equilibrium lattice constant and bulk modulus of copper.*

You should see it search SciPatch, read the tool's description, run it, and answer
with a lattice constant near 3.59 Å. It should also mention that EMT is an
approximate method; that comes from the tool's stated validity limits.

Then try the memory:

> *What have I computed with SciPatch today?*

## 4. Add more tools

You don't have to install tools in advance. When your AI app needs a tool that
is in one of your catalogs but not installed, it tells you which one and, if you
agree, installs it (installs download packages and take a few minutes). To add
the [tool collection](../tools/README.md) as a catalog, or install by hand:

```bash
scipatch catalog add <git-url>    # a collection of tools, e.g. this repository
scipatch catalog                  # what you can install
scipatch add rdkit-descriptors    # install one by hand
```

To turn a research repository into a tool, see
[Turning a repository into a tool](onboarding.md).

Some tools use an online service that needs an API key (the Materials Project,
for example). `scipatch add` asks for it and says where to get one. If you skip it,
your AI app gives you a link to a page on your computer where you can enter it
later, or use the **Keys** page of the dashboard. Never paste a key into the
chat: it would be sent to the AI model and kept in the conversation.

## 5. Use tools yourself

You don't need an AI app to use your tools:

```bash
scipatch ui        # opens a dashboard in your browser
```

The dashboard lists every tool with a form for each function, uploads input
files, shows results and output files, and keeps a history of every run.

Or from the terminal:

```bash
scipatch find "polar surface area"
scipatch info rdkit-descriptors
scipatch run rdkit-descriptors descriptors smiles="CC(=O)Oc1ccccc1C(=O)O"
scipatch runs
```

## Where things live

Everything SciPatch stores is in one folder, `~/.scipatch` (set `SCIPATCH_HOME` to use
another):

| Folder | Contents |
|---|---|
| `tools/` | installed tool packages |
| `envs/` | one Python environment per tool |
| `runs/` | one folder per run: output files and logs |
| `scipatch.db` | the history of runs |

To uninstall SciPatch completely: `scipatch disconnect <app>` for each connected app,
then `uv tool uninstall scipatch` and delete `~/.scipatch`.
