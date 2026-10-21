from __future__ import annotations

from typing import Any

from motel.manifest import Manifest
from motel.models import FunctionInfo, ToolState
from motel.paths import MotelPaths
from motel.registry import InstalledTool
from motel.schema import matches, normalize, type_label
from motel.search import ToolIndex, describe_inputs, tokenize


def tool(name: str, summary: str, functions: dict[str, str], **manifest: Any) -> InstalledTool:
    state = ToolState(
        status="ready",
        installed_from="test",
        functions=[FunctionInfo(name=fn, summary=text) for fn, text in functions.items()],
    )
    return InstalledTool(
        name,
        Manifest.model_validate({"name": name, "summary": summary, **manifest}),
        state,
        MotelPaths.from_env(),
    )


TOOLS = [
    tool(
        "chgnet",
        "Universal machine-learning interatomic potential for crystals.",
        {
            "relax": "Relax a crystal structure and return the energy.",
            "predict": "Predict energy, forces, stress and magnetic moments.",
        },
        tags=["ml-potential"],
    ),
    tool(
        "rdkit-descriptors",
        "Cheminformatics descriptors for molecules given as SMILES.",
        {"descriptors": "Molecular weight, logP and polar surface area."},
    ),
    tool(
        "ase-emt",
        "Fast approximate energies for the metals Cu, Au and Ag.",
        {"equation_of_state": "Equilibrium lattice constant and bulk modulus."},
    ),
]


def top(query: str) -> tuple[str, str]:
    hit = ToolIndex(TOOLS).search(query, limit=1)[0]
    return hit.tool, hit.function


def test_tokenize_drops_stopwords_and_splits_names() -> None:
    assert tokenize("Relax the crystal_structure of my ML-potential") == [
        "relax", "crystal", "structure", "ml", "potential",
    ]  # fmt: skip


def test_ranking_matches_intent() -> None:
    assert top("relax a structure") == ("chgnet", "relax")
    assert top("molecular weight of aspirin") == ("rdkit-descriptors", "descriptors")
    assert top("bulk modulus") == ("ase-emt", "equation_of_state")


def test_related_word_forms_match() -> None:
    assert top("relaxation") == ("chgnet", "relax")
    assert top("magnetic moment predictions") == ("chgnet", "predict")


def test_element_names_match_symbols() -> None:
    assert top("lattice constant of gold") == ("ase-emt", "equation_of_state")


def test_empty_query_lists_everything_and_nonsense_finds_nothing() -> None:
    index = ToolIndex(TOOLS)
    assert len(index) == 4
    assert len(index.search("", limit=10)) == 4
    assert index.search("zzz qqq") == []


def test_type_labels_and_input_summaries() -> None:
    assert type_label({"type": "number", "x-unit": "eV/Å"}) == "number [eV/Å]"
    assert type_label({"type": "string", "x-kind": "structure"}) == "structure"
    assert type_label({"anyOf": [{"type": "number"}, {"type": "null"}]}) == "number"
    assert type_label({"type": "array", "items": {"type": "string"}}) == "list of string"
    assert type_label({"enum": ["fcc", "bcc"], "type": "string"}) == "fcc|bcc"
    assert type_label({}) == "any"
    summary = describe_inputs(
        {
            "structure": {"type": "string", "x-kind": "structure"},
            "fmax": {"type": "number", "default": 0.05},
        },
        ["structure"],
    )
    assert summary == "structure (structure, required), fmax (number)=0.05"


def test_schema_matching_and_normalizing() -> None:
    number = {"type": "number"}
    assert matches(1, number) and matches(1.5, number)
    assert not matches("1", number) and not matches(True, number)
    assert matches(3, {"type": "integer"}) and not matches(3.5, {"type": "integer"})
    assert matches(None, {"anyOf": [{"type": "number"}, {"type": "null"}]})
    assert matches("fcc", {"enum": ["fcc", "bcc"], "type": "string"})
    assert not matches("hcp2", {"enum": ["fcc", "bcc"]})
    assert matches([1, 2], {"type": "array", "items": {"type": "integer"}})
    assert not matches([1, "x"], {"type": "array", "items": {"type": "integer"}})
    assert matches(object(), {})  # unknown schema: anything goes
    assert normalize(500.0, {"type": "integer"}) == 500
    assert isinstance(normalize(500.0, {"type": "integer"}), int)
    assert normalize(2.5, {"type": "integer"}) == 2.5  # not silently truncated
    assert normalize(1.0, {"type": "number"}) == 1.0
