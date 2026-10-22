"""End-to-end behaviour with real environments (built with uv from stdlib-only packages)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from scipatch import platforms
from scipatch.app import SciPatch
from scipatch.errors import BuildError, InvalidArgumentsError, RunError, ToolExistsError
from scipatch.installer import dev_layout
from scipatch.models import RunStatus
from scipatch.runtime.executor import SHIM_PATH, environment_python, pid_alive
from scipatch.views import run_view

from .conftest import ManifestFactory, requires_git, requires_uv

pytestmark = [pytest.mark.integration, requires_uv]

GOLDEN = [{"name": "adds", "function": "add", "args": {"a": 2, "b": 3}, "expect": {"sum": 5}}]
CORE = ["add", "write_text", "fail", "sleep", "mode"]


@pytest.fixture
def installed(scipatch: SciPatch, make_package: ManifestFactory) -> SciPatch:
    scipatch.add(str(make_package(functions=CORE, golden=GOLDEN)))
    return scipatch


def test_install_describes_functions_and_runs_golden_tests(installed: SciPatch) -> None:
    tool = installed.tool("sample")
    assert tool.status == "ready"
    assert [f.name for f in tool.functions] == CORE
    add = tool.function("add")
    assert add.summary == "Add two numbers."
    assert add.properties["b"] == {
        "type": "number",
        "description": "Second number.",
        "default": 1.0,
    }
    assert tool.state is not None
    assert tool.state.golden_summary == "1/1 golden tests passed"
    assert tool.state.python_version
    assert installed.paths.envs.joinpath("sample").is_dir()


def test_runs_record_results_files_and_errors(installed: SciPatch, tmp_path: Path) -> None:
    ok = installed.run("sample", "add", {"a": 1.5})
    assert ok.status is RunStatus.SUCCEEDED
    assert ok.result == {"sum": 2.5}

    written = installed.run("sample", "write_text", {"text": "hello"})
    output = Path(written.result["path"])
    assert output.is_absolute()
    assert output.read_text() == "hello"
    assert written.files == [str(output)]
    assert output.parent == Path(written.run_dir)

    custom = installed.run("sample", "write_text", {"text": "x"}, output_dir=tmp_path / "results")
    assert Path(custom.result["path"]).parent == (tmp_path / "results").resolve()

    failed = installed.run("sample", "fail", {"message": "bad input"})
    assert failed.status is RunStatus.FAILED
    assert failed.error is not None
    assert failed.error["type"] == "ValueError"
    assert failed.error["message"] == "bad input"
    assert Path(failed.error["logs"]).exists()

    assert installed.run("sample", "mode", {"kind": "slow"}).result == "slow"
    history = installed.history_list(tool="sample")
    assert [r.status for r in history][-1] is RunStatus.SUCCEEDED
    assert installed.history_list(query="bad input")[0].id == failed.id


def test_identical_calls_are_served_from_cache(installed: SciPatch) -> None:
    first = installed.run("sample", "add", {"a": 1, "b": 2})
    second = installed.run("sample", "add", {"b": 2, "a": 1})
    assert second.cached
    assert second.id == first.id
    third = installed.run("sample", "add", {"a": 1, "b": 2}, use_cache=False)
    assert not third.cached
    assert third.id != first.id


def test_cache_follows_file_contents(installed: SciPatch, tmp_path: Path) -> None:
    data = tmp_path / "input.txt"
    data.write_text("one")
    first = installed.run("sample", "write_text", {"text": str(data)})
    assert installed.run("sample", "write_text", {"text": str(data)}).cached
    data.write_text("two")
    assert not installed.run("sample", "write_text", {"text": str(data)}).cached
    assert first.status is RunStatus.SUCCEEDED


def test_arguments_are_checked_before_running(installed: SciPatch) -> None:
    with pytest.raises(InvalidArgumentsError, match="missing required argument"):
        installed.run("sample", "add", {})
    with pytest.raises(InvalidArgumentsError, match="unknown argument"):
        installed.run("sample", "add", {"a": 1, "c": 2})
    with pytest.raises(InvalidArgumentsError, match="a should be number, not ''"):
        installed.run("sample", "add", {"a": ""})
    with pytest.raises(InvalidArgumentsError, match=r"kind should be fast\|slow"):
        installed.run("sample", "mode", {"kind": "medium"})


def test_background_runs_can_be_collected_or_cancelled(installed: SciPatch) -> None:
    running = installed.run("sample", "sleep", {"seconds": 0.5}, wait=0)
    assert running.status is RunStatus.RUNNING
    done = installed.get_run(running.id, wait=30)
    assert done.status is RunStatus.SUCCEEDED
    assert done.result == {"slept": 0.5}

    long = installed.run("sample", "sleep", {"seconds": 60}, wait=0)
    started = time.monotonic()
    cancelled = installed.cancel_run(long.id)
    assert cancelled.status is RunStatus.CANCELLED
    assert time.monotonic() - started < 10
    assert not pid_alive(long.pid)
    with pytest.raises(RunError, match="No run"):
        installed.get_run("20260101-000000-000000")


def test_runs_finished_after_the_starter_exited_are_finalized(installed: SciPatch) -> None:
    started = installed.run("sample", "sleep", {"seconds": 0.3}, wait=0)
    # A different SciPatch instance (e.g. a later CLI call) sees and finalizes the run.
    observer = SciPatch(installed.paths)
    assert observer.get_run(started.id, wait=30).status is RunStatus.SUCCEEDED
    assert installed.get_run(started.id).status is RunStatus.SUCCEEDED


def test_failed_golden_test_aborts_install_and_cleans_up(
    scipatch: SciPatch, make_package: ManifestFactory
) -> None:
    golden = [{"name": "wrong", "function": "add", "args": {"a": 1}, "expect": {"sum": 3}}]
    package = make_package(golden=golden)
    with pytest.raises(BuildError, match="Golden tests failed: 'wrong'"):
        scipatch.add(str(package))
    assert scipatch.tools() == []
    assert not (scipatch.paths.envs / "sample").exists()
    assert list(scipatch.paths.tools.iterdir()) == []

    tool = scipatch.add(str(package), allow_failing_tests=True)
    assert tool.status == "failing-tests"
    with pytest.raises(ToolExistsError):
        scipatch.add(str(package))


def test_import_errors_explain_what_to_do(
    scipatch: SciPatch, make_package: ManifestFactory
) -> None:
    package = make_package(api="import not_a_real_package\n\ndef f() -> int:\n    return 1\n")
    with pytest.raises(BuildError) as caught:
        scipatch.add(str(package))
    assert "ModuleNotFoundError" in caught.value.message
    assert caught.value.hint is not None
    assert "environment.packages" in caught.value.hint


@requires_git
def test_source_checkout_and_patches(
    scipatch: SciPatch, make_package: ManifestFactory, upstream_repo: tuple[str, str]
) -> None:
    url, commit = upstream_repo
    package = make_package(source={"repo": url, "ref": commit, "install": False})

    # Develop in place: the source is checked out next to the package.
    outcome = scipatch.check(package)
    assert outcome.source_commit == commit
    layout = dev_layout(package)
    assert (layout.source_dir / "DATA.txt").exists()
    assert layout.env_dir.is_dir()
    assert any("no golden tests" in warning for warning in outcome.warnings)

    # Fix something in the source and keep the fix as a patch.
    (layout.source_dir / "DATA.txt").write_text("patched upstream\n")
    assert scipatch.save_patch(str(package), "fix data") is not None
    assert (package / "patches" / "0001-fix-data.patch").exists()

    # Installing rebuilds from the pinned commit plus patches.
    tool = scipatch.add(str(package))
    assert tool.state is not None
    assert tool.state.source_commit == commit
    assert scipatch.run("sample", "source_file").result == "patched upstream"
    assert not (scipatch.paths.tools / "sample" / "source").exists()  # never copied


def test_rebuild_reuses_an_unchanged_environment(installed: SciPatch) -> None:
    marker = installed.paths.envs / "sample" / "keep-me"
    marker.write_text("x")
    installed.rebuild("sample")
    assert marker.exists()  # environment was not recreated
    installed.rebuild("sample", clean=True)
    assert not marker.exists()
    assert installed.tool("sample").status == "ready"


def test_linked_install_uses_the_folder_in_place(
    scipatch: SciPatch, make_package: ManifestFactory
) -> None:
    package = make_package(functions=["add"])
    scipatch.add(str(package), link=True)
    tool = scipatch.tool("sample")
    assert tool.linked
    assert tool.package_dir.resolve() == package.resolve()
    scipatch.remove("sample")
    assert package.exists()  # removing a link keeps the original folder


def test_remove_deletes_everything_but_history(installed: SciPatch) -> None:
    run = installed.run("sample", "add", {"a": 1})
    installed.remove("sample")
    assert installed.tools() == []
    for folder in (installed.paths.envs, installed.paths.state):
        assert not any(p.name.startswith("sample") for p in folder.iterdir())
    assert installed.get_run(run.id).status is RunStatus.SUCCEEDED


def test_exec_runs_inside_the_environment(installed: SciPatch) -> None:
    code = "import sys, os; sys.exit(0 if 'envs/sample' in sys.prefix.replace(os.sep, '/') else 3)"
    assert installed.exec("sample", ["python", "-c", code]) == 0


def test_broken_rebuild_marks_the_tool(installed: SciPatch) -> None:
    (installed.paths.tools / "sample" / "api.py").write_text("raise RuntimeError('broken')\n")
    with pytest.raises(BuildError):
        installed.rebuild("sample")
    tool = installed.tool("sample")
    assert tool.status == "broken"
    assert tool.state is not None and tool.state.error
    with pytest.raises(RunError, match="not ready"):
        installed.run("sample", "add", {"a": 1})


def test_check_reports_function_warnings(scipatch: SciPatch, make_package: ManifestFactory) -> None:
    package = make_package(api="def undocumented(x):\n    return x\n")
    outcome = scipatch.check(package, run_tests=False)
    assert "undocumented: has no docstring" in outcome.warnings
    assert "undocumented: parameter 'x' has no type hint" in outcome.warnings


@pytest.mark.parametrize("version", ["3.8", "3.9"])
def test_shim_runs_on_old_pythons(version: str, tmp_path: Path) -> None:
    """Tools may need old interpreters; the shim must keep working there."""
    env = tmp_path / "env"
    created = subprocess.run(
        [shutil.which("uv") or "uv", "venv", "-q", str(env), "--python", version],
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"Python {version} is not available to uv")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "api.py").write_text(
        "from typing import List, Optional\n\n"
        "def f(x: float, tags: Optional[List[str]] = None) -> dict:\n"
        "    '''Do f.\n\n    Args:\n        x: A number.\n        tags: Labels.\n    '''\n"
        "    return {'x': x}\n"
    )
    for command, extra in (("describe", {}), ("call", {"function": "f", "args": {"x": 1}})):
        response = tmp_path / f"{command}.json"
        request = tmp_path / f"{command}-request.json"
        request.write_text(
            json.dumps(
                {"package_dir": str(package), "entrypoint": "api", "response_path": str(response)}
                | extra
            )
        )
        subprocess.run(
            [str(environment_python(env)), "-I", str(SHIM_PATH), command, str(request)], check=True
        )
        payload = json.loads(response.read_text())
        assert payload["ok"], payload
        assert payload["python"].startswith(version)
    assert payload["value"] == {"x": 1.0}


def test_editing_a_tools_code_invalidates_cached_results(
    scipatch: SciPatch, make_package: ManifestFactory
) -> None:
    package = make_package(functions=["add"])
    scipatch.add(str(package), link=True)
    first = scipatch.run("sample", "add", {"a": 1})
    assert scipatch.run("sample", "add", {"a": 1}).cached
    api = package / "api.py"
    api.write_text(api.read_text().replace('return {"sum": a + b}', 'return {"sum": a + b + 100}'))
    changed = scipatch.run("sample", "add", {"a": 1})
    assert not changed.cached
    assert changed.id != first.id
    assert changed.result == {"sum": 102.0}


def test_stale_runs_are_closed(installed: SciPatch) -> None:
    """A run whose process is gone (e.g. after a reboot) is marked failed, not 'running'."""
    record = installed.run("sample", "sleep", {"seconds": 60}, wait=0)
    observer = SciPatch(installed.paths)  # does not own the child process
    # Simulate a reboot: the stored pid now belongs to an unrelated process (this one).
    with installed.history._connect() as db:
        db.execute("UPDATE runs SET pid = ? WHERE id = ?", (os.getpid(), record.id))
    stale = observer.get_run(record.id)
    assert stale.status is RunStatus.FAILED
    assert stale.error is not None and stale.error["type"] == "ProcessExited"
    child = installed.runs._children.pop(record.id)  # clean up the real child
    child.kill()
    child.wait()


def test_running_jobs_report_their_latest_output(
    scipatch: SciPatch, make_package: ManifestFactory
) -> None:
    scipatch.add(str(make_package(functions=["count"])))
    record = scipatch.run("sample", "count", {"n": 100, "delay": 0.1}, wait=0)
    deadline = time.monotonic() + 15
    view: dict[str, object] = {}
    while time.monotonic() < deadline:
        view = run_view(scipatch.get_run(record.id))
        if "step 3/100" in str(view.get("latest_output", "")):
            break
        time.sleep(0.2)
    assert view["status"] == "running"
    assert "step 3/100" in str(view["latest_output"])
    assert float(str(view["elapsed_seconds"])) > 0
    scipatch.cancel_run(record.id)


def test_golden_tests_can_require_a_clear_error(
    scipatch: SciPatch, make_package: ManifestFactory
) -> None:
    golden = [
        {"name": "refuses", "function": "fail", "args": {"message": "Fe is not supported"},
         "raises": "not supported"},
        {"name": "wrong message", "function": "fail", "args": {"message": "boom"},
         "raises": "not supported"},
        {"name": "does not fail", "function": "add", "args": {"a": 1}, "raises": "anything"},
    ]  # fmt: skip
    outcome = scipatch.check(make_package(functions=["add", "fail"], golden=golden))
    passed = {result.name: result.passed for result in outcome.golden}
    assert passed == {"refuses": True, "wrong message": False, "does not fail": False}
    failures = {result.name: result.failures for result in outcome.golden}
    assert "got ValueError: boom" in failures["wrong message"][0]
    assert "but it succeeded" in failures["does not fail"][0]


def test_golden_tests_can_be_limited_to_some_platforms(
    scipatch: SciPatch, make_package: ManifestFactory
) -> None:
    here = platforms.current()
    elsewhere = next(name for name in platforms.PLATFORMS if name != here)
    golden = [
        {"name": "here", "function": "add", "args": {"a": 1}, "expect": {"sum": 2},
         "platforms": [here]},
        {"name": "elsewhere", "function": "add", "args": {"a": 1}, "expect": {"sum": 99},
         "platforms": [elsewhere]},
    ]  # fmt: skip
    outcome = scipatch.check(make_package(functions=["add"], golden=golden))
    results = {result.name: result for result in outcome.golden}
    assert results["here"].passed
    assert results["elsewhere"].skipped and not results["elsewhere"].passed
    assert outcome.tests_passed


def test_install_runs_only_the_quick_golden_tests(
    scipatch: SciPatch, make_package: ManifestFactory
) -> None:
    golden = [
        {"name": "quick", "function": "add", "args": {"a": 1}, "expect": {"sum": 2},
         "quick": True},
        {"name": "slow", "function": "add", "args": {"a": 2}, "expect": {"sum": 3}},
    ]  # fmt: skip
    package = make_package(functions=["add"], golden=golden)
    tool = scipatch.add(str(package))
    assert tool.state is not None
    assert tool.state.golden_summary == "1/1 golden tests passed, 1 more run with 'scipatch test'"
    tested = scipatch.test("sample")
    assert tested.state is not None
    assert tested.state.golden_summary == "2/2 golden tests passed"
    everything = scipatch.add(str(package), force=True, all_tests=True)
    assert everything.state is not None
    assert everything.state.golden_summary == "2/2 golden tests passed"
