"""``motel doctor``: check that everything Motel needs is in place, with fixes."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

from motel import __version__
from motel.app import Motel
from motel.environments.conda import CondaBackend, find_conda
from motel.environments.uv import UvBackend, find_uv
from motel.models import RunStatus
from motel.onboarding import available_agents

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
    checks.append(
        Check("conda", "ok", conda)
        if conda
        else Check(
            "conda",
            "warn",
            "not found (only needed for tools that use conda packages)",
            CondaBackend.install_hint,
        )
    )

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
