"""Starting, waiting for, and cancelling tool runs.

Every run executes in the background in its own process group, and its record
in the history is finalized by whoever looks at it next ("refresh on read").
That gives one model for quick calls and multi-hour simulations alike: a caller
waits as long as it likes, and a run that outlives the wait keeps going and can
be collected later with its id.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from motel.errors import InvalidArgumentsError, MissingSecretsError, RunError, RunNotFoundError
from motel.history import RunStore, new_run_id
from motel.models import FunctionInfo, RunRecord, RunStatus, utcnow
from motel.paths import MotelPaths
from motel.registry import InstalledTool
from motel.runtime import executor
from motel.runtime.results import absolutize_paths, list_output_files, looks_like_path
from motel.schema import matches, normalize, type_label

#: Parameter kinds whose values are file or folder paths.
PATH_KINDS = frozenset(
    {"structure", "trajectory", "spectrum", "table", "image", "file", "directory"}
)


class RunManager:
    """Owns the lifecycle of runs started by this process."""

    def __init__(self, paths: MotelPaths, store: RunStore) -> None:
        self.paths = paths
        self.store = store
        self._children: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- start

    def start(
        self,
        tool: InstalledTool,
        function: str,
        args: dict[str, Any] | None = None,
        *,
        output_dir: Path | None = None,
        use_cache: bool = True,
        origin: str = "cli",
        base_dir: Path | None = None,
    ) -> RunRecord:
        """Start ``tool.function(**args)`` and return its (running or cached) record.

        Relative file paths in ``args`` are resolved against ``base_dir``
        (default: the current directory). Outputs go to ``output_dir``, or to the
        run's own folder when it is not given.
        """
        if not tool.usable:
            raise RunError(
                f"Tool '{tool.name}' is not ready (status: {tool.status}).",
                hint=f"Rebuild it with 'motel rebuild {tool.name}'.",
            )
        info = tool.function(function)
        runtime = tool.runtime
        missing = [s for s in tool.manifest.environment.secrets if s.name not in runtime.secrets]
        if missing:
            raise MissingSecretsError(tool.name, missing)
        arguments = resolve_path_arguments(dict(args or {}), info, base_dir or Path.cwd())
        arguments = validate_arguments(tool.name, info, arguments)

        cache_key = compute_cache_key(tool, function, arguments)
        if use_cache and info.cache and output_dir is None:
            cached = self.store.find_cached(cache_key)
            if cached is not None and all(Path(f).exists() for f in cached.files):
                return cached.model_copy(update={"cached": True})

        run_id = new_run_id()
        run_dir = self.paths.runs / run_id
        workdir = output_dir.expanduser().resolve() if output_dir else run_dir
        record = RunRecord(
            id=run_id,
            tool=tool.name,
            function=function,
            args=arguments,
            tool_version=tool.manifest.version,
            source_commit=tool.state.source_commit if tool.state else None,
            workdir=str(workdir),
            run_dir=str(run_dir),
            origin=origin,
            cache_key=cache_key,
        )
        process = executor.launch(
            runtime,
            function,
            arguments,
            workdir=workdir,
            run_dir=run_dir,
            extra_env={"MOTEL_RUN_ID": run_id, "MOTEL_RUN_DIR": str(run_dir)},
        )
        record.pid = process.pid
        self.store.insert(record)
        with self._lock:
            self._children[run_id] = process
        return record

    # ------------------------------------------------------------ lifecycle

    def get(self, run_id: str) -> RunRecord:
        record = self.store.get(run_id)
        if record is None:
            raise RunNotFoundError(
                f"No run with id '{run_id}'.", hint="List recent runs with 'motel runs'."
            )
        return self._refresh(record)

    def wait(self, run_id: str, timeout: float | None = None) -> RunRecord:
        """Wait until the run finishes or ``timeout`` seconds pass (``None``: forever)."""
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        delay = 0.05
        while True:
            record = self.get(run_id)
            if record.status.finished:
                return record
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return record
            step = delay if remaining is None else min(delay, remaining)
            process = self._children.get(run_id)
            if process is not None:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=step)
            else:
                time.sleep(step)
            delay = min(delay * 2, 1.0)

    def cancel(self, run_id: str) -> RunRecord:
        record = self.get(run_id)
        if record.status.finished:
            return record
        with self._lock:
            process = self._children.pop(run_id, None)
        if record.pid:
            executor.terminate(record.pid, process=process, run_dir=Path(record.run_dir))
        self.store.finish(
            run_id,
            status=RunStatus.CANCELLED,
            error={"type": "Cancelled", "message": "The run was cancelled."},
            finished_at=utcnow(),
            duration=_elapsed(record.started_at),
        )
        return self.get(run_id)

    def _refresh(self, record: RunRecord) -> RunRecord:
        """Finalize a running record if its process has finished."""
        if record.status.finished:
            return record
        run_dir = Path(record.run_dir)
        response = executor.read_response(run_dir)
        process = self._children.get(record.id)
        returncode: int | None = None
        if response is None:
            if process is not None:
                returncode = process.poll()
                alive = returncode is None
            else:
                alive = executor.run_process_alive(record.pid, run_dir)
            if alive:
                return record
            # The process may have written its response just before exiting.
            response = executor.read_response(run_dir) or executor.missing_response_error(
                run_dir, returncode
            )
        self._finalize(record, response)
        with self._lock:
            finished = self._children.pop(record.id, None)
        if finished is not None:
            finished.wait()  # reap the child
        refreshed = self.store.get(record.id)
        return refreshed or record

    def _finalize(self, record: RunRecord, response: dict[str, Any]) -> None:
        workdir = Path(record.workdir)
        started = record.started_at.timestamp()
        if response.get("ok"):
            self.store.finish(
                record.id,
                status=RunStatus.SUCCEEDED,
                result=absolutize_paths(response.get("value"), workdir),
                files=list_output_files(workdir, since=started, run_dir=Path(record.run_dir)),
                finished_at=utcnow(),
                duration=response.get("duration") or _elapsed(record.started_at),
            )
        else:
            error = dict(response.get("error") or {})
            error.setdefault("type", "Error")
            error["logs"] = str(Path(record.run_dir) / executor.STDERR_FILE)
            self.store.finish(
                record.id,
                status=RunStatus.FAILED,
                error=error,
                files=list_output_files(workdir, since=started, run_dir=Path(record.run_dir)),
                finished_at=utcnow(),
                duration=response.get("duration") or _elapsed(record.started_at),
            )


# --------------------------------------------------------------------------- #
# Arguments
# --------------------------------------------------------------------------- #


def validate_arguments(tool: str, info: FunctionInfo, args: dict[str, Any]) -> dict[str, Any]:
    """Catch missing, unknown, and wrongly typed arguments before starting a process.

    Returns the arguments with harmless normalizations applied (``500.0`` → ``500``
    for integer parameters).
    """
    properties = info.properties
    normalized = {k: normalize(v, properties.get(k, {})) for k, v in args.items()}
    missing = [name for name in info.required if name not in normalized]
    unknown = [] if info.accepts_extra_arguments else [k for k in args if k not in properties]
    mistyped = [
        f"{name} should be {type_label(properties[name])}, not {value!r}"
        for name, value in normalized.items()
        if name in properties and not matches(value, properties[name])
    ]
    if not missing and not unknown and not mistyped:
        return normalized
    problems = []
    if missing:
        problems.append(f"missing required argument(s): {', '.join(missing)}")
    if unknown:
        problems.append(f"unknown argument(s): {', '.join(unknown)}")
    problems.extend(mistyped)
    raise InvalidArgumentsError(
        f"{tool}.{info.name}: {'; '.join(problems)}.",
        hint=f"Expected {info.signature()}. See 'motel info {tool}' for details.",
    )


def _is_path_parameter(schema: dict[str, Any]) -> bool:
    if schema.get("format") == "path" or schema.get("x-kind") in PATH_KINDS:
        return True
    return any(_is_path_parameter(option) for option in schema.get("anyOf", []))


def resolve_path_arguments(
    args: dict[str, Any], info: FunctionInfo, base_dir: Path
) -> dict[str, Any]:
    """Make relative file paths absolute, so the tool can find them from its run folder.

    Parameters declared as paths are always resolved; other string values are
    resolved only when they look like a path and the file exists.
    """
    resolved: dict[str, Any] = {}
    for key, value in args.items():
        schema = info.properties.get(key, {})
        resolved[key] = _resolve_value(value, base_dir, declared=_is_path_parameter(schema))
    return resolved


def _resolve_value(value: Any, base_dir: Path, *, declared: bool) -> Any:
    if isinstance(value, list):
        return [_resolve_value(item, base_dir, declared=declared) for item in value]
    if not isinstance(value, str) or not value or "\n" in value:
        return value
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    candidate = base_dir / path
    if declared or (looks_like_path(value) and candidate.exists()):
        return str(candidate.resolve())
    return value


def compute_cache_key(tool: InstalledTool, function: str, args: dict[str, Any]) -> str:
    """Identity of a call: tool build, function, and arguments (file *contents*, not names)."""
    state = tool.state
    material = {
        "tool": tool.name,
        "version": tool.manifest.version,
        "package": package_fingerprint(tool.package_dir),
        "source_commit": state.source_commit if state else None,
        "environment": state.env_fingerprint if state else None,
        "function": function,
        "args": _content_addressed(args),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()


#: Folders of a tool package that never affect results (rebuilt, or test-only).
_UNHASHED_DIRS = frozenset(
    {"source", ".motel", ".git", "tests", "__pycache__", ".claude", ".agents"}
)


def package_fingerprint(package_dir: Path) -> str:
    """Hash of the tool package's own files (``api.py``, ``motel.yaml``, helpers, data).

    Part of the cache key, so editing a tool's code invalidates earlier results
    even when its version number is unchanged.
    """
    digest = hashlib.sha256()
    root = package_dir.resolve()
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _UNHASHED_DIRS)
        for name in sorted(files):
            path = Path(current) / name
            digest.update(str(path.relative_to(root)).encode())
            digest.update(_hash_file(path).encode())
    return digest.hexdigest()


def _content_addressed(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _content_addressed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_content_addressed(item) for item in value]
    if isinstance(value, str) and Path(value).is_absolute():
        path = Path(value)
        if path.is_file():
            return {"file_sha256": _hash_file(path)}
        if path.is_dir():
            entries = sorted(
                (str(p.relative_to(path)), _hash_file(p)) for p in path.rglob("*") if p.is_file()
            )
            return {"dir_sha256": hashlib.sha256(json.dumps(entries).encode()).hexdigest()}
    return value


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _elapsed(started: datetime) -> float:
    return round((utcnow() - started).total_seconds(), 3)
