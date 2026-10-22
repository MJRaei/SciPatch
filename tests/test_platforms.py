"""Platforms, per-platform locks, and resolving other platforms in ``scipatch freeze``."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scipatch import freeze, platforms
from scipatch.errors import BuildError, ManifestError
from scipatch.lock import (
    LEGACY_LOCK_FILENAME,
    Lock,
    PlatformLock,
    inputs_hash,
    pins_for_build,
    save,
)
from scipatch.manifest import Environment, Manifest, load_manifest

from .conftest import ManifestFactory


def _completed(
    stdout: str = "", stderr: str = "", code: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


class FakeRunner:
    """Answers commands in order and records them."""

    def __init__(self, *answers: subprocess.CompletedProcess[str]) -> None:
        self.answers = list(answers)
        self.commands: list[list[str]] = []
        self.stdins: list[str | None] = []

    def __call__(
        self, command: list[str], stdin: str | None, env: dict[str, str] | None
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        self.stdins.append(stdin)
        return self.answers.pop(0)


def test_markers_select_packages_per_platform() -> None:
    packages = [
        "openmm=8.6.1",
        "ambertools=23.3; sys_platform != 'win32'",
        "mlx; sys_platform == 'darwin' and platform_machine == 'arm64'",
    ]
    assert platforms.for_platform(packages, "win-64", "3.12") == ["openmm=8.6.1"]
    assert platforms.for_platform(packages, "linux-64", "3.12") == [
        "openmm=8.6.1",
        "ambertools=23.3",
    ]
    assert platforms.for_platform(packages, "osx-arm64", "3.12") == [
        "openmm=8.6.1",
        "ambertools=23.3",
        "mlx",
    ]
    assert platforms.applies("x; python_version >= '3.12'", "linux-64", "3.12")
    assert not platforms.applies("x; python_version >= '3.13'", "linux-64", "3.12")


def test_manifest_rejects_bad_markers_and_unknown_platforms(make_package: ManifestFactory) -> None:
    package = make_package(environment={"manager": "conda", "conda_packages": ["x; nonsense"]})
    with pytest.raises(ManifestError, match="invalid environment marker"):
        load_manifest(package)
    package = make_package(environment={"platforms": ["win-64", "amiga-68k"]})
    with pytest.raises(ManifestError, match="amiga-68k"):
        load_manifest(package)


def _lock_for(manifest: Manifest, package: Path, **entries: PlatformLock) -> None:
    save(
        package,
        Lock(inputs=inputs_hash(manifest, package), tested_on="linux-64", platforms=entries),
    )


def test_a_build_uses_this_platforms_pins(
    make_package: ManifestFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package()
    manifest = load_manifest(package)
    monkeypatch.setattr(platforms, "current", lambda: "win-64")
    _lock_for(
        manifest,
        package,
        **{
            "linux-64": PlatformLock(pip=["numpy==2.0.0"]),
            "win-64": PlatformLock(pip=["numpy==2.0.1"]),
        },
    )
    pins = pins_for_build(manifest, package)
    assert pins.pip == ["numpy==2.0.1"]
    assert pins.warnings == []


def test_an_unsupported_platform_is_refused_with_the_reason(
    make_package: ManifestFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package()
    manifest = load_manifest(package)
    monkeypatch.setattr(platforms, "current", lambda: "win-64")
    _lock_for(
        manifest,
        package,
        **{
            "linux-64": PlatformLock(),
            "win-64": PlatformLock(unavailable="conda-forge has no Windows build of crest =2.12"),
        },
    )
    with pytest.raises(BuildError) as caught:
        pins_for_build(manifest, package)
    assert (
        "cannot be installed on Windows: conda-forge has no Windows build" in caught.value.message
    )
    assert caught.value.hint == "It is available on: Linux (x86-64)."


def test_a_stale_lock_is_not_applied(make_package: ManifestFactory) -> None:
    package = make_package()
    manifest = load_manifest(package)
    here = platforms.current() or "linux-64"
    save(package, Lock(inputs="something else", platforms={here: PlatformLock(pip=["x==1"])}))
    pins = pins_for_build(manifest, package)
    assert pins.pip == []
    assert "out of date" in pins.warnings[0]


def test_a_legacy_lock_still_applies_everywhere(make_package: ManifestFactory) -> None:
    package = make_package()
    (package / LEGACY_LOCK_FILENAME).write_text("numpy==2.0.0\n")
    pins = pins_for_build(load_manifest(package), package)
    assert pins.legacy_constraints == package / LEGACY_LOCK_FILENAME
    save(package, Lock(inputs="x", platforms={}))  # a new lock replaces it
    assert not (package / LEGACY_LOCK_FILENAME).exists()


MISSING = """Could not solve for environment specs
    The following package could not be installed
    └─ crest =2.12 * does not exist (perhaps a typo or a missing channel).
"""
CHAIN = """Could not solve for environment specs
    The following packages are incompatible
    ├─ ambertools =* * does not exist (perhaps a typo or a missing channel);
    ├─ openmmforcefields =0.16.0 * is not installable because there are no viable options
    │  ├─ openmmforcefields 0.16.0 would require
    │  │  └─ ambertools >=22,<27 *, which does not exist (perhaps a missing channel);
