# Troubleshooting

Start with:

```bash
motel doctor
```

It checks every requirement and connection, and prints a fix for each problem.

## "motel: command not found"

Open a new terminal window. If that doesn't help, run `uv tool update-shell`,
then open a new terminal again.

## My AI app doesn't see Motel

1. Run `motel doctor` and check that the app shows as *connected*.
2. Restart the app completely. Claude Desktop must be quit (not just closed) and
   reopened.
3. Claude Desktop: open *Settings → Developer* to see whether the `motel` server
   started, and its log.
4. Reconnect: `motel connect <app>`.

## Installing a tool fails

The error shows the last lines of the build log and the log's location
(`~/.motel/logs/build-<name>.log`). Run again with `--verbose` to see each
command. Typical causes:

- **"cannot be installed on Windows"** (or another platform): the scientific
  code has no build for it, so the tool's `motel.lock` marks it unsupported and
  names what is missing; `motel info <tool>` lists the platforms it runs on. On
  Windows, codes that exist only for Linux (GPAW, Quantum ESPRESSO, CREST,
  LAMMPS, AutoDock Vina) can be used from Linux under WSL (`wsl --install`).
- **No internet connection**: environments download Python and packages.
- **A package can't be built**: it may need a compiler or system library.
  Tools that need compiled scientific software should use
  `environment.manager: conda`.
- **conda is slow or fails to solve** (for example "non-default solver backend
  (libmamba) but it was not recognized"): your conda's solver plugin is broken.
  Motel uses its own micromamba unless `MOTEL_SYSTEM_CONDA` is set; to repair
  your conda, run `conda install -n base -c conda-forge conda-libmamba-solver`.
- **Golden tests fail**: the tool installed but doesn't reproduce its reference
  results on your computer. The message says which value differed. Install
  anyway with `motel add <tool> --allow-failing-tests` if you understand why.

## A run fails

```bash
motel runs                      # find the run
motel runs show <run-id>        # the error, plus the log location
motel run ... --verbose         # include the full traceback
```

The run folder (`~/.motel/runs/<run-id>/`) contains `stdout.log` and
`stderr.log` with everything the tool printed.

## A run takes too long

Runs continue in the background when you stop waiting (Ctrl+C in the terminal,
or when an AI app's wait ends). Check on them with `motel runs`, and stop one
with `motel runs cancel <run-id>`.

## A tool shows as "broken"

Its last rebuild failed, usually after a change to its package or a missing
dependency. `motel info <tool>` shows the error. `motel rebuild <tool> --clean`
rebuilds it from scratch.

## The dashboard says it needs a token

Open the exact link printed by `motel ui`; it contains a session token. A new
token is created each time the dashboard starts.

## Starting over

Everything Motel stores is in `~/.motel`. Removing a tool (`motel remove
<tool>`) deletes its environment but keeps the run history. Deleting `~/.motel`
resets Motel completely; disconnect your apps first with `motel disconnect
<app>`.
