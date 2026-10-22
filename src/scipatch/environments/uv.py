"""Environments built with `uv <https://docs.astral.sh/uv/>`_ (the default).

uv downloads the requested Python version when needed and installs packages
quickly, so tools that only need PyPI packages build in seconds to minutes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from scipatch.environments.base import (
    BuildLog,
    EnvironmentBackend,
    activated_environment,
    constraints_file,
    pip_arguments,
)
from scipatch.errors import BuildError
from scipatch.lock import BuildPins
from scipatch.manifest import Environment


def find_uv() -> str | None:
    return shutil.which("uv")


class UvBackend(EnvironmentBackend):
    name = "uv"
    install_hint = (
        "Install uv: 'curl -LsSf https://astral.sh/uv/install.sh | sh' "
        "(Windows: 'powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"')."
    )

    def is_available(self) -> bool:
        return find_uv() is not None

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
        uv = find_uv()
        if uv is None:
            raise BuildError("uv is not installed.", hint=self.install_hint)
        if env_dir.exists():
            shutil.rmtree(env_dir)
        env_dir.parent.mkdir(parents=True, exist_ok=True)
        log.run(
            [uv, "venv", str(env_dir), "--python", spec.python, "--seed", "--no-project"],
            title=f"Creating a Python {spec.python} environment",
            hint="uv downloads Python automatically; check your internet connection.",
        )
        install_python_packages(
            uv,
            python=self.python(env_dir),
            env_dir=env_dir,
            spec=spec,
            package_dir=package_dir,
            source_dir=source_dir,
            log=log,
            constraints=constraints_file(pins, env_dir),
        )
        self.run_post_install(spec, env_dir=env_dir, package_dir=package_dir, log=log)


def install_python_packages(
    uv: str,
    *,
    python: Path,
    env_dir: Path,
    spec: Environment,
    package_dir: Path,
    source_dir: Path | None,
    log: BuildLog,
    constraints: Path | None = None,
) -> None:
    """Install PyPI packages, a requirements file, and the upstream source.

    The source is installed *editable*: edits and patches in the checkout take
    effect without rebuilding, and no stale cached wheel can shadow them.
    """
    args = pip_arguments(spec, package_dir, source_dir, constraints)
    if not args:
        return
    log.run(
        [uv, "pip", "install", "--python", str(python), *args],
        title="Installing packages",
        cwd=package_dir,
        env=activated_environment(env_dir),
        hint="Check the package names and versions in environment.packages, "
        "and that the repository can be installed with pip.",
    )
