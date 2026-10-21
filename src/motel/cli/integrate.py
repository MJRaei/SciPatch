"""Commands to set up Motel and connect it to AI apps."""

from __future__ import annotations

import json
import secrets
import socket
import sys
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from motel.app import Motel
from motel.cli._app import PANEL_CONNECT, PANEL_USE, app, get_motel, reporter_of
from motel.cli.console import console
from motel.clients import APPS, SERVER_NAME, server_command
from motel.doctor import Check, run_checks
from motel.errors import ClientConfigError, MotelError
from motel.skills import skill_targets

skills_app = typer.Typer(help="Manage the Agent Skills (SKILL.md) that teach agents to use Motel.")
app.add_typer(skills_app, name="skills", rich_help_panel=PANEL_CONNECT)

DEMO_TOOL = "ase-emt"
_MARKS = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "fail": "[red]✗[/]"}


def _print_checks(checks: list[Check]) -> None:
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(width=2)
    table.add_column(style="bold")
    table.add_column(overflow="fold")
    for check in checks:
        detail = escape(check.detail)
        if check.fix:
            detail += f"\n[dim]→ {escape(check.fix)}[/]"
        table.add_row(_MARKS[check.level], check.name, detail)
    console.print(table)


@app.command(rich_help_panel=PANEL_CONNECT)
def doctor() -> None:
    """Check that everything Motel needs is installed and connected."""
    checks = run_checks(get_motel())
    _print_checks(checks)
    if any(check.level == "fail" for check in checks):
        raise typer.Exit(1)


def _connect_one(motel: Motel, key: str, *, skills: bool) -> bool:
    app_info = APPS[key]
    try:
        result = motel.connect(key, skills=skills)
    except ClientConfigError as exc:
        console.print(f"[red]✗[/] {app_info.name}: {escape(exc.message)}")
        console.print(escape(app_info.manual_instructions(server_command())))
        return False
    line = f"[green]✓[/] [bold]{app_info.name}[/]: {escape(result.message)}"
    if result.skills is not None:
        line += f"; {len(result.skills.written)} skill(s) in {result.skills.directory}"
    console.print(line)
    if result.skills and result.skills.skipped:
        console.print(f"  [yellow]![/] kept your own skills: {', '.join(result.skills.skipped)}")
    if key == "claude-desktop" and skills:
        console.print(
            "  [dim]Claude Desktop reads skills you upload: create zips with "
            "'motel skills export ~/Desktop/motel-skills --zip' and add them in Claude's "
            "Skills settings (optional; the MCP tools work without them).[/]"
        )
    console.print(f"  [dim]{app_info.restart_hint}[/]")
    return True


def _interactive_connect(motel: Motel, *, skills: bool) -> int:
    detected = [a for a in APPS.values() if a.detected()]
    if not detected:
        console.print(
            "No supported AI app was found. Motel works with: "
            + ", ".join(a.name for a in APPS.values())
            + ".\nInstall one, or configure another MCP client with [cyan]motel connect --show[/]."
        )
        return 0
    connected = 0
    for app_info in detected:
        status = " (already connected; will update)" if app_info.is_connected() else ""
        if typer.confirm(f"Connect {app_info.name}{status}?", default=True):
            connected += _connect_one(motel, app_info.key, skills=skills)
    return connected


@app.command(rich_help_panel=PANEL_CONNECT)
def connect(
    apps: Annotated[
        list[str] | None,
        typer.Argument(help=f"Apps to connect: {', '.join(APPS)}. Omit to choose interactively."),
    ] = None,
    all_detected: Annotated[
        bool, typer.Option("--all", help="Connect every app found on this computer.")
    ] = False,
    no_skills: Annotated[
        bool, typer.Option("--no-skills", help="Register the MCP server only.")
    ] = False,
    show: Annotated[
        bool, typer.Option("--show", help="Print the MCP settings to add by hand to any app.")
    ] = False,
) -> None:
    """Let your AI apps use Motel (registers the MCP server and installs skills)."""
    if show:
        command = server_command()
        console.print("Add this MCP server to your app's configuration:\n")
        console.print(json.dumps({"mcpServers": {SERVER_NAME: command.as_json_entry()}}, indent=2))
        return
    motel = get_motel()
    if all_detected:
        apps = [a.key for a in APPS.values() if a.detected()]
    if apps:
        for key in apps:
            if key not in APPS:
                raise MotelError(f"Unknown app '{key}'.", hint=f"Choose from: {', '.join(APPS)}.")
            _connect_one(motel, key, skills=not no_skills)
        return
    if not sys.stdin.isatty():
        raise MotelError(
            "Say which apps to connect.",
            hint=f"For example: motel connect claude-code ({', '.join(APPS)})",
        )
    _interactive_connect(motel, skills=not no_skills)


@app.command(rich_help_panel=PANEL_CONNECT)
def disconnect(
    app_key: Annotated[str, typer.Argument(metavar="APP", help=f"One of: {', '.join(APPS)}.")],
) -> None:
    """Remove Motel from an AI app."""
    message = get_motel().disconnect(app_key)
    console.print(f"[green]✓[/] {APPS[app_key].name}: {escape(message)}")


