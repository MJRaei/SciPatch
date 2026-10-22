"""Running Linux-only tools on Windows inside WSL.

The end-to-end test emulates Windows on any POSIX system: a stand-in ``wsl.exe``
runs the Linux commands on this machine, and a stand-in micromamba creates the
"Linux" environment, so the whole flow (build in WSL, pointer, calls through the
shim, variables, cancellation) runs without Windows.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from scipatch import platforms, wsl
from scipatch.app import SciPatch
from scipatch.environments import micromamba
from scipatch.errors import BuildError
from scipatch.lock import Lock, PlatformLock, inputs_hash, save
from scipatch.manifest import load_manifest
from scipatch.models import RunStatus
from scipatch.runtime import executor
from scipatch.runtime.executor import ToolRuntime, pid_alive

from .conftest import ManifestFactory

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="emulates WSL with shell scripts")

FAKE_WSL = """#!/bin/sh
# Stand-in for wsl.exe: runs the Linux command on this machine.
while [ $# -gt 0 ]; do
    case "$1" in
        -d) shift 2 ;;
        --cd) cd "$2" || exit 1; shift 2 ;;
        --exec) shift; break ;;
        *) break ;;
    esac
done
exec "$@"
"""

FAKE_MICROMAMBA = f"""#!/bin/sh
# Stand-in for micromamba: "creates" the environment with this test's Python.
while [ $# -gt 0 ]; do
    if [ "$1" = "-p" ]; then prefix="$2"; fi
    shift
done
mkdir -p "$prefix/bin"
ln -s "{sys.executable}" "$prefix/bin/python"
"""


def test_paths_and_commands_cross_between_windows_and_linux() -> None:
    distro = wsl.Distro(name="Ubuntu", home="/home/ada")
    assert distro.to_linux("C:\\Users\\ada\\My Data\\x.cif") == "/mnt/c/Users/ada/My Data/x.cif"
    assert distro.to_linux("\\\\wsl.localhost\\Ubuntu\\home\\ada\\f") == "/home/ada/f"
    assert distro.to_linux("/home/ada/f") == "/home/ada/f"
    assert distro.to_windows("/mnt/d/runs/a.png") == "D:\\runs\\a.png"
    assert distro.to_windows("/home/ada/f") == "\\\\wsl.localhost\\Ubuntu\\home\\ada\\f"
    assert distro.command(["python", "-V"], cwd="C:\\work") == [
        "wsl.exe", "-d", "Ubuntu", "--cd", "C:\\work", "--exec", "python", "-V",
    ]  # fmt: skip


def test_variables_and_secrets_reach_linux_through_wslenv_not_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WSLENV", "USERPROFILE/p")
    distro = wsl.Distro(name="Ubuntu", home="/home/ada")
    runtime = ToolRuntime(
        python=Path("unused"),
        env_dir=Path("C:\\scipatch\\envs\\gpaw"),
        package_dir=Path("C:\\scipatch\\tools\\gpaw"),
        entrypoint="api",
        variables={"OMP_NUM_THREADS": "1"},
        secrets={"MP_API_KEY": "s3cret"},
        linux=wsl.LinuxEnvironment(distro=distro, prefix="/home/ada/.scipatch/envs/gpaw-1"),
    )
    env = runtime.child_environment()
    shared = env["WSLENV"].split(":")
    assert shared[0] == "USERPROFILE/p"
    assert {"MP_API_KEY", "OMP_NUM_THREADS", "SCIPATCH_PREPEND_PATH", "SCIPATCH_WSL_ROOT"} <= set(
        shared
    )
    assert env["SCIPATCH_PREPEND_PATH"] == "/home/ada/.scipatch/envs/gpaw-1/bin"
    command = executor._command(runtime, "call", Path("C:\\scipatch\\runs\\r1\\request.json"))
    assert command[:3] == ["wsl.exe", "-d", "Ubuntu"]
    assert command[-2:] == ["call", "/mnt/c/scipatch/runs/r1/request.json"]
    assert "s3cret" not in " ".join(command)


def _pretend_windows(monkeypatch: pytest.MonkeyPatch, distro: wsl.Distro | None) -> None:
    monkeypatch.setattr(platforms, "current", lambda: "win-64")
    monkeypatch.setattr(wsl, "host_is_windows", lambda: True)
    monkeypatch.setattr(wsl, "detect", lambda: distro)


def _linux_only_lock(package: Path) -> None:
    manifest = load_manifest(package)
    entries = {
        "linux-64": PlatformLock(),
        "win-64": PlatformLock(unavailable="conda-forge has no Windows build of gpaw =26.7.0"),
    }
    save(
        package,
        Lock(inputs=inputs_hash(manifest, package), tested_on="linux-64", platforms=entries),
    )


def test_without_wsl_the_user_is_told_how_to_get_it(
    scipatch: SciPatch, make_package: ManifestFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(functions=["add"])
    _linux_only_lock(package)
    _pretend_windows(monkeypatch, None)
    with pytest.raises(BuildError) as caught:
        scipatch.check(package)
    assert "runs on Windows inside WSL" in caught.value.message
    assert caught.value.hint == wsl.INSTALL_HINT


def test_a_linux_only_tool_is_built_and_run_inside_wsl(
    scipatch: SciPatch,
    make_package: ManifestFactory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_wsl = tmp_path / "wsl.exe"
    fake_wsl.write_text(FAKE_WSL)
    fake_wsl.chmod(0o755)
    monkeypatch.setattr(wsl, "WSL_EXE", str(fake_wsl))
    distro = wsl.Distro(name="Test", home=str(tmp_path / "linux-home"))
    downloads = []

    def download(name: str, path: Path) -> Path:  # the verified Linux micromamba, faked
        downloads.append(name)
        path.write_text(FAKE_MICROMAMBA)
        return path

    monkeypatch.setattr(micromamba, "download", download)
    _pretend_windows(monkeypatch, distro)

    golden = [{"name": "adds", "function": "add", "args": {"a": 1}, "expect": {"sum": 2}}]
    package = make_package(
        functions=["add", "sleep", "secret_values"],
        golden=golden,
        environment={"manager": "uv", "python": f"{sys.version_info[0]}.{sys.version_info[1]}",
                     "secrets": ["DEMO_KEY"], "variables": {"OTHER_KEY": "from-manifest"}},
    )  # fmt: skip
    _linux_only_lock(package)
    scipatch.secrets.set("DEMO_KEY", "s3cret")
    scipatch.add(str(package))

    assert downloads == ["linux-64"]  # copied into WSL, executable there
    assert os.access(Path(distro.scipatch_home) / "bin" / "micromamba", os.X_OK)
    tool = scipatch.tool("sample")
    pointer = wsl.read_pointer(tool.layout.env_dir)
    assert pointer is not None and pointer.distro.name == "Test"
    assert pointer.prefix.startswith(f"{distro.home}/.scipatch/envs/sample-")
    assert tool.state is not None and tool.state.golden_summary == "1/1 golden tests passed"

    record = scipatch.run("sample", "secret_values")
    assert record.result == {"demo": "s3cret", "other": "from-manifest"}
    assert (Path(record.run_dir) / wsl.PID_FILE).exists()  # the Linux process group

    long = scipatch.run("sample", "sleep", {"seconds": 60}, wait=0)
    deadline = time.monotonic() + 20
    while not (Path(long.run_dir) / wsl.PID_FILE).exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    cancelled = scipatch.cancel_run(long.id)
    assert cancelled.status is RunStatus.CANCELLED
    assert not pid_alive(long.pid)

    scipatch.remove("sample")
    assert not Path(pointer.prefix).exists()  # the Linux side is deleted too
    assert os.environ.get("WSLENV") is None or "DEMO_KEY" not in os.environ["WSLENV"]


def test_the_shim_translates_paths_inside_wsl(tmp_path: Path) -> None:
    from scipatch.runtime import shim

    root = "/mnt/"
    assert (
        shim.linux_path("C:\\Users\\ada\\My Data\\x.cif", root) == "/mnt/c/Users/ada/My Data/x.cif"
    )
    assert shim.linux_path("D:/runs/abc", root) == "/mnt/d/runs/abc"
    assert shim.linux_path("\\\\wsl.localhost\\Ubuntu\\home\\ada\\f", root) == "/home/ada/f"
    for text in ("CCO", "1/2<110>", "c1ccccc1", "C:"):  # not paths: unchanged
        assert shim.linux_path(text, root) == text
    assert (
        shim.windows_path("/mnt/c/Users/ada/plot.png", root, "Ubuntu") == "C:\\Users\\ada\\plot.png"
    )
    existing = str(tmp_path)
    assert shim.windows_path(existing, root, "Ubuntu") == (
        "\\\\wsl.localhost\\Ubuntu" + existing.replace("/", "\\")
    )
    assert shim.windows_path("/no/such/file", root, "Ubuntu") == "/no/such/file"
    assert shim.windows_path("/mnt/cdrom", root, "Ubuntu") == "/mnt/cdrom"
    nested = {"files": ["C:\\a\\b.txt", 3], "name": "x"}
    assert shim.map_strings(nested, lambda s: shim.linux_path(s, root)) == {
        "files": ["/mnt/c/a/b.txt", 3],
        "name": "x",
    }
