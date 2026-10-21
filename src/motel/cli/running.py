"""Commands to run tool functions and look at past runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.json import JSON
from rich.markup import escape
from rich.table import Table

from motel.app import Motel
from motel.cli._app import PANEL_USE, app, get_motel, settings
from motel.cli.console import console, err_console, print_json
from motel.errors import MotelError
from motel.models import FunctionInfo, RunRecord, RunStatus
from motel.registry import InstalledTool
from motel.views import run_view

JsonOption = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]

runs_app = typer.Typer(
    help="Look at past and running jobs.", invoke_without_command=True, no_args_is_help=False
)
app.add_typer(runs_app, name="runs", rich_help_panel=PANEL_USE)


# --------------------------------------------------------------------------- #
# Parsing key=value arguments
# --------------------------------------------------------------------------- #

_STRING_KINDS = {"structure", "trajectory", "spectrum", "table", "image", "file", "directory"}


def _schema_types(schema: dict[str, Any]) -> set[str]:
    types: set[str] = set()
    declared = schema.get("type")
    if isinstance(declared, str):
        types.add(declared)
    elif isinstance(declared, list):
        types.update(str(t) for t in declared)
    if schema.get("format") == "path" or schema.get("x-kind") in _STRING_KINDS:
        types.add("string")
    for value in schema.get("enum", []):
        types.add("string" if isinstance(value, str) else "number")
    for option in schema.get("anyOf", []):
        types |= _schema_types(option)
    return types


def parse_value(raw: str, schema: dict[str, Any]) -> Any:
    """Interpret a command-line value using the parameter's JSON Schema."""
    types = _schema_types(schema)
    if types == {"string"} or (types == {"string", "null"} and raw != "null"):
        return raw
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if "string" in types and not isinstance(value, str):
        compatible = (
            (isinstance(value, bool) and "boolean" in types)
            or (isinstance(value, int | float) and not isinstance(value, bool)
                and types & {"number", "integer"})
            or (isinstance(value, list) and "array" in types)
            or (isinstance(value, dict) and "object" in types)
            or (value is None and "null" in types)
        )  # fmt: skip
        if not compatible:
            return raw
    return value


def parse_assignments(pairs: list[str], function: FunctionInfo) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for pair in pairs:
        key, separator, raw = pair.partition("=")
        key = key.strip()
        if not separator or not key:
            raise MotelError(
                f"'{pair}' is not an argument of the form key=value.",
                hint=f"Expected {function.signature()}.",
            )
        args[key] = parse_value(raw, function.properties.get(key, {}))
    return args


