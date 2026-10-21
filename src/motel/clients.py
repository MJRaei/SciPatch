"""Connect Motel to AI apps: register the MCP server and install skills.

Each supported app has an :class:`AppIntegration` that knows where the app keeps
its MCP configuration and its skills. Configuration files are edited safely:

* a one-time backup (``<file>.motel-backup``) is made before the first change;
* files that cannot be parsed are never modified (manual steps are shown);
* writes are atomic, and only Motel's own entry (``motel``) is touched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from motel.errors import ClientConfigError
from motel.paths import ENV_VAR

SERVER_NAME = "motel"


@dataclass(frozen=True)
class ServerCommand:
    """How an app should start Motel's MCP server."""

    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)

    def as_json_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"command": self.command, "args": self.args}
        if self.env:
            entry["env"] = self.env
        return entry


def server_command() -> ServerCommand:
    """Absolute command for ``motel serve`` (GUI apps do not inherit the shell PATH)."""
    env = {ENV_VAR: os.environ[ENV_VAR]} if os.environ.get(ENV_VAR) else {}
    launcher = Path(sys.argv[0])
    if launcher.name in ("motel", "motel.exe") and launcher.exists():
        return ServerCommand(str(launcher.absolute()), ["serve"], env)
    found = shutil.which("motel")
    if found:
        return ServerCommand(str(Path(found).absolute()), ["serve"], env)
    return ServerCommand(sys.executable, ["-m", "motel", "serve"], env)


class AppIntegration(ABC):
    key: str
    name: str
    restart_hint: str = "Restart the app to load the change."

    @property
    def skills_dir(self) -> Path | None:
        """Where the app reads user-level skills (``None``: skills can't be installed as files)."""
        return None

    @abstractmethod
    def detected(self) -> bool:
        """Whether the app appears to be installed."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Whether Motel's MCP server is registered."""

    @abstractmethod
    def connect(self, server: ServerCommand) -> str:
        """Register (or update) the MCP server; returns a short description of what changed."""

    @abstractmethod
    def disconnect(self) -> str:
        """Remove Motel's MCP server entry."""

    def manual_instructions(self, server: ServerCommand) -> str:
        """What to do by hand if automatic configuration is not possible."""
        snippet = json.dumps({"mcpServers": {SERVER_NAME: server.as_json_entry()}}, indent=2)
        return f"Add this to the app's MCP configuration:\n{snippet}"


# --------------------------------------------------------------------------- #
# Safe file editing
# --------------------------------------------------------------------------- #


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.motel-tmp")
    temporary.write_text(text, encoding="utf-8")
    if path.exists():
        shutil.copymode(path, temporary)
    temporary.replace(path)


def _backup_once(path: Path) -> None:
    backup = path.with_name(path.name + ".motel-backup")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)


