"""The featured tools that ship with Motel must be valid packages."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from motel import frontmatter
from motel.catalog import catalog_entries, catalog_path
from motel.manifest import MANIFEST_FILENAME, Manifest, load_manifest

ENTRIES = catalog_entries()


def test_catalog_is_not_empty() -> None:
    assert {manifest.name for manifest, _ in ENTRIES} >= {"ase-emt", "rdkit-descriptors"}
    assert catalog_path("ase-emt") is not None
    assert catalog_path("does-not-exist") is None


@pytest.mark.parametrize(("manifest", "folder"), ENTRIES, ids=[m.name for m, _ in ENTRIES])
def test_catalog_package_is_complete(manifest: Manifest, folder: Path) -> None:
    assert folder.name == manifest.name
    assert manifest.validity, "featured tools must state their validity limits"
    assert manifest.source.citation and manifest.source.license
    assert manifest.golden, "featured tools must have golden tests"
    pinned = [p for p in manifest.environment.packages if "==" in p]
    assert pinned == manifest.environment.packages, "featured tools pin exact versions"

    # Every exported and tested function exists in api.py, typed and documented.
    tree = ast.parse((folder / f"{manifest.entrypoint}.py").read_text())
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    for name in [*(manifest.functions or {}), *(test.function for test in manifest.golden)]:
        assert name in functions, f"{name} is not defined in api.py"
    for node in functions.values():
        assert ast.get_docstring(node), f"{node.name} has no docstring"
        assert "Args:" in (ast.get_docstring(node) or "")
        assert node.returns is not None
        assert all(arg.annotation is not None for arg in node.args.args)

    # Golden-test input files exist.
    for test in manifest.golden:
        for value in test.args.values():
            if isinstance(value, str) and value.startswith("tests/"):
                assert (folder / value).is_file()

    meta = frontmatter.read((folder / "SKILL.md").read_text())
    assert meta.get("description")


EXAMPLES = sorted(
    (Path(__file__).parent.parent / "examples").glob(f"*/{MANIFEST_FILENAME}"),
)


@pytest.mark.parametrize("manifest_path", EXAMPLES, ids=[p.parent.name for p in EXAMPLES])
def test_example_packages_are_valid(manifest_path: Path) -> None:
    manifest = load_manifest(manifest_path.parent)
    assert manifest.golden and manifest.validity and manifest.source.citation
    for test in manifest.golden:
        for value in test.args.values():
            if isinstance(value, str) and value.startswith("tests/"):
                assert (manifest_path.parent / value).is_file()
