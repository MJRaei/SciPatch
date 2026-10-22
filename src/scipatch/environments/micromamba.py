"""A micromamba that SciPatch downloads and manages itself, for tools built with conda.

micromamba is one self-contained executable that creates conda environments
quickly, without touching the user's own conda installation or configuration
(a broken or slow conda is common on scientists' computers). SciPatch downloads a
pinned release once into ``~/.scipatch/bin`` and checks it against the SHA-256
recorded here before using it. Set ``SCIPATCH_SYSTEM_CONDA=1`` to use the system
conda instead.
"""

from __future__ import annotations

import hashlib
import os
import platform
import tempfile
import urllib.request
from pathlib import Path

from scipatch import platforms

VERSION = "2.9.0-0"
_URL = (
    "https://github.com/mamba-org/micromamba-releases/releases/download/{version}/micromamba-{name}"
)
#: SHA-256 of each release binary, from the release's .sha256 files.
_SHA256 = {
    "osx-arm64": "ec2a072f028e1a7cf20f3e2e74d5a8127cf5a5f27636375b5359811565f4e5be",
    "osx-64": "1e71054bb3ac9a076e21f7ec48acfef536f9b3f1408f371a942784bf5ef83d8a",
    "linux-64": "366cd9cd8be14df1ab8ed50352a82111082a36686b2d389fdb79a92c3fafb3e3",
    "linux-aarch64": "9f93b974adcb4d166996af969b6cd371287d1a3e52733704727884d9b74cb7a7",
    "win-64": "a6d804394b2418991c4e29562853eaace2f2ce9d9da661a98e74e02e8dbb44b0",
}
OPT_OUT_VARIABLE = "SCIPATCH_SYSTEM_CONDA"


class DownloadError(Exception):
    """micromamba could not be downloaded or did not match its checksum."""


def platform_name() -> str | None:
    """micromamba's name for this platform, or None if there is no release for it."""
    name = platforms.current()
    return name if name in _SHA256 else None


def enabled() -> bool:
    return not os.environ.get(OPT_OUT_VARIABLE) and platform_name() is not None


def executable(home: Path) -> Path:
    return home / "bin" / ("micromamba.exe" if platform.system() == "Windows" else "micromamba")


def root_prefix(home: Path) -> Path:
    """micromamba's own folder for its package cache."""
    return home / "micromamba"


def installed(home: Path) -> Path | None:
    path = executable(home)
    return path if enabled() and path.exists() else None


def ensure(home: Path) -> Path:
    """The managed micromamba, downloading and verifying it first if needed."""
    path = executable(home)
    if path.exists():
        return path
    name = platform_name()
    if name is None:
        here = f"{platform.system()} {platform.machine()}"
        raise DownloadError(f"micromamba has no release for {here}.")
    return download(name, path)


def download(name: str, path: Path) -> Path:
    """Download micromamba for platform ``name`` to ``path``, checked against its SHA-256."""
    url = _URL.format(version=VERSION, name=name)
    try:
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - fixed https URL
            data = response.read()
    except OSError as exc:
        raise DownloadError(f"Could not download micromamba from {url}: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != _SHA256[name]:
        raise DownloadError(
            f"The downloaded micromamba does not match its published checksum ({digest})."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(data)
    temporary = Path(handle.name)
    temporary.chmod(0o755)
    temporary.replace(path)
    return path
