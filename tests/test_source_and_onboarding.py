"""Source checkouts with patches, and scaffolding new packages."""

from __future__ import annotations

from pathlib import Path

import pytest

from scipatch.environments import BuildLog
from scipatch.errors import BuildError, SciPatchError
from scipatch.manifest import load_manifest
from scipatch.onboarding import install_project_skills, name_from_repo, scaffold
from scipatch.reporting import NullReporter
from scipatch.source import SourceCheckout, patch_files, resolve_remote_ref

from .conftest import requires_git


@pytest.mark.parametrize(
    ("repo", "name"),
    [
        ("https://github.com/CederGroupHub/chgnet", "chgnet"),
        ("https://github.com/ACEsuit/mace.git", "mace"),
        ("git@github.com:materialsproject/pymatgen.git", "pymatgen"),
        ("https://gitlab.com/ase/ase/", "ase"),
        ("https://github.com/x/My_Cool.Tool", "my-cool-tool"),
    ],
)
def test_name_from_repo(repo: str, name: str) -> None:
    assert name_from_repo(repo) == name


def test_scaffold_creates_a_valid_package_without_overwriting(tmp_path: Path) -> None:
    folder = tmp_path / "chgnet"
    created = scaffold(
        folder, "chgnet", repo="https://github.com/x/chgnet", ref="abc", paper="doi:1"
    )
    assert {p.name for p in created} == {"scipatch.yaml", "api.py", "SKILL.md", ".gitignore"}
    manifest = load_manifest(folder)
    assert manifest.source.repo == "https://github.com/x/chgnet"
    assert manifest.source.ref == "abc"
    assert manifest.source.install is True
    assert (folder / "patches").is_dir()
    assert (folder / "tests" / "data").is_dir()

    (folder / "api.py").write_text("# edited")
    assert scaffold(folder, "chgnet") == []
    assert (folder / "api.py").read_text() == "# edited"


def test_scaffold_without_repo_is_valid(tmp_path: Path) -> None:
    scaffold(tmp_path / "pkg", "my-tool")
    manifest = load_manifest(tmp_path / "pkg")
    assert manifest.source.repo is None
    assert manifest.source.install is False


def test_scaffold_rejects_bad_names(tmp_path: Path) -> None:
    with pytest.raises(SciPatchError, match="not a valid tool name"):
        scaffold(tmp_path / "x", "Bad_Name")


def test_project_skills_are_installed_for_agents(tmp_path: Path) -> None:
    install_project_skills(tmp_path)
    for folder in (".claude/skills", ".agents/skills"):
        assert (tmp_path / folder / "scipatch-onboard" / "SKILL.md").is_file()
        assert (tmp_path / folder / "scipatch-onboard" / "references" / "manifest.md").is_file()


@requires_git
def test_checkout_applies_and_saves_patches(tmp_path: Path, upstream_repo: tuple[str, str]) -> None:
    url, commit = upstream_repo
    assert resolve_remote_ref(url) == commit
    package = tmp_path / "package"
    (package / "patches").mkdir(parents=True)
    log = BuildLog(tmp_path / "build.log", NullReporter())
    checkout = SourceCheckout(package / "source", log)

    info = checkout.prepare(url, commit, patch_files(package), fresh=False)
    assert info.commit == commit
    assert not info.reused
    assert checkout.unsaved_changes() == []

    # Edit the source, then save the edit as a patch.
    (package / "source" / "DATA.txt").write_text("patched\n \n")
    (package / "source" / "NEW.txt").write_text("new file\n")
    (package / "source" / "WINDOWS.txt").write_bytes(b"crlf\r\nlines\r\n")
    assert sorted(checkout.unsaved_changes()) == ["DATA.txt", "NEW.txt", "WINDOWS.txt"]
    patch = checkout.save_patch(package / "patches", "Fix the data file!")
    assert patch is not None
    assert patch.name == "0001-fix-the-data-file.patch"
    assert checkout.unsaved_changes() == []
    assert checkout.save_patch(package / "patches", "nothing") is None

    # Reusing the checkout keeps it; a fresh checkout re-applies the patch exactly.
    assert checkout.prepare(url, commit, patch_files(package), fresh=False).reused
    fresh = checkout.prepare(url, commit, patch_files(package), fresh=True)
    assert not fresh.reused
    assert fresh.patches == ["0001-fix-the-data-file.patch"]
    assert (package / "source" / "DATA.txt").read_text() == "patched\n \n"
    assert (package / "source" / "NEW.txt").read_text() == "new file\n"
    assert (package / "source" / "WINDOWS.txt").read_bytes() == b"crlf\r\nlines\r\n"


@requires_git
def test_unsaved_edits_are_not_silently_discarded(
    tmp_path: Path, upstream_repo: tuple[str, str]
) -> None:
    url, commit = upstream_repo
    package = tmp_path / "package"
    package.mkdir()
    checkout = SourceCheckout(package / "source", BuildLog(tmp_path / "log", NullReporter()))
    checkout.prepare(url, commit, [], fresh=False)
    (package / "source" / "DATA.txt").write_text("unsaved edit\n")
    # A changed patch list would require a re-checkout, which would lose the edit.
    (package / "patches").mkdir()
    (package / "patches" / "0001-x.patch").write_text("")
    with pytest.raises(BuildError, match="unsaved edits"):
        checkout.prepare(url, commit, patch_files(package), fresh=False)


@requires_git
def test_broken_patch_reports_which_one(tmp_path: Path, upstream_repo: tuple[str, str]) -> None:
    url, commit = upstream_repo
    patch = tmp_path / "0001-bad.patch"
    patch.write_text(
        "diff --git a/NOPE.txt b/NOPE.txt\n--- a/NOPE.txt\n+++ b/NOPE.txt\n@@ -1 +1 @@\n-a\n+b\n"
    )
    checkout = SourceCheckout(tmp_path / "source", BuildLog(tmp_path / "log", NullReporter()))
    with pytest.raises(BuildError, match=r"Applying patch 0001-bad\.patch failed"):
        checkout.prepare(url, commit, [patch], fresh=True)
