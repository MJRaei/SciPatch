"""Launch the runtime shim with a tool's own interpreter.

Motel never imports tool code into its own process. Every describe or call
request runs ``<tool env python> -I shim.py <command> request.json`` in a child
process, so tools with conflicting dependencies coexist. Requests and responses
travel as JSON files in a per-run directory, alongside the child's logs::

    runs/<run-id>/request.json    what was asked
    runs/<run-id>/response.json   what the shim answered (written atomically)
    runs/<run-id>/stdout.log      anything the tool printed
    runs/<run-id>/stderr.log      warnings and tracebacks
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from motel import wsl
from motel.errors import BuildError

SHIM_PATH = Path(__file__).with_name("shim.py")

REQUEST_FILE = "request.json"
RESPONSE_FILE = "response.json"
STDOUT_FILE = "stdout.log"
STDERR_FILE = "stderr.log"
INTERNAL_FILES = frozenset({REQUEST_FILE, RESPONSE_FILE, STDOUT_FILE, STDERR_FILE})

IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class ToolRuntime:
    """Everything needed to execute a tool's functions in its environment."""

    python: Path
    env_dir: Path
    package_dir: Path
    entrypoint: str
    functions: list[str] | None = None
    variables: dict[str, str] = field(default_factory=dict)
    #: Upstream checkout, exposed to tools as ``MOTEL_SOURCE_DIR`` (for scripts and data).
    source_dir: Path | None = None
    #: Secrets the tool declared and the user provided (e.g. API keys).
    secrets: dict[str, str] = field(default_factory=dict)
    #: On Windows, a tool with only Linux builds runs in this environment inside WSL.
    linux: wsl.LinuxEnvironment | None = None

    def ready(self) -> bool:
        """Whether the environment has been built."""
        if self.linux is not None:
            return (self.env_dir / wsl.POINTER).exists()
        return self.python.exists()

    def child_environment(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Process environment that behaves like an activated tool environment."""
        if self.linux is not None:
            return self._wsl_environment(self.linux, extra)
        env = {k: v for k, v in os.environ.items() if k not in _LEAKY_VARIABLES}
        bin_dirs = environment_bin_dirs(self.env_dir)
        env["PATH"] = os.pathsep.join([*map(str, bin_dirs), env.get("PATH", "")])
        env["VIRTUAL_ENV"] = str(self.env_dir)
        env["PYTHONIOENCODING"] = "utf-8"
        if self.source_dir is not None:
            env["MOTEL_SOURCE_DIR"] = str(self.source_dir)
        env.update(self.variables)
        env.update(self.secrets)
        env.update(extra or {})
        return env

    def _wsl_environment(
        self, linux: wsl.LinuxEnvironment, extra: dict[str, str] | None
    ) -> dict[str, str]:
        """Variables for the Linux process, handed over through WSLENV (never argv)."""
        distro = linux.distro
        variables = {
            "PYTHONIOENCODING": "utf-8",
            "VIRTUAL_ENV": linux.prefix,
            "MOTEL_PREPEND_PATH": f"{linux.prefix}/bin",
            "MOTEL_WSL_ROOT": distro.mount_root,
        }
        if self.source_dir is not None:
            variables["MOTEL_SOURCE_DIR"] = distro.to_linux(self.source_dir)
        variables.update(self.variables)
        variables.update(self.secrets)
        variables.update(extra or {})
        env = distro.environment(variables)
        for name in _LEAKY_VARIABLES:
            env.pop(name, None)
        return env


# Variables from Motel's own environment that would confuse a tool's interpreter.
_LEAKY_VARIABLES = frozenset(
    {
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "__PYVENV_LAUNCHER__",
    }
)


def environment_bin_dirs(env_dir: Path) -> list[Path]:
    if IS_WINDOWS:
        return [env_dir / "Scripts", env_dir, env_dir / "Library" / "bin"]
    return [env_dir / "bin"]


def environment_python(env_dir: Path) -> Path:
    """Interpreter path for a venv or conda environment."""
    if IS_WINDOWS:
        for candidate in (env_dir / "Scripts" / "python.exe", env_dir / "python.exe"):
            if candidate.exists():
                return candidate
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def _request(runtime: ToolRuntime, response_path: Path, **extra: Any) -> dict[str, Any]:
    return {
        "package_dir": str(runtime.package_dir),
        "entrypoint": runtime.entrypoint,
        "functions": runtime.functions,
        "response_path": str(response_path),
        **extra,
    }


def _command(
    runtime: ToolRuntime, command: str, request_path: Path, cwd: Path | None = None
) -> list[str]:
    if runtime.linux is not None:
        distro = runtime.linux.distro
        shim, request = distro.to_linux(SHIM_PATH), distro.to_linux(request_path)
        return distro.command([runtime.linux.python, "-I", shim, command, request], cwd=cwd)
    return [str(runtime.python), "-I", str(SHIM_PATH), command, str(request_path)]


def _detach_kwargs() -> dict[str, Any]:
    """Run children in their own process group so a whole run can be cancelled."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        return {"start_new_session": True}


def launch(
    runtime: ToolRuntime,
    function: str,
    args: dict[str, Any],
    *,
    workdir: Path,
    run_dir: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    """Start a call in the background and return the child process."""
    if not runtime.ready():
        raise BuildError(
            f"The environment for this tool is missing ({runtime.python}).",
            hint="Rebuild it with 'motel rebuild <tool>'.",
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)
    request_path = run_dir / REQUEST_FILE
    request = _request(runtime, run_dir / RESPONSE_FILE, function=function, args=args)
    request_path.write_text(json.dumps(request, indent=1), encoding="utf-8")
    with (run_dir / STDOUT_FILE).open("wb") as stdout, (run_dir / STDERR_FILE).open("wb") as stderr:
        return subprocess.Popen(
            _command(runtime, "call", request_path, workdir),
            cwd=workdir,
            env=runtime.child_environment(extra_env),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            **_detach_kwargs(),
        )


def read_response(run_dir: Path) -> dict[str, Any] | None:
    """The shim's answer, or ``None`` if it has not finished writing one."""
    path = run_dir / RESPONSE_FILE
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return {"ok": False, "error": {"type": "ProtocolError", "message": "Unreadable response."}}
    return data


def call_sync(
    runtime: ToolRuntime,
    function: str,
    args: dict[str, Any],
    *,
    workdir: Path,
    run_dir: Path,
    timeout: float | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a call to completion and return the shim's response (used by golden tests)."""
    process = launch(runtime, function, args, workdir=workdir, run_dir=run_dir, extra_env=extra_env)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate(process.pid, process=process, run_dir=run_dir)
        return {
            "ok": False,
            "error": {"type": "Timeout", "message": f"Did not finish within {timeout:g} s."},
        }
    return read_response(run_dir) or missing_response_error(run_dir, process.returncode)


@dataclass(frozen=True)
class Description:
    """What introspection found: raw function descriptions and the interpreter version."""

    functions: list[dict[str, Any]]
    python_version: str | None


def describe(runtime: ToolRuntime, *, work_dir: Path, timeout: float = 600) -> Description:
    """Ask the shim to introspect the tool's functions."""
    work_dir.mkdir(parents=True, exist_ok=True)
    request_path = work_dir / "describe-request.json"
    response_path = work_dir / "describe-response.json"
    response_path.unlink(missing_ok=True)
    request_path.write_text(json.dumps(_request(runtime, response_path)), encoding="utf-8")
    log_path = work_dir / "describe.log"
    with log_path.open("wb") as log:
        try:
            completed = subprocess.run(
                _command(runtime, "describe", request_path, work_dir),
                cwd=work_dir,
                env=runtime.child_environment(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BuildError(
                f"Importing the tool took longer than {timeout:g} s.", log_path=str(log_path)
            ) from exc
    try:
        response = json.loads(response_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BuildError(
            f"The tool's interpreter exited (code {completed.returncode}) before describing "
            f"its functions:\n{tail(log_path)}",
            hint="The environment may be incomplete; check the log above.",
            log_path=str(log_path),
        ) from None
    if not response.get("ok"):
        error = response.get("error", {})
        raise BuildError(
            f"Could not import '{runtime.entrypoint}': {error.get('type')}: {error.get('message')}"
            f"\n{error.get('traceback', '')}".rstrip(),
            hint="A missing package usually means it must be added to environment.packages.",
            log_path=str(log_path),
        )
    return Description(functions=response["functions"], python_version=response.get("python"))


def missing_response_error(run_dir: Path, returncode: int | None) -> dict[str, Any]:
    """Build an error payload for a child that died without answering."""
    code = "unknown" if returncode is None else str(returncode)
    if returncode is not None and returncode < 0:
        code = f"{returncode} (killed by signal {-returncode})"
    details = tail(run_dir / STDERR_FILE)
    message = f"The tool process exited (code {code}) without returning a result."
    if details:
        message += f"\nLast lines of stderr:\n{details}"
    return {"ok": False, "error": {"type": "ProcessExited", "message": message}}


def tail(path: Path, lines: int = 25, *, max_bytes: int = 64 * 1024) -> str:
    """Last ``lines`` lines of a text file, reading at most ``max_bytes`` from its end."""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - max_bytes))
            content = handle.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return "\n".join(content.splitlines()[-lines:])


def pid_alive(pid: int | None) -> bool:
    """Whether a process with this id is still running."""
    if not pid:
        return False
    if IS_WINDOWS:  # pragma: no cover - exercised on Windows only
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_process_alive(pid: int | None, run_dir: Path) -> bool:
    """Whether the process running the request in ``run_dir`` is still alive.

    Besides checking the pid, this confirms the process is really that run (its
    command line names the run's request file), so a pid reused by an unrelated
    program, for example after a reboot, does not keep a run "running" forever.
    """
    if not pid_alive(pid):
        return False
    if IS_WINDOWS:  # pragma: no cover - no portable command-line lookup without extra deps
        return True
    try:
        command = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return True  # can't tell; assume it is ours
    return str(run_dir / REQUEST_FILE) in command


def terminate(
    pid: int,
    *,
    process: subprocess.Popen[bytes] | None = None,
    grace: float = 5.0,
    run_dir: Path | None = None,
) -> None:
    """Stop a run and everything it started; escalate if it ignores the request.

    Pass ``process`` when this process started the child, so it is reaped
    (otherwise a finished child lingers as a zombie that looks alive), and
    ``run_dir`` so a run inside WSL is stopped on the Linux side too.
    """
    if run_dir is not None:
        wsl.stop_run(run_dir, grace=grace)
    if IS_WINDOWS:  # pragma: no cover - exercised on Windows only
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, check=False)
        if process is not None:
            process.wait()
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    if _wait_for_exit(pid, process, grace):
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)
    _wait_for_exit(pid, process, grace)


def _wait_for_exit(pid: int, process: subprocess.Popen[bytes] | None, timeout: float) -> bool:
    if process is not None:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


def _windows_pid_alive(pid: int) -> bool:  # pragma: no cover - Windows only
    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
