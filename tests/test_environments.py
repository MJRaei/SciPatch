"""Environment backends, with fake executables (no downloads)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scipatch.environments import BuildLog, CondaBackend, micromamba
from scipatch.environments.conda import find_conda
from scipatch.errors import BuildError
from scipatch.manifest import Environment
from scipatch.paths import SciPatchPaths
from scipatch.reporting import NullReporter

FAKE_CONDA = f"""#!/bin/sh
# Fails like a conda whose libmamba solver plugin is missing, unless CONDA_SOLVER=classic.
if [ "$CONDA_SOLVER" != "classic" ]; then
    echo "CondaValueError: You have chosen a non-default solver backend (libmamba) but..."
    exit 1
fi
while [ $# -gt 0 ]; do
    if [ "$1" = "-p" ]; then prefix="$2"; fi
    shift
done
mkdir -p "$prefix/bin"
ln -s "{sys.executable}" "$prefix/bin/python"
"""


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX shell script")
def test_conda_retries_with_classic_solver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conda = tmp_path / "conda"
    conda.write_text(FAKE_CONDA)
    conda.chmod(0o755)
    monkeypatch.setenv("CONDA_EXE", str(conda))
    monkeypatch.setenv(micromamba.OPT_OUT_VARIABLE, "1")
    monkeypatch.delenv("MAMBA_EXE", raising=False)
    monkeypatch.delenv("CONDA_SOLVER", raising=False)

    log = BuildLog(tmp_path / "build.log", NullReporter())
    env_dir = tmp_path / "env"
    CondaBackend().create(
        Environment(manager="conda", python="3.12"),
        env_dir=env_dir,
        package_dir=tmp_path,
        source_dir=None,
        log=log,
    )
    assert (env_dir / "bin" / "python").exists()
    assert "retrying with the classic solver" in log.path.read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX shell script")
def test_conda_uses_only_the_manifest_channels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conda = tmp_path / "conda"
    record = f'#!/bin/sh\necho "$@" > "{tmp_path}/args"\n'
    conda.write_text(FAKE_CONDA.replace("#!/bin/sh\n", record))
    conda.chmod(0o755)
    monkeypatch.setenv("CONDA_EXE", str(conda))
    monkeypatch.setenv(micromamba.OPT_OUT_VARIABLE, "1")
    monkeypatch.delenv("MAMBA_EXE", raising=False)
    monkeypatch.setenv("CONDA_SOLVER", "classic")
    CondaBackend().create(
        Environment(manager="conda", python="3.12", conda_packages=["xtb=6.7.1"]),
        env_dir=tmp_path / "env",
        package_dir=tmp_path,
        source_dir=None,
        log=BuildLog(tmp_path / "build.log", NullReporter()),
    )
    arguments = (tmp_path / "args").read_text().split()
    assert "--override-channels" in arguments
    assert arguments[arguments.index("-c") + 1] == "conda-forge"


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX shell script")
def test_conda_errors_name_the_problem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conda = tmp_path / "conda"
    conda.write_text("#!/bin/sh\necho 'PackagesNotFoundError: nope'\nexit 1\n")
    conda.chmod(0o755)
    monkeypatch.setenv("CONDA_EXE", str(conda))
    monkeypatch.setenv(micromamba.OPT_OUT_VARIABLE, "1")
    with pytest.raises(BuildError) as caught:
        CondaBackend().create(
            Environment(manager="conda", conda_packages=["nope"]),
            env_dir=tmp_path / "env",
            package_dir=tmp_path,
            source_dir=None,
            log=BuildLog(tmp_path / "build.log", NullReporter()),
        )
    assert "PackagesNotFoundError: nope" in caught.value.message
    assert caught.value.hint is not None and "conda_packages" in caught.value.hint


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.data


def _serve(monkeypatch: pytest.MonkeyPatch, data: bytes, published: bytes) -> list[str]:
    """Serve ``data`` for micromamba downloads, with the hash of ``published`` pinned."""
    import hashlib

    requested: list[str] = []
    monkeypatch.setattr(micromamba, "platform_name", lambda: "linux-64")
    monkeypatch.setitem(micromamba._SHA256, "linux-64", hashlib.sha256(published).hexdigest())

    def urlopen(url: str, timeout: float) -> _FakeResponse:
        requested.append(url)
        return _FakeResponse(data)

    monkeypatch.setattr(micromamba.urllib.request, "urlopen", urlopen)
    return requested


def test_managed_micromamba_is_downloaded_once_and_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested = _serve(monkeypatch, b"binary", b"binary")
    path = micromamba.ensure(tmp_path)
    assert path == micromamba.executable(tmp_path)
    assert path.read_bytes() == b"binary"
    assert path.stat().st_mode & 0o111
    assert requested[0].endswith(f"{micromamba.VERSION}/micromamba-linux-64")
    micromamba.ensure(tmp_path)
    assert len(requested) == 1  # never downloaded twice


def test_a_tampered_micromamba_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, b"tampered", b"binary")
    with pytest.raises(micromamba.DownloadError, match="checksum"):
        micromamba.ensure(tmp_path)
    assert not micromamba.executable(tmp_path).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX shell script")
def test_conda_tools_use_scipatch_micromamba_before_plain_conda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = SciPatchPaths.from_env().home
    fake = micromamba.executable(home)
    fake.parent.mkdir(parents=True, exist_ok=True)
    record = f'#!/bin/sh\necho "$MAMBA_ROOT_PREFIX $@" > "{tmp_path}/args"\n'
    script = FAKE_CONDA.replace("#!/bin/sh\n", record)
    fake.write_text(script.replace('"$CONDA_SOLVER" != "classic"', "1 = 0"))  # always succeeds
    fake.chmod(0o755)
    conda = tmp_path / "conda"
    conda.write_text("#!/bin/sh\necho 'plain conda must not be used'\nexit 1\n")
    conda.chmod(0o755)
    monkeypatch.setenv("CONDA_EXE", str(conda))
    monkeypatch.delenv("MAMBA_EXE", raising=False)
    monkeypatch.delenv(micromamba.OPT_OUT_VARIABLE, raising=False)
    monkeypatch.setattr(micromamba, "platform_name", lambda: "linux-64")
    monkeypatch.setattr("scipatch.environments.conda.shutil.which", lambda name: None)

    assert find_conda() == str(fake)
    CondaBackend().create(
        Environment(manager="conda", python="3.12"),
        env_dir=tmp_path / "env",
        package_dir=tmp_path,
        source_dir=None,
        log=BuildLog(tmp_path / "build.log", NullReporter()),
    )
    recorded = (tmp_path / "args").read_text().split()
    assert recorded[0] == str(micromamba.root_prefix(home))  # its own package cache
    assert "--override-channels" in recorded

    monkeypatch.setenv(micromamba.OPT_OUT_VARIABLE, "1")
    assert find_conda() == str(conda)
