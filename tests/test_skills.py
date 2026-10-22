from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scipatch import frontmatter
from scipatch.models import FunctionInfo, ToolState
from scipatch.paths import SciPatchPaths
from scipatch.registry import InstalledTool, Registry
from scipatch.schema import type_label
from scipatch.skills import (
    DESCRIPTION_LIMIT,
    MARKER_FILE,
    SkillManager,
    _cell,
    _demote_headings,
    bundled_skills,
    render_tool_skill,
)


@pytest.fixture
def installed_tool(tmp_path: Path) -> InstalledTool:
    paths = SciPatchPaths.from_env().ensure()
    package = paths.tools / "chgnet"
    package.mkdir(parents=True)
    (package / "scipatch.yaml").write_text(
        "name: chgnet\nsummary: Relax crystals with a universal ML potential.\n"
        "validity: Trained on PBE data.\n"
        "source: {repo: 'https://github.com/x/chgnet', ref: v1, license: BSD-3-Clause, "
        "citation: 'Deng et al. (2023)'}\n"
    )
    (package / "SKILL.md").write_text(
        "---\nname: chgnet\ndescription: Use for fast pre-relaxation before DFT.\n---\n"
        "# Recipes\n\nRelax first, then compare with DFT.\n"
    )
    (package / "references").mkdir()
    (package / "references" / "paper.md").write_text("notes")
    state = ToolState(
        status="ready",
        installed_from="test",
        source_commit="abc123def4567890",
        functions=[
            FunctionInfo(
                name="relax",
                summary="Relax a structure.",
                parameters={
                    "type": "object",
                    "properties": {
                        "structure": {
                            "type": "string",
                            "x-kind": "structure",
                            "description": "CIF | POSCAR",
                        },
                        "fmax": {"type": "number", "default": 0.05, "x-unit": "eV/Å"},
                    },
                    "required": ["structure"],
                },
            )
        ],
    )
    Registry(paths).save_state("chgnet", state)
    return Registry(paths).get("chgnet")


def test_tool_skill_is_valid_and_complete(installed_tool: InstalledTool) -> None:
    files = render_tool_skill(installed_tool)
    text = str(files["SKILL.md"])
    meta = frontmatter.read(text)
    assert meta["name"] == "scipatch-chgnet"
    assert meta["description"].startswith("Use for fast pre-relaxation before DFT.")
    assert "Runs locally through SciPatch" in meta["description"]
    assert len(meta["description"]) <= DESCRIPTION_LIMIT
    assert meta["license"] == "BSD-3-Clause"
    assert all(isinstance(v, str) for v in meta["metadata"].values())
    assert "scipatch run chgnet relax structure=... --json" in text
    assert "| `structure` | structure | *required* | CIF \\| POSCAR |" in text
    assert "| `fmax` | number [eV/Å] | `0.05` |" in text
    assert "### Recipes" in text  # package headings are nested under "Usage notes"
    assert "Trained on PBE data." in text
    assert "https://github.com/x/chgnet @ `abc123def456`" in text
    assert files["references/paper.md"] == b"notes"


def test_tool_skill_explains_keys(installed_tool: InstalledTool) -> None:
    manifest = installed_tool.package_dir / "scipatch.yaml"
    manifest.write_text(
        manifest.read_text()
        + "environment: {secrets: [{name: DEMO_KEY, description: Demo key, url: 'https://x.org'}]}\n"
    )
    text = str(render_tool_skill(Registry(SciPatchPaths.from_env()).get("chgnet"))["SKILL.md"])
    assert "## API keys" in text
    assert "- `DEMO_KEY` (Demo key; get one at https://x.org)" in text
    assert "Never ask the user to type a key into the chat." in text
    assert "`scipatch secret set DEMO_KEY`: it opens that page" in text


def test_bundled_skills_have_valid_frontmatter() -> None:
    skills = bundled_skills()
    assert {"scipatch", "scipatch-onboard"} <= set(skills)
    for name, files in skills.items():
        meta = frontmatter.read(
            files["SKILL.md"].decode()
            if isinstance(files["SKILL.md"], bytes)
            else files["SKILL.md"]
        )
        assert meta["name"] == name
        assert 0 < len(meta["description"]) <= DESCRIPTION_LIMIT


def test_sync_writes_updates_and_removes_only_managed_skills(
    installed_tool: InstalledTool, tmp_path: Path
) -> None:
    manager = SkillManager(Registry(installed_tool.paths))
    target = tmp_path / "skills"
    (target / "my-own-skill").mkdir(parents=True)
    (target / "my-own-skill" / "SKILL.md").write_text("mine")
    (target / "scipatch-onboard").mkdir()  # same name as a bundled skill, but not ours
    (target / "scipatch-onboard" / "SKILL.md").write_text("user's version")
    (target / "scipatch-stale").mkdir()
    (target / "scipatch-stale" / MARKER_FILE).write_text("{}")

    report = manager.sync(target)
    assert set(report.written) == {"scipatch", "scipatch-chgnet"}
    assert report.skipped == ["scipatch-onboard"]
    assert report.removed == ["scipatch-stale"]
    assert (target / "my-own-skill" / "SKILL.md").read_text() == "mine"
    assert (target / "scipatch-onboard" / "SKILL.md").read_text() == "user's version"
    assert (target / "scipatch-chgnet" / "references" / "paper.md").exists()
    assert (target / "scipatch-chgnet" / MARKER_FILE).exists()

    assert SkillManager.remove_all(target) == ["scipatch", "scipatch-chgnet"]
    assert sorted(p.name for p in target.iterdir()) == ["my-own-skill", "scipatch-onboard"]


def test_export_as_zip(installed_tool: InstalledTool, tmp_path: Path) -> None:
    manager = SkillManager(Registry(installed_tool.paths))
    paths = manager.export(tmp_path / "out", as_zip=True)
    archive = next(p for p in paths if p.name == "scipatch-chgnet.zip")
    with zipfile.ZipFile(archive) as zipped:
        assert "scipatch-chgnet/SKILL.md" in zipped.namelist()
        assert MARKER_FILE not in " ".join(zipped.namelist())


def test_headings_are_nested_and_pipes_escaped() -> None:
    assert _cell(type_label({"enum": ["fcc", "bcc"]})) == "fcc\\|bcc"
    assert _demote_headings("## A\ntext\n### B\n```\n# not a heading\n```") == (
        "### A\ntext\n#### B\n```\n# not a heading\n```"
    )
    assert _demote_headings("no headings") == "no headings"
