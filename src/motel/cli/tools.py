"""Commands to discover, inspect, install, and maintain tools."""

from __future__ import annotations

import io
import select
import sys
import webbrowser
from typing import Annotated

import typer
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from motel import hardware
from motel.catalogs import DEFAULT_PATH, CatalogStore
from motel.cli._app import PANEL_MANAGE, PANEL_USE, app, get_motel, reporter_of
from motel.cli.console import console, print_json
from motel.errors import MotelError
from motel.hardware import install_blocker
from motel.keypage import KeyPage
from motel.lock import platform_summary, runs_in_wsl, unavailable_here
from motel.manifest import Secret
from motel.maturity import LEVELS
from motel.models import FunctionInfo
from motel.platforms import current as current_platform
from motel.platforms import label as platform_label
from motel.registry import InstalledTool
from motel.schema import type_label
from motel.search import describe_inputs
from motel.secrets import check_name
from motel.settings import SETTINGS, Settings
from motel.views import (
    installable_view,
    match_view,
    maturity_view,
    resources_view,
    secrets_view,
    tool_summary_view,
    tool_view,
)

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

#: How long `motel secret set` waits for a key entered in the browser.
BROWSER_WAIT_SECONDS = 10 * 60

_STATUS_STYLE = {
    "ready": "[green]ready[/]",
    "failing-tests": "[yellow]tests failing[/]",
    "broken": "[red]broken[/]",
    "not-built": "[red]not built[/]",
}

_MATURITY_STYLE = {
    "established": "established",
    "published": "[cyan]published[/]",
    "experimental": "[yellow]experimental[/]",
}


def short(text: str, limit: int = 90) -> str:
    """The first sentence of ``text``, cut at a word boundary if still too long."""
    sentence = text.split(". ")[0].rstrip(".")
    if len(sentence) <= limit:
        return sentence
    return sentence[:limit].rsplit(" ", 1)[0] + "…"


def status_label(tool: InstalledTool) -> str:
    return _STATUS_STYLE.get(tool.status, tool.status)


def maturity_label(level: str) -> str:
    return _MATURITY_STYLE.get(level, level)


def prompt_secret(secret: Secret, *, optional: bool) -> str | None:
    """Ask for a secret without showing it; with ``optional``, Enter skips it."""
    console.print(
        f"\n[bold]{escape(secret.label)}[/]" + (f" ({secret.name})" if secret.description else "")
    )
    if secret.url:
        console.print(f"Get one at {escape(secret.url)}")
    question = "Paste it here (hidden)" + (", or press Enter to skip" if optional else "")
    value: str = typer.prompt(
        question, default="" if optional else None, hide_input=True, show_default=False
    )
    return value.strip() or None


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
    table.add_column("Maturity")
    table.add_column("Functions")
    table.add_column("Summary", overflow="fold")
    for tool in tools:
        names = ", ".join(f.name for f in tool.functions) or "-"
        table.add_row(
            tool.name,
            status_label(tool),
            maturity_label(tool.maturity),
            names,
            escape(short(tool.manifest.summary)),
        )
    console.print(table)


