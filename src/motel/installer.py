"""Install, rebuild, check, and test tool packages."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from motel import __version__
from motel.build import BuildLayout, BuildOutcome, build, run_golden_tests
from motel.catalogs import CatalogStore
from motel.environments import BuildLog
from motel.environments.uv import UvBackend, find_uv
from motel.errors import BuildError, MotelError, ToolExistsError, ToolNotFoundError
from motel.manifest import (
    LOCK_FILENAME,
    MANIFEST_FILENAME,
    Manifest,
    find_manifest,
    load_manifest,
)
from motel.models import ToolState, utcnow
from motel.paths import MotelPaths
from motel.registry import InstalledTool, Registry
from motel.reporting import Reporter
from motel.runtime.executor import environment_python
from motel.secrets import SecretStore
from motel.source import SourceCheckout, git_executable

#: Never copied into an installed tool: they are rebuilt from the manifest.
COPY_IGNORE = shutil.ignore_patterns(
    "source", ".motel", ".git", ".venv", "__pycache__", "*.pyc", ".DS_Store",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
)  # fmt: skip

#: Where ``motel check`` builds a package under development.
DEV_ENV_DIR = Path(".motel") / "env"
DEV_LOG = Path(".motel") / "build.log"
DEV_SOURCE_DIR = Path("source")

_GIT_URL_PREFIXES = ("https://", "http://", "git@", "ssh://", "git+", "file://")


@dataclass(frozen=True)
class ResolvedPackage:
    path: Path
    origin: str
    is_local: bool


def is_git_url(spec: str) -> bool:
    return spec.startswith(_GIT_URL_PREFIXES) or spec.endswith(".git")


def dev_layout(package_dir: Path) -> BuildLayout:
    """Build locations for a package folder under development."""
    return BuildLayout(
        package_dir=package_dir,
        env_dir=package_dir / DEV_ENV_DIR,
        source_dir=package_dir / DEV_SOURCE_DIR,
        log_path=package_dir / DEV_LOG,
    )


def resolve_package(
    spec: str,
    *,
    scratch: Path,
    ref: str | None = None,
    catalogs: CatalogStore | None = None,
) -> ResolvedPackage:
    """Find the tool package ``spec`` refers to: a folder, a catalog name, or a git URL."""
    path = Path(spec).expanduser()
    if path.exists():
        folder = path.parent if path.name == MANIFEST_FILENAME else path
        try:
            find_manifest(folder)
        except MotelError:
            raise MotelError(
                f"{folder} is not a Motel tool package (it has no {MANIFEST_FILENAME}).",
                hint=f"To turn a code repository into a tool, run 'motel onboard {folder}'.",
            ) from None
        return ResolvedPackage(folder.resolve(), str(folder.resolve()), is_local=True)

    if is_git_url(spec):
        return _clone_package(spec, scratch=scratch, ref=ref)

    entry = catalogs.find(spec) if catalogs is not None else None
    if entry is not None:
        return ResolvedPackage(entry.folder, entry.origin, is_local=False)

    raise ToolNotFoundError(
        f"'{spec}' is not a folder, a tool in your catalogs, or a git URL.",
        hint="See what's available with 'motel catalog'.",
    )


def _clone_package(spec: str, *, scratch: Path, ref: str | None) -> ResolvedPackage:
    url, _, fragment = spec.partition("#")
    url = url.removeprefix("git+")
    subdirectory = fragment.removeprefix("subdirectory=").strip("/")
    target = scratch / "package"
    git = git_executable()
    clone = [git, "clone", "--quiet", "--depth", "1"]
    if ref:
        clone += ["--branch", ref]
    completed = subprocess.run(
        [*clone, url, str(target)], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0 and ref:
        # --branch does not accept commit ids: fall back to a full clone + checkout.
        shutil.rmtree(target, ignore_errors=True)
        completed = subprocess.run(
            [git, "clone", "--quiet", url, str(target)], capture_output=True, text=True, check=False
        )
        if completed.returncode == 0:
            completed = subprocess.run(
                [git, "-C", str(target), "checkout", "--quiet", ref],
                capture_output=True,
                text=True,
                check=False,
            )
    if completed.returncode != 0:
        raise MotelError(
            f"Could not download {url}: {completed.stderr.strip()}",
            hint="Check the URL (and --ref), and your internet connection.",
        )
    commit = subprocess.run(
        [git, "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    folder = target / subdirectory if subdirectory else target
    if not (folder / MANIFEST_FILENAME).is_file():
        raise MotelError(
            f"{url} is a code repository, not a Motel tool package (no {MANIFEST_FILENAME}"
            f"{' in ' + subdirectory if subdirectory else ''}).",
            hint=f"Turn it into a tool with your AI agent: motel onboard {url}",
        )
    origin = f"{url}@{commit[:12]}" + (f"#subdirectory={subdirectory}" if subdirectory else "")
    return ResolvedPackage(folder, origin, is_local=False)


class Installer:
    def __init__(self, paths: MotelPaths, registry: Registry, reporter: Reporter) -> None:
        self.paths = paths
        self.registry = registry
        self.reporter = reporter

    def install(
        self,
        spec: str,
        *,
        link: bool = False,
        force: bool = False,
        run_tests: bool = True,
        allow_failing_tests: bool = False,
        ref: str | None = None,
    ) -> InstalledTool:
        """Install a tool package and build it from scratch."""
        with tempfile.TemporaryDirectory(prefix="motel-add-") as scratch:
            package = resolve_package(
                spec, scratch=Path(scratch), ref=ref, catalogs=CatalogStore(self.paths)
            )
            if link and not package.is_local:
                raise MotelError("--link only works with a local folder.")
            manifest = load_manifest(package.path)
            name = manifest.name
            replacing = self.registry.exists(name)
            if replacing and not force:
                raise ToolExistsError(
                    f"A tool named '{name}' is already installed.",
                    hint=f"Use --force to replace it, or 'motel rebuild {name}' to rebuild it.",
                )

            self.paths.ensure()
            staging = self.paths.tools / f".{name}.staging"
            _remove_path(staging)
            if link:
                staging.symlink_to(package.path, target_is_directory=True)
            else:
                shutil.copytree(package.path, staging, ignore=COPY_IGNORE)

            layout = BuildLayout(
                package_dir=staging,
                env_dir=self.paths.envs / name,
                source_dir=self.paths.sources / name,
                log_path=self.paths.logs / f"build-{name}.log",
            )
            self.reporter.step(f"Installing '{name}' from {package.origin}")
            try:
                outcome = build(
                    manifest,
                    layout,
                    reporter=self.reporter,
                    fresh=True,
                    run_tests=run_tests,
                    secrets=self._secrets_for(manifest),
                )
                if not outcome.tests_passed and not allow_failing_tests:
                    raise BuildError(
                        f"Golden tests failed: {_failed_tests(outcome)}.",
                        hint="Fix the tool, or install anyway with --allow-failing-tests.",
                        log_path=str(layout.log_path),
                    )
            except BaseException as exc:
                _remove_path(staging)
                if replacing:
                    self._mark_broken(name, f"Replacing the tool failed: {exc}")
                else:
                    for directory in (layout.env_dir, layout.source_dir):
                        _remove_path(directory)
                raise

            target = self.paths.tools / name
            _remove_path(target)
            staging.rename(target)
            self.registry.save_state(
                name,
                _state_from(
                    outcome, manifest.environment.manager, origin=package.origin, linked=link
                ),
            )
        tool = self.registry.get(name)
        self.reporter.success(f"Installed '{name}' ({len(tool.functions)} function(s))")
        return tool

    def rebuild(self, name: str, *, clean: bool = False, run_tests: bool = True) -> InstalledTool:
        tool = self.registry.get(name)
        previous = tool.state
        self.reporter.step(f"Rebuilding '{name}'" + (" from scratch" if clean else ""))
        try:
            outcome = build(
                tool.manifest,
                tool.layout,
                reporter=self.reporter,
                fresh=clean,
                run_tests=run_tests,
                secrets=self._secrets_for(tool.manifest),
            )
        except MotelError as exc:
            self._mark_broken(name, exc.message)
            raise
        state = _state_from(
            outcome,
            tool.manifest.environment.manager,
            origin=previous.installed_from if previous else str(tool.package_dir),
            linked=tool.linked,
        )
        if previous:
            state.installed_at = previous.installed_at
            if not run_tests:
                state.golden, state.status = previous.golden, previous.status
        self.registry.save_state(name, state)
        self.reporter.success(f"Rebuilt '{name}'")
        return self.registry.get(name)

    def check(
        self, package_dir: Path, *, clean: bool = False, run_tests: bool = True
    ) -> BuildOutcome:
        """Build and verify a package folder in place, without installing it."""
        package_dir = package_dir.resolve()
        manifest = load_manifest(package_dir)
        return build(
            manifest,
            dev_layout(package_dir),
            reporter=self.reporter,
            fresh=clean,
            run_tests=run_tests,
            secrets=self._secrets_for(manifest),
        )

    def test(self, name: str) -> InstalledTool:
        """Re-run an installed tool's golden tests and record the outcome."""
        tool = self.registry.get(name)
        if not tool.manifest.golden:
            raise MotelError(f"'{name}' has no golden tests.")
        state = tool.state
        if state is None or not tool.usable:
            raise BuildError(f"'{name}' is not built.", hint=f"Run 'motel rebuild {name}' first.")
        self.reporter.step(f"Running {len(tool.manifest.golden)} golden test(s) for '{name}'")
        results = run_golden_tests(tool.manifest, tool.runtime, tool.package_dir, self.reporter)
        state.golden = results
        state.status = "ready" if all(r.passed or r.skipped for r in results) else "failing-tests"
        self.registry.save_state(name, state)
        return self.registry.get(name)

    def save_patch(self, target: str, label: str) -> Path | None:
        """Save unsaved source edits of a package folder (or installed tool) as a patch."""
        folder = Path(target).expanduser()
        if (folder / MANIFEST_FILENAME).is_file():
            package_dir, source_dir = folder.resolve(), folder.resolve() / DEV_SOURCE_DIR
        else:
            tool = self.registry.get(target)
            package_dir, source_dir = tool.package_dir.resolve(), tool.layout.source_dir
        if not (source_dir / ".git").exists():
            raise MotelError(
                f"There is no source checkout at {source_dir}.",
                hint="Run 'motel check' first; it downloads the source named in motel.yaml.",
            )
        log = BuildLog(self.paths.logs / "patch.log", self.reporter)
        return SourceCheckout(source_dir, log).save_patch(package_dir / "patches", label)

    def freeze(self, target: str) -> tuple[Path, int, Path]:
        """Pin the package versions of a built environment into the package's lock file.

        ``target`` is a tool package folder (the one you share). Versions come
        from its development build (``motel check``), or else from the installed
        tool of the same name. Returns the lock path, the number of pinned
        packages, and the environment they were read from.
        """
        package_dir = Path(target).expanduser().resolve()
        if not (package_dir / MANIFEST_FILENAME).is_file():
            raise MotelError(
                f"{target} is not a tool package folder.",
                hint="Freeze the folder you share, e.g. 'motel freeze tools/chgnet'.",
            )
        manifest = load_manifest(package_dir)
        candidates = [dev_layout(package_dir).env_dir, self.paths.envs / manifest.name]
        env_dir = next((d for d in candidates if environment_python(d).exists()), None)
        if env_dir is None:
            raise MotelError(
                f"'{manifest.name}' has no built environment to read versions from.",
                hint=f"Build and test it first with 'motel check {target}'.",
            )
        uv = find_uv()
        if uv is None:
            raise BuildError("uv is not installed.", hint=UvBackend.install_hint)
        python = environment_python(env_dir)
        frozen = subprocess.run(
            [uv, "pip", "freeze", "--python", str(python), "--exclude-editable"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        pins = sorted(
            (line for line in frozen.splitlines() if line and " @ file://" not in line),
            key=str.lower,
        )
        describe_python = "import platform as p; print(p.python_version(), p.system(), p.machine())"
        about = subprocess.run(
            [str(python), "-c", describe_python],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        lock = package_dir / LOCK_FILENAME
        lock.write_text(
            "# Exact versions this tool was tested with, written by 'motel freeze'.\n"
            f"# Built with Python {about}. Applied as constraints when building the\n"
            "# environment; packages not listed here resolve normally.\n"
            + "".join(f"{pin}\n" for pin in pins),
            encoding="utf-8",
        )
        return lock, len(pins), env_dir

    def _secrets_for(self, manifest: Manifest) -> dict[str, str]:
        return SecretStore(self.paths.secrets).resolve(manifest.environment.secrets)

    def _mark_broken(self, name: str, reason: str) -> None:
        state = self.registry.load_state(name)
        if state is None:
            return
        state.status = "broken"
        state.error = reason
        self.registry.save_state(name, state)


def _state_from(outcome: BuildOutcome, manager: str, *, origin: str, linked: bool) -> ToolState:
    return ToolState(
        status="ready" if outcome.tests_passed else "failing-tests",
        installed_from=origin,
        linked=linked,
        built_at=utcnow(),
        motel_version=__version__,
        python_version=outcome.python_version,
        env_manager=manager,
        env_fingerprint=outcome.env_fingerprint,
        source_commit=outcome.source_commit,
        functions=outcome.functions,
        golden=outcome.golden,
        warnings=outcome.warnings,
    )


def _failed_tests(outcome: BuildOutcome) -> str:
    failed = [r for r in outcome.golden if not (r.passed or r.skipped)]
    return "; ".join(f"'{r.name}' ({r.error or ', '.join(r.failures)})" for r in failed)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
