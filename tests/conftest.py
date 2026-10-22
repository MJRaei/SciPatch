"""Shared fixtures.

Every test runs with its own ``SCIPATCH_HOME`` and ``HOME``, so nothing touches the
real user configuration. Integration tests build real environments with uv from
tool packages that use only the standard library, so they work offline.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from scipatch.app import SciPatch
from scipatch.paths import SciPatchPaths

#: Use the running interpreter's version so uv finds it locally (no download).
PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"

requires_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

SAMPLE_API = '''
"""Sample tool used by SciPatch's tests."""

from __future__ import annotations

import os
import time
from typing import Literal


def add(a: float, b: float = 1.0) -> dict:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The sum.
    """
    return {"sum": a + b}


def write_text(text: str, output: str = "out.txt") -> dict:
    """Write text to a file.

    Args:
        text: What to write.
        output: File name.
    """
    with open(output, "w") as handle:
        handle.write(text)
    return {"path": output, "length": len(text)}


def fail(message: str = "boom") -> dict:
    """Always raise an error.

    Args:
        message: Error message.
    """
    raise ValueError(message)


def sleep(seconds: float = 30.0) -> dict:
    """Sleep for a while.

    Args:
        seconds: How long, in seconds.
    """
    time.sleep(seconds)
    return {"slept": seconds}


def mode(kind: Literal["fast", "slow"] = "fast") -> str:
    """Echo a choice.

    Args:
        kind: Which mode.
    """
    return kind


def count(n: int = 3, delay: float = 0.2) -> int:
    """Print progress lines, slowly.

    Args:
        n: How many steps.
        delay: Seconds per step.
    """
    for step in range(n):
        print(f"step {step + 1}/{n}")  # no flush: SciPatch makes output line-buffered
        time.sleep(delay)
    return n


def secret_values() -> dict:
    """Report which secrets the tool can see."""
    return {"demo": os.environ.get("DEMO_KEY"), "other": os.environ.get("OTHER_KEY")}


def source_file() -> str:
    """Read DATA.txt from the upstream source checkout."""
    with open(os.path.join(os.environ["SCIPATCH_SOURCE_DIR"], "DATA.txt")) as handle:
        return handle.read().strip()
'''


def _uv_dirs() -> dict[str, str]:
    """uv's real cache and Python folders, so a temporary HOME doesn't force downloads."""
    uv = shutil.which("uv")
    if uv is None:
        return {}
    dirs = {}
    for variable, command in (("UV_CACHE_DIR", "cache"), ("UV_PYTHON_INSTALL_DIR", "python")):
        output = subprocess.run([uv, command, "dir"], capture_output=True, text=True, check=False)
        if output.returncode == 0 and output.stdout.strip():
            dirs[variable] = output.stdout.strip()
    return dirs


_UV_DIRS = _uv_dirs()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME and SCIPATCH_HOME at temporary folders for every test."""
    home = tmp_path / "home"
    home.mkdir()
    for variable, value in _UV_DIRS.items():
        monkeypatch.setenv(variable, value)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SCIPATCH_HOME", str(home / ".scipatch"))
    for variable in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "XDG_CONFIG_HOME", "APPDATA"):
        monkeypatch.delenv(variable, raising=False)
    return home


@pytest.fixture
def scipatch() -> SciPatch:
    return SciPatch(SciPatchPaths.from_env())


ManifestFactory = Callable[..., Path]


@pytest.fixture
def make_package(tmp_path: Path) -> ManifestFactory:
    """Create a tool package folder; keyword arguments override manifest fields."""

    def factory(
        name: str = "sample",
        *,
        api: str = SAMPLE_API,
        folder: Path | None = None,
        **manifest: object,
    ) -> Path:
        package = folder or tmp_path / "packages" / name
        package.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {
            "schema": 1,
            "name": name,
            "summary": "A sample tool for adding numbers and writing files.",
            "domains": ["testing"],
            "environment": {"manager": "uv", "python": PYTHON},
        }
        data.update(manifest)
        (package / "scipatch.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
        (package / "api.py").write_text(textwrap.dedent(api))
        return package

    return factory


@pytest.fixture
def upstream_repo(tmp_path: Path) -> tuple[str, str]:
    """A local git repository with one commit; returns (url, commit)."""
    repo = tmp_path / "upstream"
    repo.mkdir()
    (repo / "DATA.txt").write_text("hello from upstream\n")
    (repo / "README.md").write_text("# upstream\n")
    git = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "-C", str(repo)]
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "--quiet", "-m", "initial"], check=True)
    commit = subprocess.run(
        [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return repo.as_uri(), commit
