"""Build a tool package into something runnable, and verify it.

Building has four stages:

1. **Source**: check out the pinned upstream commit and apply ``patches/``.
2. **Environment**: create the isolated environment (skipped when nothing
   that affects it has changed since the last build).
3. **Introspection**: import the entry-point module *inside* that environment
   and describe each function (signature, docs, JSON Schema).
4. **Golden tests**: call functions with known inputs and compare the results
   with known values.

The same builder serves ``motel check`` (a package folder under development)
and ``motel add``/``motel rebuild`` (installed tools); only the
:class:`BuildLayout` differs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from motel import golden, hardware, platforms, wsl
from motel.environments import BuildLog, get_backend
from motel.environments.inside_wsl import WslBackend
from motel.errors import BuildError
from motel.lock import (
    LEGACY_LOCK_FILENAME,
    LOCK_FILENAME,
    BuildPins,
    PlatformUnavailableError,
    pins_for_build,
)
from motel.manifest import GoldenTest, Manifest
from motel.models import FunctionInfo, GoldenResult
from motel.reporting import Reporter
from motel.runtime import executor
from motel.runtime.executor import ToolRuntime
from motel.runtime.results import absolutize_paths
from motel.source import SourceCheckout, patch_files

_ENV_MARKER = ".motel-env.json"


@dataclass(frozen=True)
class BuildLayout:
    """Where a build reads the package from and writes its outputs."""

    package_dir: Path
    env_dir: Path
    source_dir: Path
    log_path: Path


@dataclass
class BuildOutcome:
    functions: list[FunctionInfo]
    golden: list[GoldenResult] = field(default_factory=list)
    source_commit: str | None = None
    python_version: str | None = None
    env_fingerprint: str = ""
    env_size_mb: float | None = None
    warnings: list[str] = field(default_factory=list)
    unsaved_source_changes: list[str] = field(default_factory=list)

    @property
    def tests_passed(self) -> bool:
        return all(result.passed or result.skipped for result in self.golden)


def runtime_for(
    manifest: Manifest, layout: BuildLayout, secrets: Mapping[str, str] | None = None
) -> ToolRuntime:
    """How to run a tool built at ``layout``; only its declared secrets are passed on."""
    declared = manifest.environment.secret_names
    linux = wsl.read_pointer(layout.env_dir)
    return ToolRuntime(
        python=layout.env_dir / wsl.POINTER
        if linux
        else executor.environment_python(layout.env_dir),
        linux=linux,
        env_dir=layout.env_dir,
        package_dir=layout.package_dir,
        entrypoint=manifest.entrypoint,
        functions=manifest.exported_names,
        variables=dict(manifest.environment.variables),
        source_dir=layout.source_dir if manifest.source.repo else None,
        secrets={name: value for name, value in (secrets or {}).items() if name in declared},
    )


def build(
    manifest: Manifest,
    layout: BuildLayout,
    *,
    reporter: Reporter,
    fresh: bool = False,
    run_tests: bool = True,
    quick_tests: bool = False,
    secrets: Mapping[str, str] | None = None,
) -> BuildOutcome:
    """Build and verify a tool package. Raises :class:`BuildError` on failure.

    With ``quick_tests``, only the golden tests marked ``quick`` run (all of them if
    the tool marks none), as when installing.
    """
    log = BuildLog(layout.log_path, reporter)
    # Before anything is downloaded: can this platform build the tool at all?
    pins, distro = _pins_for_this_computer(manifest, layout.package_dir)
    warnings: list[str] = list(pins.warnings)
    fit = hardware.assess(manifest.resources_for(), hardware.detect(), use_gpu=False)
    if fit.blockers and run_tests:
        raise BuildError(
            f"'{manifest.name}' {'; '.join(fit.blockers)}, so its golden tests cannot run here.",
            hint="Install it on a computer that has one ('--skip-tests' builds it without "
            "checking it).",
        )
    warnings.extend(fit.blockers)

    # 1. Source
    source_commit: str | None = None
    source_install_dir: Path | None = None
    unsaved: list[str] = []
    source = manifest.source
    if source.repo and source.ref:
        reporter.step(f"Preparing source {source.repo} @ {source.ref}")
        checkout = SourceCheckout(layout.source_dir, log)
        info = checkout.prepare(
            source.repo, source.ref, patch_files(layout.package_dir), fresh=fresh
        )
        source_commit = info.commit
        unsaved = info.unsaved_changes
        if info.patches:
            reporter.detail(f"Applied patches: {', '.join(info.patches)}")
        if unsaved:
            warnings.append(
                f"{len(unsaved)} edited file(s) in the source are not saved as patches yet "
                "(run 'motel patch save' to keep them)"
            )
        if source.install:
            source_install_dir = layout.source_dir / (source.subdirectory or "")
            if not source_install_dir.is_dir():
                raise BuildError(f"source.subdirectory '{source.subdirectory}' does not exist.")

    # 2. Environment
    fingerprint = environment_fingerprint(manifest, layout.package_dir, source_commit)
    spec = manifest.environment
    if fresh or read_env_fingerprint(layout.env_dir) != fingerprint:
        backend = (
            WslBackend(distro, distro.environment_prefix(_wsl_key(manifest, layout)))
            if distro is not None
            else get_backend(spec.manager)
        )
        what = f"{len(spec.packages)} package(s)" if spec.packages else "no extra packages"
        reporter.step(f"Building the environment ({spec.manager}, Python {spec.python}, {what})")
        _remove_marker(layout.env_dir)
        backend.create(
            spec,
            env_dir=layout.env_dir,
            package_dir=layout.package_dir,
            source_dir=source_install_dir,
            log=log,
            pins=pins,
        )
        write_env_fingerprint(layout.env_dir, fingerprint)
    else:
        reporter.detail("Environment is up to date")
    env_size_mb = None if distro is not None else hardware.folder_size_mb(layout.env_dir)

    # 3. Introspection
    reporter.step("Inspecting the tool's functions")
    runtime = runtime_for(manifest, layout, secrets)
    with tempfile.TemporaryDirectory(prefix="motel-describe-") as scratch:
        try:
            description = executor.describe(runtime, work_dir=Path(scratch))
        except BuildError as exc:
            exc.log_path = exc.log_path and _keep_log(Path(exc.log_path), layout.log_path)
            raise
    functions = merge_function_options(description.functions, manifest, warnings)
    if not functions:
        raise BuildError(
            f"'{manifest.entrypoint}' does not define any public functions.",
            hint="Define typed functions with docstrings in the entry-point module, "
            "or list them under 'functions' in motel.yaml.",
        )
    for function in functions:
        reporter.detail(f"Found {function.signature()}")
        warnings.extend(f"{function.name}: {warning}" for warning in function.warnings)

    # 4. Golden tests
    results: list[GoldenResult] = []
    if run_tests and manifest.golden:
        selected = quick_selection(manifest) if quick_tests else manifest.golden
        reporter.step(f"Running {len(selected)} golden test(s)")
        results = run_golden_tests(manifest, runtime, layout.package_dir, reporter, only=selected)
    elif not manifest.golden:
        warnings.append("no golden tests: add one that reproduces a number from the paper")

    return BuildOutcome(
        functions=functions,
        golden=results,
        source_commit=source_commit,
        python_version=description.python_version,
        env_fingerprint=fingerprint,
        env_size_mb=env_size_mb,
        warnings=warnings,
        unsaved_source_changes=unsaved,
    )


def _pins_for_this_computer(
    manifest: Manifest, package_dir: Path
) -> tuple[BuildPins, wsl.Distro | None]:
    """The locked packages for this computer, and the WSL distribution to build in, if any.

    On Windows, a tool whose lock has Linux packages but no Windows ones is built
    inside WSL, as the scientific codes' own documentation recommends.
    """
    try:
        return pins_for_build(manifest, package_dir), None
    except PlatformUnavailableError as unavailable:
        linux = {
            name: entry
            for name, entry in unavailable.lock.platforms.items()
            if name.startswith("linux") and not entry.unavailable
        }
        if not wsl.host_is_windows() or not linux:
            raise
        distro = wsl.detect()
        if distro is None:
            raise BuildError(
                f"'{manifest.name}' has no Windows build ({unavailable.reason}). It runs on "
                "Windows inside WSL (the Windows Subsystem for Linux), which is not set up "
                "on this computer.",
                hint=wsl.INSTALL_HINT,
            ) from None
        entry = linux.get(distro.platform)
        if entry is None:
            raise BuildError(
                f"'{manifest.name}' has no build for {platforms.label(distro.platform)}, "
                f"so it cannot run inside WSL ({distro.name}) either."
            ) from None
        note = f"no Windows build: built and run inside WSL ({distro.name})"
        return BuildPins(conda=list(entry.conda), pip=list(entry.pip), warnings=[note]), distro


def _wsl_key(manifest: Manifest, layout: BuildLayout) -> str:
    """A name for the Linux environment of one build location of a tool."""
    digest = hashlib.sha256(str(layout.env_dir).encode()).hexdigest()[:10]
    return f"{manifest.name}-{digest}"


def merge_function_options(
    described: list[dict[str, Any]], manifest: Manifest, warnings: list[str]
) -> list[FunctionInfo]:
    """Combine introspected signatures with per-function settings from the manifest."""
    functions = []
    for raw in described:
        options = manifest.options_for(raw["name"])
        parameters = copy.deepcopy(raw.get("parameters") or {})
        properties = parameters.setdefault("properties", {})
        for name, info in options.params.items():
            if name not in properties:
                warnings.append(f"{raw['name']}: motel.yaml describes unknown parameter '{name}'")
                continue
            if info.kind:
                properties[name]["x-kind"] = info.kind
            if info.unit:
                properties[name]["x-unit"] = info.unit
            if info.description:
                properties[name]["description"] = info.description
        outputs = {
            key: value.model_dump(exclude_none=True) for key, value in options.outputs.items()
        }
        functions.append(
            FunctionInfo(
                name=raw["name"],
                summary=raw.get("summary", ""),
                description=raw.get("description", ""),
                parameters=parameters,
                returns=raw.get("returns") or {},
                is_async=raw.get("is_async", False),
                warnings=raw.get("warnings", []),
                long_running=options.long_running,
                cache=options.cache,
                timeout=options.timeout,
                outputs=outputs,
            )
        )
    return functions


def quick_selection(manifest: Manifest) -> list[GoldenTest]:
    """The golden tests to run at install: those marked quick, or all if none are."""
    quick = [test for test in manifest.golden if test.quick]
    return quick or list(manifest.golden)


def run_golden_tests(
    manifest: Manifest,
    runtime: ToolRuntime,
    package_dir: Path,
    reporter: Reporter,
    only: list[GoldenTest] | None = None,
) -> list[GoldenResult]:
    results = []
    here = platforms.current()
    machine = hardware.detect()
    for test in manifest.golden:
        if only is not None and test not in only:
            results.append(
                GoldenResult(
                    name=test.name,
                    function=test.function,
                    passed=False,
                    skipped=True,
                    error=f"skipped: not run at install ('motel test {manifest.name}' runs it)",
                    reference=test.reference,
                )
            )
            continue
        if test.platforms and here not in test.platforms:
            reporter.detail(f"golden test '{test.name}' skipped on {platforms.label(here)}")
            results.append(
                GoldenResult(
                    name=test.name,
                    function=test.function,
                    passed=False,
                    skipped=True,
                    error=f"skipped: not run on {platforms.label(here)}",
                    reference=test.reference,
                )
            )
            continue
        # Golden tests run on the CPU, for reproducible values, unless a GPU is required.
        fit = hardware.assess(manifest.resources_for(test.function), machine, use_gpu=False)
        if fit.blockers:
            reporter.detail(f"golden test '{test.name}' skipped: {'; '.join(fit.blockers)}")
            results.append(
                GoldenResult(
                    name=test.name,
                    function=test.function,
                    passed=False,
                    skipped=True,
                    error=f"skipped: this computer lacks what it needs ({'; '.join(fit.blockers)})",
                    reference=test.reference,
                )
            )
            continue
        missing = [n for n in test.requires if n not in runtime.secrets and not os.environ.get(n)]
        if missing:
            reporter.warn(f"golden test '{test.name}' skipped: needs {', '.join(missing)}")
            results.append(
                GoldenResult(
                    name=test.name,
                    function=test.function,
                    passed=False,
                    skipped=True,
                    error=f"skipped: needs {', '.join(missing)}",
                    reference=test.reference,
                )
            )
            continue
        with tempfile.TemporaryDirectory(prefix="motel-golden-") as scratch:
            run_dir = Path(scratch)
            args = golden.resolve_paths(test.args, package_dir)
            response = executor.call_sync(
                runtime,
                test.function,
                args,
                workdir=run_dir,
                run_dir=run_dir,
                timeout=test.timeout,
                extra_env={"MOTEL_DEVICE": fit.device},
            )
            # Check while output files still exist (``exists`` matchers look at them).
            failure = response.get("error") or {}
            message = f"{failure.get('type')}: {failure.get('message')}"
            error = None
            if test.raises is not None:
                # The call must fail, with a message that explains why.
                if response.get("ok"):
                    failures = [f"expected an error containing {test.raises!r}, but it succeeded"]
                elif test.raises not in message:
                    failures = [f"expected an error containing {test.raises!r}, got {message}"]
                else:
                    failures = []
            elif response.get("ok"):
                value = absolutize_paths(response.get("value"), run_dir)
                failures = golden.check(test.expect, value)
            else:
                failures, error = [], message
        result = GoldenResult(
            name=test.name,
            function=test.function,
            passed=not failures and error is None,
            failures=failures,
            error=error,
            duration=response.get("duration"),
            reference=test.reference,
        )
        if result.passed:
            reporter.success(f"golden test '{test.name}' passed")
        else:
            reporter.warn(f"golden test '{test.name}' FAILED: {error or '; '.join(failures)}")
        results.append(result)
    return results


def environment_fingerprint(
    manifest: Manifest, package_dir: Path, source_commit: str | None
) -> str:
    """Hash of everything that, when changed, requires rebuilding the environment."""
    spec = manifest.environment
    material: dict[str, Any] = {
        "environment": spec.model_dump(mode="json"),
        "source": manifest.source.model_dump(
            mode="json", include={"repo", "ref", "subdirectory", "install"}
        ),
        "source_commit": source_commit,
        "patches": [_file_hash(p) for p in patch_files(package_dir)],
    }
    for relative in (spec.requirements, spec.conda_file):
        if relative:
            material[relative] = _file_hash(package_dir / relative)
    for lock_file in (LOCK_FILENAME, LEGACY_LOCK_FILENAME):
        if (package_dir / lock_file).is_file():
            material[lock_file] = _file_hash(package_dir / lock_file)
    blob = json.dumps(material, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError as exc:
        raise BuildError(f"{path.name} is referenced in motel.yaml but does not exist.") from exc


def read_env_fingerprint(env_dir: Path) -> str | None:
    try:
        data = json.loads((env_dir / _ENV_MARKER).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not (executor.environment_python(env_dir).exists() or (env_dir / wsl.POINTER).exists()):
        return None
    fingerprint = data.get("fingerprint")
    return fingerprint if isinstance(fingerprint, str) else None


def write_env_fingerprint(env_dir: Path, fingerprint: str) -> None:
    (env_dir / _ENV_MARKER).write_text(json.dumps({"fingerprint": fingerprint}), encoding="utf-8")


def _remove_marker(env_dir: Path) -> None:
    (env_dir / _ENV_MARKER).unlink(missing_ok=True)


def _keep_log(source: Path, build_log: Path) -> str:
    """Copy a log out of a temporary folder next to the build log, so it survives."""
    target = build_log.with_name(build_log.stem + "-describe.log")
    try:
        shutil.copyfile(source, target)
    except OSError:
        return str(build_log)
    return str(target)
