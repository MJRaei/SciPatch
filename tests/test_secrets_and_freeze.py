"""Secrets for tools, and pinned package versions."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scipatch import platforms
from scipatch.app import SciPatch
from scipatch.errors import RunError, SciPatchError
from scipatch.lock import LOCK_FILENAME
from scipatch.manifest import Secret
from scipatch.secrets import SecretStore

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
    with pytest.raises(SciPatchError, match="not a valid secret name"):
        store.set("lower-case", "x")
    with pytest.raises(SciPatchError, match="empty"):
        store.set("EMPTY", "")


@pytest.mark.integration
@requires_uv
def test_tools_get_only_their_declared_secrets(
    scipatch: SciPatch, make_package: ManifestFactory, monkeypatch: pytest.MonkeyPatch
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
    tool = scipatch.add(str(package))  # installs: the golden test is skipped, not failed
    assert tool.state is not None
    assert tool.state.golden[0].skipped
    assert tool.state.golden_summary == "0/0 golden tests passed, 1 skipped (missing secrets)"
    with pytest.raises(RunError, match="needs DEMO_KEY"):
        scipatch.run("sample", "secret_values")

    scipatch.secrets.set("DEMO_KEY", "s3cret")
    scipatch.secrets.set("OTHER_KEY", "not-declared")
    run = scipatch.run("sample", "secret_values")
    assert run.result == {"demo": "s3cret", "other": None}
    # Secrets reach the tool through its environment only, never through SciPatch's files.
    assert "s3cret" not in (Path(run.run_dir) / "request.json").read_text()
    assert "s3cret" not in str(run.args)
    tested = scipatch.test("sample")
    assert tested.state is not None
    assert tested.state.golden_summary == "1/1 golden tests passed"


@pytest.mark.integration
@requires_uv
def test_install_asks_for_missing_secrets_before_building(
    scipatch: SciPatch, make_package: ManifestFactory, monkeypatch: pytest.MonkeyPatch
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

    tool = scipatch.add(str(package), ask_secret=ask)
    assert [(s.name, s.url) for s in asked] == [("DEMO_KEY", "https://example.org")]
    assert tool.state is not None
    assert tool.state.golden_summary == "1/1 golden tests passed"  # the key was there in time
    scipatch.add(str(package), force=True, ask_secret=ask)
    assert len(asked) == 1  # a key that is set is not asked for again


@pytest.mark.integration
@requires_uv
def test_freeze_pins_every_platform_and_triggers_a_rebuild(
    scipatch: SciPatch, make_package: ManifestFactory
) -> None:
    package = make_package(functions=["add"])
    with pytest.raises(SciPatchError, match="no built environment"):
        scipatch.freeze(str(package))
    first = scipatch.check(package, run_tests=False)
    result = scipatch.freeze(str(package))
    assert result.path == package / LOCK_FILENAME
    assert result.env_dir == package / ".scipatch" / "env"
    data = json.loads(result.path.read_text())
    here = platforms.current()
    assert data["tested_on"] == here
    assert set(data["platforms"]) == set(platforms.PLATFORMS)
    assert here is not None
    assert any(pin.startswith("pip==") for pin in data["platforms"][here]["pip"])
    second = scipatch.check(package, run_tests=False)
    assert second.env_fingerprint != first.env_fingerprint  # the lock is part of the build
