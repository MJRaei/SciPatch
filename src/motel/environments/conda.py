"""Environments built with conda, mamba, or micromamba.

Use ``manager: conda`` for tools that need conda-forge packages (compiled
chemistry and simulation codes such as OpenMM, xtb, or LAMMPS builds). PyPI
packages listed in ``environment.packages`` are installed on top with uv when
available, otherwise with the environment's own pip.

The user's own micromamba or mamba is used if there is one; otherwise Motel
uses its own micromamba (downloaded and verified on first need, see
``micromamba.py``), and plain conda only as a fallback.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

import yaml

from motel import platforms
from motel.environments import micromamba
from motel.environments.base import (
    BuildLog,
    EnvironmentBackend,
    activated_environment,
    constraints_file,
    pip_arguments,
)
from motel.environments.uv import find_uv, install_python_packages
from motel.errors import BuildError
from motel.lock import BuildPins
from motel.manifest import Environment
from motel.paths import MotelPaths

_COMMON_LOCATIONS = (
    "~/miniforge3/bin/conda",
    "~/mambaforge/bin/conda",
    "~/miniconda3/bin/conda",
    "~/anaconda3/bin/conda",
    "/opt/miniforge3/bin/conda",
    "/opt/miniconda3/bin/conda",
    "/opt/anaconda3/bin/conda",
    "/opt/homebrew/Caskroom/miniforge/base/bin/conda",
)


def find_conda(home: Path | None = None) -> str | None:
    """Locate a conda front end that is already installed.

    In order of preference: the user's micromamba or mamba, Motel's own
    micromamba, then conda.
    """
    value = os.environ.get("MAMBA_EXE")
    if value and Path(value).exists():
        return value
    for name in ("micromamba", "mamba"):
        found = shutil.which(name)
        if found:
            return found
    managed = micromamba.installed(home or MotelPaths.from_env().home)
    if managed is not None:
        return str(managed)
    value = os.environ.get("CONDA_EXE")
    if value and Path(value).exists():
        return value
    found = shutil.which("conda")
    if found:
        return found
    for candidate in _COMMON_LOCATIONS:
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
    return None


INSTALL_HINT = (
    "Install Miniforge (https://conda-forge.org/download/) or micromamba, "
    "then run 'motel doctor' again."
)


def conda_frontend(note: Callable[[str], None] = lambda _: None) -> tuple[str, dict[str, str]]:
    """The conda front end to run, and the process environment to run it with.

    Plain conda is replaced by Motel's own micromamba (downloaded on first use),
    which is faster and immune to broken conda configurations.
    """
    home = MotelPaths.from_env().home
    conda = find_conda(home)
    if (conda is None or Path(conda).name.startswith("conda")) and micromamba.enabled():
        try:
            conda = str(micromamba.ensure(home))
            note(f"Using micromamba {micromamba.VERSION} (managed by Motel)")
        except micromamba.DownloadError as exc:
            note(f"{exc} Using conda instead.")
    if conda is None:
        raise BuildError("conda (or mamba/micromamba) is not installed.", hint=INSTALL_HINT)
    env = dict(os.environ)
    if conda == str(micromamba.executable(home)):
        env["MAMBA_ROOT_PREFIX"] = str(micromamba.root_prefix(home))
    return conda, env


def channels_of(spec: Environment, package_dir: Path) -> list[str]:
    """The channels to install from: the environment file's, or the manifest's."""
    if spec.conda_file:
        data = yaml.safe_load((package_dir / spec.conda_file).read_text(encoding="utf-8")) or {}
        listed = data.get("channels") if isinstance(data, dict) else None
        if listed:
            return [str(channel) for channel in listed]
    return list(spec.channels)


def channel_arguments(channels: list[str]) -> list[str]:
    """Only these channels: a user's own conda configuration (often with Anaconda's
    defaults channel) must not change, or slow down, a tool's environment."""
    arguments = [arg for channel in channels for arg in ("-c", channel)]
    return ["--override-channels", *arguments] if arguments else []


class CondaBackend(EnvironmentBackend):
    name = "conda"
    install_hint = INSTALL_HINT

    def is_available(self) -> bool:
        return find_conda() is not None or micromamba.enabled()

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
        conda, tool_env = conda_frontend(log.note)
        if env_dir.exists():
            shutil.rmtree(env_dir)
        env_dir.parent.mkdir(parents=True, exist_ok=True)

        is_micromamba = Path(conda).name.startswith("micromamba")
        if pins is not None and pins.conda:
            # Exactly the packages the tool was tested with (motel.lock).
            channels = channel_arguments(channels_of(spec, package_dir))
            command = [conda, "create", "-y", "-p", str(env_dir), *channels, *pins.conda]
        elif spec.conda_file:
            file = str(package_dir / spec.conda_file)
            command = (
                [conda, "create", "-y", "-p", str(env_dir), "-f", file]
                if is_micromamba
                else [conda, "env", "create", "-p", str(env_dir), "-f", file]
            )
        else:
            wanted = platforms.for_this_platform(spec.conda_packages, spec.python)
            packages = [f"python={spec.python}", *wanted]
            channels = channel_arguments(spec.channels)
            command = [conda, "create", "-y", "-p", str(env_dir), *channels, *packages]
        hint = "Check the names in environment.conda_packages, channels, or conda_file."
        try:
            log.run(
                command,
                title="Creating the conda environment",
                cwd=package_dir,
                env=tool_env,
                hint=hint,
            )
        except BuildError as exc:
            # A common broken setup: conda is configured for the libmamba solver, but
            # the plugin is missing. The built-in classic solver still works.
            if is_micromamba or "solver backend" not in exc.message:
                raise
            log.note("conda's configured solver is unavailable; retrying with the classic solver")
            if env_dir.exists():
                shutil.rmtree(env_dir)
            log.run(
                command,
                title="Creating the conda environment (classic solver)",
                cwd=package_dir,
                env={**os.environ, "CONDA_SOLVER": "classic"},
                hint=hint,
            )

        python = self.python(env_dir)
        if not python.exists():
            raise BuildError(
                "The conda environment has no Python interpreter.",
                hint="Add 'python' to the dependencies in your environment file.",
            )
        constraints = constraints_file(pins, env_dir)
        uv = find_uv()
        if uv is not None:
            install_python_packages(
                uv,
                python=python,
                env_dir=env_dir,
                spec=spec,
                package_dir=package_dir,
                source_dir=source_dir,
                log=log,
                constraints=constraints,
            )
        else:
            self._pip_install(python, spec, env_dir, package_dir, source_dir, log, constraints)
        self.run_post_install(spec, env_dir=env_dir, package_dir=package_dir, log=log)

    @staticmethod
    def _pip_install(
        python: Path,
        spec: Environment,
        env_dir: Path,
        package_dir: Path,
        source_dir: Path | None,
        log: BuildLog,
        constraints: Path | None,
    ) -> None:
        args = pip_arguments(spec, package_dir, source_dir, constraints)
        if args:
            log.run(
                [str(python), "-m", "pip", "install", *args],
                title="Installing packages with pip",
                cwd=package_dir,
                env=activated_environment(env_dir),
            )
