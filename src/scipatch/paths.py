"""Locations of everything SciPatch stores on disk.

All state lives under one directory (``~/.scipatch`` by default, or ``$SCIPATCH_HOME``)
so users can find, back up, or delete it in one place::

    ~/.scipatch/
      tools/<name>/        installed tool packages (copies, or symlinks with --link)
      envs/<name>/         one isolated Python environment per tool
      sources/<name>/      upstream source checkouts with patches applied
      state/<name>.json    build state: functions, test results, versions
      runs/<run-id>/       working directory, logs, and result of each run
      logs/                build logs
      workspace/<name>/    drafts created by ``scipatch onboard``
      scipatch.db             run history (SQLite)
      connections.json     AI apps that SciPatch has been connected to
      secrets.json         API keys for tools (readable only by you)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "SCIPATCH_HOME"


@dataclass(frozen=True)
class SciPatchPaths:
    """Resolved directory layout for one SciPatch home."""

    home: Path

    @classmethod
    def from_env(cls) -> SciPatchPaths:
        """Use ``$SCIPATCH_HOME`` when set, otherwise ``~/.scipatch``."""
        raw = os.environ.get(ENV_VAR)
        home = Path(raw).expanduser() if raw else Path.home() / ".scipatch"
        return cls(home.resolve())

    @property
    def tools(self) -> Path:
        return self.home / "tools"

    @property
    def envs(self) -> Path:
        return self.home / "envs"

    @property
    def sources(self) -> Path:
        return self.home / "sources"

    @property
    def state(self) -> Path:
        return self.home / "state"

    @property
    def runs(self) -> Path:
        return self.home / "runs"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def workspace(self) -> Path:
        return self.home / "workspace"

    @property
    def database(self) -> Path:
        return self.home / "scipatch.db"

    @property
    def connections(self) -> Path:
        return self.home / "connections.json"

    @property
    def secrets(self) -> Path:
        return self.home / "secrets.json"

    @property
    def config(self) -> Path:
        """The user's settings (``scipatch config``)."""
        return self.home / "config.json"

    @property
    def maturity(self) -> Path:
        """Maturity levels the user lowered on this computer."""
        return self.home / "maturity.json"

    def ensure(self) -> SciPatchPaths:
        """Create the directory skeleton if it does not exist yet."""
        for directory in (self.tools, self.envs, self.sources, self.state, self.runs, self.logs):
            directory.mkdir(parents=True, exist_ok=True)
        return self
