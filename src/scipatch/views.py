"""JSON views of tools, search matches, and runs.

These shapes are what agents see, via the MCP gateway or ``--json`` on the
command line, so both interfaces return identical structures.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scipatch import hardware, maturity
from scipatch.app import Match
from scipatch.catalogs import CatalogEntry, CatalogStore
from scipatch.lock import format_size, platform_summary, runs_in_wsl, tested_size, unavailable_here
from scipatch.manifest import Resources
from scipatch.models import RunRecord, RunStatus, utcnow
from scipatch.platforms import label as platform_label
from scipatch.registry import InstalledTool
from scipatch.runtime.executor import RESPONSE_FILE, STDOUT_FILE, tail
from scipatch.search import describe_inputs
from scipatch.settings import Settings

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


def maturity_view(tool: InstalledTool, alternatives: list[str] | None = None) -> dict[str, Any]:
    """A tool's maturity level, what it means, and the evidence behind it.

    ``alternatives`` are better-established tools for the same kind of task,
    suggested for cross-checks in the caution that experimental tools carry.
    """
    manifest = tool.manifest
    origin = tool.state.installed_from if tool.state else str(tool.package_dir)
    view: dict[str, Any] = {
        "level": tool.maturity,
        "meaning": maturity.MEANING[tool.maturity],
        "evidence": maturity.evidence(manifest),
        "declared_in": CatalogStore(tool.paths).describe_origin(origin),
    }
    if tool.maturity != manifest.maturity:
        view["lowered_by_user"] = f"declared '{manifest.maturity}'; lowered on this computer"
    caution = maturity.caution(tool.maturity, alternatives or [])
    if caution:
        view["caution"] = caution
    return view


def run_view(
    record: RunRecord, *, full: bool = False, tool: InstalledTool | None = None
) -> dict[str, Any]:
    """A run as JSON. ``full=True`` skips truncation of the result and traceback.

    With the run's ``tool``, the view says the tool's maturity level, and for an
    experimental tool, how to treat its results.
    """
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
    if tool is not None:
        view["maturity"] = tool.maturity
        caution = maturity.caution(tool.maturity, [])
        if caution and record.status is RunStatus.SUCCEEDED:
            view["caution"] = caution
    return view


def match_view(match: Match) -> dict[str, Any]:
    function = match.function
    view = {
        "tool": match.tool.name,
        "function": function.name,
        "summary": function.summary or match.tool.manifest.summary,
        "inputs": describe_inputs(function.properties, function.required),
        "long_running": function.long_running,
        "maturity": match.tool.maturity,
        "score": match.hit.score,
    }
    needs = match.tool.manifest.resources_for(function.name)
    if words := hardware.describe_needs(needs):
        view["needs"] = words
        fit = _fit(needs, match.tool)
        if fit.blockers:
            view["cannot_run_here"] = fit.blockers
        elif fit.warnings:
            view["warnings"] = fit.warnings
    return view


def _fit(needs: Resources, tool: InstalledTool) -> hardware.Fit:
    return hardware.assess(needs, hardware.detect(), use_gpu=Settings(tool.paths.config).use_gpu)


def resources_view(tool: InstalledTool) -> dict[str, Any]:
    """What a tool needs, what this computer has, and how they fit (per function if different)."""
    manifest = tool.manifest
    needs = manifest.resources_for()
    view: dict[str, Any] = {
        "needs": hardware.describe_needs(needs) or ["nothing beyond a CPU"],
        "this_computer": hardware.detect().summary(),
        **_fit_view(_fit(needs, tool)),
    }
    functions = {}
    for function in tool.functions:
        own = manifest.resources_for(function.name)
        if own != needs:
            functions[function.name] = {
                "needs": hardware.describe_needs(own),
                **_fit_view(_fit(own, tool)),
            }
    if functions:
        view["functions"] = functions
    size = tool.state.env_size_mb if tool.state else None
    if size:
        view["disk_space"] = f"{format_size(size)} for its environment, plus files it downloads"
    return view


def _fit_view(fit: hardware.Fit) -> dict[str, Any]:
    view: dict[str, Any] = {"device": fit.device}
    if fit.blockers:
        view["cannot_run_here"] = fit.blockers
    if fit.warnings:
        view["warnings"] = fit.warnings
    if fit.notes:
        view["notes"] = fit.notes
    return view


def installable_view(entry: CatalogEntry) -> dict[str, Any]:
    """A catalog tool that is not installed yet, as find_tools suggests it."""
    manifest = entry.manifest
    needs = manifest.resources_for()
    reason = unavailable_here(entry.folder) or hardware.install_blocker(needs)
    size = tested_size(entry.folder)
    return {
        "tool": manifest.name,
        "title": manifest.display_title,
        "summary": manifest.summary,
        "catalog": entry.catalog,
        "maturity": manifest.maturity,
        "installable_here": reason is None,
        **({"why_not": reason} if reason else {}),
        **({"needs": words} if (words := hardware.describe_needs(needs)) else {}),
        **({"download_size": size} if size else {}),
    }


def tool_summary_view(tool: InstalledTool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "title": tool.manifest.display_title,
        "summary": tool.manifest.summary,
        "domains": tool.manifest.domains,
        "functions": [f.name for f in tool.functions],
        "status": tool.status,
        "maturity": tool.maturity,
    }


def tool_view(tool: InstalledTool, alternatives: list[str] | None = None) -> dict[str, Any]:
    """Everything about a tool; ``alternatives`` as for :func:`maturity_view`."""
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
        "maturity": maturity_view(tool, alternatives),
        "resources": resources_view(tool),
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
        "secrets_needed": [
            {
                "name": secret.name,
                "description": secret.description,
                "get_one_at": secret.url,
                "set": secret.name in tool.runtime.secrets,
            }
            for secret in manifest.environment.secrets
        ],
        "platforms": _platforms_view(tool.package_dir),
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


def _platforms_view(package_dir: Path) -> dict[str, str] | None:
    """Where the tool can be installed: "available", or the reason it cannot."""
    summary = platform_summary(package_dir)
    if summary is None:
        return None
    view = {platform_label(name): reason or "available" for name, reason in summary.items()}
    if runs_in_wsl(summary):
        view[platform_label("win-64")] = "available inside WSL (no Windows build)"
    return view


def secrets_view(tools: Iterable[InstalledTool], stored: Iterable[str]) -> list[dict[str, Any]]:
    """Every secret that is stored or needed, and the tools that use it (never values).

    ``source`` says where a tool gets it: an environment variable (which wins),
    the store, or nowhere yet (None).
    """
    stored = set(stored)
    entries: dict[str, dict[str, Any]] = {}
    for tool in tools:
        for secret in tool.manifest.environment.secrets:
            entry = entries.setdefault(
                secret.name,
                {"name": secret.name, "description": None, "get_one_at": None, "used_by": []},
            )
            entry["description"] = entry["description"] or secret.description
            entry["get_one_at"] = entry["get_one_at"] or secret.url
            entry["used_by"].append(tool.name)
    for name in stored:
        entries.setdefault(
            name, {"name": name, "description": None, "get_one_at": None, "used_by": []}
        )
    for name, entry in entries.items():
        in_environment = bool(os.environ.get(name))
        entry["source"] = "environment" if in_environment else "stored" if name in stored else None
    return [entries[name] for name in sorted(entries)]
