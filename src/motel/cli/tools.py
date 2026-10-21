"""Commands to discover, inspect, install, and maintain tools."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from motel.catalog import catalog_entries
from motel.cli._app import PANEL_MANAGE, PANEL_USE, app, get_motel, reporter_of
from motel.cli.console import console, print_json
from motel.models import FunctionInfo
from motel.registry import InstalledTool
from motel.schema import type_label
from motel.search import describe_inputs
from motel.views import match_view, tool_summary_view, tool_view

JsonOption = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]

_STATUS_STYLE = {
    "ready": "[green]ready[/]",
    "failing-tests": "[yellow]tests failing[/]",
    "broken": "[red]broken[/]",
    "not-built": "[red]not built[/]",
}


def short(text: str, limit: int = 90) -> str:
    """The first sentence of ``text``, cut at a word boundary if still too long."""
    sentence = text.split(". ")[0].rstrip(".")
    if len(sentence) <= limit:
        return sentence
    return sentence[:limit].rsplit(" ", 1)[0] + "…"


def status_label(tool: InstalledTool) -> str:
    return _STATUS_STYLE.get(tool.status, tool.status)


@app.command("list", rich_help_panel=PANEL_USE)
def list_tools(as_json: JsonOption = False) -> None:
    """List installed tools."""
    tools = get_motel().tools()
    if as_json:
        print_json([tool_summary_view(tool) for tool in tools])
        return
    if not tools:
        console.print(
            "No tools installed yet.\n"
            "  Try a featured tool:     [cyan]motel add ase-emt[/]  (see [cyan]motel catalog[/])\n"
            "  Turn a repo into a tool: [cyan]motel onboard <repository-url>[/]"
        )
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("Tool", style="bold")
    table.add_column("Status")
    table.add_column("Functions")
    table.add_column("Summary", overflow="fold")
    for tool in tools:
        names = ", ".join(f.name for f in tool.functions) or "-"
        table.add_row(tool.name, status_label(tool), names, escape(short(tool.manifest.summary)))
    console.print(table)


@app.command(rich_help_panel=PANEL_USE)
def find(
    query: Annotated[str, typer.Argument(help="What you need, in plain words.")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum results.")] = 10,
    as_json: JsonOption = False,
) -> None:
    """Search installed tools for a capability, e.g. [cyan]motel find "relax a structure"[/]."""
    matches = get_motel().find(query, limit=limit)
    if as_json:
        print_json([match_view(match) for match in matches])
        return
    if not matches:
        console.print(
            f"No tool matches [bold]{escape(query)}[/]. See everything with [cyan]motel list[/]."
        )
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("Tool and function", style="bold")
    table.add_column("What it does", overflow="fold")
    table.add_column("Inputs", overflow="fold", style="dim")
    for match in matches:
        function = match.function
        table.add_row(
            f"{match.tool.name} {function.name}",
            escape(function.summary or match.tool.manifest.summary),
            escape(describe_inputs(function.properties, function.required)),
        )
    console.print(table)
    first = matches[0]
    console.print(
        f"\nDetails: [cyan]motel info {first.tool.name}[/]   "
        f"Run: [cyan]motel run {first.tool.name} {first.function.name} key=value ...[/]"
    )


@app.command(rich_help_panel=PANEL_USE)
def info(
    tool: Annotated[str, typer.Argument(help="Tool name.")],
    as_json: JsonOption = False,
) -> None:
    """Show a tool's functions, parameters, usage notes, validity limits, and citation."""
    installed = get_motel().tool(tool)
    if as_json:
        print_json(tool_view(installed))
        return
    manifest = installed.manifest
    state = installed.state
    header = (
        f"[bold]{escape(manifest.display_title)}[/] ({installed.name} {escape(manifest.version)})"
    )
    lines = [escape(manifest.summary), ""]
    lines.append(
        f"Status: {status_label(installed)}"
        + (f" · {state.golden_summary}" if state else "")
        + (" · [dim]linked for development[/]" if installed.linked else "")
    )
    if state and state.error:
        lines.append(f"[red]Last error:[/] {escape(state.error)}")
    console.print(Panel("\n".join(lines), title=header, title_align="left", expand=False))

    for function in installed.functions:
        _print_function(installed.name, function)

    guide = installed.guide()
    if guide:
        console.rule("Usage notes", align="left", style="dim")
        console.print(Markdown(guide))
    if manifest.validity:
        console.rule("Before trusting a result", align="left", style="dim")
        console.print(escape(manifest.validity.strip()))
    source = manifest.source
    citation = [
        f"Code: {source.repo} @ {(state.source_commit if state else source.ref) or ''}"[:120]
        if source.repo
        else None,
        f"Paper: {source.paper}" if source.paper else None,
        f"Cite as: {source.citation}" if source.citation else None,
        f"License: {source.license}" if source.license else None,
    ]
    if any(citation):
        console.rule("Provenance", align="left", style="dim")
        for line in filter(None, citation):
            console.print(escape(line))


