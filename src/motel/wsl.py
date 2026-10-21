"""Run Linux-only tools on Windows inside WSL (the Windows Subsystem for Linux).

Some scientific codes have no Windows build (GPAW, Quantum ESPRESSO, CREST,
LAMMPS); their own documentation recommends WSL on Windows. When a tool's
``motel.lock`` has no Windows packages but has Linux ones, Motel builds the Linux
environment inside the user's WSL distribution, from exactly the locked Linux
packages, and runs the tool there.

The environment lives on the Linux file system (Microsoft recommends it for
speed); on Windows, the tool's environment folder only holds a pointer to it
(``wsl.json``). Tools read their inputs and write their outputs on Windows
through ``/mnt/<drive>``. Paths are translated both ways, and variables (secrets
included) reach the Linux process through ``WSLENV``, never the command line.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

#: The program that runs Linux commands from Windows.
WSL_EXE = "wsl.exe"
#: In a Windows environment folder: where the Linux environment of a WSL tool is.
POINTER = "wsl.json"
#: Written next to a run's response by the shim: the Linux process group to stop.
PID_FILE = "linux-process.json"
#: Linux platform names (as in motel.lock) for WSL machine types.
_LINUX_PLATFORMS = {"x86_64": "linux-64", "aarch64": "linux-aarch64"}
_DRIVE = re.compile(r"^([A-Za-z]):[\\/]?(.*)$", re.DOTALL)
_UNC = re.compile(r"^[\\/]{2}wsl(?:\$|\.localhost)[\\/]([^\\/]+)(.*)$", re.IGNORECASE | re.DOTALL)

INSTALL_HINT = (
    "Install WSL: open PowerShell as administrator, run 'wsl --install', restart the "
    "computer, and finish setting up Ubuntu; then try again."
)


@dataclass(frozen=True)
class Distro:
    """A WSL distribution that Linux tools can run in."""

    name: str
    #: Home folder of the default Linux user, e.g. /home/ada.
    home: str
    #: Where Windows drives are mounted, e.g. /mnt/ (C: is /mnt/c).
    mount_root: str = "/mnt/"
    #: Platform of the Linux side, as named in motel.lock.
    platform: str = "linux-64"

    def to_linux(self, path: str | os.PathLike[str]) -> str:
        """``C:\\Users\\ada\\x`` -> ``/mnt/c/Users/ada/x``; Linux paths stay as they are."""
        text = os.fspath(path)
        unc = _UNC.match(text)
        if unc:
            return "/" + unc.group(2).replace("\\", "/").lstrip("/")
        drive = _DRIVE.match(text)
        if drive:
            rest = drive.group(2).replace("\\", "/")
            return f"{self.mount_root}{drive.group(1).lower()}/{rest}".rstrip("/")
        return text.replace("\\", "/") if text.startswith("/") else text

    def to_windows(self, path: str) -> str:
        """``/mnt/c/Users/ada/x`` -> ``C:\\Users\\ada\\x``; other Linux paths as UNC paths."""
        root = self.mount_root
        if path.startswith(root) and len(path) > len(root) and path[len(root)].isalpha():
            letter, rest = path[len(root)], path[len(root) + 1 :]
            if rest == "" or rest.startswith("/"):
                return f"{letter.upper()}:\\" + rest.lstrip("/").replace("/", "\\")
        return f"\\\\wsl.localhost\\{self.name}" + path.replace("/", "\\")

    def command(self, argv: list[str], cwd: str | os.PathLike[str] | None = None) -> list[str]:
        """A Windows command line that runs ``argv`` in this distribution."""
        prefix = [WSL_EXE, "-d", self.name]
        if cwd is not None:
            prefix += ["--cd", os.fspath(cwd)]
        return [*prefix, "--exec", *argv]

    def environment(self, variables: dict[str, str]) -> dict[str, str]:
        """The Windows process environment that hands ``variables`` to the Linux side."""
        env = dict(os.environ)
        env.update(variables)
        shared = [name for name in variables if name != "WSLENV"]
        existing = [part for part in env.get("WSLENV", "").split(":") if part]
        env["WSLENV"] = ":".join([*existing, *shared])
        return env

    def run(
        self, argv: list[str], *, timeout: float | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run a short Linux command and capture its output."""
        return subprocess.run(
            self.command(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    def environment_prefix(self, key: str) -> str:
        """Where the Linux environment for ``key`` (a tool and layout) lives."""
        return f"{self.home}/.motel/envs/{key}"

    @property
    def motel_home(self) -> str:
        return f"{self.home}/.motel"


def host_is_windows() -> bool:
    return sys.platform == "win32"


@functools.cache
def detect() -> Distro | None:
    """The default WSL distribution, if WSL is installed and works (Windows only)."""
    if not host_is_windows():
        return None
    script = 'printf "%s\\n%s\\n%s\\n" "$WSL_DISTRO_NAME" "$HOME" "$(uname -m)"; wslpath -u C:/'
    try:
        completed = subprocess.run(
            [WSL_EXE, "--exec", "sh", "-c", script],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    # wsl.exe's own messages are UTF-16; the Linux side prints UTF-8.
    lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
    if completed.returncode != 0 or len(lines) < 4 or not lines[0] or not lines[1]:
        return None
    platform = _LINUX_PLATFORMS.get(lines[2].strip())
    if platform is None:
        return None
    mount = lines[3].strip()  # e.g. /mnt/c/
    root = mount[: -len("c/")] if mount.endswith("c/") else "/mnt/"
    return Distro(name=lines[0].strip(), home=lines[1].strip(), mount_root=root, platform=platform)


@dataclass(frozen=True)
class LinuxEnvironment:
    """A tool environment that lives inside WSL."""

    distro: Distro
    prefix: str

    @property
    def python(self) -> str:
        return f"{self.prefix}/bin/python"


def read_pointer(env_dir: Path) -> LinuxEnvironment | None:
    """The Linux environment a Windows environment folder points to, if it is one."""
    try:
        data = json.loads((env_dir / POINTER).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    distro = Distro(**data["distro"])
    return LinuxEnvironment(distro=distro, prefix=data["prefix"])


def write_pointer(env_dir: Path, environment: LinuxEnvironment) -> None:
    env_dir.mkdir(parents=True, exist_ok=True)
    data = {"distro": environment.distro.__dict__, "prefix": environment.prefix}
    (env_dir / POINTER).write_text(json.dumps(data, indent=1), encoding="utf-8")


def remove_environment(env_dir: Path) -> None:
    """Delete the Linux side of a WSL environment folder (the folder itself stays)."""
    environment = read_pointer(env_dir)
    if environment is None:
        return
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        environment.distro.run(["rm", "-rf", environment.prefix], timeout=600)


def stop_run(run_dir: Path, *, grace: float = 5.0) -> bool:
    """Stop the Linux processes of a run inside WSL; False if it did not run in WSL."""
    try:
        data = json.loads((run_dir / PID_FILE).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    distro = Distro(name=data["distro"], home="")
    group = f"-{int(data['pgid'])}"

    def signal(name: str) -> int:
        return distro.run(["kill", f"-{name}", "--", group], timeout=30).returncode

    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        signal("TERM")
        deadline = time.monotonic() + grace
        while signal("0") == 0 and time.monotonic() < deadline:
            time.sleep(0.5)
        if signal("0") == 0:
            signal("KILL")
    return True
