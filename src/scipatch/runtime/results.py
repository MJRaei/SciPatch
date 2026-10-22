"""Post-processing of tool results: absolute output paths and produced files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scipatch.runtime.executor import INTERNAL_FILES

MAX_LISTED_FILES = 200
MAX_SCAN_DEPTH = 4


def looks_like_path(value: str) -> bool:
    """Heuristic: contains a separator, or ends with a file extension."""
    name = Path(value).name
    return os.sep in value or "/" in value or ("." in name and not name.startswith("."))


def absolutize_paths(value: Any, workdir: Path) -> Any:
    """Turn relative paths of files the tool wrote into absolute ones."""
    if isinstance(value, dict):
        return {key: absolutize_paths(item, workdir) for key, item in value.items()}
    if isinstance(value, list):
        return [absolutize_paths(item, workdir) for item in value]
    if isinstance(value, str) and value and "\n" not in value and not Path(value).is_absolute():
        try:
            candidate = workdir / value
            if looks_like_path(value) and candidate.exists():
                return str(candidate.resolve())
        except OSError:  # e.g. a string too long to be a file name
            return value
    return value


def list_output_files(workdir: Path, *, since: float, run_dir: Path) -> list[str]:
    """Files created or modified in ``workdir`` during the run (SciPatch's own files excluded)."""
    if not workdir.is_dir():
        return []
    found: list[str] = []
    base_depth = len(workdir.parts)
    for root, dirs, files in os.walk(workdir):
        if len(Path(root).parts) - base_depth >= MAX_SCAN_DEPTH:
            dirs[:] = []
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for name in files:
            path = Path(root) / name
            if path.parent == run_dir and name in INTERNAL_FILES:
                continue
            try:
                if path.stat().st_mtime >= since - 1:
                    found.append(str(path))
            except OSError:
                continue
            if len(found) >= MAX_LISTED_FILES:
                return sorted(found)
    return sorted(found)
