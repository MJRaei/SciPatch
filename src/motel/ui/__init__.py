"""``motel ui``: a local dashboard to browse, run, and review tools without a terminal.

Forms are generated from each function's JSON Schema, so every installed tool
gets a usable interface automatically, replacing the separate UIs that research
projects ship (or lack).

Security: the server binds to localhost only, accepts requests only for local
host names (against DNS rebinding), and requires a random per-session token on
every API call (so websites open in the same browser cannot trigger runs).
"""

from __future__ import annotations

import re
import secrets
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from motel.app import Motel
from motel.errors import MotelError, RunNotFoundError, ToolNotFoundError
from motel.models import RunRecord, RunStatus
from motel.views import match_view, run_view, tool_summary_view, tool_view

STATIC_DIR = Path(__file__).parent / "static"
TOKEN_HEADER = "X-Motel-Token"  # noqa: S105 - a header name, not a secret
LOCAL_HOSTS = ["127.0.0.1", "localhost"]
INITIAL_WAIT_SECONDS = 2.0
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

Handler = Callable[[Request], Awaitable[Response]]


def _json_error(message: str, status: int, hint: str | None = None) -> JSONResponse:
    return JSONResponse({"error": message, "hint": hint}, status_code=status)


def create_app(motel: Motel, token: str, *, allowed_hosts: list[str] | None = None) -> Starlette:
    """Build the dashboard application."""
    uploads = motel.paths.home / "uploads"

    def api(handler: Handler) -> Handler:
        """Check the session token and turn Motel errors into JSON responses."""

        async def endpoint(request: Request) -> Response:
            if not secrets.compare_digest(request.headers.get(TOKEN_HEADER, ""), token):
                return _json_error("Missing or wrong session token.", 403)
            try:
                return await handler(request)
            except (ToolNotFoundError, RunNotFoundError) as exc:
                return _json_error(exc.message, 404, exc.hint)
            except MotelError as exc:
                return _json_error(exc.message, 400, exc.hint)

        return endpoint

    async def index(request: Request) -> Response:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    async def list_tools(request: Request) -> Response:
        tools = await run_in_threadpool(motel.tools)
        return JSONResponse([tool_summary_view(tool) for tool in tools])

    async def describe(request: Request) -> Response:
        tool = await run_in_threadpool(motel.tool, request.path_params["name"])
        return JSONResponse(tool_view(tool))

    async def find(request: Request) -> Response:
        matches = await run_in_threadpool(motel.find, request.query_params.get("q", ""), 20)
        return JSONResponse([match_view(match) for match in matches])

    def _start(body: dict[str, Any]) -> RunRecord:
        record = motel.runs.start(
            motel.tool(str(body.get("tool", ""))),
            str(body.get("function", "")),
            dict(body.get("arguments") or {}),
            origin="ui",
            base_dir=Path.home(),
        )
        if record.cached or record.status.finished:
            return record
        return motel.runs.wait(record.id, timeout=INITIAL_WAIT_SECONDS)

    async def start_run(request: Request) -> Response:
        body = await request.json()
        if not isinstance(body, dict):
            return _json_error("Expected a JSON object.", 400)
        return JSONResponse(run_view(await run_in_threadpool(_start, body)))

    async def list_runs(request: Request) -> Response:
        params = request.query_params
        status = params.get("status")
        records = await run_in_threadpool(
            lambda: motel.history_list(
                tool=params.get("tool") or None,
                status=RunStatus(status) if status else None,
                query=params.get("q") or None,
                limit=int(params.get("limit", "50")),
            )
        )
        return JSONResponse([run_view(record) for record in records])

    async def get_run(request: Request) -> Response:
        record = await run_in_threadpool(motel.get_run, request.path_params["run_id"])
        return JSONResponse(run_view(record, full=True))

    async def cancel_run(request: Request) -> Response:
        record = await run_in_threadpool(motel.cancel_run, request.path_params["run_id"])
        return JSONResponse(run_view(record))

    async def run_file(request: Request) -> Response:
        # Only files recorded as outputs of this run can be downloaded.
        record = await run_in_threadpool(motel.get_run, request.path_params["run_id"])
        index = request.path_params["index"]
        if not 0 <= index < len(record.files) or not Path(record.files[index]).is_file():
            return _json_error("No such file for this run.", 404)
        path = Path(record.files[index])
        return FileResponse(path, filename=path.name)

    async def upload(request: Request) -> Response:
        form = await request.form(max_files=1, max_fields=1)
        item = form.get("file")
        if not isinstance(item, UploadFile):
            return _json_error("No file was uploaded.", 400)
        name = _SAFE_NAME.sub("_", Path(item.filename or "upload").name).strip("._") or "upload"
        folder = uploads / secrets.token_hex(8)
        folder.mkdir(parents=True)
        target = folder / name
        size = 0
        with target.open("wb") as handle:
            while chunk := await item.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    break
                handle.write(chunk)
        if size > MAX_UPLOAD_BYTES:
            shutil.rmtree(folder, ignore_errors=True)
            return _json_error("The file is too large.", 413)
        return JSONResponse({"path": str(target)})

    routes = [
        Route("/", index),
        Route("/api/tools", api(list_tools)),
        Route("/api/tools/{name}", api(describe)),
        Route("/api/find", api(find)),
        Route("/api/run", api(start_run), methods=["POST"]),
        Route("/api/upload", api(upload), methods=["POST"]),
        Route("/api/runs", api(list_runs)),
        Route("/api/runs/{run_id}", api(get_run)),
        Route("/api/runs/{run_id}/cancel", api(cancel_run), methods=["POST"]),
        Route("/api/runs/{run_id}/files/{index:int}", api(run_file)),
    ]
    hosts = allowed_hosts or LOCAL_HOSTS
    return Starlette(
        routes=routes, middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=hosts)]
    )
