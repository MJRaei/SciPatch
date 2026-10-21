"""API keys and other secrets for tools that call online services.

Desktop apps start Motel with a minimal environment, so keys exported in a
shell profile never reach the tools. Motel therefore keeps secrets in one file,
``~/.motel/secrets.json``, readable only by the user, and gives each tool only
the secrets its manifest declares (``environment.secrets``). A variable that is
set in Motel's own environment takes precedence, which suits CI.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from pathlib import Path

from motel.errors import MotelError

NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def check_name(name: str) -> str:
    if not NAME_PATTERN.match(name):
        raise MotelError(
            f"'{name}' is not a valid secret name.",
            hint="Use the environment variable name the tool expects, e.g. MP_API_KEY.",
        )
    return name


class SecretStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save(self, secrets: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.unlink(missing_ok=True)  # O_CREAT keeps the mode of an existing file
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(secrets, handle, indent=2)
        temporary.replace(self.path)

    def names(self) -> list[str]:
        return sorted(self._load())

    def set(self, name: str, value: str) -> None:
        if not value:
            raise MotelError("The secret's value is empty.")
        secrets = self._load()
        secrets[check_name(name)] = value
        self._save(secrets)

    def remove(self, name: str) -> bool:
        secrets = self._load()
        if secrets.pop(name, None) is None:
            return False
        self._save(secrets)
        return True

    def resolve(self, names: Iterable[str]) -> dict[str, str]:
        """Values of ``names`` that are available (environment first, then the store)."""
        stored = self._load()
        values = {}
        for name in names:
            value = os.environ.get(name) or stored.get(name)
            if value:
                values[name] = value
        return values