def _load_args_option(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    text = Path(value[1:]).read_text(encoding="utf-8") if value.startswith("@") else value
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MotelError(f"--args is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MotelError("--args must be a JSON object, e.g. '{\"fmax\": 0.02}'.")
    return data


def _resolve_target(
    motel: Motel, tool_name: str, function_name: str | None, assignments: list[str]
) -> tuple[InstalledTool, FunctionInfo, list[str]]:
    """Accept ``TOOL FUNCTION``, ``TOOL.FUNCTION``, or just ``TOOL`` for one-function tools."""
    if "." in tool_name:  # tool names never contain dots
        tool_name, dotted = tool_name.split(".", 1)
        if function_name is not None:
            assignments = [function_name, *assignments]
        function_name = dotted
    tool = motel.tool(tool_name)
    if function_name is not None and "=" in function_name:
        assignments = [function_name, *assignments]
        function_name = None
    if function_name is None:
        if len(tool.functions) != 1:
            names = ", ".join(f.name for f in tool.functions)
            raise MotelError(
                f"Which function of '{tool.name}'? Available: {names}.",
                hint=f"For example: motel run {tool.name} {tool.functions[0].name} ...",
            )
        function_name = tool.functions[0].name
    return tool, tool.function(function_name), assignments


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def print_record(record: RunRecord) -> None:
    label = f"[bold]{record.tool} {record.function}[/]"
    took = f" in {record.duration:.1f} s" if record.duration is not None else ""
    if record.status is RunStatus.SUCCEEDED:
        note = " [dim](reused an identical earlier run)[/]" if record.cached else ""
        console.print(f"[green]✓[/] {label} finished{took}{note}  [dim]run {record.id}[/]")
        if record.result is not None:
            console.print(JSON.from_data(record.result, default=str))
    elif record.status is RunStatus.RUNNING:
        console.print(f"[cyan]…[/] {label} is running  [dim]run {record.id}[/]")
        console.print(
            f"  Check on it: [cyan]motel runs show {record.id}[/]   "
            f"Stop it: [cyan]motel runs cancel {record.id}[/]"
        )
    else:
        verb = "was cancelled" if record.status is RunStatus.CANCELLED else "failed"
        console.print(f"[red]✗[/] {label} {verb}{took}  [dim]run {record.id}[/]")
        error = record.error or {}
        message = escape(f"{error.get('type', 'Error')}: {error.get('message', '')}")
        console.print(f"  [red]{message}[/]")
        traceback = error.get("traceback")
        if isinstance(traceback, str) and (settings.verbose or settings.debug):
            console.print(f"[dim]{escape(traceback)}[/]")
        elif traceback:
            console.print("  [dim](add --verbose to see the traceback)[/]")
        if error.get("logs"):
            console.print(f"  [dim]Logs: {escape(str(error['logs']))}[/]")
    if record.files:
        console.print("[dim]Files:[/]")
        for path in record.files[:20]:
            console.print(f"  {escape(path)}")
        if len(record.files) > 20:
            console.print(
                f"  [dim]... and {len(record.files) - 20} more in {escape(record.workdir)}[/]"
            )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


@app.command(rich_help_panel=PANEL_USE)
def run(
    tool: Annotated[str, typer.Argument(help="Tool name (or tool.function).")],
    function: Annotated[
        str | None, typer.Argument(help="Function name.", show_default=False)
    ] = None,
    assignments: Annotated[
        list[str] | None,
        typer.Argument(help="Arguments as key=value (values are read as JSON when possible)."),
    ] = None,
    args_json: Annotated[
        str | None,
        typer.Option("--args", help="Arguments as a JSON object, or @file.json."),
    ] = None,
    output_dir: Annotated[
        Path | None, typer.Option("--output-dir", "-o", help="Folder for output files.")
    ] = None,
    background: Annotated[
        bool, typer.Option("--background", "-b", help="Start the run and return immediately.")
    ] = False,
    wait: Annotated[
        float | None,
        typer.Option(help="Stop waiting after this many seconds (the run continues)."),
    ] = None,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Run again even if an identical run exists.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Run a tool function, e.g. [cyan]motel run ase-emt relax structure=Cu.cif fmax=0.02[/]."""
    motel = get_motel()
    installed, info, pairs = _resolve_target(motel, tool, function, list(assignments or []))
    arguments = {**_load_args_option(args_json), **parse_assignments(pairs, info)}
    record = motel.runs.start(
        installed, info.name, arguments, output_dir=output_dir, use_cache=not no_cache, origin="cli"
    )
    if not (background or record.cached or record.status.finished):
        try:
            if as_json:
                record = motel.runs.wait(record.id, timeout=wait)
            else:
                message = f"Running {installed.name} {info.name}... [dim](Ctrl+C stops waiting)[/]"
                with err_console.status(message):
                    record = motel.runs.wait(record.id, timeout=wait)
        except KeyboardInterrupt:
            err_console.print(
                "\nStopped waiting; the run continues in the background.\n"
                f"  Check on it: motel runs show {record.id}\n"
                f"  Stop it:     motel runs cancel {record.id}"
            )
            raise typer.Exit(130) from None

    if as_json:
        print_json(run_view(record))
    else:
        print_record(record)
    if record.status in (RunStatus.FAILED, RunStatus.CANCELLED):
        raise typer.Exit(1)


@runs_app.callback()
def runs_list(
    ctx: typer.Context,
    tool: Annotated[str | None, typer.Option(help="Only runs of this tool.")] = None,
    search: Annotated[
        str | None, typer.Option("--search", "-s", help="Words that must appear in the run.")
    ] = None,
    status: Annotated[RunStatus | None, typer.Option(help="Only runs with this status.")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many runs to show.")] = 20,
    as_json: JsonOption = False,
) -> None:
    """List recent runs, newest first."""
    if ctx.invoked_subcommand is not None:
        return
    records = get_motel().history_list(tool=tool, status=status, query=search, limit=limit)
    if as_json:
        print_json([run_view(record) for record in records])
        return
    if not records:
        console.print("No runs yet. Start one with [cyan]motel run <tool> <function> ...[/]")
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("Run", style="dim")
    table.add_column("Tool and function", style="bold")
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Took", justify="right")
    styles = {"succeeded": "green", "failed": "red", "running": "cyan", "cancelled": "yellow"}
    for record in records:
        style = styles.get(record.status.value, "")
        table.add_row(
            record.id,
            f"{record.tool} {record.function}",
            f"[{style}]{record.status.value}[/]",
            f"{record.started_at.astimezone():%Y-%m-%d %H:%M}",
            f"{record.duration:.1f}s" if record.duration is not None else "",
        )
    console.print(table)


@runs_app.command("show")
def runs_show(
    run_id: Annotated[str, typer.Argument(help="Run id.")],
    wait: Annotated[float, typer.Option(help="Wait up to this many seconds for it to finish.")] = 0,
    as_json: JsonOption = False,
) -> None:
    """Show the status, result, files, or error of one run."""
    record = get_motel().get_run(run_id, wait=wait)
    if as_json:
        print_json(run_view(record, full=True))
        return
    console.print(f"[dim]{record.tool}.{record.function}({escape(json.dumps(record.args))})[/]")
    print_record(record)


@runs_app.command("cancel")
def runs_cancel(run_id: Annotated[str, typer.Argument(help="Run id.")]) -> None:
    """Stop a running job."""
    record = get_motel().cancel_run(run_id)
    if record.status is RunStatus.CANCELLED:
        console.print(f"[green]✓[/] Cancelled {run_id}.")
    else:
        console.print(f"Run {run_id} had already finished ({record.status.value}).")
