---
name: scipatch
description: >-
  Use the user's SciPatch: their local collection of scientific tools (materials
  science, chemistry, and more) wrapped from research repositories and papers,
  with a shared history of past results. Use when a question could be answered by
  running a computation, model, or simulation (relax a structure, compute energies
  or properties, analyze molecules, predict with a published model), when the user
  mentions their tools or SciPatch, or to look up results of earlier runs.
---

# Using SciPatch tools

SciPatch holds the user's installed research tools. Each runs in its own isolated
environment, every run is recorded with full provenance, and identical calls are
answered from cache.

Use the **MCP tools** (`find_tools`, `describe_tool`, `install_tool`, `run_tool`,
`get_run`, `search_history`, `cancel_run`) when the `scipatch` server is connected.
Otherwise use the **`scipatch` command line** with `--json`.

## Workflow

1. **Check what is already known.**
   `scipatch runs --search "<keywords>" --json` (MCP: `search_history`). Earlier runs
   may already answer the question.
2. **Find a tool.** `scipatch find "<what you need, in plain words>" --json`
   (MCP: `find_tools`). Results marked `"installed": false` (MCP: under
   `not_installed`) exist in a catalog but are not installed: ask the user before
   installing, naming its maturity and catalog (it downloads packages and takes
   minutes), then `scipatch add <tool>` (MCP: `install_tool`, called again until it
   reports `ready`).
3. **Read it before running it.** `scipatch info <tool> --json` (MCP: `describe_tool`)
   gives parameters with units, usage notes, validity limits, the citation, and
   `resources`: what the tool needs (GPU, memory, internet) and how that fits
   this computer. Pass any warning on to the user before a large run, and try a
   small input first when memory is short.
4. **Run it.**
   `scipatch run <tool> <function> key=value ... --json` (MCP: `run_tool`).
   - Values are read as JSON when possible: `fmax=0.02`, `elements='["Cu","Au"]'`,
     `verbose=true`. Anything else is a string.
   - File paths may be relative to the current folder.
   - Output files are written to the run's folder (or `--output-dir`), and their
     absolute paths are returned in the result.
5. **Slow jobs.** Add `--background` and collect later with
   `scipatch runs show <run-id> --json`. Over MCP, `run_tool` returns
   `status: "running"` and a `run_id` when the job outlives `wait_seconds`; poll it
   with `get_run`. While it runs, `latest_output` shows its most recent progress
   lines and `elapsed_seconds` how long it has been running.
6. **Report.** Give numbers with units, name the tool, its maturity, and the run
   id, cite the paper (`scipatch info` shows how), and state any validity caveat that
   applies.

## Maturity

Every tool has a level, shown by `find`, `info`, and in run results:

- **established**: mature, widely used code, checked against independent
  references or exact results;
- **published**: research code from a publication, less widely tested;
- **experimental**: little outside validation, such as a small project without a
  publication.

When several tools fit, prefer the more established one (search already ranks
it first among similar matches). Use a less mature tool when it is the only fit
or the user asks for it. With an experimental tool, tell the user, and
cross-check key numbers with an established tool that covers the task
(`scipatch info` suggests some); if none does, present the numbers as provisional.

## Good practice

- **Respect validity limits.** If a request is outside a tool's stated domain
  (elements, conditions, training data), say so instead of reporting a number.
- **Cross-check what matters.** When two independent tools can answer, run both
  and report whether they agree.
- **Chain through files.** Pass an output path (e.g. a relaxed structure) as the
  input of the next tool.
- **Don't repeat work.** Identical calls are cached; search the history first.
- **No suitable tool?** Say so. The user can add one with
  `scipatch onboard <repository-url>`.

## Command reference

| Command | Purpose |
|---|---|
| `scipatch list --json` | installed tools and their status |
| `scipatch find "<query>" --json` | search functions across all tools |
| `scipatch info <tool> --json` | parameters, notes, validity, citation |
| `scipatch run <tool> <function> k=v ... --json` | run a function |
| `scipatch run ... --background` | start a long job and return immediately |
| `scipatch runs [--tool T] [--search Q] --json` | recent runs, newest first |
| `scipatch runs show <run-id> --json` | status, result, files, and error of one run |
| `scipatch runs cancel <run-id>` | stop a running job |
| `scipatch doctor` | what this computer has (cores, memory, GPU) and what is missing |
