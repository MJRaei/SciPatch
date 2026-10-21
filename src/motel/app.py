"""The ``Motel`` facade: one object behind the CLI, the MCP gateway, and the Python API.

Example::

    from motel.app import Motel

    motel = Motel()
    hits = motel.find("relax a crystal structure")
    record = motel.run("ase-emt", "relax", {"structure": "Cu.cif"}, wait=60)
    print(record.status, record.result)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from motel.build import BuildOutcome, runtime_for
from motel.clients import APPS, AppIntegration, ConnectionStore, get_app, server_command
from motel.errors import MotelError
from motel.freeze import FreezeResult
from motel.history import RunStore
from motel.installer import Installer, dev_layout
from motel.manifest import MANIFEST_FILENAME, load_manifest
from motel.models import FunctionInfo, RunRecord, RunStatus
from motel.paths import MotelPaths
from motel.registry import InstalledTool, Registry
from motel.reporting import NullReporter, Reporter
from motel.runs import RunManager
from motel.search import SearchHit, ToolIndex
from motel.secrets import SecretStore
from motel.skills import SkillManager, SyncReport


@dataclass(frozen=True)
class Match:
    """A search result with its tool and function resolved."""

    hit: SearchHit
    tool: InstalledTool
    function: FunctionInfo


@dataclass(frozen=True)
class ConnectResult:
    app: AppIntegration
    message: str
    skills: SyncReport | None


class Motel:
    def __init__(self, paths: MotelPaths | None = None, reporter: Reporter | None = None) -> None:
        self.paths = (paths or MotelPaths.from_env()).ensure()
        self.reporter: Reporter = reporter or NullReporter()
        self.registry = Registry(self.paths)
        self.history = RunStore(self.paths.database)
        self.runs = RunManager(self.paths, self.history)
        self.installer = Installer(self.paths, self.registry, self.reporter)
        self.skills = SkillManager(self.registry)
        self.connections = ConnectionStore(self.paths.connections)
        self.secrets = SecretStore(self.paths.secrets)

    # ------------------------------------------------------------------ tools

    def tools(self) -> list[InstalledTool]:
        return self.registry.tools()

    def tool(self, name: str) -> InstalledTool:
        return self.registry.get(name)

    def find(self, query: str, limit: int = 10) -> list[Match]:
        tools = {tool.name: tool for tool in self.tools() if tool.usable}
        index = ToolIndex(list(tools.values()))
        matches = []
        for hit in index.search(query, limit=limit):
            tool = tools[hit.tool]
            matches.append(Match(hit, tool, tool.function(hit.function)))
        return matches

    def add(self, spec: str, **options: Any) -> InstalledTool:
        """Install a tool package (folder, featured tool name, or git URL)."""
        tool = self.installer.install(spec, **options)
        self.sync_skills()
        return tool

    def remove(self, name: str) -> None:
        self.registry.get(name)  # raises a helpful error for unknown names
        self.registry.remove(name)
        self.sync_skills()

    def rebuild(self, name: str, *, clean: bool = False, run_tests: bool = True) -> InstalledTool:
        tool = self.installer.rebuild(name, clean=clean, run_tests=run_tests)
        self.sync_skills()
        return tool

    def test(self, name: str) -> InstalledTool:
        tool = self.installer.test(name)
        self.sync_skills()
        return tool

    def check(
        self, package_dir: Path, *, clean: bool = False, run_tests: bool = True
    ) -> BuildOutcome:
        return self.installer.check(package_dir, clean=clean, run_tests=run_tests)

    def save_patch(self, target: str, label: str) -> Path | None:
        return self.installer.save_patch(target, label)

    def freeze(self, target: str) -> FreezeResult:
        return self.installer.freeze(target)

    def exec(self, target: str, command: list[str]) -> int:
        """Run a command inside a tool's environment (package folder or installed tool)."""
        folder = Path(target).expanduser()
        if (folder / MANIFEST_FILENAME).is_file():
            manifest = load_manifest(folder)
            layout = dev_layout(folder.resolve())
            hint = f"Build it first with 'motel check {target}'."
        else:
            tool = self.tool(target)
            manifest, layout = tool.manifest, tool.layout
            hint = f"Rebuild it with 'motel rebuild {target}'."
        secrets = SecretStore(self.paths.secrets).resolve(manifest.environment.secret_names)
        runtime = runtime_for(manifest, layout, secrets)
        if not runtime.ready():
            raise MotelError(f"The environment for '{target}' does not exist yet.", hint=hint)
        env = runtime.child_environment()
        if runtime.linux is not None:  # inside WSL, with the environment first on PATH
            script = 'PATH="$MOTEL_PREPEND_PATH:$PATH"; export PATH; exec "$@"'
            command = runtime.linux.distro.command(["sh", "-c", script, "sh", *command], Path.cwd())
        try:
            return subprocess.call(command, env=env)
        except FileNotFoundError as exc:
            raise MotelError(f"Command not found: {command[0]}") from exc

    # ------------------------------------------------------------------- runs

    def run(
        self,
        tool: str,
        function: str,
        args: dict[str, Any] | None = None,
        *,
        wait: float | None = None,
        output_dir: Path | None = None,
        use_cache: bool = True,
        origin: str = "python",
        base_dir: Path | None = None,
    ) -> RunRecord:
        """Run a function, waiting up to ``wait`` seconds (``None``: until it finishes)."""
        record = self.runs.start(
            self.tool(tool),
            function,
            args,
            output_dir=output_dir,
            use_cache=use_cache,
            origin=origin,
            base_dir=base_dir,
        )
        if record.cached or record.status.finished:
            return record
        return self.runs.wait(record.id, timeout=wait)

    def get_run(self, run_id: str, *, wait: float = 0) -> RunRecord:
        return self.runs.wait(run_id, timeout=wait) if wait > 0 else self.runs.get(run_id)

    def cancel_run(self, run_id: str) -> RunRecord:
        return self.runs.cancel(run_id)

    def history_list(
        self,
        *,
        tool: str | None = None,
        status: RunStatus | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[RunRecord]:
        records = self.history.query(tool=tool, status=status, query=query, limit=limit)
        return [self.runs.get(r.id) if r.status is RunStatus.RUNNING else r for r in records]

    # ----------------------------------------------------------------- skills

    def sync_skills(self) -> list[SyncReport]:
        """Refresh skills in every connected app's skills folder."""
        return [self.skills.sync(directory) for directory in self.connections.skills_dirs()]

    # ---------------------------------------------------------------- clients

    def connect(self, app_key: str, *, skills: bool = True) -> ConnectResult:
        app = get_app(app_key)
        message = app.connect(server_command())
        self.connections.add(app)
        report = self.skills.sync(app.skills_dir) if skills and app.skills_dir else None
        return ConnectResult(app, message, report)

    def disconnect(self, app_key: str) -> str:
        app = get_app(app_key)
        message = app.disconnect()
        self.connections.remove(app.key)
        # Keep skills that another connected app still reads from the same folder.
        if app.skills_dir and app.skills_dir not in self.connections.skills_dirs():
            removed = self.skills.remove_all(app.skills_dir)
            if removed:
                message += f"; removed {len(removed)} skill(s) from {app.skills_dir}"
        return message

    @staticmethod
    def apps() -> list[AppIntegration]:
        return list(APPS.values())