def update_json_file(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    """Load a JSON object from ``path``, apply ``mutate``, and write it back safely."""
    data: dict[str, Any] = {}
    if path.exists() and path.read_text(encoding="utf-8").strip():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ClientConfigError(
                f"{path} is not plain JSON (line {exc.lineno}), so Motel will not edit it.",
                hint="Fix the file, or add the server by hand (see 'motel connect --show').",
            ) from exc
        if not isinstance(loaded, dict):
            raise ClientConfigError(f"{path} does not contain a JSON object.")
        data = loaded
    _backup_once(path)
    mutate(data)
    _atomic_write(path, json.dumps(data, indent=2) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


class JsonMcpApp(AppIntegration):
    """An app whose MCP servers live under ``mcpServers`` in a JSON file."""

    config_key = "mcpServers"

    @property
    @abstractmethod
    def config_path(self) -> Path: ...

    def entry(self, server: ServerCommand) -> dict[str, Any]:
        return server.as_json_entry()

    def is_connected(self) -> bool:
        servers = _read_json(self.config_path).get(self.config_key) or {}
        return isinstance(servers, dict) and SERVER_NAME in servers

    def connect(self, server: ServerCommand) -> str:
        def mutate(data: dict[str, Any]) -> None:
            servers = data.get(self.config_key)
            if not isinstance(servers, dict):
                servers = {}
                data[self.config_key] = servers
            servers[SERVER_NAME] = self.entry(server)

        update_json_file(self.config_path, mutate)
        return f"registered the MCP server in {self.config_path}"

    def disconnect(self) -> str:
        if not self.is_connected():
            return "was not connected"

        def mutate(data: dict[str, Any]) -> None:
            data.get(self.config_key, {}).pop(SERVER_NAME, None)

        update_json_file(self.config_path, mutate)
        return f"removed the MCP server from {self.config_path}"


# --------------------------------------------------------------------------- #
# Apps
# --------------------------------------------------------------------------- #


class ClaudeDesktop(JsonMcpApp):
    key = "claude-desktop"
    name = "Claude Desktop"
    restart_hint = "Quit Claude Desktop completely and open it again."

    @property
    def config_dir(self) -> Path:
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Claude"
        elif sys.platform == "win32":
            return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude"
        else:
            return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Claude"

    @property
    def config_path(self) -> Path:
        return self.config_dir / "claude_desktop_config.json"

    def detected(self) -> bool:
        return self.config_dir.exists() or Path("/Applications/Claude.app").exists()


class ClaudeCode(JsonMcpApp):
    key = "claude-code"
    name = "Claude Code"
    restart_hint = "Start a new Claude Code session to load the change."

    @property
    def _config_home(self) -> Path:
        return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home()))

    @property
    def config_path(self) -> Path:
        # User-scoped MCP servers live in ~/.claude.json (or $CLAUDE_CONFIG_DIR/.claude.json).
        return self._config_home / ".claude.json"

    @property
    def skills_dir(self) -> Path:
        base = os.environ.get("CLAUDE_CONFIG_DIR")
        return (Path(base) if base else Path.home() / ".claude") / "skills"

    def entry(self, server: ServerCommand) -> dict[str, Any]:
        return {"type": "stdio", **server.as_json_entry()}

    def detected(self) -> bool:
        return shutil.which("claude") is not None or (Path.home() / ".claude").exists()

    def connect(self, server: ServerCommand) -> str:
        claude = shutil.which("claude")
        if claude is None:
            return super().connect(server)  # edit ~/.claude.json directly
        env_args = [arg for key, value in server.env.items() for arg in ("-e", f"{key}={value}")]
        subprocess.run(
            [claude, "mcp", "remove", "--scope", "user", SERVER_NAME],
            capture_output=True,
            check=False,
        )
        completed = subprocess.run(
            [
                claude,
                "mcp",
                "add",
                "--scope",
                "user",
                *env_args,
                SERVER_NAME,
                "--",
                server.command,
                *server.args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ClientConfigError(
                f"'claude mcp add' failed: {completed.stderr.strip() or completed.stdout.strip()}"
            )
        return "registered the MCP server with 'claude mcp add --scope user'"

    def disconnect(self) -> str:
        claude = shutil.which("claude")
        if claude is None:
            return super().disconnect()
        subprocess.run(
            [claude, "mcp", "remove", "--scope", "user", SERVER_NAME],
            capture_output=True,
            check=False,
        )
        return "removed the MCP server with 'claude mcp remove'"


class Cursor(JsonMcpApp):
    key = "cursor"
    name = "Cursor"

    @property
    def config_path(self) -> Path:
        return Path.home() / ".cursor" / "mcp.json"

    @property
    def skills_dir(self) -> Path:
        return Path.home() / ".cursor" / "skills"

    def detected(self) -> bool:
        return (Path.home() / ".cursor").exists()


class GeminiCli(JsonMcpApp):
    key = "gemini"
    name = "Gemini CLI"
    restart_hint = "Start a new Gemini CLI session to load the change."

    @property
    def config_path(self) -> Path:
        return Path.home() / ".gemini" / "settings.json"

    @property
    def skills_dir(self) -> Path:
        return Path.home() / ".gemini" / "skills"

    def detected(self) -> bool:
        return shutil.which("gemini") is not None or (Path.home() / ".gemini").exists()


class Codex(AppIntegration):
    """OpenAI Codex: ``[mcp_servers.motel]`` in ``~/.codex/config.toml``."""

    key = "codex"
    name = "Codex"
    restart_hint = "Start a new Codex session to load the change."

    @property
    def config_path(self) -> Path:
        return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"

    @property
    def skills_dir(self) -> Path:
        return Path.home() / ".agents" / "skills"

    def detected(self) -> bool:
        return shutil.which("codex") is not None or self.config_path.parent.exists()

    def _load(self) -> tuple[str, dict[str, Any]]:
        text = self.config_path.read_text(encoding="utf-8") if self.config_path.exists() else ""
        try:
            return text, tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ClientConfigError(
                f"{self.config_path} is not valid TOML, so Motel will not edit it: {exc}"
            ) from exc

    def is_connected(self) -> bool:
        try:
            _, data = self._load()
        except ClientConfigError:
            return False
        return SERVER_NAME in (data.get("mcp_servers") or {})

    def connect(self, server: ServerCommand) -> str:
        text, _ = self._load()
        block = [
            f"[mcp_servers.{SERVER_NAME}]",
            f"command = {json.dumps(server.command)}",
            f"args = {json.dumps(server.args)}",
        ]
        if server.env:
            pairs = ", ".join(f"{json.dumps(k)} = {json.dumps(v)}" for k, v in server.env.items())
            block.append(f"env = {{ {pairs} }}")
        new_text = _remove_toml_table(text, f"mcp_servers.{SERVER_NAME}").rstrip()
        new_text = (new_text + "\n\n" if new_text else "") + "\n".join(block) + "\n"
        tomllib.loads(new_text)  # never write something Codex cannot read
        _backup_once(self.config_path)
        _atomic_write(self.config_path, new_text)
        return f"registered the MCP server in {self.config_path}"

    def disconnect(self) -> str:
        if not self.is_connected():
            return "was not connected"
        text, _ = self._load()
        new_text = _remove_toml_table(text, f"mcp_servers.{SERVER_NAME}")
        tomllib.loads(new_text)
        _backup_once(self.config_path)
        _atomic_write(self.config_path, new_text)
        return f"removed the MCP server from {self.config_path}"

    def manual_instructions(self, server: ServerCommand) -> str:
        return (
            f"Add this to {self.config_path}:\n\n[mcp_servers.{SERVER_NAME}]\n"
            f"command = {json.dumps(server.command)}\nargs = {json.dumps(server.args)}"
        )


def _remove_toml_table(text: str, table: str) -> str:
    """Remove ``[table]`` and its sub-tables (``[table.x]``) from TOML text."""
    header = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        match = header.match(line)
        if match:
            name = match.group(1).replace('"', "").replace(" ", "")
            skipping = name == table or name.startswith(table + ".")
        if not skipping:
            kept.append(line)
    return "\n".join(kept) + ("\n" if kept else "")


APPS: dict[str, AppIntegration] = {
    app.key: app for app in (ClaudeDesktop(), ClaudeCode(), Codex(), Cursor(), GeminiCli())
}


def get_app(key: str) -> AppIntegration:
    try:
        return APPS[key]
    except KeyError:
        raise ClientConfigError(
            f"Unknown app '{key}'.", hint=f"Choose from: {', '.join(APPS)}."
        ) from None


# --------------------------------------------------------------------------- #
# Remember which apps are connected (so skills stay in sync)
# --------------------------------------------------------------------------- #


class ConnectionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, dict[str, Any]]:
        apps = _read_json(self.path).get("apps", {})
        return apps if isinstance(apps, dict) else {}

    def _save(self, apps: dict[str, dict[str, Any]]) -> None:
        _atomic_write(self.path, json.dumps({"apps": apps}, indent=2) + "\n")

    def add(self, app: AppIntegration) -> None:
        apps = self.load()
        apps[app.key] = {
            "connected_at": datetime.now(UTC).isoformat(),
            "skills_dir": str(app.skills_dir) if app.skills_dir else None,
        }
        self._save(apps)

    def remove(self, key: str) -> None:
        apps = self.load()
        if apps.pop(key, None) is not None:
            self._save(apps)

    def skills_dirs(self) -> list[Path]:
        dirs = {Path(info["skills_dir"]) for info in self.load().values() if info.get("skills_dir")}
        return sorted(dirs)
