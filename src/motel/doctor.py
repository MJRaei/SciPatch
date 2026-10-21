"""``motel doctor``: check that everything Motel needs is in place, with fixes."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

from motel import __version__, hardware, platforms, wsl
from motel.app import Motel
from motel.environments import micromamba
from motel.environments.conda import CondaBackend, find_conda
from motel.environments.uv import UvBackend, find_uv
from motel.models import RunStatus
from motel.onboarding import available_agents
from motel.settings import Settings

#: Free disk space below which installing tools is likely to fail (environments take GBs).
LOW_DISK_GB = 10

Level = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class Check:
    name: str
    level: Level
    detail: str
    fix: str | None = None


def _version(command: list[str]) -> str:
    try:
        output = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown version"
    text = (output.stdout or output.stderr).strip()
    return text.splitlines()[0] if text else "unknown version"


def run_checks(motel: Motel) -> list[Check]:
    checks = [
        Check("Motel", "ok", f"version {__version__} on Python {platform.python_version()}"),
    ]

    home = motel.paths.home
    writable = os.access(home, os.W_OK)
    checks.append(
        Check(
            "Data folder",
            "ok" if writable else "fail",
            str(home),
            None if writable else f"Make {home} writable, or set MOTEL_HOME to another folder.",
        )
    )

    checks.append(_computer(motel))

    uv = find_uv()
    checks.append(
        Check("uv", "ok", _version([uv, "--version"]))
        if uv
        else Check("uv", "fail", "not found (needed to build most tools)", UvBackend.install_hint)
    )

    git = shutil.which("git")
    checks.append(
        Check("git", "ok", _version([git, "--version"]))
        if git
        else Check(
            "git",
            "fail",
            "not found (needed to download source code)",
            "macOS: run 'xcode-select --install'. Linux: install git with your package manager.",
        )
    )

    conda = find_conda()
    if conda:
        checks.append(Check("conda", "ok", conda))
    elif micromamba.enabled():
        checks.append(
            Check(
                "conda",
                "ok",
                f"Motel will download micromamba {micromamba.VERSION} when a tool needs it",
            )
        )
    else:
        checks.append(
            Check(
                "conda",
                "warn",
                "not found (only needed for tools that use conda packages)",
                CondaBackend.install_hint,
            )
        )

    if wsl.host_is_windows():
        distro = wsl.detect()
        checks.append(
            Check("WSL", "ok", f"{distro.name} ({platforms.label(distro.platform)}): "
                  "tools with only Linux builds run there")
            if distro
            else Check(
                "WSL",
                "warn",
                "not set up (needed only for tools with Linux builds only: CREST, GPAW, "
                "LAMMPS, Quantum ESPRESSO)",
                wsl.INSTALL_HINT,
            )
        )  # fmt: skip

    on_path = shutil.which("motel")
    checks.append(
        Check("motel command", "ok", on_path)
        if on_path
        else Check(
            "motel command",
            "warn",
            "not on PATH",
            "Run 'uv tool update-shell' and open a new terminal.",
        )
    )

    tools = motel.tools()
    broken = [tool.name for tool in tools if not tool.usable]
    failing = [tool.name for tool in tools if tool.status == "failing-tests"]
    if not tools:
        checks.append(
            Check("Tools", "warn", "none installed", "Try a featured tool: 'motel add ase-emt'.")
        )
    elif broken:
        checks.append(
            Check(
                "Tools",
                "warn",
                f"{len(tools)} installed; not working: {', '.join(broken)}",
                f"Run 'motel rebuild {broken[0]}' (see the error with 'motel info {broken[0]}').",
            )
        )
    else:
        detail = f"{len(tools)} installed"
        if failing:
            detail += f"; golden tests failing: {', '.join(failing)}"
        checks.append(Check("Tools", "warn" if failing else "ok", detail))

    running = motel.history_list(status=RunStatus.RUNNING, limit=1000)
    checks.append(
        Check("Runs", "ok", f"{motel.history.count()} recorded, {len(running)} running now")
    )

    connected = motel.connections.load()
    for app in motel.apps():
        if not app.detected():
            continue
        if app.is_connected():
            checks.append(Check(app.name, "ok", "connected"))
        else:
            checks.append(
                Check(app.name, "warn", "installed but not connected", f"motel connect {app.key}")
            )
        if app.key in connected and not app.is_connected():
            checks.append(
                Check(
                    app.name,
                    "warn",
                    "Motel's entry was removed from the app's configuration",
                    f"motel connect {app.key}",
                )
            )

    agents = available_agents()
    checks.append(
        Check("Onboarding agents", "ok", ", ".join(agents))
        if agents
        else Check(
            "Onboarding agents",
            "warn",
            "no coding agent CLI found (claude, codex, or gemini)",
            "Install Claude Code (https://claude.com/claude-code) to onboard new repositories.",
        )
    )
    return checks


def _computer(motel: Motel) -> Check:
    """Cores, memory, GPUs, free disk space, and whether tools may use the GPU."""
    machine = hardware.detect()
    free_gb = shutil.disk_usage(motel.paths.home).free / 1024**3
    detail = f"{machine.summary()}; {free_gb:.0f} GB free disk"
    fix = None
    if machine.gpus:
        on = Settings(motel.paths.config).use_gpu
        detail += f"; GPU use {'on' if on else 'off'}"
        kinds = {gpu.kind for gpu in machine.gpus}
        faster = [
            tool.name
            for tool in motel.tools()
            for needs in [tool.manifest.resources_for()]
            if needs.gpu == "optional" and kinds & set(needs.gpu_types or [])
        ]
        if faster and not on:
            fix = f"{', '.join(faster)} can run on this GPU: 'motel config gpu on'."
    if free_gb < LOW_DISK_GB:
        return Check("Computer", "warn", detail, "Free disk space: tool environments take GBs.")
    return Check("Computer", "ok", detail, fix)