def _print_function(tool: str, function: FunctionInfo) -> None:
    console.print()
    title = f"[bold cyan]{function.name}[/]"
    if function.long_running:
        title += " [yellow](long-running)[/]"
    console.print(f"{title}  {escape(function.summary)}")
    if function.description:
        console.print(f"[dim]{escape(function.description)}[/]")
    if function.properties:
        table = Table(box=None, pad_edge=False, show_header=True, header_style="dim")
        table.add_column("  parameter")
        table.add_column("type")
        table.add_column("default")
        table.add_column("description", overflow="fold")
        for name, schema in function.properties.items():
            default = (
                "[bold]required[/]"
                if name in function.required
                else escape(repr(schema.get("default")))
            )
            table.add_row(
                f"  {name}",
                escape(type_label(schema)),
                default,
                escape(schema.get("description", "")),
            )
        console.print(table)
    returns = function.returns.get("description")
    if returns:
        console.print(f"  [dim]returns:[/] {escape(returns)}")
    example = " ".join(f"{p}=..." for p in function.required)
    console.print(f"  [dim]run:[/] motel run {tool} {function.name} {example}".rstrip())


@app.command(rich_help_panel=PANEL_MANAGE)
def catalog(as_json: JsonOption = False) -> None:
    """Show featured tools that ship with Motel."""
    entries = catalog_entries()
    if as_json:
        print_json(
            [{"name": m.name, "summary": m.summary, "domains": m.domains} for m, _ in entries]
        )
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("Name", style="bold")
    table.add_column("Domains")
    table.add_column("Summary", overflow="fold")
    for manifest, _ in entries:
        table.add_row(manifest.name, escape(", ".join(manifest.domains)), escape(manifest.summary))
    console.print(table)
    console.print("\nInstall one with [cyan]motel add <name>[/].")


@app.command(rich_help_panel=PANEL_MANAGE)
def add(
    source: Annotated[
        str,
        typer.Argument(help="A featured tool name, a tool package folder, or a git URL."),
    ],
    link: Annotated[
        bool, typer.Option("--link", help="Use the folder in place (for tools you are developing).")
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="Replace an installed tool.")] = False,
    ref: Annotated[str | None, typer.Option(help="Branch, tag, or commit (git URLs).")] = None,
    skip_tests: Annotated[
        bool, typer.Option("--skip-tests", help="Don't run golden tests.")
    ] = False,
    allow_failing_tests: Annotated[
        bool, typer.Option("--allow-failing-tests", help="Install even if golden tests fail.")
    ] = False,
) -> None:
    """Install a tool, e.g. [cyan]motel add ase-emt[/] or [cyan]motel add ./my-tool[/]."""
    motel = get_motel()
    with reporter_of(motel).live("Installing..."):
        tool = motel.add(
            source,
            link=link,
            force=force,
            ref=ref,
            run_tests=not skip_tests,
            allow_failing_tests=allow_failing_tests,
        )
    console.print(f"\n[green]✓[/] [bold]{tool.name}[/] is ready.")
    for warning in tool.state.warnings if tool.state else []:
        console.print(f"  [yellow]![/] {escape(warning)}")
    console.print(f"  See what it does: [cyan]motel info {tool.name}[/]")
    if not motel.connections.load():
        console.print("  Use it from your AI app: [cyan]motel connect[/]")


@app.command(rich_help_panel=PANEL_MANAGE)
def remove(
    tool: Annotated[str, typer.Argument(help="Tool name.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Don't ask for confirmation.")] = False,
) -> None:
    """Uninstall a tool (its run history is kept)."""
    motel = get_motel()
    installed = motel.tool(tool)
    if not yes:
        typer.confirm(f"Remove '{installed.name}' and its environment?", default=False, abort=True)
    motel.remove(tool)
    console.print(f"[green]✓[/] Removed {tool}.")


@app.command(rich_help_panel=PANEL_MANAGE)
def rebuild(
    tool: Annotated[str, typer.Argument(help="Tool name.")],
    clean: Annotated[
        bool, typer.Option("--clean", help="Rebuild everything from scratch.")
    ] = False,
    skip_tests: Annotated[
        bool, typer.Option("--skip-tests", help="Don't run golden tests.")
    ] = False,
) -> None:
    """Rebuild a tool's environment and re-check its functions."""
    motel = get_motel()
    with reporter_of(motel).live("Rebuilding..."):
        installed = motel.rebuild(tool, clean=clean, run_tests=not skip_tests)
    console.print(f"[green]✓[/] {installed.name}: {status_label(installed)}")


@app.command(rich_help_panel=PANEL_MANAGE)
def test(tool: Annotated[str, typer.Argument(help="Tool name.")]) -> None:
    """Run a tool's golden tests (checks that it reproduces known results)."""
    motel = get_motel()
    with reporter_of(motel).live("Testing..."):
        installed = motel.test(tool)
    state = installed.state
    console.print(f"{installed.name}: {state.golden_summary if state else 'not built'}")
    if installed.status != "ready":
        raise typer.Exit(1)
