"""Commands to build new tools: onboarding with an agent, scaffolding, checking, patching."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

from scipatch.cli._app import PANEL_BUILD, app, get_scipatch, reporter_of
from scipatch.cli.console import console, print_json
from scipatch.errors import SciPatchError
from scipatch.onboarding import (
    AGENT_PROMPT,
    AGENTS,
    available_agents,
    launch_agent,
    name_from_repo,
    prepare_workspace,
    scaffold,
)
from scipatch.platforms import label as platform_label
from scipatch.source import resolve_remote_ref

patch_app = typer.Typer(help="Save fixes to a tool's upstream source as patch files.")
app.add_typer(patch_app, name="patch", rich_help_panel=PANEL_BUILD)


@app.command(rich_help_panel=PANEL_BUILD)
def onboard(
    repo: Annotated[str, typer.Argument(help="Git URL of the research repository.")],
    paper: Annotated[str | None, typer.Option(help="DOI or URL of the paper.")] = None,
    name: Annotated[str | None, typer.Option(help="Tool name (default: from the URL).")] = None,
    ref: Annotated[str | None, typer.Option(help="Branch, tag, or commit to use.")] = None,
    focus: Annotated[
        str | None, typer.Option(help="What you want to use it for, in plain words.")
    ] = None,
    directory: Annotated[
        Path | None,
        typer.Option("--dir", help="Workspace folder (default: ~/.scipatch/workspace/NAME)."),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option(help=f"Agent to start: {', '.join(AGENTS)}, or 'none' to do it yourself."),
    ] = None,
) -> None:
    """Turn a research repository into a tool, with your AI coding agent doing the setup.

    SciPatch prepares a workspace (source code, scaffold, instructions) and starts your
    agent there. The agent installs the code, wraps its key capabilities, and checks
    that it reproduces the paper.
    """
    scipatch = get_scipatch()
    tool_name = name or name_from_repo(repo)
    folder = (directory or scipatch.paths.workspace / tool_name).expanduser().resolve()
    with reporter_of(scipatch).live("Preparing the workspace..."):
        workspace = prepare_workspace(
            repo,
            folder,
            name=tool_name,
            ref=ref,
            paper=paper,
            focus=focus,
            reporter=scipatch.reporter,
        )
    console.print(f"\n[green]✓[/] Workspace ready: [bold]{escape(str(workspace.directory))}[/]")

    chosen = agent or next(iter(available_agents()), "none")
    if chosen == "none":
        console.print(
            "\nNo coding agent was started. Open your AI coding assistant in that folder and ask:\n"
            f"  [italic]{escape(AGENT_PROMPT)}[/]\n"
            "(Claude Code: [cyan]https://claude.com/claude-code[/])"
        )
        _next_steps(workspace.directory)
        return
    console.print(
        f"Starting [bold]{chosen}[/] in the workspace. Follow along and answer its questions.\n"
    )
    launch_agent(chosen, workspace.directory)
    _next_steps(workspace.directory)


def _next_steps(directory: Path) -> None:
    console.print(
        "\nWhen the package is ready:\n"
        f"  Verify:  [cyan]scipatch check {directory} --clean[/]\n"
        f"  Install: [cyan]scipatch add {directory}[/]"
    )


@app.command(rich_help_panel=PANEL_BUILD)
def new(
    name: Annotated[str, typer.Argument(help="Tool name: lowercase letters, digits, hyphens.")],
    directory: Annotated[
        Path | None, typer.Option("--dir", help="Where to create it (default: ./NAME).")
    ] = None,
    repo: Annotated[str | None, typer.Option(help="Git URL of the code to wrap.")] = None,
    ref: Annotated[
        str | None, typer.Option(help="Branch, tag, or commit (default: latest).")
    ] = None,
    paper: Annotated[str | None, typer.Option(help="DOI or URL of the paper.")] = None,
    python: Annotated[str, typer.Option(help="Python version for the environment.")] = "3.11",
) -> None:
    """Create a new, empty tool package to fill in by hand."""
    folder = (directory or Path(name)).expanduser().resolve()
    pinned = resolve_remote_ref(repo, ref) if repo else None
    created = scaffold(folder, name, repo=repo, ref=pinned, paper=paper, python=python)
    if not created:
        raise SciPatchError(f"{folder} already contains a tool package; nothing was overwritten.")
    console.print(f"[green]✓[/] Created [bold]{escape(str(folder))}[/]")
    for path in created:
        console.print(f"  {escape(str(path.relative_to(folder)))}")
    console.print(
        f"\nNext: describe the environment in scipatch.yaml, write functions in api.py, then run\n"
        f"  [cyan]scipatch check {folder}[/]"
    )


@app.command(rich_help_panel=PANEL_BUILD)
def check(
    directory: Annotated[Path, typer.Argument(help="Tool package folder.")] = Path(),
    clean: Annotated[
        bool, typer.Option("--clean", help="Rebuild source and environment from scratch.")
    ] = False,
    skip_tests: Annotated[
        bool, typer.Option("--skip-tests", help="Don't run golden tests.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Build a tool package in place and verify it: environment, functions, golden tests."""
    scipatch = get_scipatch()
    with reporter_of(scipatch).live("Checking..."):
        outcome = scipatch.check(directory, clean=clean, run_tests=not skip_tests)
    if as_json:
        print_json(
            {
                "functions": [f.model_dump() for f in outcome.functions],
                "golden": [g.model_dump() for g in outcome.golden],
                "warnings": outcome.warnings,
                "source_commit": outcome.source_commit,
                "python": outcome.python_version,
                "ok": outcome.tests_passed,
            }
        )
    else:
        # Golden-test results were already shown as they ran.
        console.print("\nFunctions:")
        for function in outcome.functions:
            console.print(
                f"  [green]✓[/] {escape(function.signature())}  [dim]{escape(function.summary)}[/]"
            )
        for warning in outcome.warnings:
            console.print(f"  [yellow]![/] {escape(warning)}")
        skipped = [result for result in outcome.golden if result.skipped]
        need_secrets = [r for r in skipped if (r.error or "").startswith("skipped: needs")]
        if need_secrets:
            console.print(
                f"\n[yellow]{len(need_secrets)} golden test(s) skipped[/] because a secret is "
                "missing; set it with [cyan]scipatch secret set NAME[/] to run them."
            )
        if len(skipped) > len(need_secrets):
            console.print(
                f"\n[dim]{len(skipped) - len(need_secrets)} golden test(s) run only on other "
                "platforms.[/]"
            )
        if not outcome.tests_passed:
            console.print("\n[red]Golden tests failed[/] (see above).")
        elif skip_tests:
            console.print(
                "\nThe environment builds and the functions look right; run without "
                "--skip-tests to verify results."
            )
        else:
            console.print(
                f"\n[green]Package is valid.[/] Install it with [cyan]scipatch add {directory}[/]"
            )
    if not outcome.tests_passed:
        raise typer.Exit(1)