@app.command(rich_help_panel=PANEL_USE)
def find(
    query: Annotated[str, typer.Argument(help="What you need, in plain words.")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum results.")] = 10,
    as_json: JsonOption = False,
) -> None:
    """Search installed tools for a capability, e.g. [cyan]motel find "relax a structure"[/].

    Tools from catalogs that match but are not installed are listed too.
    """
    motel = get_motel()
    matches = motel.find(query, limit=limit)
    best = max((match.hit.score for match in matches), default=0.0)
    available = [entry for entry, score in motel.find_installable(query) if score >= 0.5 * best]
    if as_json:
        suggestions = [
            {
                **installable_view(entry),
                "installed": False,
                "install": f"motel add {entry.manifest.name}",
            }
            for entry in available
        ]
        print_json([{**match_view(match), "installed": True} for match in matches] + suggestions)
        return
    if available:
        console.print("[bold]Not installed yet[/] (install with [cyan]motel add <name>[/]):")
        for entry in available:
            reason = unavailable_here(entry.folder) or install_blocker(
                entry.manifest.resources_for()
            )
            note = f" [dim](not for this computer: {escape(reason)})[/]" if reason else ""
            level = maturity_label(entry.manifest.maturity)
            console.print(
                f"  {entry.manifest.name} ({level}, {escape(entry.catalog)}): "
                f"{escape(short(entry.manifest.summary))}{note}"
            )
        console.print()
    if not matches:
        if not available:
            console.print(
                f"No tool matches [bold]{escape(query)}[/]. See everything with "
                "[cyan]motel list[/]."
            )
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("Tool and function", style="bold")
    table.add_column("What it does", overflow="fold")
    table.add_column("Inputs", overflow="fold", style="dim")
    for match in matches:
        function = match.function
        level = match.tool.maturity
        table.add_row(
            f"{match.tool.name} {function.name}"
            + ("" if level == "established" else f"\n[not bold]{maturity_label(level)}[/]"),
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
    motel = get_motel()
    installed = motel.tool(tool)
    experimental = installed.maturity == "experimental"
    alternatives = motel.stronger_alternatives(installed) if experimental else None
    if as_json:
        print_json(tool_view(installed, alternatives))
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
    lines.extend(_maturity_lines(installed, alternatives))
    lines.extend(_resource_lines(installed))
    summary = platform_summary(installed.package_dir)
    if summary:
        supported = [platform_label(name) for name, reason in summary.items() if not reason]
        if runs_in_wsl(summary):
            supported.append("Windows (inside WSL)")
        lines.append(f"Runs on: {', '.join(supported) or 'no platform'}")
        for name, reason in summary.items():
            if reason and not (name == "win-64" and runs_in_wsl(summary)):
                lines.append(f"  [dim]Not on {platform_label(name)}: {escape(reason)}[/]")
    available = installed.runtime.secrets
    for secret in manifest.environment.secrets:
        status = (
            "[green]set[/]"
            if secret.name in available
            else f"[red]not set[/] (motel secret set {secret.name})"
        )
        label = f" ({escape(secret.description)})" if secret.description else ""
        lines.append(f"Needs {secret.name}{label}: {status}")
        if secret.url and secret.name not in available:
            lines.append(f"  Get one at {escape(secret.url)}")
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


def _maturity_lines(tool: InstalledTool, alternatives: list[str] | None) -> list[str]:
    view = maturity_view(tool, alternatives)
    lines = [
        f"Maturity: {maturity_label(view['level'])} · {escape(view['evidence'])}",
        f"  [dim]Declared in {escape(view['declared_in'])}[/]",
    ]
    if "lowered_by_user" in view:
        lines.append(f"  [dim]{escape(view['lowered_by_user'])}[/]")
    if "caution" in view:
        lines.append(f"  [yellow]{escape(view['caution'])}[/]")
    return lines


def _resource_lines(tool: InstalledTool) -> list[str]:
    view = resources_view(tool)
    lines = [f"Needs: {escape(', '.join(view['needs']))}"]
    if "disk_space" in view:
        lines[0] += f" · uses {escape(view['disk_space'])}"
    for key, style in (("cannot_run_here", "red"), ("warnings", "yellow"), ("notes", "dim")):
        lines.extend(f"  [{style}]{escape(text)}[/]" for text in view.get(key, []))
    for name, function in view.get("functions", {}).items():
        needs = ", ".join(function["needs"]) or "nothing beyond a CPU"
        lines.append(f"  [dim]{name}: {escape(needs)}[/]")
        for key, style in (("cannot_run_here", "red"), ("warnings", "yellow")):
            lines.extend(f"    [{style}]{escape(text)}[/]" for text in function.get(key, []))
    return lines


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
                    "maturity": e.manifest.maturity,
                    "installed": e.manifest.name in installed,
                    "unavailable_here": unavailable_here(e.folder)
                    or install_blocker(e.manifest.resources_for()),
                }
                for e in entries
            ]
        )
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("Name", style="bold")
    table.add_column("Catalog")
    table.add_column("Maturity")
    table.add_column("Summary", overflow="fold")
    unavailable = 0
    for entry in entries:
        name = entry.manifest.name + (" [green]✓[/]" if entry.manifest.name in installed else "")
        reason = unavailable_here(entry.folder) or install_blocker(entry.manifest.resources_for())
        summary = escape(short(entry.manifest.summary))
        if reason:
            unavailable += 1
            name = f"[dim]{name} ✗[/]"
            summary = (
                f"[dim]{summary}\nNot for {platform_label(current_platform())}: {escape(reason)}[/]"
            )
        table.add_row(name, entry.catalog, maturity_label(entry.manifest.maturity), summary)
    console.print(table)
    console.print(
        "\n[green]✓[/] installed"
        + ("  ✗ cannot be installed on this computer" if unavailable else "")
        + ".  Install one with [cyan]motel add <name>[/]; "
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
    all_tests: Annotated[
        bool,
        typer.Option("--all-tests", help="Run every golden test, not only the quick ones."),
    ] = False,
    allow_failing_tests: Annotated[
        bool, typer.Option("--allow-failing-tests", help="Install even if golden tests fail.")
    ] = False,
) -> None:
    """Install a tool, e.g. [cyan]motel add ase-emt[/] or [cyan]motel add ./my-tool[/]."""
    motel = get_motel()
    reporter = reporter_of(motel)

    def ask(secret: Secret) -> str | None:
        with reporter.paused():
            return prompt_secret(secret, optional=True)

    with reporter.live("Installing..."):
        tool = motel.add(
            source,
            link=link,
            force=force,
            ref=ref,
            run_tests=not skip_tests,
            all_tests=all_tests,
            allow_failing_tests=allow_failing_tests,
            ask_secret=ask if _is_terminal() else None,
        )
    console.print(f"\n[green]✓[/] [bold]{tool.name}[/] is ready.")
    for warning in tool.state.warnings if tool.state else []:
        console.print(f"  [yellow]![/] {escape(warning)}")
    for secret in tool.manifest.environment.secrets:
        if secret.name not in tool.runtime.secrets:
            console.print(
                f"  [yellow]![/] It needs {escape(secret.label)} before it can run: "
                f"[cyan]motel secret set {secret.name}[/]"
            )
    if tool.maturity == "experimental":
        console.print(
            "  [yellow]![/] It is experimental (little outside validation): AI apps are told to "
            "prefer established tools and to cross-check its results."
        )
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
    all_tests: Annotated[
        bool,
        typer.Option("--all-tests", help="Run every golden test, not only the quick ones."),
    ] = False,
) -> None:
    """Rebuild a tool's environment and re-check its functions."""
    motel = get_motel()
    with reporter_of(motel).live("Rebuilding..."):
        installed = motel.rebuild(tool, clean=clean, run_tests=not skip_tests, all_tests=all_tests)
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


