"""JSON views of tools, search matches, and runs.

These shapes are what agents see, via the MCP gateway or ``--json`` on the
command line, so both interfaces return identical structures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from motel.app import Match
from motel.models import RunRecord, RunStatus, utcnow
from motel.registry import InstalledTool
from motel.runtime.executor import RESPONSE_FILE, STDOUT_FILE, tail
from motel.search import describe_inputs

MAX_LIST_ITEMS = 100
MAX_STRING = 4000
TRACEBACK_LINES = 15
PROGRESS_LINES = 8


def preview(value: Any, depth: int = 0) -> tuple[Any, bool]:
    """Shorten long lists and strings; returns the preview and whether anything was cut."""
    if depth > 20:
        return "...", True
    if isinstance(value, str) and len(value) > MAX_STRING:
        return value[:MAX_STRING] + f"... [{len(value) - MAX_STRING} more characters]", True
    if isinstance(value, list):
        items = [preview(item, depth + 1) for item in value[:MAX_LIST_ITEMS]]
        shown = [item for item, _ in items]
        cut = len(value) > MAX_LIST_ITEMS or any(was_cut for _, was_cut in items)
        if len(value) > MAX_LIST_ITEMS:
            shown.append(f"... [{len(value) - MAX_LIST_ITEMS} more items]")
        return shown, cut
    if isinstance(value, dict):
        pairs = {key: preview(item, depth + 1) for key, item in value.items()}
        return (
            {key: item for key, (item, _) in pairs.items()},
            any(was_cut for _, was_cut in pairs.values()),
        )
    return value, False


def run_view(record: RunRecord, *, full: bool = False) -> dict[str, Any]:
    """A run as JSON. ``full=True`` skips truncation of the result and traceback."""
    view: dict[str, Any] = {
        "run_id": record.id,
        "status": record.status.value,
        "tool": record.tool,
        "function": record.function,
        "arguments": record.args,
        "started_at": record.started_at.isoformat(),
    }
    if record.cached:
        view["cached"] = True
        view["note"] = "Identical earlier run; result reused from the history."
    if record.status is RunStatus.SUCCEEDED:
        result, truncated = (record.result, False) if full else preview(record.result)
        view["result"] = result
        if truncated:
            view["full_result_file"] = str(Path(record.run_dir) / RESPONSE_FILE)
    if record.error:
        error = dict(record.error)
        traceback = error.get("traceback")
        if isinstance(traceback, str) and not full:
            error["traceback"] = "\n".join(traceback.splitlines()[-TRACEBACK_LINES:])
        view["error"] = error
    if record.files:
        view["files"] = record.files if full else record.files[:MAX_LIST_ITEMS]
    if record.duration is not None:
        view["duration_seconds"] = round(record.duration, 3)
    view["output_folder"] = record.workdir
    if record.status is RunStatus.RUNNING:
        # Progress for every client, including those without shell access to the logs.
        view["elapsed_seconds"] = round((utcnow() - record.started_at).total_seconds(), 1)
        latest = tail(Path(record.run_dir) / STDOUT_FILE, PROGRESS_LINES)
        if latest:
            view["latest_output"] = latest
        view["next_step"] = f"Still running. Collect it later with run id '{record.id}'."
    view["provenance"] = {
        "tool_version": record.tool_version,
        "source_commit": record.source_commit,
    }
    return view


def match_view(match: Match) -> dict[str, Any]:
    function = match.function
    return {
        "tool": match.tool.name,
        "function": function.name,
        "summary": function.summary or match.tool.manifest.summary,
        "inputs": describe_inputs(function.properties, function.required),
        "long_running": function.long_running,
        "score": match.hit.score,
    }


def tool_summary_view(tool: InstalledTool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "title": tool.manifest.display_title,
        "summary": tool.manifest.summary,
        "domains": tool.manifest.domains,
        "functions": [f.name for f in tool.functions],
        "status": tool.status,
    }


def tool_view(tool: InstalledTool) -> dict[str, Any]:
    manifest = tool.manifest
    state = tool.state
    source = manifest.source
    return {
        "name": tool.name,
        "title": manifest.display_title,
        "summary": manifest.summary,
        "description": manifest.description,
        "domains": manifest.domains,
        "tags": manifest.tags,
        "version": manifest.version,
        "status": tool.status,
        "golden_tests": state.golden_summary if state else "not built",
        "functions": [
            {
                "name": f.name,
                "summary": f.summary,
                "description": f.description or None,
                "parameters": f.parameters,
                "returns": f.returns.get("description") or None,
                "outputs": f.outputs or None,
                "long_running": f.long_running,
            }
            for f in tool.functions
        ],
        "usage_notes": tool.guide(),
        "validity": manifest.validity,
        "citation": {
            "paper": source.paper,
            "cite_as": source.citation,
            "code": source.repo,
            "commit": state.source_commit if state else source.ref,
            "license": source.license,
        },
    }
