"""Common pieces for environment backends."""

from __future__ import annotations

import os
import shlex
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from scipatch.errors import BuildError
from scipatch.lock import BuildPins
from scipatch.manifest import Environment
from scipatch.reporting import Reporter
from scipatch.runtime.executor import environment_bin_dirs, environment_python, tail


class BuildLog:
    """Runs build commands, streaming their output into one log file.

    Failures raise :class:`BuildError` with the last lines of output and the
    log location, which is usually enough to diagnose a broken install.
    """

    def __init__(self, path: Path, reporter: Reporter) -> None:
        self.path = path
        self.reporter = reporter
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def note(self, message: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"# {message}\n")

    def run(
        self,
        command: list[str] | str,
        *,
        title: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        hint: str | None = None,
    ) -> None:
        """Run ``command``; a string is executed by the shell (used for ``post_install``)."""
        shell = isinstance(command, str)
        printable = command if isinstance(command, str) else shlex.join(command)
        self.reporter.detail(printable)
        with self.path.open("ab") as handle:
            handle.write(f"\n$ {printable}\n".encode())
            handle.flush()
            try:
                completed = subprocess.run(
                    command,
                    shell=shell,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise BuildError(
                    f"{title} failed: {exc}", hint=hint, log_path=str(self.path)
                ) from exc
        if completed.returncode != 0:
            raise BuildError(
                f"{title} failed (exit code {completed.returncode}). Last lines of the log:\n"
                f"{tail(self.path, 30)}",
                hint=hint or f"The full log is at {self.path}",
                log_path=str(self.path),
            )


def pip_arguments(
    spec: Environment,
    package_dir: Path,
    source_dir: Path | None,
    constraints: Path | None = None,
) -> list[str]:
    """Arguments for ``pip install``: packages, requirements, the source, and constraints.

    The pinned versions from ``scipatch.lock`` are applied as *constraints*: every
    package listed is pinned, while packages it doesn't mention still resolve.
    """
    args: list[str] = list(spec.packages)
    if spec.requirements:
        args += ["-r", str(package_dir / spec.requirements)]
    if source_dir is not None:
        args += ["--editable", str(source_dir)]
    if args and constraints is not None:
        args += ["--constraint", str(constraints)]
    return args


def constraints_file(pins: BuildPins | None, env_dir: Path) -> Path | None:
    """A constraints file with the pinned PyPI versions for this build, if any."""
    if pins is None:
        return None
    if pins.legacy_constraints is not None:
        return pins.legacy_constraints
    if not pins.pip:
        return None
    path = env_dir / ".scipatch-constraints.txt"
    path.write_text("".join(f"{pin}\n" for pin in pins.pip), encoding="utf-8")
    return path


def activated_environment(env_dir: Path, variables: dict[str, str] | None = None) -> dict[str, str]:
    """Process environment equivalent to activating ``env_dir`` in a shell."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    env["PATH"] = os.pathsep.join([*map(str, environment_bin_dirs(env_dir)), env.get("PATH", "")])
    env["VIRTUAL_ENV"] = str(env_dir)
    env.pop("CONDA_PREFIX", None)
    env.update(variables or {})
    return env


class EnvironmentBackend(ABC):
    """Creates an isolated environment for one tool."""

    #: Value of ``environment.manager`` that selects this backend.
    name: str
    #: What to tell the user when the backend's executable is missing.
    install_hint: str

    @abstractmethod
    def is_available(self) -> bool:
        """Whether the backend can be used on this machine."""

    @abstractmethod
    def create(
        self,
        spec: Environment,
        *,
        env_dir: Path,
        package_dir: Path,
        source_dir: Path | None,
        log: BuildLog,
        pins: BuildPins | None = None,
    ) -> None:
        """Build the environment from scratch at ``env_dir``.

        ``source_dir`` is the upstream checkout to install (editable) into the
        environment, or ``None`` when there is nothing to install from source.
        ``pins`` are the exact versions from ``scipatch.lock`` for this platform.
        """

    def python(self, env_dir: Path) -> Path:
        return environment_python(env_dir)

    def run_post_install(
        self, spec: Environment, *, env_dir: Path, package_dir: Path, log: BuildLog
    ) -> None:
        env = activated_environment(env_dir, spec.variables)
        for command in spec.post_install:
            log.run(command, title=f"post_install command '{command}'", cwd=package_dir, env=env)
