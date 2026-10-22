# Turning a repository into a tool

You found a paper with code and want to use it, now and in the future, from
your AI assistant alongside your other tools. This page explains how.

## The easy way: let your coding agent do it

```bash
scipatch onboard https://github.com/CederGroupHub/chgnet \
    --paper https://doi.org/10.1038/s42256-023-00716-3 \
    --focus "relax crystal structures and predict energies"
```

SciPatch then:

1. pins the repository to its current commit and downloads it;
2. creates a workspace (`~/.scipatch/workspace/<name>/`) with a skeleton tool
   package, a brief (`ONBOARDING.md`), and the `scipatch-onboard` skill;
3. starts your coding agent (Claude Code, Codex, or Gemini CLI) in that
   workspace.

The agent follows the skill step by step. It reads the code and the paper,
proposes which capabilities to expose (and asks you when the choice is
scientific), makes the environment build, reproduces a published number, writes
the functions, golden tests, and usage notes, and verifies everything from
scratch. Follow along and answer its questions. When it's done:

```bash
scipatch check ~/.scipatch/workspace/chgnet --clean   # the agent normally does this
scipatch add ~/.scipatch/workspace/chgnet
```

No coding agent installed? Use `--agent none`. SciPatch prepares the workspace and
prints the request to paste into any AI assistant that can edit files and run
commands.

## What a good tool looks like

The agent (or you) is done when:

- `scipatch check . --clean` passes: the environment builds from the pinned commit
  plus patches, every function is typed and documented, and the golden tests
  pass;
- at least one golden test reproduces a number from the paper or the
  repository's documented example, and says exactly where the number comes from;
- `summary`, `validity`, `citation`, and `license` are filled in;
- the `SKILL.md` description says what the tool does *and when to use it*.

## Doing it by hand

```bash
scipatch new chgnet --repo https://github.com/CederGroupHub/chgnet --paper <doi>
cd chgnet
```

Then repeat this loop until it is right:

1. **Describe the environment** in `scipatch.yaml` (Python version, packages).
2. **Build and inspect**: `scipatch check .` (it downloads the source into
   `source/` and builds `.scipatch/env/`).
3. **Experiment** inside the environment: `scipatch exec . -- python`.
4. **Write functions** in `api.py`; `scipatch check .` lists them and warns about
   missing type hints or docs.
5. **Add golden tests** to `scipatch.yaml`. Input files go in `tests/data/`, or
   come from the project itself as `source/<path in the repository>`.

Then `scipatch check . --clean` and `scipatch add .`. While iterating on an installed
tool, `scipatch add . --link` uses the folder in place.

The format is described in [Tool package format](tool-format.md).

## Repositories with a user interface

Many research repositories ship a web app (Gradio, Streamlit, Dash) or a desktop
program. A tool exposes what the interface computes, never the interface: its
functions call the code behind the buttons, with the form fields as typed
parameters and the plots, tables, and viewers as files and values. The interface
packages are left out of the environment. Computation written inside the
interface's callbacks is moved into a function (saved as a patch). Desktop
programs are used through their Python module, command line, or batch mode; a
program that can only be driven by clicking cannot become a tool. SciPatch's
dashboard (`scipatch ui`) gives every function a form, so people who prefer clicking
still have one.

## Fixing the upstream code

Research code often needs a small fix to install or run (a pinned dependency, a
hard-coded path, an incompatibility with a newer library). Edit the files in
`source/`, then record the change:

```bash
scipatch patch save . -m "fix compatibility with numpy 2"
```

This writes `patches/0001-fix-compatibility-with-numpy-2.patch`. Patches are
applied in order on every build, so the fix survives rebuilds, reinstalls, and
moves to other computers. `scipatch check` warns about edits not yet saved as
patches, and refuses to discard them.

## Common build problems

| Symptom | What to do |
|---|---|
| A compiler or system library is missing | Use `environment.manager: conda` and add the library to `conda_packages` |
| Version conflicts (NumPy 2, PyTorch, CUDA) | Pin versions in `environment.packages` |
| `ModuleNotFoundError` while inspecting functions | Add the package to `environment.packages` |
| The repository is not pip-installable | Set `source.install: false`; `api.py` finds the code via the `SCIPATCH_SOURCE_DIR` environment variable |
| Model weights must be downloaded | Add a command to `environment.post_install` |
| It needs a GPU, a cluster, or licensed software | Say so in `validity` and the usage notes; choose golden tests that run on a laptop |

The complete output of every build step is in the build log: `.scipatch/build.log`
in a package folder, or `~/.scipatch/logs/build-<name>.log` for installed tools.
Add `--verbose` to see each command as it runs.

## Sharing a tool

1. Pin what you tested: `scipatch freeze .` writes `scipatch.lock` (exact versions for
   every platform, and where the tool cannot be installed), then
   `scipatch check . --clean` confirms the pinned build still passes.
2. Put the package folder in a git repository (the scaffold's `.gitignore`
   already excludes `source/` and `.scipatch/`). A **collection** of tools is a
   repository with one folder per tool under `tools/`, like this project's own
   [tools/](../tools/README.md).

Others can then install it directly:

```bash
scipatch add https://github.com/you/chgnet-scipatch
scipatch add "https://github.com/you/scipatch-tools#subdirectory=tools/chgnet"
```

or add the whole collection once and install tools by name:

```bash
scipatch catalog add https://github.com/you/scipatch-tools   # once
scipatch catalog                                             # browse
scipatch add chgnet                                          # install by name
scipatch catalog update                                      # fetch new and updated tools
```

Tools that call online services declare their API keys under
`environment.secrets`, with a description and where to get one ([API
keys](tool-format.md#api-keys)). SciPatch asks users for them on install, on the
dashboard, or through a one-time local link, and keys are never written into
tool packages or run records, nor passed through the chat.
