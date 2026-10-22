"""The user's preferences for this computer (``scipatch config``), stored as JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Each setting: its default, and what it means.
SETTINGS: dict[str, tuple[Any, str]] = {
    "gpu": (
        False,
        "Let tools that run faster on a GPU use one (tools that require a GPU always use it).",
    ),
}


class Settings:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, name: str) -> Any:
        return self._load().get(name, SETTINGS[name][0])

    def set(self, name: str, value: Any) -> None:
        data = self._load()
        data[name] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @property
    def use_gpu(self) -> bool:
        return bool(self.get("gpu"))