@app.command("maturity", rich_help_panel=PANEL_MANAGE)
def maturity_command(
    tool: Annotated[str, typer.Argument(help="Tool name.")],
    level: Annotated[
        str | None, typer.Argument(help="Lower it to this level: published or experimental.")
    ] = None,
    reset: Annotated[
        bool, typer.Option("--reset", help="Go back to the level its motel.yaml declares.")
    ] = False,
) -> None:
    """Show a tool's maturity level and its evidence, or lower the level on this computer.

    AI apps prefer more established tools and cross-check experimental ones. Lower
    a tool you trust less than its catalog does, e.g.
    [cyan]motel maturity some-tool experimental[/].
    """
    motel = get_motel()
    if level is not None and level not in LEVELS:
        raise MotelError(
            f"'{level}' is not a maturity level.", hint=f"Use one of: {', '.join(LEVELS)}."
        )
    if level is not None or reset:
        installed = motel.lower_maturity(tool, None if reset else level)
        console.print(
            f"[green]✓[/] {tool} is {maturity_label(installed.maturity)} on this computer."
        )
    else:
        installed = motel.tool(tool)
    for line in _maturity_lines(installed, None):
        console.print(line)


@app.command("config", rich_help_panel=PANEL_MANAGE)
def config_command(
    name: Annotated[str | None, typer.Argument(help="Setting, e.g. gpu.")] = None,
    value: Annotated[str | None, typer.Argument(help="New value: on or off.")] = None,
) -> None:
    """Show or change settings for this computer, e.g. [cyan]motel config gpu on[/]."""
    settings = Settings(get_motel().paths.config)
    if name is None:
        for key, (_default, meaning) in SETTINGS.items():
            console.print(f"[bold]{key}[/] {_on_off(settings.get(key))}  [dim]{meaning}[/]")
        console.print(f"\nThis computer: {escape(hardware.detect().summary())}")
        return
    if name not in SETTINGS:
        raise MotelError(f"No setting named '{name}'.", hint=f"Settings: {', '.join(SETTINGS)}.")
    if value is not None:
        choice = value.strip().lower()
        if choice not in ("on", "off", "true", "false", "yes", "no"):
            raise MotelError(f"'{value}' is not on or off.")
        settings.set(name, choice in ("on", "true", "yes"))
    console.print(f"[bold]{name}[/] {_on_off(settings.get(name))}  [dim]{SETTINGS[name][1]}[/]")


