"""The MCP gateway: one server that gives any AI app access to every installed tool.

Instead of registering one MCP tool per function (which floods the model's
context as a collection grows), the gateway exposes a small, fixed set of
discovery and execution tools:

* ``search_history``: find results of earlier runs (Motel's memory)
* ``find_tools`` / ``list_tools``: discover capabilities by plain-language query
* ``describe_tool``: parameters, usage notes, validity limits, citation
* ``run_tool``: run a function; long jobs continue in the background
* ``get_run`` / ``cancel_run``: collect or stop a background run

Tools installed while the server is running are picked up immediately.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, ParamSpec, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from motel import __version__
from motel.app import Motel
from motel.errors import MotelError
from motel.models import RunRecord, RunStatus
from motel.views import match_view, run_view, tool_summary_view, tool_view

INSTRUCTIONS = """\
Motel runs the user's scientific tools (materials science, chemistry, and more),
each wrapped from a research repository and running in its own environment.
Every run is recorded.

Recommended workflow:
1. search_history: an earlier run may already answer the question.
2. find_tools with a plain-language description of what you need.
3. describe_tool before the first use: parameters and units, usage notes,
   validity limits, and how to cite.
4. run_tool. If it returns status "running", call get_run later with the run_id.
5. Report numbers with units, the tool and run id, the citation, and any
   validity caveat. Outputs that are files are returned as absolute paths and
   can be passed to other tools.
"""

MAX_WAIT_SECONDS = 600.0

P = ParamSpec("P")
R = TypeVar("R")

_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def _client_base_dir() -> Path:
    """Folder that relative paths from the client refer to.

    Coding agents start the server in the project folder; desktop apps often
    start it in the filesystem root, where the home folder is a better guess.
    """
    cwd = Path.cwd()
    return Path.home() if cwd == Path(cwd.anchor) else cwd


def _run_view(record: RunRecord) -> dict[str, Any]:
    view = run_view(record)
    if record.status is RunStatus.RUNNING:
        view["next_step"] = f"Still running. Call get_run(run_id='{record.id}') to collect it."
    return view


def _friendly_errors(function: Callable[P, R]) -> Callable[P, R]:
    """Report Motel's anticipated errors to the model as readable tool errors."""

    @functools.wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except MotelError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #


def build_server(motel: Motel) -> MCPServer:
    """Create the MCP server bound to a :class:`Motel` instance."""
    server: MCPServer = MCPServer(
        "motel", instructions=INSTRUCTIONS, version=__version__, log_level="WARNING"
    )

    @_friendly_errors
    def find_tools(
        query: Annotated[
            str,
            Field(description="What you need, in plain words, e.g. 'relax a crystal structure'."),
        ],
        limit: Annotated[int, Field(ge=1, le=50, description="Maximum number of matches.")] = 8,
    ) -> dict[str, Any]:
        matches = [match_view(m) for m in motel.find(query, limit=limit)]
        if not matches:
            return {
                "matches": [],
                "hint": "No installed tool matches. Try other words, or list_tools. The user "
                "can add tools with 'motel onboard <repository-url>'.",
            }
        return {"matches": matches}

    @_friendly_errors
    def list_tools() -> dict[str, Any]:
        return {"tools": [tool_summary_view(tool) for tool in motel.tools()]}

    @_friendly_errors
    def describe_tool(
        tool: Annotated[str, Field(description="Tool name, as returned by find_tools.")],
    ) -> dict[str, Any]:
        return tool_view(motel.tool(tool))

    @_friendly_errors
    def run_tool(
        tool: Annotated[str, Field(description="Tool name.")],
        function: Annotated[str, Field(description="Function name within the tool.")],
        arguments: Annotated[
            dict[str, Any] | None,
            Field(description="Arguments as an object; see describe_tool for the schema."),
        ] = None,
        wait_seconds: Annotated[
            float,
            Field(
                ge=0,
                le=MAX_WAIT_SECONDS,
                description="How long to wait for the result. Longer runs keep going in the "
                "background; collect them with get_run.",
            ),
        ] = 60,
        output_dir: Annotated[
            str | None,
            Field(
                description="Folder for output files (absolute path). Default: the run's folder."
            ),
        ] = None,
        use_cache: Annotated[
            bool, Field(description="Reuse the result of an identical earlier run.")
        ] = True,
    ) -> dict[str, Any]:
        installed = motel.tool(tool)
        info = installed.function(function)
        wait = 0.0 if info.long_running else wait_seconds
        record = motel.run(
            tool,
            function,
            arguments or {},
            wait=wait,
            output_dir=Path(output_dir) if output_dir else None,
            use_cache=use_cache,
            origin="mcp",
            base_dir=_client_base_dir(),
        )
        return _run_view(record)

    @_friendly_errors
    def get_run(
        run_id: Annotated[str, Field(description="Run id returned by run_tool.")],
        wait_seconds: Annotated[
            float,
            Field(ge=0, le=MAX_WAIT_SECONDS, description="Wait up to this long for it to finish."),
        ] = 0,
    ) -> dict[str, Any]:
        return _run_view(motel.get_run(run_id, wait=wait_seconds))

    @_friendly_errors
    def cancel_run(
        run_id: Annotated[str, Field(description="Run id of a running job.")],
    ) -> dict[str, Any]:
        return _run_view(motel.cancel_run(run_id))

    @_friendly_errors
    def search_history(
        query: Annotated[
            str,
            Field(description="Words that must all appear in the run (tool, arguments, result)."),
        ] = "",
        tool: Annotated[str | None, Field(description="Only runs of this tool.")] = None,
        status: Annotated[
            RunStatus | None, Field(description="Only runs with this status.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 10,
    ) -> dict[str, Any]:
        records = motel.history_list(tool=tool, status=status, query=query or None, limit=limit)
        return {"runs": [_run_view(record) for record in records]}

    server.add_tool(
        search_history,
        description="Search earlier tool runs (newest first). Check here before running "
        "something that may already have been computed.",
        annotations=_READ_ONLY,
    )
    server.add_tool(
        find_tools,
        description="Find installed tool functions that can do what you need, ranked by relevance.",
        annotations=_READ_ONLY,
    )
    server.add_tool(
        list_tools,
        description="List every installed tool with its functions.",
        annotations=_READ_ONLY,
    )
    server.add_tool(
        describe_tool,
        description="Full details of one tool: function parameters (JSON Schema with units), "
        "usage notes, validity limits, and citation. Read before the first use.",
        annotations=_READ_ONLY,
    )
    server.add_tool(
        run_tool,
        description="Run a tool function with arguments. Returns the result, or a run_id with "
        "status 'running' if it takes longer than wait_seconds.",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, open_world_hint=False
        ),
    )
    server.add_tool(
        get_run,
        description="Status, result, output files, or error of a run; can wait for it to finish.",
        annotations=_READ_ONLY,
    )
    server.add_tool(
        cancel_run,
        description="Stop a running job.",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, open_world_hint=False
        ),
    )
    return server


def serve(
    motel: Motel | None = None,
    *,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run the gateway until the client disconnects (stdio) or the process is stopped."""
    server = build_server(motel or Motel())
    if transport == "stdio":
        server.run("stdio")
    elif transport == "http":
        server.run("streamable-http", host=host, port=port)
    else:
        raise MotelError(f"Unknown transport '{transport}'.", hint="Use 'stdio' or 'http'.")
