"""Environments built inside WSL, for Linux-only tools on Windows (see ``motel.wsl``).

The environment is created on the Linux file system with a Linux micromamba
(downloaded by Motel and checked against its SHA-256), from exactly the Linux
packages in the tool's ``motel.lock``; PyPI packages are installed with the
environment's own pip. On Windows, the tool's environment folder then holds a
pointer to it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from motel import platforms
from motel.environments import micromamba
from motel.environments.base import BuildLog, EnvironmentBackend, constraints_file, pip_arguments
from motel.environments.conda import channel_arguments, channels_of
from motel.errors import BuildError
from motel.lock import BuildPins
from motel.manifest import Environment
from motel.wsl import POINTER, Distro, LinuxEnvironment, write_pointer


class WslBackend(EnvironmentBackend):
    name = "wsl"
    install_hint = "Install WSL with 'wsl --install' (as administrator) and restart."

    def __init__(self, distro: Distro, prefix: str) -> None:
        self.distro = distro
        self.prefix = prefix

    def is_available(self) -> bool:
        return True

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
        distro, prefix = self.distro, self.prefix
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / POINTER).unlink(missing_ok=True)
        log.note(f"Building inside WSL ({distro.name}) at {prefix}")
        mamba = self._micromamba(log)
        log.run(distro.command(["rm", "-rf", prefix]), title="Removing the old WSL environment")
        specs = (
            pins.conda
            if pins is not None and pins.conda
            else [
                f"python={spec.python}",
                *platforms.for_platform(spec.conda_packages, distro.platform, spec.python),
            ]
        )
        spec_file = env_dir / "conda-packages.txt"
        spec_file.write_text("".join(f"{line}\n" for line in specs), encoding="utf-8")
        channels = channel_arguments(channels_of(spec, package_dir))
        root = f"MAMBA_ROOT_PREFIX={distro.motel_home}/micromamba"
        log.run(
            distro.command(
                [
                    "env",
                    root,
                    mamba,
                    "create",
                    "-y",
                    "-p",
                    prefix,
                    *channels,
                    "--file",
                    distro.to_linux(spec_file),
                ]
            ),
            title="Creating the environment inside WSL",
            hint="Check that WSL can reach the internet (conda-forge).",
        )
        arguments = pip_arguments(spec, package_dir, source_dir, constraints_file(pins, env_dir))
        if arguments:
            log.run(
                distro.command(
                    [
                        f"{prefix}/bin/python",
                        "-m",
                        "pip",
                        "install",
                        "--no-input",
                        *[distro.to_linux(argument) for argument in arguments],
                    ]
                ),
                title="Installing PyPI packages inside WSL",
            )
        path = f"PATH={prefix}/bin:/usr/local/bin:/usr/bin:/bin"
        variables = [f"{name}={value}" for name, value in spec.variables.items()]
        for command in spec.post_install:
            log.run(
                distro.command(["env", path, *variables, "sh", "-c", command], cwd=package_dir),
                title=f"post_install command '{command}' (inside WSL)",
            )
        write_pointer(env_dir, LinuxEnvironment(distro=distro, prefix=prefix))

    def _micromamba(self, log: BuildLog) -> str:
        """micromamba inside WSL, copied in from a verified download if needed."""
        distro = self.distro
        target = f"{distro.motel_home}/bin/micromamba"
        if distro.run(["test", "-x", target], timeout=120).returncode == 0:
            return target
        with tempfile.TemporaryDirectory(prefix="motel-wsl-") as scratch:
            try:
                downloaded = micromamba.download(distro.platform, Path(scratch) / "micromamba")
            except micromamba.DownloadError as exc:
                raise BuildError(str(exc)) from exc
            script = 'mkdir -p "$(dirname "$1")" && cp "$0" "$1" && chmod 755 "$1"'
            log.run(
                distro.command(["sh", "-c", script, distro.to_linux(downloaded), target]),
                title=f"Installing micromamba {micromamba.VERSION} inside WSL",
            )
        return target
