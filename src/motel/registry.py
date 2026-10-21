"""The registry of installed tools.

The registry is deliberately just folders: ``tools/<name>/`` holds each tool
package (or a symlink to it, for tools under development) and
``state/<name>.json`` holds what the last build learned. Users can inspect
both directly, and nothing needs migrating when Motel is upgraded.
"""

from __future__ import annotations

import difflib
import json
import logging
import shutil
from pathlib import Path

from pydantic import ValidationError

from motel import frontmatter, wsl
from motel.build import BuildLayout, runtime_for
from motel.errors import ManifestError, ToolNotFoundError
from motel.manifest import MANIFEST_FILENAME, NAME_PATTERN, Manifest, load_manifest
from motel.maturity import MaturityOverrides, effective
from motel.models import FunctionInfo, ToolState
from motel.paths import MotelPaths
from motel.runtime.executor import ToolRuntime
from motel.secrets import SecretStore

logger = logging.getLogger(__name__)

GUIDE_FILENAME = "SKILL.md"


class InstalledTool:
    """A tool in the registry: its package, manifest, and build state."""

    def __init__(
        self, name: str, manifest: Manifest, state: ToolState | None, paths: MotelPaths
    ) -> None:
        self.name = name
        self.manifest = manifest
        self.state = state
        self.paths = paths

    def __repr__(self) -> str:
        return f"InstalledTool({self.name!r}, status={self.status!r})"

    @property
    def package_dir(self) -> Path:
        return self.paths.tools / self.name

    @property
    def layout(self) -> BuildLayout:
        return BuildLayout(
            package_dir=self.package_dir,
            env_dir=self.paths.envs / self.name,
            source_dir=self.paths.sources / self.name,
            log_path=self.paths.logs / f"build-{self.name}.log",
        )

    @property
    def runtime(self) -> ToolRuntime:
        secrets = SecretStore(self.paths.secrets).resolve(self.manifest.environment.secret_names)
        return runtime_for(self.manifest, self.layout, secrets)

    @property
    def linked(self) -> bool:
        return self.package_dir.is_symlink()

    @property
    def status(self) -> str:
        return self.state.status if self.state else "not-built"

    @property
    def usable(self) -> bool:
        return self.status in ("ready", "failing-tests")

    @property
    def maturity(self) -> str:
        """The manifest's maturity level, or the lower one the user set on this computer."""
        lowered = MaturityOverrides(self.paths.maturity).get(self.name)
        return effective(self.manifest.maturity, lowered)

    @property
    def functions(self) -> list[FunctionInfo]:
        return self.state.functions if self.state else []

    def function(self, name: str) -> FunctionInfo:
        """Look up one function, suggesting close matches when the name is wrong."""
        for function in self.functions:
            if function.name == name:
                return function
        names = [f.name for f in self.functions]
        close = difflib.get_close_matches(name, names, n=3)
        hint = f"Did you mean: {', '.join(close)}?" if close else None
        raise ToolNotFoundError(
            f"Tool '{self.name}' has no function '{name}'. "
            f"Available: {', '.join(names) or 'none'}.",
            hint=hint,
        )

    def _guide_text(self) -> str | None:
        path = self.package_dir / GUIDE_FILENAME
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def guide(self) -> str | None:
        """The package's own SKILL.md body (usage notes written for agents)."""
        text = self._guide_text()
        return (frontmatter.body(text).strip() or None) if text else None

    def guide_description(self) -> str | None:
        """``description`` from the package SKILL.md frontmatter: when to use the tool."""
        text = self._guide_text()
        description = frontmatter.read(text).get("description") if text else None
        return str(description).strip() if description else None


class Registry:
    """Read and modify the set of installed tools."""

    def __init__(self, paths: MotelPaths) -> None:
        self.paths = paths

    def names(self) -> list[str]:
        if not self.paths.tools.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.paths.tools.iterdir()
            if NAME_PATTERN.match(entry.name) and (entry / MANIFEST_FILENAME).is_file()
        )

    def exists(self, name: str) -> bool:
        return name in self.names()

    def tools(self) -> list[InstalledTool]:
        """All installed tools whose manifest can be read (broken ones are logged)."""
        found = []
        for name in self.names():
            try:
                found.append(self.get(name))
            except ManifestError as exc:
                logger.warning("Skipping tool '%s': %s", name, exc.message)
        return found

    def get(self, name: str) -> InstalledTool:
        if (
            not NAME_PATTERN.match(name)
            or not (self.paths.tools / name / MANIFEST_FILENAME).is_file()
        ):
            close = difflib.get_close_matches(name, self.names(), n=3)
            hint = (
                f"Did you mean: {', '.join(close)}?"
                if close
                else "See installed tools with 'motel list', or add one with 'motel add'."
            )
            raise ToolNotFoundError(f"No tool named '{name}' is installed.", hint=hint)
        manifest = load_manifest(self.paths.tools / name)
        return InstalledTool(name, manifest, self.load_state(name), self.paths)

    # ------------------------------------------------------------------ state

    def _state_path(self, name: str) -> Path:
        return self.paths.state / f"{name}.json"

    def load_state(self, name: str) -> ToolState | None:
        path = self._state_path(name)
        try:
            return ToolState.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (ValidationError, json.JSONDecodeError):
            logger.warning("Ignoring unreadable state file %s", path)
            return None

    def save_state(self, name: str, state: ToolState) -> None:
        path = self._state_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    # ----------------------------------------------------------------- remove

    def remove(self, name: str) -> None:
        """Delete a tool's package copy, environment, source checkout, and state.

        For linked tools only the link is removed; the original folder is kept.
        """
        tool_dir = self.paths.tools / name
        if tool_dir.is_symlink():
            tool_dir.unlink()
        elif tool_dir.exists():
            shutil.rmtree(tool_dir)
        wsl.remove_environment(self.paths.envs / name)  # its Linux side, if it has one
        for directory in (self.paths.envs / name, self.paths.sources / name):
            if directory.exists():
                shutil.rmtree(directory)
        self._state_path(name).unlink(missing_ok=True)