def _on_off(value: object) -> str:
    return "[green]on[/]" if value else "off"


@secret_app.command("set")
def secret_set(
    name: Annotated[str, typer.Argument(help="Name the tool expects, e.g. MP_API_KEY.")],
    value: Annotated[
        str | None, typer.Argument(help="The value (omit to type it without showing it).")
    ] = None,
) -> None:
    """Store a secret, such as an API key, for the tools that declare it.

    Without a value, it is typed hidden in the terminal. Without a terminal (for
    example when an AI agent runs this), a page on this computer opens in the
    browser for the user to enter it, so the key never passes through the agent.
    """
    motel = get_motel()
    users = [t.name for t in motel.tools() if name in t.manifest.environment.secret_names]
    if value is None:
        declared = next(
            (s for t in motel.tools() for s in t.manifest.environment.secrets if s.name == name),
            None,
        )
        secret = declared or Secret(name=check_name(name))
        if _is_terminal():
            value = prompt_secret(secret, optional=False)
        elif (piped := _piped_value()) is not None:
            value = piped
        else:
            _enter_in_browser(secret, users[0] if users else "Motel")
    if value is not None:
        motel.secrets.set(name, value)
    console.print(f"[green]✓[/] Saved {name}" + (f" (used by {', '.join(users)})" if users else ""))


def _is_terminal() -> bool:
    return sys.stdin.isatty()


def _piped_value() -> str | None:
    """A value piped in (``echo $KEY | motel secret set NAME``), if any arrives at once."""
    try:
        ready = bool(select.select([sys.stdin], [], [], 0.2)[0])
    except io.UnsupportedOperation:  # an in-memory stream: reading it cannot block
        ready = True
    except (OSError, ValueError):  # e.g. Windows pipes, or no stdin at all
        return None
    line = sys.stdin.readline().strip() if ready else ""
    return line or None


def _enter_in_browser(secret: Secret, tool: str) -> None:
    page = KeyPage(get_motel().secrets)
    try:
        url = page.link(tool, [secret])
        console.print(
            f"Opening a page on this computer where you can enter {escape(secret.label)}:\n"
            f"{url}\nIf no browser opens, open the link yourself. Waiting up to "
            f"{int(BROWSER_WAIT_SECONDS // 60)} minutes..."
        )
        webbrowser.open(url)
        if not page.wait([secret.name], BROWSER_WAIT_SECONDS):
            raise MotelError(
                f"{secret.name} was not entered in time.",
                hint=f"Run 'motel secret set {secret.name}' again, or use the Keys page of "
                "'motel ui'.",
            )
    finally:
        page.close()


@secret_app.command("list")
def secret_list() -> None:
    """Show which secrets are set and which tools need them (values are never shown)."""
    motel = get_motel()
    entries = secrets_view(motel.tools(), motel.secrets.names())
    if not entries:
        console.print("No secrets stored, and no installed tool needs one.")
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("Secret", style="bold")
    table.add_column("Set")
    table.add_column("Used by")
    marks = {"stored": "[green]yes[/]", "environment": "[green]yes[/] (environment variable)"}
    for entry in entries:
        description = f" [dim]({escape(entry['description'])})[/]" if entry["description"] else ""
        mark = marks.get(entry["source"], "[red]no[/]")
        table.add_row(entry["name"] + description, mark, ", ".join(entry["used_by"]) or "-")
    console.print(table)


@secret_app.command("remove")
def secret_remove(name: Annotated[str, typer.Argument(help="Secret name.")]) -> None:
    """Delete a stored secret."""
    if get_motel().secrets.remove(name):
        console.print(f"[green]✓[/] Removed {name}")
    else:
        console.print(f"No secret named {name} is stored.")
