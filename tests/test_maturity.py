"""Maturity levels: the evidence they need, search ranking, and what agents see."""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from scipatch.app import SciPatch
from scipatch.cli import app
from scipatch.errors import SciPatchError
from scipatch.manifest import Manifest
from scipatch.maturity import evidence, paper_kind
from scipatch.models import FunctionInfo, RunRecord, RunStatus, ToolState
from scipatch.registry import InstalledTool, Registry
from scipatch.skills import skill_description
from scipatch.views import run_view, tool_view

from .test_gateway import call

PAPER = "https://doi.org/10.1000/example"
REFUSAL = {"name": "refuses iron", "function": "relax", "raises": "no parameters for Fe"}


def check(against: str | None = None, name: str = "matches a reference") -> dict[str, Any]:
    test = {"name": name, "function": "relax", "expect": {"a": 1}, "reference": "somewhere"}
    return {**test, "against": against} if against else test


def manifest(**fields: Any) -> Manifest:
    return Manifest.model_validate({"name": "tool", "summary": "Relax crystals.", **fields})


def test_tools_are_experimental_unless_they_say_otherwise() -> None:
    assert manifest().maturity == "experimental"


@pytest.mark.parametrize(
    ("fields", "missing"),
    [
        ({"maturity": "published", "golden": [check("paper")]}, "source.paper"),
        (
            {"maturity": "published", "source": {"paper": PAPER}, "golden": [check("regression")]},
            "a golden test with 'against' set to 'exact' or 'independent' or 'paper'",
        ),
        (
            {"maturity": "established", "source": {"paper": PAPER}, "golden": [check("paper")]},
            "a golden test with 'against' set to 'exact' or 'independent'",
        ),
    ],
)
def test_a_level_needs_its_evidence(fields: dict[str, Any], missing: str) -> None:
    with pytest.raises(ValidationError, match=missing):
        manifest(**fields)


def test_supported_levels_are_accepted_and_refusals_have_no_reference() -> None:
    with_paper = {"source": {"paper": PAPER}}
    assert manifest(maturity="published", golden=[check("upstream-tests")], **with_paper)
    assert manifest(maturity="established", golden=[check("exact")], **with_paper)
    with pytest.raises(ValidationError, match="a test with 'raises' has none"):
        manifest(golden=[{**REFUSAL, "against": "exact"}])


def test_evidence_summarizes_the_publication_and_the_golden_tests() -> None:
    tool = manifest(
        source={"paper": "https://arxiv.org/abs/2401.00096"},
        golden=[check("paper"), check("independent", "b"), check(None, "c"), REFUSAL],
    )
    assert evidence(tool) == (
        "preprint: https://arxiv.org/abs/2401.00096; 3 golden tests (1 against independent "
        "references, 1 against its paper, 1 other); 1 refusal check"
    )
    assert evidence(manifest()) == "no publication; no golden tests of results"


@pytest.mark.parametrize(
    ("paper", "kind"),
    [
        ("https://doi.org/10.1038/s42256-023-00716-3", "paper"),
        ("https://doi.org/10.48550/arXiv.2504.06231", "preprint"),
        ("https://doi.org/10.26434/chemrxiv-2024-abc", "preprint"),
        ("https://doi.org/10.1101/2024.01.02.123456", "preprint"),
        ("https://doi.org/10.1101/gr.123456.111", "paper"),  # Genome Research
        ("https://doi.org/10.5281/zenodo.591637", "software record"),
        (None, None),
    ],
)
def test_publications_are_told_apart_from_preprints_and_software_records(
    paper: str | None, kind: str | None
) -> None:
    assert paper_kind(paper) == kind


def install(name: str, summary: str, level: str) -> InstalledTool:
    """An installed tool with one function, ``run``, at a maturity level."""
    scipatch = SciPatch()
    package = scipatch.paths.tools / name
    package.mkdir(parents=True)
    data = {
        "name": name,
        "summary": summary,
        "maturity": level,
        "source": {"paper": PAPER},
        "golden": [{**check("independent"), "function": "run"}],
    }
    (package / "scipatch.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    state = ToolState(
        status="ready",
        installed_from=str(package),
        functions=[FunctionInfo(name="run", summary=summary)],
    )
    Registry(scipatch.paths).save_state(name, state)
    return scipatch.tool(name)


@pytest.fixture
def two_md_tools() -> SciPatch:
    install(
        "classical-md", "Molecular dynamics of metals with classical potentials.", "established"
    )
    install("tiny-md", "Molecular dynamics of metals with classical potentials.", "experimental")
    install("dislocations", "Dislocation densities in deformed metal crystals.", "experimental")
    return SciPatch()


def test_search_prefers_established_tools_but_still_finds_the_only_fit(
    two_md_tools: SciPatch,
) -> None:
    ranked = [match.tool.name for match in two_md_tools.find("molecular dynamics of metals")]
    assert ranked[:2] == ["classical-md", "tiny-md"]
    assert two_md_tools.find("dislocation density")[0].tool.name == "dislocations"


def test_experimental_tools_come_with_a_caution_naming_alternatives(two_md_tools: SciPatch) -> None:
    tiny = two_md_tools.tool("tiny-md")
    alternatives = two_md_tools.stronger_alternatives(tiny)
    assert alternatives == ["classical-md"]
    view = tool_view(tiny, alternatives)["maturity"]
    assert view["level"] == "experimental"
    assert "classical-md" in view["caution"]
    assert view["evidence"].startswith(f"paper: {PAPER}; 1 golden test (1 against independent")
    assert view["declared_in"].startswith("the folder ")
    assert "caution" not in tool_view(two_md_tools.tool("classical-md"))["maturity"]

    record = RunRecord(id="r1", tool="tiny-md", function="run", status=RunStatus.SUCCEEDED)
    ran = run_view(record, tool=tiny)
    assert ran["maturity"] == "experimental" and "Experimental tool" in ran["caution"]

    assert "Experimental" in skill_description(tiny)
    assert "Experimental" not in skill_description(two_md_tools.tool("classical-md"))


def test_agents_see_maturity_in_search_and_descriptions(two_md_tools: SciPatch) -> None:
    found, described = call(
        two_md_tools,
        ("find_tools", {"query": "molecular dynamics of metals"}),
        ("describe_tool", {"tool": "tiny-md"}),
    )
    levels = {m["tool"]: m["maturity"] for m in found.structured_content["matches"]}
    assert levels["classical-md"] == "established" and levels["tiny-md"] == "experimental"
    assert "classical-md" in described.structured_content["maturity"]["caution"]


def test_users_can_lower_a_level_but_not_raise_it(two_md_tools: SciPatch) -> None:
    lowered = two_md_tools.lower_maturity("classical-md", "experimental")
    assert lowered.maturity == "experimental"
    assert "lowered on this computer" in tool_view(lowered)["maturity"]["lowered_by_user"]
    assert two_md_tools.lower_maturity("classical-md", None).maturity == "established"
    with pytest.raises(SciPatchError, match="can only be lowered"):
        two_md_tools.lower_maturity("tiny-md", "published")

    runner = CliRunner()
    shown = runner.invoke(app, ["maturity", "tiny-md"])
    assert shown.exit_code == 0 and "experimental" in shown.output
    assert runner.invoke(app, ["maturity", "classical-md", "published"]).exit_code == 0
    assert two_md_tools.tool("classical-md").maturity == "published"
    assert runner.invoke(app, ["maturity", "classical-md", "--reset"]).exit_code == 0
    assert two_md_tools.tool("classical-md").maturity == "established"