@app.command(rich_help_panel=PANEL_CONNECT)
def setup() -> None:
    """Guided first-time setup: check requirements, connect apps, try a tool."""
    console.print("[bold]Welcome to Motel.[/] Let's get you set up.\n")
    motel = get_motel()

    console.rule("1. Requirements", align="left", style="dim")
    checks = [c for c in run_checks(motel) if c.name not in {a.name for a in APPS.values()}]
    _print_checks(checks)
    if any(check.level == "fail" for check in checks):
        console.print("\n[red]Please fix the items marked ✗, then run 'motel setup' again.[/]")
        raise typer.Exit(1)

    console.rule("2. AI apps", align="left", style="dim")
    if sys.stdin.isatty():
        _interactive_connect(motel, skills=True)
    else:
        console.print("Run [cyan]motel connect[/] in a terminal to connect your AI apps.")

    console.rule("3. A first tool", align="left", style="dim")
    tools = motel.tools()
    if tools:
        console.print(f"You have {len(tools)} tool(s) installed: see [cyan]motel list[/].")
    elif sys.stdin.isatty() and typer.confirm(
        f"Install the example tool '{DEMO_TOOL}' (fast materials simulations, about a minute)?",
        default=True,
    ):
        with reporter_of(motel).live("Installing..."):
            motel.add(DEMO_TOOL)
        console.print(f"[green]✓[/] Installed {DEMO_TOOL}.")
    else:
        console.print(f"Install an example tool with [cyan]motel add {DEMO_TOOL}[/].")

    console.print(
        "\n[bold]You're ready.[/] Try asking your AI app:\n"
        '  [italic]"Use my Motel tools to find the equilibrium lattice constant of copper."[/]\n\n'
        "Add a research repository as a new tool:  [cyan]motel onboard <repository-url>[/]\n"
        "See all commands:                        [cyan]motel --help[/]"
    )


@app.command(rich_help_panel=PANEL_CONNECT)
def serve(
    http: Annotated[
        bool, typer.Option("--http", help="Serve over HTTP instead of stdio (for remote clients).")
    ] = False,
    host: Annotated[str, typer.Option(help="HTTP host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="HTTP port.")] = 8765,
) -> None:
    """Run the MCP server (AI apps start this automatically once connected)."""
    from motel.gateway import serve as run_server  # imported lazily: loads the MCP SDK

    if http:
        console.print(f"Serving MCP over HTTP at http://{host}:{port}/mcp (Ctrl+C to stop)")
    run_server(Motel(), transport="http" if http else "stdio", host=host, port=port)


@app.command(rich_help_panel=PANEL_USE)
def ui(
    port: Annotated[int, typer.Option(help="Port for the local web server.")] = 8770,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Don't open the browser automatically.")
    ] = False,
) -> None:
    """Open the dashboard in your browser: browse, run, and review tools without a terminal."""
    # Imported lazily: the web stack is only needed for this command.
    import uvicorn

    from motel.ui import create_app

    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise MotelError(
                f"Port {port} is already in use.", hint=f"Try 'motel ui --port {port + 1}'."
            )
    token = secrets.token_urlsafe(24)
    url = f"http://127.0.0.1:{port}/#token={token}"
    console.print(f"Motel dashboard: {url}\n[dim]Keep this window open; press Ctrl+C to stop.[/]")
    if not no_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(Motel(), token), host="127.0.0.1", port=port, log_level="warning")


@skills_app.command("sync")
def skills_sync() -> None:
    """Refresh Motel's skills in every connected app."""
    reports = get_motel().sync_skills()
    if not reports:
        console.print("No connected apps use skill files. Connect one with [cyan]motel connect[/].")
    for report in reports:
        console.print(
            f"[green]✓[/] {report.directory}: {len(report.written)} written, "
            f"{len(report.removed)} removed"
        )


@skills_app.command("install")
def skills_install(
    target: Annotated[
        str,
        typer.Argument(
            help=f"A known target ({', '.join(skill_targets())}) or a folder path.",
        ),
    ],
) -> None:
    """Install Motel's skills into an agent's skills folder (without registering MCP)."""
    targets = skill_targets()
    directory = targets[target].directory if target in targets else Path(target).expanduser()
    report = get_motel().skills.sync(directory)
    console.print(f"[green]✓[/] {len(report.written)} skill(s) in {directory}")


@skills_app.command("export")
def skills_export(
    directory: Annotated[Path, typer.Argument(help="Folder to write the skills to.")],
    as_zip: Annotated[
        bool, typer.Option("--zip", help="One zip per skill (for uploading to Claude apps).")
    ] = False,
) -> None:
    """Write Motel's skills to a folder, e.g. to upload them to Claude Desktop or claude.ai."""
    paths = get_motel().skills.export(directory.expanduser(), as_zip=as_zip)
    for path in paths:
        console.print(f"  {path}")
    console.print(f"[green]✓[/] Exported {len(paths)} skill(s).")
