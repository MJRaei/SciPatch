"""Catalogs: installing tools by name from git repositories."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from motel.app import Motel
from motel.catalogs import BUILT_IN, CatalogStore
from motel.errors import MotelError

from .conftest import ManifestFactory, requires_git, requires_uv

pytestmark = requires_git


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def tools_repo(tmp_path: Path, make_package: ManifestFactory) -> Path:
    """A git repository shaped like a published tool collection: tools/<name>/."""
    repo = tmp_path / "lab-tools"
    make_package("sample", folder=repo / "tools" / "sample", functions=["add"])
    make_package("other-tool", folder=repo / "tools" / "other-tool", functions=["add"])
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "tools")
    return repo


def test_add_list_find_update_remove(motel: Motel, tools_repo: Path) -> None:
    store = CatalogStore(motel.paths)
    catalog = store.add(str(tools_repo))
    assert catalog.name == "lab-tools"

    entries = store.entries()
    assert {e.catalog for e in entries} == {BUILT_IN, "lab-tools"}
    sample = store.find("sample")
    assert sample is not None
    assert sample.qualified_name == "lab-tools/sample"
    assert sample.origin.startswith(f"{tools_repo}@")
    assert sample.origin.endswith("#subdirectory=tools/sample")
    assert store.find("ase-emt") is not None  # built-in tools are found too
    assert store.find("nothing") is None

    # A new commit in the collection shows up after an update.
    manifest = tools_repo / "tools" / "sample" / "motel.yaml"
    data = yaml.safe_load(manifest.read_text())
    data["version"] = "2.0.0"
    manifest.write_text(yaml.safe_dump(data))
    _git(tools_repo, "commit", "--quiet", "-am", "bump")
    assert store.find("sample").manifest.version == "0.1.0"  # type: ignore[union-attr]
    [(updated, commit)] = store.update()
    assert updated.name == "lab-tools" and len(commit) == 40
    assert store.find("sample").manifest.version == "2.0.0"  # type: ignore[union-attr]

    store.remove("lab-tools")
    assert store.find("sample") is None
    assert not (motel.paths.home / "catalogs" / "lab-tools").exists()


def test_same_name_in_two_catalogs_must_be_qualified(motel: Motel, tools_repo: Path) -> None:
    store = CatalogStore(motel.paths)
    store.add(str(tools_repo))
    store.add(str(tools_repo), name="mirror")
    with pytest.raises(MotelError, match="several catalogs"):
        store.find("sample")
    found = store.find("mirror/sample")
    assert found is not None and found.catalog == "mirror"


def test_rejected_catalogs_leave_nothing_behind(motel: Motel, tools_repo: Path) -> None:
    store = CatalogStore(motel.paths)
    with pytest.raises(MotelError, match="No tool packages found"):
        store.add(str(tools_repo), path="nowhere")
    assert store.catalogs() == []
    store.add(str(tools_repo))
    with pytest.raises(MotelError, match="already exists"):
        store.add(str(tools_repo))
    with pytest.raises(MotelError, match="not a valid catalog name"):
        store.add(str(tools_repo), name=BUILT_IN)


@pytest.mark.integration
@requires_uv
def test_install_by_name_records_the_catalog_commit(motel: Motel, tools_repo: Path) -> None:
    CatalogStore(motel.paths).add(str(tools_repo))
    tool = motel.add("lab-tools/sample")
    assert tool.state is not None
    assert tool.state.installed_from.endswith("#subdirectory=tools/sample")
    assert motel.run("sample", "add", {"a": 1}).result == {"sum": 2.0}
