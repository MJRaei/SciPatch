"""Environment backends, with fake executables (no downloads)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from motel.environments import BuildLog, CondaBackend
from motel.errors import BuildError
from motel.manifest import Environment
from motel.reporting import NullReporter

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
def test_conda_errors_name_the_problem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conda = tmp_path / "conda"
    conda.write_text("#!/bin/sh\necho 'PackagesNotFoundError: nope'\nexit 1\n")
    conda.chmod(0o755)
    monkeypatch.setenv("CONDA_EXE", str(conda))
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
