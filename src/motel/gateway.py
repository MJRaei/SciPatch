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
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, ParamSpec, TypeVar

import anyio.from_thread
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ElicitRequest, ElicitRequestURLParams, InputRequiredResult, ToolAnnotations
from mcp_types.version import is_version_at_least
from pydantic import Field

from motel import __version__
from motel.app import Motel
from motel.errors import MissingSecretsError, MotelError
from motel.installs import BackgroundInstalls
from motel.keypage import LINK_LIFETIME_SECONDS, KeyPage
from motel.lock import unavailable_here
from motel.models import RunRecord, RunStatus
from motel.views import installable_view as _installable_view
from motel.views import match_view, run_view, tool_summary_view, tool_view

INSTRUCTIONS = """\
Motel runs the user's scientific tools (materials science, chemistry, and more),
each wrapped from a research repository and running in its own environment.
Every run is recorded.

Recommended workflow:
1. search_history: an earlier run may already answer the question.
2. find_tools with a plain-language description of what you need. If the best
   match is listed under "not_installed", ask the user whether to install it
   (installs download packages, often hundreds of MB, and take minutes); if they
   agree, call install_tool and call it again until it reports "ready".
3. describe_tool before the first use: parameters and units, usage notes,
   validity limits, and how to cite.
4. run_tool. If it returns status "running", call get_run later with the run_id.
5. Report numbers with units, the tool and run id, the citation, and any
   validity caveat. Outputs that are files are returned as absolute paths and
   can be passed to other tools.

Never ask the user to type an API key or password into the chat. If a tool
needs a key that is not set, run_tool returns a link to a page on the user's
computer where they can enter it; give them the link, then run the tool again.
"""

MAX_WAIT_SECONDS = 600.0
#: How long a run waits for the user to enter a key after agreeing to open the page.
KEY_WAIT_SECONDS = 300.0
#: The protocol revision that asks for input by returning an InputRequiredResult.
_INPUT_REQUIRED_VERSION = "2026-07-28"
_KEY_REQUEST = "motel-api-key"

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


def _ask_for_secrets(
    error: MissingSecretsError, page: KeyPage, ctx: Context
) -> InputRequiredResult | None:
    """Get missing keys from the user on a local page, never through the chat.

    Apps that can open links for a server (MCP URL elicitation) are asked to open
    the page, and the run continues once the key is saved: on 2026-07-28
    connections through an ``InputRequiredResult`` that the app answers by
    retrying the call, on older ones through a request in the middle of the call.

    Returns the ``InputRequiredResult`` to send, or None once the keys are set.
    Otherwise raises a ``ToolError`` with a link for the agent to pass on.
    """
    names = [secret.name for secret in error.secrets]
    capabilities = ctx.client_capabilities
    elicitation = capabilities.elicitation if capabilities else None
    if elicitation is None or elicitation.url is None:
        raise _link_error(error, page)
    message = (
        f"The tool '{error.tool}' needs {_needed(error)}. Enter it on this page; it stays on "
        "your computer."
    )
    input_required = is_version_at_least(ctx.protocol_version or "", _INPUT_REQUIRED_VERSION)
    if input_required:
        response = (ctx.input_responses or {}).get(_KEY_REQUEST)
        if response is None:
            url = page.link(error.tool, error.secrets)
            request = ElicitRequest(params=ElicitRequestURLParams(message=message, url=url))
            return InputRequiredResult(input_requests={_KEY_REQUEST: request})
        accepted = getattr(response, "action", None) == "accept"
    else:
        elicitation_id = uuid.uuid4().hex
        url = page.link(error.tool, error.secrets)
        result = anyio.from_thread.run(ctx.elicit_url, message, url, elicitation_id)
        accepted = result.action == "accept"
    if not accepted:
        raise _link_error(error, page, "The user did not open the page.")
    if not page.wait(names, KEY_WAIT_SECONDS):
        raise _link_error(error, page, "The key was not entered in time.")
    if not input_required:
        anyio.from_thread.run(ctx.session.send_elicit_complete, elicitation_id)
    return None


def _needed(error: MissingSecretsError) -> str:
    return " and ".join(secret.label for secret in error.secrets)