@app.command(
    "exec",
    rich_help_panel=PANEL_BUILD,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def exec_command(
    target: Annotated[str, typer.Argument(help="Tool package folder or installed tool name.")],
    command: Annotated[list[str], typer.Argument(help="Command to run, after '--'.")],
) -> None:
    """Run a command in a tool's environment, e.g. [cyan]scipatch exec . -- python demo.py[/]."""
    raise typer.Exit(get_scipatch().exec(target, command))


@app.command(rich_help_panel=PANEL_BUILD)
def freeze(
    directory: Annotated[Path, typer.Argument(help="Tool package folder.")] = Path(),
) -> None:
    """Pin the exact packages a tool was tested with, for every platform (writes scipatch.lock).

    Also resolves Linux, macOS, and Windows without installing anything, and records
    where the tool cannot be installed and why. Do this before sharing a tool.
    """
    result = get_scipatch().freeze(str(directory))
    console.print(f"[green]✓[/] Wrote {escape(str(result.path))}")
    console.print(f"  [dim]tested environment: {escape(str(result.env_dir))}[/]")
    for name, entry in result.platforms.items():
        label = platform_label(name)
        if entry.unavailable:
            console.print(f"  [red]✗[/] {label}: {escape(entry.unavailable)}")
            continue
        count = len(entry.conda) + len(entry.pip)
        tested = " [dim](tested here)[/]" if name == result.tested_on else ""
        console.print(f"  [green]✓[/] {label}: {count} packages pinned{tested}")
        if entry.note:
            console.print(f"    [yellow]{escape(entry.note)}[/]")
    for warning in result.warnings:
        console.print(f"  [yellow]![/] {escape(warning)}")
    folder = escape(str(directory))
    console.print(f"  Verify the pinned build: [cyan]scipatch check {folder} --clean[/]")


@patch_app.command("save")
def patch_save(
    target: Annotated[
        str, typer.Argument(help="Tool package folder or installed tool name.")
    ] = ".",
    message: Annotated[
        str, typer.Option("--message", "-m", help="Why the change is needed.")
    ] = "local changes",
) -> None:
    """Save edits made in the package's source/ folder as a numbered patch file."""
    path = get_scipatch().save_patch(target, message)
    if path is None:
        console.print("Nothing to save: the source has no unsaved edits.")
    else:
        console.print(f"[green]✓[/] Saved {escape(str(path))}")
