"""Install, rebuild, check, and test tool packages."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scipatch import __version__, wsl
from scipatch.build import BuildLayout, BuildOutcome, build, run_golden_tests
from scipatch.catalogs import CatalogStore
from scipatch.environments import BuildLog
from scipatch.errors import BuildError, SciPatchError, ToolExistsError, ToolNotFoundError
from scipatch.freeze import FreezeResult
from scipatch.freeze import freeze as freeze_platforms
from scipatch.manifest import (
    MANIFEST_FILENAME,
    Manifest,
    Secret,
    find_manifest,
    load_manifest,
)
from scipatch.models import ToolState, utcnow
from scipatch.paths import SciPatchPaths
from scipatch.platforms import label as platform_label
from scipatch.registry import InstalledTool, Registry
from scipatch.reporting import Reporter
from scipatch.runtime.executor import environment_python
from scipatch.secrets import SecretStore
from scipatch.source import SourceCheckout, git_executable

#: Never copied into an installed tool: they are rebuilt from the manifest.
COPY_IGNORE = shutil.ignore_patterns(
    "source", ".scipatch", ".git", ".venv", "__pycache__", "*.pyc", ".DS_Store",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
)  # fmt: skip

#: Where ``scipatch check`` builds a package under development.
DEV_ENV_DIR = Path(".scipatch") / "env"
DEV_LOG = Path(".scipatch") / "build.log"
DEV_SOURCE_DIR = Path("source")

#: Asks the user for a secret during install; returns None to skip it.
AskSecret = Callable[[Secret], str | None]

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
        except SciPatchError:
            raise SciPatchError(
                f"{folder} is not a SciPatch tool package (it has no {MANIFEST_FILENAME}).",
                hint=f"To turn a code repository into a tool, run 'scipatch onboard {folder}'.",
            ) from None
        return ResolvedPackage(folder.resolve(), str(folder.resolve()), is_local=True)

    if is_git_url(spec):
        return _clone_package(spec, scratch=scratch, ref=ref)

    entry = catalogs.find(spec) if catalogs is not None else None
    if entry is not None:
        return ResolvedPackage(entry.folder, entry.origin, is_local=False)

    raise ToolNotFoundError(
        f"'{spec}' is not a folder, a tool in your catalogs, or a git URL.",
        hint="See what's available with 'scipatch catalog'.",
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
        raise SciPatchError(
            f"Could not download {url}: {completed.stderr.strip()}",
            hint="Check the URL (and --ref), and your internet connection.",
        )
    commit = subprocess.run(
        [git, "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    folder = target / subdirectory if subdirectory else target
    if not (folder / MANIFEST_FILENAME).is_file():
        raise SciPatchError(
            f"{url} is a code repository, not a SciPatch tool package (no {MANIFEST_FILENAME}"
            f"{' in ' + subdirectory if subdirectory else ''}).",
            hint=f"Turn it into a tool with your AI agent: scipatch onboard {url}",
        )
    origin = f"{url}@{commit[:12]}" + (f"#subdirectory={subdirectory}" if subdirectory else "")
    return ResolvedPackage(folder, origin, is_local=False)


class Installer:
    def __init__(self, paths: SciPatchPaths, registry: Registry, reporter: Reporter) -> None:
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
        all_tests: bool = False,
        allow_failing_tests: bool = False,
        ref: str | None = None,
        ask_secret: AskSecret | None = None,
    ) -> InstalledTool:
        """Install a tool package and build it from scratch.

        ``ask_secret`` is called for each declared secret that is not set yet;
        a returned value is stored before building, so golden tests can use it.
        Only the quick golden tests run unless ``all_tests`` is set.
        """
        with tempfile.TemporaryDirectory(prefix="scipatch-add-") as scratch:
            package = resolve_package(
                spec, scratch=Path(scratch), ref=ref, catalogs=CatalogStore(self.paths)
            )
            if link and not package.is_local:
                raise SciPatchError("--link only works with a local folder.")
            manifest = load_manifest(package.path)
            name = manifest.name
            replacing = self.registry.exists(name)
            if replacing and not force:
                raise ToolExistsError(
                    f"A tool named '{name}' is already installed.",
                    hint=f"Use --force to replace it, or 'scipatch rebuild {name}' to rebuild it.",
                )
            if ask_secret is not None:
                self._ask_missing_secrets(manifest, ask_secret)

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
                    quick_tests=not all_tests,
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
                    wsl.remove_environment(layout.env_dir)
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

    def rebuild(
        self, name: str, *, clean: bool = False, run_tests: bool = True, all_tests: bool = False
    ) -> InstalledTool:
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
                quick_tests=not all_tests,
                secrets=self._secrets_for(tool.manifest),
            )
        except SciPatchError as exc:
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
            raise SciPatchError(f"'{name}' has no golden tests.")
        state = tool.state
        if state is None or not tool.usable:
            raise BuildError(
                f"'{name}' is not built.", hint=f"Run 'scipatch rebuild {name}' first."
            )
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
            raise SciPatchError(
                f"There is no source checkout at {source_dir}.",
                hint="Run 'scipatch check' first; it downloads the source named in scipatch.yaml.",
            )
        log = BuildLog(self.paths.logs / "patch.log", self.reporter)
        return SourceCheckout(source_dir, log).save_patch(package_dir / "patches", label)

    def freeze(self, target: str) -> FreezeResult:
        """Pin the packages of a tested environment, and resolve every other platform.

        ``target`` is a tool package folder (the one you share). Versions come
        from its development build (``scipatch check``), or else from the installed
        tool of the same name; other platforms are resolved without installing.
        """
        package_dir = Path(target).expanduser().resolve()
        if not (package_dir / MANIFEST_FILENAME).is_file():
            raise SciPatchError(
                f"{target} is not a tool package folder.",
                hint="Freeze the folder you share, e.g. 'scipatch freeze tools/chgnet'.",
            )
        manifest = load_manifest(package_dir)
        installed = self.paths.envs / manifest.name
        layouts = [
            (dev_layout(package_dir).env_dir, dev_layout(package_dir).source_dir),
            (installed, self.paths.sources / manifest.name),
        ]
        found = next(
            ((env, source) for env, source in layouts if environment_python(env).exists()), None
        )
        if found is None:
            raise SciPatchError(
                f"'{manifest.name}' has no built environment to read versions from.",
                hint=f"Build and test it first with 'scipatch check {target}'.",
            )
        env_dir, source_root = found
        if wsl.read_pointer(env_dir) is not None:
            raise SciPatchError(
                f"'{manifest.name}' was built inside WSL; freeze reads the tested environment "
                "directly, which needs Linux or macOS.",
                hint="Run 'scipatch check' and 'scipatch freeze' for this tool on Linux or macOS.",
            )
        source = manifest.source
        source_dir = (
            source_root / (source.subdirectory or "") if source.repo and source.install else None
        )
        return freeze_platforms(
            manifest,
            package_dir,
            env_dir,
            source_dir,
            progress=lambda name: self.reporter.detail(f"Resolving for {platform_label(name)}"),
        )

    def _secrets_for(self, manifest: Manifest) -> dict[str, str]:
        return SecretStore(self.paths.secrets).resolve(manifest.environment.secret_names)

    def _ask_missing_secrets(self, manifest: Manifest, ask: AskSecret) -> None:
        store = SecretStore(self.paths.secrets)
        available = store.resolve(manifest.environment.secret_names)
        for secret in manifest.environment.secrets:
            if secret.name not in available and (value := ask(secret)):
                store.set(secret.name, value)

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
        scipatch_version=__version__,
        python_version=outcome.python_version,
        env_manager=manager,
        env_fingerprint=outcome.env_fingerprint,
        env_size_mb=outcome.env_size_mb,
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
