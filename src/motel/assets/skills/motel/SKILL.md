---
name: motel
description: >-
  Use the user's Motel: their local collection of scientific tools (materials
  science, chemistry, and more) wrapped from research repositories and papers,
  with a shared history of past results. Use when a question could be answered by
  running a computation, model, or simulation (relax a structure, compute energies
  or properties, analyze molecules, predict with a published model), when the user
  mentions their tools or Motel, or to look up results of earlier runs.
---

# Using Motel tools

Motel holds the user's installed research tools. Each runs in its own isolated
environment, every run is recorded with full provenance, and identical calls are
answered from cache.

Use the **MCP tools** (`find_tools`, `describe_tool`, `run_tool`, `get_run`,
`search_history`, `cancel_run`) when the `motel` server is connected. Otherwise
use the **`motel` command line** with `--json`.

## Workflow

1. **Check what is already known.**
   `motel runs --search "<keywords>" --json` (MCP: `search_history`). Earlier runs
   may already answer the question.
2. **Find a tool.** `motel find "<what you need, in plain words>" --json`
   (MCP: `find_tools`).
3. **Read it before running it.** `motel info <tool> --json` (MCP: `describe_tool`)
   gives parameters with units, usage notes, validity limits, and the citation.
4. **Run it.**
   `motel run <tool> <function> key=value ... --json` (MCP: `run_tool`).
   - Values are read as JSON when possible: `fmax=0.02`, `elements='["Cu","Au"]'`,
     `verbose=true`. Anything else is a string.
   - File paths may be relative to the current folder.
   - Output files are written to the run's folder (or `--output-dir`), and their
     absolute paths are returned in the result.
5. **Slow jobs.** Add `--background` and collect later with
   `motel runs show <run-id> --json`. Over MCP, `run_tool` returns
   `status: "running"` and a `run_id` when the job outlives `wait_seconds`; poll it
   with `get_run`.
6. **Report.** Give numbers with units, name the tool and run id, cite the paper
   (`motel info` shows how), and state any validity caveat that applies.

## Good practice

- **Respect validity limits.** If a request is outside a tool's stated domain
  (elements, conditions, training data), say so instead of reporting a number.
- **Cross-check what matters.** When two independent tools can answer, run both
  and report whether they agree.
- **Chain through files.** Pass an output path (e.g. a relaxed structure) as the
  input of the next tool.
- **Don't repeat work.** Identical calls are cached; search the history first.
- **No suitable tool?** Say so. The user can add one with
  `motel onboard <repository-url>`.

## Command reference

| Command | Purpose |
|---|---|
| `motel list --json` | installed tools and their status |
| `motel find "<query>" --json` | search functions across all tools |
| `motel info <tool> --json` | parameters, notes, validity, citation |
| `motel run <tool> <function> k=v ... --json` | run a function |
| `motel run ... --background` | start a long job and return immediately |
| `motel runs [--tool T] [--search Q] --json` | recent runs, newest first |
| `motel runs show <run-id> --json` | status, result, files, and error of one run |
| `motel runs cancel <run-id>` | stop a running job |
