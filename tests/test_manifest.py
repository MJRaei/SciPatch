from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from motel.errors import ManifestError
from motel.manifest import Manifest, load_manifest


def minimal(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"name": "chgnet", "summary": "Relax crystal structures with CHGNet."}
    data.update(overrides)
    return data


def test_minimal_manifest_gets_sensible_defaults() -> None:
    manifest = Manifest.model_validate(minimal())
    assert manifest.environment.manager == "uv"
    assert manifest.entrypoint == "api"
    assert manifest.exported_names is None
    assert manifest.display_title == "chgnet"
    assert manifest.options_for("relax").cache is True


@pytest.mark.parametrize("name", ["CHGNet", "my_tool", "-tool", "tool-", "a--b", "x" * 49, ""])
def test_invalid_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="valid tool name"):
        Manifest.model_validate(minimal(name=name))


def test_repo_requires_pinned_ref() -> None:
    with pytest.raises(ValueError, match=r"source\.ref is required"):
        Manifest.model_validate(minimal(source={"repo": "https://github.com/x/y"}))


def test_conda_fields_require_conda_manager() -> None:
    with pytest.raises(ValueError, match="manager: conda"):
        Manifest.model_validate(minimal(environment={"conda_packages": ["xtb"]}))
    manifest = Manifest.model_validate(
        minimal(environment={"manager": "conda", "conda_packages": ["xtb"]})
    )
    assert manifest.environment.channels == ["conda-forge"]


def test_python_version_is_validated() -> None:
    with pytest.raises(ValueError, match="not a Python version"):
        Manifest.model_validate(minimal(environment={"python": "latest"}))


def test_functions_accept_a_plain_list() -> None:
    manifest = Manifest.model_validate(minimal(functions=["relax", "predict"]))
    assert manifest.exported_names == ["relax", "predict"]


def test_private_function_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="public Python function"):
        Manifest.model_validate(minimal(functions=["_helper"]))


def test_golden_tests_must_use_exported_functions() -> None:
    with pytest.raises(ValueError, match="not listed under 'functions'"):
        Manifest.model_validate(
            minimal(functions=["relax"], golden=[{"name": "t", "function": "predict"}])
        )


def test_newer_schema_asks_for_upgrade() -> None:
    with pytest.raises(ValueError, match="upgrade Motel"):
        Manifest.model_validate(minimal(schema=99))


def test_load_reports_unknown_fields_readably(tmp_path: Path) -> None:
    (tmp_path / "motel.yaml").write_text("name: x\nsumary: typo in the field name\n")
    with pytest.raises(ManifestError) as caught:
        load_manifest(tmp_path)
    message = caught.value.message
    assert "sumary: unknown field" in message
    assert "summary: Field required" in message


def test_load_reports_yaml_errors(tmp_path: Path) -> None:
    (tmp_path / "motel.yaml").write_text("name: [unclosed\n")
    with pytest.raises(ManifestError, match="not valid YAML"):
        load_manifest(tmp_path)


def test_missing_manifest_has_a_hint(tmp_path: Path) -> None:
    with pytest.raises(ManifestError) as caught:
        load_manifest(tmp_path)
    assert caught.value.hint is not None
    assert "motel new" in caught.value.hint
