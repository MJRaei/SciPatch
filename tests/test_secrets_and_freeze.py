"""Secrets for tools, and pinned package versions."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from motel.app import Motel
from motel.errors import MotelError, RunError
from motel.manifest import LOCK_FILENAME, Secret
from motel.secrets import SecretStore

from .conftest import ManifestFactory, requires_uv


def test_store_is_private_and_environment_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SecretStore(tmp_path / "secrets.json")
    store.set("DEMO_KEY", "from-store")
    store.set("OTHER_KEY", "other")
    assert stat.S_IMODE((tmp_path / "secrets.json").stat().st_mode) == 0o600
    assert store.names() == ["DEMO_KEY", "OTHER_KEY"]
    assert store.resolve(["DEMO_KEY", "MISSING"]) == {"DEMO_KEY": "from-store"}
    monkeypatch.setenv("DEMO_KEY", "from-env")
    assert store.resolve(["DEMO_KEY"]) == {"DEMO_KEY": "from-env"}
    assert store.remove("OTHER_KEY")
    assert not store.remove("OTHER_KEY")
    with pytest.raises(MotelError, match="not a valid secret name"):
        store.set("lower-case", "x")
    with pytest.raises(MotelError, match="empty"):
        store.set("EMPTY", "")


@pytest.mark.integration
@requires_uv
def test_tools_get_only_their_declared_secrets(
    motel: Motel, make_package: ManifestFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEMO_KEY", raising=False)
    golden = [
        {"name": "needs a key", "function": "secret_values", "requires": ["DEMO_KEY"],
         "expect": {"demo": "s3cret"}},
    ]  # fmt: skip
    package = make_package(
        functions=["secret_values"],
        environment={"manager": "uv", "python": "3.12", "secrets": ["DEMO_KEY"]},
        golden=golden,
    )
    tool = motel.add(str(package))  # installs: the golden test is skipped, not failed
    assert tool.state is not None
    assert tool.state.golden[0].skipped
    assert tool.state.golden_summary == "0/0 golden tests passed, 1 skipped (missing secrets)"
    with pytest.raises(RunError, match="needs DEMO_KEY"):
        motel.run("sample", "secret_values")

    motel.secrets.set("DEMO_KEY", "s3cret")
    motel.secrets.set("OTHER_KEY", "not-declared")
    run = motel.run("sample", "secret_values")
    assert run.result == {"demo": "s3cret", "other": None}
    # Secrets reach the tool through its environment only, never through Motel's files.
    assert "s3cret" not in (Path(run.run_dir) / "request.json").read_text()
    assert "s3cret" not in str(run.args)
    tested = motel.test("sample")
    assert tested.state is not None
    assert tested.state.golden_summary == "1/1 golden tests passed"


@pytest.mark.integration
@requires_uv
def test_install_asks_for_missing_secrets_before_building(
    motel: Motel, make_package: ManifestFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEMO_KEY", raising=False)
    described = {"name": "DEMO_KEY", "description": "Demo key", "url": "https://example.org"}
    golden = [
        {"name": "needs a key", "function": "secret_values", "requires": ["DEMO_KEY"],
         "expect": {"demo": "s3cret"}},
    ]  # fmt: skip
    package = make_package(
        functions=["secret_values"],
        environment={"manager": "uv", "python": "3.12", "secrets": [described]},
        golden=golden,
    )
    asked: list[Secret] = []

    def ask(secret: Secret) -> str | None:
        asked.append(secret)
        return "s3cret"

    tool = motel.add(str(package), ask_secret=ask)
    assert [(s.name, s.url) for s in asked] == [("DEMO_KEY", "https://example.org")]
    assert tool.state is not None
    assert tool.state.golden_summary == "1/1 golden tests passed"  # the key was there in time
    motel.add(str(package), force=True, ask_secret=ask)
    assert len(asked) == 1  # a key that is set is not asked for again


@pytest.mark.integration
@requires_uv
def test_freeze_pins_versions_and_triggers_a_rebuild(
    motel: Motel, make_package: ManifestFactory
) -> None:
    package = make_package(functions=["add"])
    with pytest.raises(MotelError, match="no built environment"):
        motel.freeze(str(package))
    first = motel.check(package, run_tests=False)
    lock, count, env_dir = motel.freeze(str(package))
    assert lock == package / LOCK_FILENAME
    assert env_dir == package / ".motel" / "env"
    text = lock.read_text()
    assert text.startswith("# Exact versions this tool was tested with")
    assert count == len([line for line in text.splitlines() if not line.startswith("#")])
    assert "pip==" in text  # seeded into every environment
    second = motel.check(package, run_tests=False)
    assert second.env_fingerprint != first.env_fingerprint  # the lock is part of the build