def _link_error(error: MissingSecretsError, page: KeyPage, note: str | None = None) -> ToolError:
    url = page.link(error.tool, error.secrets)
    return ToolError(
        f"{error.message}" + (f" {note}" if note else "") + f"\nAsk the user to open this link "
        f"and enter {_needed(error)} there (it stays on their computer and is never shown to "
        f"you): {url}\nThe link works once, for {LINK_LIFETIME_SECONDS // 60} minutes. Do not "
        "ask for the key in the chat. When they are done, run the tool again."
    )


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
    key_page = KeyPage(motel.secrets)
    installs = BackgroundInstalls(motel.paths)

    def require_installed(tool: str) -> None:
        """A clear way forward when the tool exists in a catalog but is not installed."""
        if motel.registry.exists(tool):
            return
        entry = motel.catalog_entry(tool)
        if entry is not None:
            raise MotelError(
                f"'{tool}' is not installed; it is available from the '{entry.catalog}' catalog.",
                hint=f"Ask the user, then call install_tool(tool='{tool}').",
            )

    @_friendly_errors
    def find_tools(
        query: Annotated[
            str,
            Field(description="What you need, in plain words, e.g. 'relax a crystal structure'."),
        ],
        limit: Annotated[int, Field(ge=1, le=50, description="Maximum number of matches.")] = 8,
    ) -> dict[str, Any]:
        found = motel.find(query, limit=limit)
        matches = [match_view(m) for m in found]
        best = max((m.hit.score for m in found), default=0.0)
        suggestions = [
            _installable_view(entry)
            for entry, score in motel.find_installable(query)
            if score >= 0.5 * best
        ]
        result: dict[str, Any] = {"matches": matches}
        if suggestions:
            result["not_installed"] = suggestions
            result["hint"] = (
                "Tools under not_installed match too. Ask the user before installing one with "
                "install_tool: installs download packages and take minutes."
            )
        elif not matches:
            result["hint"] = (
                "No tool matches. Try other words, or list_tools. The user can add tools "
                "with 'motel onboard <repository-url>'."
            )
        return result

    @_friendly_errors
    def list_tools() -> dict[str, Any]:
        return {"tools": [tool_summary_view(tool) for tool in motel.tools()]}

    @_friendly_errors
    def describe_tool(
        tool: Annotated[str, Field(description="Tool name, as returned by find_tools.")],
    ) -> dict[str, Any]:
        require_installed(tool)
        return tool_view(motel.tool(tool))

    @_friendly_errors
    def install_tool(
        tool: Annotated[str, Field(description="Tool name from find_tools' not_installed list.")],
        wait_seconds: Annotated[
            float,
            Field(ge=0, le=MAX_WAIT_SECONDS, description="Wait up to this long for it to finish."),
        ] = 60,
    ) -> dict[str, Any]:
        if motel.registry.exists(tool) and motel.tool(tool).usable:
            return {
                "tool": tool,
                "status": "ready",
                "next_step": f"Call describe_tool(tool='{tool}') before the first run.",
            }
        entry = motel.catalog_entry(tool)
        if entry is None:
            raise MotelError(
                f"No catalog has a tool named '{tool}'.",
                hint="Use a name from find_tools. The user can add new tools with "
                "'motel onboard <repository-url>'.",
            )
        reason = unavailable_here(entry.folder)
        if reason:
            raise MotelError(f"'{tool}' cannot be installed on this computer: {reason}")
        install = installs.start(tool)
        if install.thread is not None:
            install.thread.join(timeout=wait_seconds)
        if install.running:
            return {
                "tool": tool,
                "status": "installing",
                "elapsed_seconds": install.elapsed,
                "latest_steps": list(install.reporter.lines),
                "next_step": f"Call install_tool(tool='{tool}') again to wait for it; "
                "installs usually take a few minutes.",
            }
        if install.error:
            return {"tool": tool, "status": "failed", "error": install.error}
        return {
            "tool": tool,
            "status": "ready",
            "elapsed_seconds": install.elapsed,
            "next_step": f"Call describe_tool(tool='{tool}') before the first run.",
        }

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
        ctx: Context | None = None,
    ) -> dict[str, Any] | InputRequiredResult:
        require_installed(tool)
        installed = motel.tool(tool)
        info = installed.function(function)
        wait = 0.0 if info.long_running else wait_seconds

        def start() -> RunRecord:
            return motel.run(
                tool,
                function,
                arguments or {},
                wait=wait,
                output_dir=Path(output_dir) if output_dir else None,
                use_cache=use_cache,
                origin="mcp",
                base_dir=_client_base_dir(),
            )

        try:
            record = start()
        except MissingSecretsError as exc:
            if ctx is None:
                raise
            if (request := _ask_for_secrets(exc, key_page, ctx)) is not None:
                return request
            record = start()  # the user entered the key
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
        install_tool,
        description="Install a tool listed under not_installed by find_tools (only after the "
        "user agrees: installs download packages and take minutes). Returns status "
        "'installing' while it runs; call again until 'ready'.",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, open_world_hint=True
        ),
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
