"""The command line, as people and agents use it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from motel import __version__
from motel.cli import app, hoist_global_flags
from motel.cli import tools as cli_tools
from motel.cli._app import get_motel

from .conftest import ManifestFactory, requires_uv

runner = CliRunner()


def motel(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the real entry point (including error handling) in a subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "motel", *args], capture_output=True, text=True, check=False
    )


def test_help_and_version() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("setup", "find", "run", "onboard", "connect"):
        assert command in result.output
    assert __version__ in runner.invoke(app, ["--version"]).output


def test_empty_list_suggests_next_steps() -> None:
    result = runner.invoke(app, ["list"])
    assert "No tools installed yet" in result.output
    assert "motel add ase-emt" in result.output
    assert json.loads(runner.invoke(app, ["list", "--json"]).output) == []


def test_secrets_are_typed_hidden_and_never_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_KEY", raising=False)
    monkeypatch.setattr(cli_tools, "_is_terminal", lambda: True)
    result = runner.invoke(app, ["secret", "set", "DEMO_KEY"], input="s3cret\n")
    assert result.exit_code == 0, result.output
    assert "Paste it here (hidden)" in result.output
    assert "Saved DEMO_KEY" in result.output
    assert "s3cret" not in result.output
    listed = runner.invoke(app, ["secret", "list"]).output
    assert "DEMO_KEY" in listed and "yes" in listed and "s3cret" not in listed
    assert runner.invoke(app, ["secret", "set", "bad-name"], input="x\n").exit_code != 0
    assert "Removed DEMO_KEY" in runner.invoke(app, ["secret", "remove", "DEMO_KEY"]).output


def test_without_a_terminal_secrets_are_piped_or_entered_in_the_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEMO_KEY", raising=False)
    piped = runner.invoke(app, ["secret", "set", "DEMO_KEY"], input="from-pipe\n")
    assert piped.exit_code == 0 and "Saved DEMO_KEY" in piped.output
    assert get_motel().secrets.resolve(["DEMO_KEY"]) == {"DEMO_KEY": "from-pipe"}

    # An AI agent's shell has neither: the user gets a page on this computer instead.
    opened: list[str] = []

    def user_enters_key(url: str) -> bool:
        opened.append(url)
        assert "Saved" in httpx.post(url, data={"DEMO_KEY": "from-browser"}).text
        return True

    monkeypatch.setattr(cli_tools.webbrowser, "open", user_enters_key)
    agent = runner.invoke(app, ["secret", "set", "DEMO_KEY"], input="")
    assert agent.exit_code == 0, agent.output
    assert opened and opened[0] in agent.output and "from-browser" not in agent.output
    assert get_motel().secrets.resolve(["DEMO_KEY"]) == {"DEMO_KEY": "from-browser"}

    monkeypatch.setattr(cli_tools, "BROWSER_WAIT_SECONDS", 0.5)
    monkeypatch.setattr(cli_tools.webbrowser, "open", lambda url: False)
    late = runner.invoke(app, ["secret", "set", "OTHER_KEY"], input="")
    assert late.exit_code != 0 and "not entered in time" in str(late.exception)


def test_catalog_lists_featured_tools() -> None:
    result = runner.invoke(app, ["catalog", "--json"])
    names = [entry["name"] for entry in json.loads(result.output)]
    assert "ase-emt" in names


def test_errors_are_friendly_with_exit_code_1() -> None:
    result = motel("info", "nothing-here")
    assert result.returncode == 1
    assert "Error: No tool named 'nothing-here' is installed." in result.stderr
    assert "Hint:" in result.stderr
    assert "Traceback" not in result.stderr


def test_new_creates_a_package(tmp_path: Path) -> None:
    target = tmp_path / "my-tool"
    result = runner.invoke(app, ["new", "my-tool", "--dir", str(target)])
    assert result.exit_code == 0, result.output
    assert (target / "motel.yaml").exists()
    again = motel("new", "my-tool", "--dir", str(target))
    assert again.returncode == 1
    assert "nothing was overwritten" in again.stderr


def test_connect_show_prints_config() -> None:
    result = runner.invoke(app, ["connect", "--show"])
    assert result.exit_code == 0
    assert '"motel"' in result.output
    assert '"serve"' in result.output


def test_connect_writes_app_config_and_skills(isolated_home: Path) -> None:
    result = runner.invoke(app, ["connect", "cursor"])
    assert result.exit_code == 0, result.output
    config = json.loads((isolated_home / ".cursor" / "mcp.json").read_text())
    assert config["mcpServers"]["motel"]["args"][-1] == "serve"
    assert (isolated_home / ".cursor" / "skills" / "motel" / "SKILL.md").exists()

    result = runner.invoke(app, ["disconnect", "cursor"])
    assert result.exit_code == 0
    assert (
        "motel"
        not in json.loads((isolated_home / ".cursor" / "mcp.json").read_text())["mcpServers"]
    )
    assert not (isolated_home / ".cursor" / "skills" / "motel").exists()


@pytest.mark.integration
@requires_uv
def test_add_find_run_and_history(make_package: ManifestFactory, tmp_path: Path) -> None:
    package = make_package(functions=["add", "write_text", "fail"])
    result = runner.invoke(app, ["add", str(package)])
    assert result.exit_code == 0, result.output
    assert "sample is ready" in result.output

    found = json.loads(runner.invoke(app, ["find", "add numbers", "--json"]).output)
    assert found[0]["function"] == "add"

    ran = runner.invoke(app, ["run", "sample", "add", "a=2", "b=0.5", "--json"])
    assert ran.exit_code == 0, ran.output
    view = json.loads(ran.output)
    assert view["result"] == {"sum": 2.5}

    # tool.function form, and an argument that must stay a string.
    ran = runner.invoke(app, ["run", "sample.write_text", "text=123", "--json"])
    assert json.loads(ran.output)["result"]["length"] == 3

    failed = runner.invoke(app, ["run", "sample", "fail", "message=oops"])
    assert failed.exit_code == 1
    assert "ValueError: oops" in failed.output

    runs = json.loads(runner.invoke(app, ["runs", "--json", "--tool", "sample"]).output)
    assert len(runs) == 3
    shown = json.loads(runner.invoke(app, ["runs", "show", view["run_id"], "--json"]).output)
    assert shown["status"] == "succeeded"

    info = json.loads(runner.invoke(app, ["info", "sample", "--json"]).output)
    assert info["status"] == "ready"
    assert runner.invoke(app, ["remove", "sample", "--yes"]).exit_code == 0


def test_global_flags_are_accepted_anywhere() -> None:
    assert hoist_global_flags(["run", "t", "f", "a=1", "--verbose"]) == [
        "--verbose", "run", "t", "f", "a=1",
    ]  # fmt: skip
    assert hoist_global_flags(["exec", ".", "--", "python", "-v"]) == [
        "exec", ".", "--", "python", "-v",
    ]  # fmt: skip
    result = motel("list", "--debug")
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
@requires_uv
def test_human_readable_views_render(make_package: ManifestFactory, tmp_path: Path) -> None:
    """Every human-facing view renders, including text with [brackets] (Rich markup)."""
    package = make_package(
        summary="Adds numbers [eV] and writes files [for testing], with a summary long enough "
        "to wrap inside the info panel's border ending in zebra.",
        validity="Valid for [all] inputs.",
        functions={"add": {"params": {"a": {"unit": "eV/Å"}}}, "fail": {}},
        golden=[{"name": "adds [ok]", "function": "add", "args": {"a": 1}, "expect": {"sum": 2}}],
    )
    (package / "SKILL.md").write_text("---\ndescription: test [tool]\n---\n# Notes [x]\nUse it.\n")
    assert runner.invoke(app, ["add", str(package)]).exit_code == 0

    checks = [
        (["list"], "sample"),
        (["info", "sample"], "number [eV/Å]"),
        (["info", "sample"], "zebra"),  # long text wraps instead of being cut off
        (["find", "add numbers"], "sample add"),
        (["run", "sample", "add", "a=1"], '"sum": 2.0'),
        (["run", "sample", "fail", "message=[bad]"], "ValueError: [bad]"),
        (["runs"], "sample add"),
        (["check", str(package)], "Package is valid"),
        (["check", str(package), "--skip-tests"], "functions look right"),
        (["doctor"], "Tools"),
        (["skills", "export", str(tmp_path / "skills")], "Exported"),
    ]
    for args, expected in checks:
        result = runner.invoke(app, args)
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            args,
            result.exception,
        )
        assert expected in result.output, (args, result.output)
    run_id = json.loads(runner.invoke(app, ["runs", "--json", "-n", "1"]).output)[0]["run_id"]
    shown = motel("runs", "show", run_id, "--verbose")  # real entry point: flag after command
    assert "Traceback" in shown.stdout
