"""Featured tool packages that ship with SciPatch.

Each sub-folder is a complete tool package (``scipatch.yaml`` + ``api.py`` + ...)
that can be installed by name, e.g. ``scipatch add ase-emt``. They double as
reference examples for writing your own packages.
"""

from __future__ import annotations

from pathlib import Path

from scipatch.errors import ManifestError
from scipatch.manifest import MANIFEST_FILENAME, Manifest, load_manifest

CATALOG_DIR = Path(__file__).parent


def catalog_entries() -> list[tuple[Manifest, Path]]:
    entries = []
    for folder in sorted(CATALOG_DIR.iterdir()):
        if (folder / MANIFEST_FILENAME).is_file():
            try:
                entries.append((load_manifest(folder), folder))
            except ManifestError:  # pragma: no cover - catalog is validated by tests
                continue
    return entries


def catalog_path(name: str) -> Path | None:
    folder = CATALOG_DIR / name
    return folder if (folder / MANIFEST_FILENAME).is_file() else None
