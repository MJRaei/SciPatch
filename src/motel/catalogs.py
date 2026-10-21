"""Catalogs: collections of tool packages that can be installed by name.

A catalog is a git repository with one tool package per folder under a path
(``tools/`` by default), so any git host works, including private and local
repositories. Motel keeps a shallow clone of each catalog under
``~/.motel/catalogs/<name>/`` and reads the tools' manifests directly, so there
is no separate index to keep in sync. The tools that ship with Motel form the
built-in catalog.

    motel catalog add https://github.com/org/tools     # a lab's or community collection
    motel catalog                                      # everything available
    motel add chgnet                                   # install by name
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from motel.catalog import catalog_entries
from motel.errors import ManifestError, MotelError
from motel.manifest import MANIFEST_FILENAME, Manifest, load_manifest
from motel.paths import MotelPaths
from motel.source import git_executable

BUILT_IN = "built-in"
DEFAULT_PATH = "tools"
_NAME = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


@dataclass(frozen=True)
class Catalog:
    name: str
    url: str
    path: str = DEFAULT_PATH


@dataclass(frozen=True)
class CatalogEntry:
    """One installable tool package in a catalog."""

    catalog: str
    manifest: Manifest
    folder: Path
    origin: str

    @property
    def qualified_name(self) -> str:
        return f"{self.catalog}/{self.manifest.name}"


def _git(*args: str) -> str:
    completed = subprocess.run(
        [git_executable(), *args], capture_output=True, text=True, check=False, timeout=600
    )
    if completed.returncode != 0:
        raise MotelError(
            f"git {args[0]} failed: {completed.stderr.strip()}",
            hint="Check the catalog URL and your internet connection.",
        )
    return completed.stdout.strip()


class CatalogStore:
    """The catalogs a user has added, and their local clones."""

    def __init__(self, paths: MotelPaths) -> None:
        self.config = paths.home / "catalogs.json"
        self.clones = paths.home / "catalogs"

    # ---------------------------------------------------------------- config

    def catalogs(self) -> list[Catalog]:
        try:
            data = json.loads(self.config.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return [Catalog(**item) for item in data.get("catalogs", [])]

    def _save(self, catalogs: list[Catalog]) -> None:
        self.config.parent.mkdir(parents=True, exist_ok=True)
        payload = {"catalogs": [asdict(catalog) for catalog in catalogs]}
        self.config.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _clone_dir(self, name: str) -> Path:
        return self.clones / name

    # ------------------------------------------------------------ operations

    def add(self, url: str, *, name: str | None = None, path: str = DEFAULT_PATH) -> Catalog:
        """Clone a catalog and register it. Local folders work too (for development)."""
        local = Path(url).expanduser()
        if local.is_dir():
            url = str(local.resolve())
        name = name or _name_from_url(url)
        if not _NAME.match(name) or name == BUILT_IN:
            raise MotelError(
                f"'{name}' is not a valid catalog name.", hint="Choose another with --name."
            )
        if any(catalog.name == name for catalog in self.catalogs()):
            raise MotelError(
                f"A catalog named '{name}' already exists.",
                hint=f"Use --name, or remove it first with 'motel catalog remove {name}'.",
            )
        target = self._clone_dir(name)
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", "--depth", "1", url, str(target))
        catalog = Catalog(name=name, url=url, path=path.strip("/"))
        if not self._entries_of(catalog):
            shutil.rmtree(target)
            raise MotelError(
                f"No tool packages found in '{catalog.path}/' of {url}.",
                hint="Point --path at the folder that contains the tool folders.",
            )
        self._save([*self.catalogs(), catalog])
        return catalog

    def update(self, name: str | None = None) -> list[tuple[Catalog, str]]:
        """Fetch the latest version of one or all catalogs; returns (catalog, commit)."""
        updated = []
        for catalog in self.catalogs():
            if name and catalog.name != name:
                continue
            directory = str(self._clone_dir(catalog.name))
            _git("-C", directory, "fetch", "--quiet", "--depth", "1", "origin")
            _git("-C", directory, "reset", "--quiet", "--hard", "FETCH_HEAD")
            updated.append((catalog, _git("-C", directory, "rev-parse", "HEAD")))
        if name and not updated:
            raise MotelError(f"No catalog named '{name}'.", hint="See them with 'motel catalog'.")
        return updated

    def remove(self, name: str) -> None:
        remaining = [catalog for catalog in self.catalogs() if catalog.name != name]
        if len(remaining) == len(self.catalogs()):
            raise MotelError(f"No catalog named '{name}'.")
        shutil.rmtree(self._clone_dir(name), ignore_errors=True)
        self._save(remaining)

    # --------------------------------------------------------------- lookups

    def _entries_of(self, catalog: Catalog) -> list[CatalogEntry]:
        clone = self._clone_dir(catalog.name)
        root = clone / catalog.path
        if not root.is_dir():
            return []
        try:
            commit = _git("-C", str(clone), "rev-parse", "HEAD")[:12]
        except MotelError:
            commit = "unknown"
        entries = []
        for manifest_file in sorted(root.glob(f"*/{MANIFEST_FILENAME}")):
            try:
                manifest = load_manifest(manifest_file.parent)
            except ManifestError:
                continue  # one broken package must not hide the rest
            relative = manifest_file.parent.relative_to(clone).as_posix()
            origin = f"{catalog.url}@{commit}#subdirectory={relative}"
            entries.append(CatalogEntry(catalog.name, manifest, manifest_file.parent, origin))
        return entries

    def entries(self) -> list[CatalogEntry]:
        """Every installable tool: built-in first, then each catalog in the order added."""
        found = [
            CatalogEntry(BUILT_IN, manifest, folder, f"{BUILT_IN}:{manifest.name}")
            for manifest, folder in catalog_entries()
        ]
        for catalog in self.catalogs():
            found.extend(self._entries_of(catalog))
        return found

    def find(self, name: str) -> CatalogEntry | None:
        """Find a tool by ``name`` or ``catalog/name``; ambiguous names raise an error."""
        catalog_name, _, tool_name = name.rpartition("/")
        matches = [
            entry
            for entry in self.entries()
            if entry.manifest.name == tool_name and catalog_name in ("", entry.catalog)
        ]
        if len(matches) > 1:
            options = ", ".join(entry.qualified_name for entry in matches)
            raise MotelError(
                f"'{name}' is in several catalogs: {options}.",
                hint=f"Say which one, e.g. 'motel add {matches[0].qualified_name}'.",
            )
        return matches[0] if matches else None


def _name_from_url(url: str) -> str:
    stem = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1].removesuffix(".git")
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "catalog"
