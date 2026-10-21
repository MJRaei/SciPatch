"""``motel.lock``: the exact packages a tool was tested with, for every platform.

``motel freeze`` writes it: the platform the tool was tested on gets the
packages of that working environment; every other platform gets a solution
resolved for it (with the tested versions wherever they exist there), or the
reason the tool cannot be installed there. Builds install exactly the pinned
conda packages and use the pinned PyPI versions as constraints.

A lock records a hash of the environment it was made for; when ``motel.yaml``
asks for different packages, the lock is stale and is not applied.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from motel import platforms
from motel.errors import BuildError
from motel.manifest import Manifest

LOCK_FILENAME = "motel.lock"
#: The lock of Motel 0.x: one list of PyPI pins, used as constraints everywhere.
LEGACY_LOCK_FILENAME = "requirements.lock"
LOCK_VERSION = 1


class PlatformLock(BaseModel):
    """What to install on one platform, or why the tool cannot be installed there."""

    model_config = ConfigDict(extra="forbid")

    conda: list[str] = Field(default_factory=list, description="name==version=build")
    pip: list[str] = Field(default_factory=list, description="name==version")
    unavailable: str | None = None
    note: str | None = None


class Lock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lock_version: int = LOCK_VERSION
    inputs: str
    tested_on: str | None = None
    platforms: dict[str, PlatformLock]

    def supported(self) -> list[str]:
        return [name for name, entry in self.platforms.items() if not entry.unavailable]


def inputs_hash(manifest: Manifest, package_dir: Path) -> str:
    """Hash of what a lock is resolved from: the requested packages and source."""
    spec = manifest.environment
    material: dict[str, Any] = {
        "environment": spec.model_dump(
            mode="json",
            include={"manager", "python", "packages", "conda_packages", "channels", "platforms"},
        ),
        "source": manifest.source.model_dump(
            mode="json", include={"repo", "ref", "subdirectory", "install"}
        ),
    }
    for relative in (spec.requirements, spec.conda_file):
        if relative and (package_dir / relative).is_file():
            material[relative] = hashlib.sha256((package_dir / relative).read_bytes()).hexdigest()
    blob = json.dumps(material, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def load(package_dir: Path) -> Lock | None:
    path = package_dir / LOCK_FILENAME
    if not path.is_file():
        return None
    try:
        return Lock.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise BuildError(
            f"{path} is not a valid lock file: {exc}",
            hint="Write it again with 'motel freeze', or delete it.",
        ) from exc


def save(package_dir: Path, lock: Lock) -> Path:
    path = package_dir / LOCK_FILENAME
    data = lock.model_dump(mode="json", exclude_defaults=False)
    for entry in data["platforms"].values():
        for key in ("unavailable", "note"):
            if entry[key] is None:
                del entry[key]
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    (package_dir / LEGACY_LOCK_FILENAME).unlink(missing_ok=True)
    return path


@dataclass
class BuildPins:
    """What a build on this computer installs exactly (empty lists: resolve freely)."""

    conda: list[str] = field(default_factory=list)
    pip: list[str] = field(default_factory=list)
    #: A legacy ``requirements.lock`` to use as constraints instead of ``pip``.
    legacy_constraints: Path | None = None
    warnings: list[str] = field(default_factory=list)


def pins_for_build(manifest: Manifest, package_dir: Path) -> BuildPins:
    """The pins for this computer's platform; raises if the tool cannot be built here."""
    lock = load(package_dir)
    if lock is None:
        legacy = package_dir / LEGACY_LOCK_FILENAME
        return BuildPins(legacy_constraints=legacy if legacy.is_file() else None)
    if lock.inputs != inputs_hash(manifest, package_dir):
        return BuildPins(
            warnings=[
                "motel.lock is out of date (motel.yaml asks for different packages); "
                "it was not applied. Run 'motel freeze' after testing."
            ]
        )
    here = platforms.current()
    entry = lock.platforms.get(here or "")
    if entry is None:
        return BuildPins(warnings=[f"motel.lock has no versions for {platforms.label(here)}"])
    if entry.unavailable:
        supported = ", ".join(platforms.label(name) for name in lock.supported()) or "none"
        raise BuildError(
            f"'{manifest.name}' cannot be installed on {platforms.label(here)}: "
            f"{entry.unavailable}",
            hint=f"It is available on: {supported}.",
        )
    return BuildPins(conda=list(entry.conda), pip=list(entry.pip))


def platform_summary(package_dir: Path) -> dict[str, str | None] | None:
    """Each platform's availability (None = available, else the reason), if locked."""
    try:
        lock = load(package_dir)
    except BuildError:
        return None
    if lock is None:
        return None
    return {name: entry.unavailable for name, entry in lock.platforms.items()}


def unavailable_here(package_dir: Path) -> str | None:
    """Why the tool cannot be installed on this computer (None if it can, or unknown)."""
    summary = platform_summary(package_dir) or {}
    return summary.get(platforms.current() or "")
