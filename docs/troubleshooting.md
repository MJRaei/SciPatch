# Troubleshooting

Start with:

```bash
scipatch doctor
```

It checks every requirement and connection, and prints a fix for each problem.

## "scipatch: command not found"

Open a new terminal window. If that doesn't help, run `uv tool update-shell`,
then open a new terminal again.

## My AI app doesn't see SciPatch

1. Run `scipatch doctor` and check that the app shows as *connected*.
2. Restart the app completely. Claude Desktop must be quit (not just closed) and
   reopened.
3. Claude Desktop: open *Settings → Developer* to see whether the `scipatch` server
   started, and its log.
4. Reconnect: `scipatch connect <app>`.

## Installing a tool fails

The error shows the last lines of the build log and the log's location
(`~/.scipatch/logs/build-<name>.log`). Run again with `--verbose` to see each
command. Typical causes:

- **"cannot be installed on Windows"** (or another platform): the scientific
  code has no build for it, so the tool's `scipatch.lock` marks it unsupported and
  names what is missing; `scipatch info <tool>` lists the platforms it runs on. On
  Windows, tools that exist only for Linux (GPAW, Quantum ESPRESSO, CREST,
  LAMMPS) run inside WSL: if the message says WSL is not set up, open PowerShell
  as administrator, run `wsl --install`, restart, finish setting up Ubuntu, and
  install the tool again. `scipatch doctor` shows whether WSL is ready.
- **"needs an NVIDIA GPU (CUDA); this computer has none"**: the tool cannot run
  without one, so it is not installed. `scipatch doctor` shows the GPUs SciPatch
  found; NVIDIA GPUs are detected with `nvidia-smi`, which comes with the
  NVIDIA driver.
- **No internet connection**: environments download Python and packages.
- **A package can't be built**: it may need a compiler or system library.
  Tools that need compiled scientific software should use
  `environment.manager: conda`.
- **conda is slow or fails to solve** (for example "non-default solver backend
  (libmamba) but it was not recognized"): your conda's solver plugin is broken.
  SciPatch uses its own micromamba unless `SCIPATCH_SYSTEM_CONDA` is set; to repair
  your conda, run `conda install -n base -c conda-forge conda-libmamba-solver`.
- **Golden tests fail**: the tool installed but doesn't reproduce its reference
  results on your computer. The message says which value differed. Install
  anyway with `scipatch add <tool> --allow-failing-tests` if you understand why.

## A run fails

```bash
scipatch runs                      # find the run
scipatch runs show <run-id>        # the error, plus the log location
scipatch run ... --verbose         # include the full traceback
```

The run folder (`~/.scipatch/runs/<run-id>/`) contains `stdout.log` and
`stderr.log` with everything the tool printed.

## A run takes too long

Runs continue in the background when you stop waiting (Ctrl+C in the terminal,
or when an AI app's wait ends). Check on them with `scipatch runs`, and stop one
with `scipatch runs cancel <run-id>`.

If the tool is faster on a GPU (`scipatch info <tool>` says so under "Needs") and
your computer has a suitable one, let tools use it with `scipatch config gpu on`.
It is off by default so that results are reproducible.

## A run fails or crawls on a large input

`scipatch info <tool>` shows the memory a tool recommends next to what your
computer has. Try a smaller input first (fewer atoms, a shorter trajectory, a
smaller basis set), then scale up.

## A tool shows as "broken"

Its last rebuild failed, usually after a change to its package or a missing
dependency. `scipatch info <tool>` shows the error. `scipatch rebuild <tool> --clean`
rebuilds it from scratch.

## The dashboard says it needs a token

Open the exact link printed by `scipatch ui`; it contains a session token. A new
token is created each time the dashboard starts.

## Starting over

Everything SciPatch stores is in `~/.scipatch`. Removing a tool (`scipatch remove
<tool>`) deletes its environment but keeps the run history. Deleting `~/.scipatch`
resets SciPatch completely; disconnect your apps first with `scipatch disconnect
<app>`.
