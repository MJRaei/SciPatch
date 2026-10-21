# Getting started

This guide takes you from nothing to asking your AI assistant to run a
scientific tool, in about ten minutes.

## 1. Install Motel

Motel needs [uv](https://docs.astral.sh/uv/), a small program that installs
Python and keeps each tool in its own environment. The installer sets it up for
you.

### macOS and Linux

Open a terminal in your copy of the Motel repository and run:

```bash
./install.sh
```

### Windows (experimental)

Open PowerShell in your copy of the Motel repository and run:

```powershell
powershell -ExecutionPolicy ByPass -File install.ps1
```

Most tools run natively on Windows. A few scientific codes have no Windows build
(CREST, GPAW, LAMMPS, Quantum ESPRESSO), and their own documentation recommends
WSL, the Windows Subsystem for Linux; Motel runs them there by itself, with the
same Linux packages it tests. To use them, set WSL up once: open PowerShell as
administrator, run `wsl --install`, restart, and finish setting up Ubuntu.
`motel doctor` shows whether WSL is ready.

### By hand

If you already use uv:

```bash
uv tool install --python 3.12 /path/to/motel     # a folder, a git URL, or "motel" from PyPI
uv tool update-shell                               # put 'motel' on your PATH
```

Open a **new** terminal afterwards so the `motel` command is found.

## 2. Run the guided setup

```bash
motel setup
```

The setup:

1. **Checks requirements**: uv and git. Anything missing is shown with the
   command that fixes it. You don't need conda: for tools that use conda
   packages, Motel downloads its own micromamba (and checks it) the first time
   one is installed.
2. **Connects your AI apps**: it finds Claude Desktop, Claude Code, Codex,
   Cursor, and Gemini CLI on your computer and asks before connecting each one.
3. **Offers an example tool**: `ase-emt`, which simulates simple metals in
   milliseconds. It is a good way to see everything working.

Then **restart your AI app** (quit Claude Desktop completely and open it again;
start a new session in the others).

## 3. Try it

Ask your assistant:

> *Use my Motel tools to find the equilibrium lattice constant and bulk modulus of copper.*

You should see it search Motel, read the tool's description, run it, and answer
with a lattice constant near 3.59 Å. It should also mention that EMT is an
approximate method; that comes from the tool's stated validity limits.

Then try the memory:

> *What have I computed with Motel today?*

## 4. Add more tools

```bash
motel catalog                  # featured tools that ship with Motel
motel add rdkit-descriptors    # chemistry: properties of molecules from SMILES
```

To turn a research repository into a tool, see
[Turning a repository into a tool](onboarding.md).

Some tools use an online service that needs an API key (the Materials Project,
for example). `motel add` asks for it and says where to get one. If you skip it,
your AI app gives you a link to a page on your computer where you can enter it
later, or use the **Keys** page of the dashboard. Never paste a key into the
chat: it would be sent to the AI model and kept in the conversation.

## 5. Use tools yourself

You don't need an AI app to use your tools:

```bash
motel ui        # opens a dashboard in your browser
```

The dashboard lists every tool with a form for each function, uploads input
files, shows results and output files, and keeps a history of every run.

Or from the terminal:

```bash
motel find "polar surface area"
motel info rdkit-descriptors
motel run rdkit-descriptors descriptors smiles="CC(=O)Oc1ccccc1C(=O)O"
motel runs
```

## Where things live

Everything Motel stores is in one folder, `~/.motel` (set `MOTEL_HOME` to use
another):

| Folder | Contents |
|---|---|
| `tools/` | installed tool packages |
| `envs/` | one Python environment per tool |
| `runs/` | one folder per run: output files and logs |
| `motel.db` | the history of runs |

To uninstall Motel completely: `motel disconnect <app>` for each connected app,
then `uv tool uninstall motel` and delete `~/.motel`.
