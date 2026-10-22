"""Editing AI apps' configuration files safely."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from scipatch.clients import (
    ClaudeCode,
    ClaudeDesktop,
    Codex,
    ConnectionStore,
    Cursor,
    GeminiCli,
    ServerCommand,
    _remove_toml_table,
    update_json_file,
)
from scipatch.errors import ClientConfigError

SERVER = ServerCommand("/opt/bin/scipatch", ["serve"])


@pytest.mark.parametrize("app", [ClaudeDesktop(), Cursor(), GeminiCli()])
def test_json_apps_add_and_remove_only_their_entry(app: ClaudeDesktop) -> None:
    config = app.config_path
    config.parent.mkdir(parents=True, exist_ok=True)
    original = {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}
    config.write_text(json.dumps(original))

    app.connect(SERVER)
    data = json.loads(config.read_text())
    assert data["mcpServers"]["scipatch"] == {"command": "/opt/bin/scipatch", "args": ["serve"]}
    assert data["mcpServers"]["other"] == {"command": "x"}
    assert data["theme"] == "dark"
    assert app.is_connected()
    # The file as it was before SciPatch touched it is kept.
    backup = config.with_name(config.name + ".scipatch-backup")
    assert json.loads(backup.read_text()) == original

    app.disconnect()
    assert json.loads(config.read_text()) == original
    assert not app.is_connected()


def test_claude_code_without_cli_edits_user_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scipatch.clients.shutil.which", lambda _: None)
    app = ClaudeCode()
    app.config_path.write_text(json.dumps({"projects": {"/x": {}}}))
    app.connect(ServerCommand("/opt/bin/scipatch", ["serve"], {"SCIPATCH_HOME": "/data"}))
    data = json.loads(app.config_path.read_text())
    assert data["mcpServers"]["scipatch"] == {
        "type": "stdio",
        "command": "/opt/bin/scipatch",
        "args": ["serve"],
        "env": {"SCIPATCH_HOME": "/data"},
    }
    assert data["projects"] == {"/x": {}}


def test_invalid_json_is_never_modified(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ // comments are not JSON\n}")
    with pytest.raises(ClientConfigError, match="not plain JSON"):
        update_json_file(path, lambda data: data.update(x=1))
    assert path.read_text() == "{ // comments are not JSON\n}"


def test_missing_config_file_is_created(tmp_path: Path) -> None:
    path = tmp_path / "new" / "config.json"
    update_json_file(path, lambda data: data.update(mcpServers={}))
    assert json.loads(path.read_text()) == {"mcpServers": {}}


def test_codex_toml_is_updated_in_place() -> None:
    app = Codex()
    app.config_path.parent.mkdir(parents=True)
    app.config_path.write_text(
        'model = "o5"\n\n[mcp_servers.other]\ncommand = "x"\n\n'
        '[mcp_servers.scipatch]\ncommand = "old"\n\n[mcp_servers.scipatch.env]\nA = "1"\n\n'
        '[profiles.fast]\nmodel = "mini"\n'
    )
    app.connect(SERVER)
    data = tomllib.loads(app.config_path.read_text())
    assert data["mcp_servers"]["scipatch"] == {"command": "/opt/bin/scipatch", "args": ["serve"]}
    assert data["mcp_servers"]["other"] == {"command": "x"}
    assert data["profiles"]["fast"] == {"model": "mini"}
    assert data["model"] == "o5"
    assert app.is_connected()

    app.disconnect()
    data = tomllib.loads(app.config_path.read_text())
    assert "scipatch" not in data["mcp_servers"]
    assert data["profiles"]["fast"] == {"model": "mini"}


def test_codex_creates_config_with_env() -> None:
    app = Codex()
    app.connect(
        ServerCommand("C:\\scipatch\\scipatch.exe", ["serve"], {"SCIPATCH_HOME": "D:\\data"})
    )
    data = tomllib.loads(app.config_path.read_text())
    assert data["mcp_servers"]["scipatch"]["command"] == "C:\\scipatch\\scipatch.exe"
    assert data["mcp_servers"]["scipatch"]["env"] == {"SCIPATCH_HOME": "D:\\data"}


def test_remove_toml_table_keeps_other_tables() -> None:
    text = "[a]\nx = 1\n[a.b]\ny = 2\n[ab]\nz = 3\n[[c]]\nw = 4\n"
    assert _remove_toml_table(text, "a") == "[ab]\nz = 3\n[[c]]\nw = 4\n"


def test_connection_store_tracks_skills_folders(tmp_path: Path) -> None:
    store = ConnectionStore(tmp_path / "connections.json")
    store.add(ClaudeCode())
    store.add(Codex())
    store.add(ClaudeDesktop())  # no skills folder
    assert store.skills_dirs() == sorted([ClaudeCode().skills_dir, Codex().skills_dir])
    store.remove("codex")
    assert set(store.load()) == {"claude-code", "claude-desktop"}