"""


def test_conda_failures_are_explained_in_one_line() -> None:
    assert (
        freeze.conda_reason(MISSING, "win-64", ["conda-forge"])
        == "conda-forge has no Windows build of crest =2.12"
    )
    assert (
        freeze.conda_reason(CHAIN, "win-64", ["conda-forge"])
        == "conda-forge has no Windows build of ambertools >=22,<27"
    )


def _dry_run_output(*packages: tuple[str, str, str]) -> subprocess.CompletedProcess[str]:
    links = [{"name": n, "version": v, "build_string": b} for n, v, b in packages]
    return _completed(json.dumps({"success": True, "actions": {"LINK": links}}))


def test_conda_solves_keep_the_tested_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(freeze, "conda_frontend", lambda: ("micromamba", {}))
    run = FakeRunner(
        _dry_run_output(("python", "3.12.16", "h1"), ("xtb", "6.7.1", "h2")),
        _dry_run_output(("python", "3.12.15", "h3"), ("xtb", "6.7.1", "h2")),
    )
    spec = Environment(manager="conda", python="3.12", conda_packages=["xtb=6.7.1"])
    pins, error, note = freeze.solve_conda(
        "win-64", spec, tmp_path, ["python==3.12.15=habc", "xtb==6.7.1=hdef"], run
    )
    assert error is None and note is None
    assert pins == ["python==3.12.15=h3", "xtb==6.7.1=h2"]
    assert "--platform" in run.commands[0] and "win-64" in run.commands[0]
    assert "python==3.12.15" in run.commands[1]  # the tested version is asked for


def test_conda_reports_an_impossible_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(freeze, "conda_frontend", lambda: ("micromamba", {}))
    failure = json.dumps({"log_history": [{"level": "error", "message": MISSING}]})
    run = FakeRunner(_completed(failure, code=1))
    spec = Environment(manager="conda", python="3.12", conda_packages=["crest=2.12"])
    pins, error, _ = freeze.solve_conda("win-64", spec, tmp_path, [], run)
    assert pins == []
    assert error == "conda-forge has no Windows build of crest =2.12"


NO_WHEELS = """  No solution found when resolving dependencies:
  ╰─▶ Because {release} has no usable wheels and you require
      {release}, we can conclude that your requirements are
      unsatisfiable."""


def test_pure_python_source_packages_are_allowed() -> None:
    run = FakeRunner(
        _completed(stderr=NO_WHEELS.format(release="matcalc==0.6.0"), code=1),
        _completed("matcalc==0.6.0\nnumpy==2.5.4\n"),
    )
    pins, error = freeze._compile(
        "uv", "win-64", ["matcalc==0.6.0"], "3.12", [], run, lambda name, version: False
    )
    assert error is None
    assert pins == ["matcalc==0.6.0", "numpy==2.5.4"]
    assert run.commands[1][-2:] == ["--no-binary", "matcalc"]
    assert "x86_64-pc-windows-msvc" in run.commands[0]


def test_compiled_packages_without_a_wheel_make_a_platform_unavailable() -> None:
    run = FakeRunner(_completed(stderr=NO_WHEELS.format(release="pyscf==2.14.0"), code=1))
    pins, error = freeze._compile(
        "uv", "win-64", ["pyscf==2.14.0"], "3.12", [], run, lambda name, version: True
    )
    assert pins == []
    assert error == "pyscf 2.14.0 has no prebuilt package for Windows (Python 3.12)"


def test_other_versions_are_used_when_the_tested_ones_do_not_exist() -> None:
    mismatch = (
        "Because ovito{sys_platform == 'darwin'}==3.16.1.post1 has no wheels with a matching "
        "platform tag (e.g., `win_amd64`) and you require ovito==3.16.1.post1, we can conclude..."
    )
    run = FakeRunner(_completed(stderr=mismatch, code=1), _completed("ovito==3.16.1\n"))
    pins, error, note = freeze.resolve_pip(
        "uv", "win-64", ["ovito"], "3.13", ["ovito==3.16.1.post1"], run, lambda n, v: True
    )
    assert error is None
    assert pins == ["ovito==3.16.1"]
    assert (
        note == "PyPI versions differ from the tested platform: ovito 3.16.1 (tested 3.16.1.post1)"
    )
    assert "--constraint" in run.commands[0] and "--constraint" not in run.commands[1]


def test_a_dependency_without_wheels_is_named() -> None:
    message = (
        "Because only the following versions of torch are available: torch<=2.4.1 "
        "torch==2.5.0 and torch>=2.4.1 has no wheels with a matching platform tag "
        "(e.g., `macosx_13_0_x86_64`), we can conclude that torch>=2.4.1 cannot be used."
    )
    run = FakeRunner(_completed(stderr=message, code=1))
    _, error = freeze._compile("uv", "osx-64", ["chgnet"], "3.12", [], run, lambda n, v: True)
    assert error == "torch>=2.4.1 has no prebuilt package for macOS (Intel) (Python 3.12)"
