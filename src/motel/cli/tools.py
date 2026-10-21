"""Commands to discover, inspect, install, and maintain tools."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from motel.catalogs import DEFAULT_PATH, CatalogStore
from motel.cli._app import PANEL_MANAGE, PANEL_USE, app, get_motel, reporter_of
from motel.cli.console import console, print_json
from motel.models import FunctionInfo
from motel.registry import InstalledTool
from motel.schema import type_label
from motel.search import describe_inputs
from motel.views import match_view, tool_summary_view, tool_view

JsonOption = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]

catalog_app = typer.Typer(
    help="Tools you can install: built-in ones and collections you add.",
    invoke_without_command=True,
)
app.add_typer(catalog_app, name="catalog", rich_help_panel=PANEL_MANAGE)
secret_app = typer.Typer(
    help="API keys for tools that use online services (stored only on this computer)."
)
app.add_typer(secret_app, name="secret", rich_help_panel=PANEL_MANAGE)

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
    available = installed.runtime.secrets
    for name in manifest.environment.secrets:
        status = (
            "[green]set[/]" if name in available else f"[red]not set[/] (motel secret set {name})"
        )
        lines.append(f"Needs {name}: {status}")
    # Panels lay out their own text; soft wrapping would cut it off at the border.
    panel = Panel("\n".join(lines), title=header, title_align="left", expand=False)
    console.print(panel, soft_wrap=False)

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


@catalog_app.callback()
def catalog_list(
    ctx: typer.Context,
    as_json: JsonOption = False,
) -> None:
    """Tools available to install: built-in ones and those in catalogs you added."""
    if ctx.invoked_subcommand is not None:
        return
    motel = get_motel()
    entries = CatalogStore(motel.paths).entries()
    installed = set(motel.registry.names())
    if as_json:
        print_json(
            [
                {
                    "name": e.manifest.name,
                    "catalog": e.catalog,
                    "summary": e.manifest.summary,
                    "domains": e.manifest.domains,
                    "installed": e.manifest.name in installed,
                }
                for e in entries
            ]
        )
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("Name", style="bold")
    table.add_column("Catalog")
    table.add_column("Summary", overflow="fold")
    for entry in entries:
        name = entry.manifest.name + (" [green]✓[/]" if entry.manifest.name in installed else "")
        table.add_row(name, entry.catalog, escape(short(entry.manifest.summary)))
    console.print(table)
    console.print(
        "\n[green]✓[/] installed.  Install one with [cyan]motel add <name>[/]; "
        "add a collection with [cyan]motel catalog add <git-url>[/]."
    )


@catalog_app.command("add")
def catalog_add(
    url: Annotated[str, typer.Argument(help="Git URL (or local folder) of the collection.")],
    name: Annotated[str | None, typer.Option(help="Short name (default: from the URL).")] = None,
    path: Annotated[
        str, typer.Option(help="Folder inside the repository that holds the tools.")
    ] = DEFAULT_PATH,
) -> None:
    """Add a collection of tools (a git repository with one folder per tool)."""
    store = CatalogStore(get_motel().paths)
    catalog = store.add(url, name=name, path=path)
    count = sum(entry.catalog == catalog.name for entry in store.entries())
    console.print(f"[green]✓[/] Added catalog [bold]{catalog.name}[/] with {count} tool(s).")
    console.print("  See them with [cyan]motel catalog[/].")


@catalog_app.command("update")
def catalog_update(
    name: Annotated[str | None, typer.Argument(help="Catalog to update (default: all).")] = None,
) -> None:
    """Fetch the latest version of your catalogs (installed tools are not changed)."""
    updated = CatalogStore(get_motel().paths).update(name)
    if not updated:
        console.print("No catalogs added yet. Add one with [cyan]motel catalog add <git-url>[/].")
    for catalog, commit in updated:
        console.print(f"[green]✓[/] {catalog.name} @ {commit[:12]}")


@catalog_app.command("remove")
def catalog_remove(name: Annotated[str, typer.Argument(help="Catalog name.")]) -> None:
    """Remove a catalog (tools installed from it stay installed)."""
    CatalogStore(get_motel().paths).remove(name)
    console.print(f"[green]✓[/] Removed catalog {name}.")


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


@secret_app.command("set")
def secret_set(
    name: Annotated[str, typer.Argument(help="Name the tool expects, e.g. MP_API_KEY.")],
    value: Annotated[
        str | None, typer.Argument(help="The value (omit to type it without showing it).")
    ] = None,
) -> None:
    """Store a secret, such as an API key, for the tools that declare it."""
    if value is None:
        value = typer.prompt(f"Value for {name}", hide_input=True)
    motel = get_motel()
    motel.secrets.set(name, value)
    users = [t.name for t in motel.tools() if name in t.manifest.environment.secrets]
    console.print(f"[green]✓[/] Saved {name}" + (f" (used by {', '.join(users)})" if users else ""))


@secret_app.command("list")
def secret_list() -> None:
    """Show which secrets are stored and which tools need them (values are never shown)."""
    motel = get_motel()
    stored = set(motel.secrets.names())
    needed: dict[str, list[str]] = {}
    for tool in motel.tools():
        for name in tool.manifest.environment.secrets:
            needed.setdefault(name, []).append(tool.name)
    if not stored and not needed:
        console.print("No secrets stored, and no installed tool needs one.")
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("Secret", style="bold")
    table.add_column("Stored")
    table.add_column("Used by")
    for name in sorted(stored | set(needed)):
        mark = "[green]yes[/]" if name in stored else "[red]no[/]"
        table.add_row(name, mark, ", ".join(needed.get(name, [])) or "-")
    console.print(table)


@secret_app.command("remove")
def secret_remove(name: Annotated[str, typer.Argument(help="Secret name.")]) -> None:
    """Delete a stored secret."""
    if get_motel().secrets.remove(name):
        console.print(f"[green]✓[/] Removed {name}")
    else:
        console.print(f"No secret named {name} is stored.")
