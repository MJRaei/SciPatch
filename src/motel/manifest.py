"""The ``motel.yaml`` manifest: the catalog card of a tool package.

A *tool package* is a folder containing ``motel.yaml`` plus a Python module
(``api.py`` by default) whose typed, documented functions are the tool's
capabilities. The manifest records where the science comes from, how to build
an isolated environment for it, which functions to expose, when results can be
trusted, and *golden tests* that reproduce known numbers.

See ``docs/tool-format.md`` for the user-facing reference.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from motel.errors import ManifestError

MANIFEST_FILENAME = "motel.yaml"
#: Exact package versions a tool was tested with (written by ``motel freeze``).
LOCK_FILENAME = "requirements.lock"
SCHEMA_VERSION = 1

#: Tool names become folder names, skill names (``motel-<name>``) and CLI words.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_MAX_LENGTH = 48

#: Shared vocabulary for what a parameter or output *is*, so agents can chain tools.
#: Free-form values are allowed; these are the documented ones.
KNOWN_KINDS = frozenset(
    {
        "structure",  # crystal or periodic structure file: CIF, POSCAR, extended XYZ
        "molecule",  # molecule: SMILES string, or SDF/MOL/XYZ file
        "trajectory",  # MD or optimization trajectory file
        "spectrum",  # spectral data file
        "table",  # CSV/TSV/Parquet table
        "image",  # PNG/JPEG/TIFF image
        "file",  # any other input/output file
        "directory",  # folder of files
    }
)

_PYTHON_VERSION = re.compile(r"^3(\.\d+){0,2}$")
_MODULE_PATH = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Source(_Model):
    """Where the scientific code comes from."""

    repo: str | None = Field(None, description="Git URL of the upstream repository.")
    ref: str | None = Field(None, description="Tag, branch, or commit to check out (pinned).")
    subdirectory: str | None = Field(None, description="Install from this subfolder of the repo.")
    install: bool = Field(True, description="Install the checkout into the tool environment.")
    paper: str | None = Field(None, description="DOI or URL of the paper.")
    citation: str | None = Field(None, description="How to cite the work.")
    license: str | None = Field(None, description="License of the upstream code.")
    homepage: str | None = None

    @model_validator(mode="after")
    def _ref_required_with_repo(self) -> Source:
        if self.repo and not self.ref:
            raise ValueError(
                "source.ref is required when source.repo is set: pin a tag or commit "
                "so the tool can be rebuilt exactly"
            )
        return self


class Environment(_Model):
    """How to build the tool's isolated environment."""

    manager: Literal["uv", "conda"] = "uv"
    python: str = "3.11"
    packages: list[str] = Field(default_factory=list, description="PyPI requirement strings.")
    requirements: str | None = Field(None, description="Path to a requirements.txt file.")
    conda_packages: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=lambda: ["conda-forge"])
    conda_file: str | None = Field(None, description="Path to an environment.yml file.")
    post_install: list[str] = Field(
        default_factory=list,
        description="Shell commands run inside the environment after installing (e.g. weights).",
    )
    variables: dict[str, str] = Field(
        default_factory=dict, description="Environment variables set whenever the tool runs."
    )
    secrets: list[str] = Field(
        default_factory=list,
        description="Names of secrets (e.g. API keys) the tool receives as environment variables.",
    )

    @field_validator("python")
    @classmethod
    def _check_python(cls, value: str) -> str:
        if not _PYTHON_VERSION.match(value):
            raise ValueError(f"'{value}' is not a Python version like '3.11'")
        return value

    @field_validator("secrets")
    @classmethod
    def _check_secret_names(cls, names: list[str]) -> list[str]:
        for name in names:
            if not _SECRET_NAME.match(name):
                raise ValueError(f"'{name}' is not an environment variable name like MP_API_KEY")
        return names

    @model_validator(mode="after")
    def _conda_fields_need_conda(self) -> Environment:
        if self.manager != "conda" and (self.conda_packages or self.conda_file):
            raise ValueError("conda_packages and conda_file need 'manager: conda'")
        return self


class ValueInfo(_Model):
    """Extra meaning for one parameter or output, beyond its Python type."""

    kind: str | None = Field(None, description="Shared data kind, e.g. 'structure'.")
    unit: str | None = Field(None, description="Physical unit, e.g. 'eV/atom'.")
    description: str | None = None


class FunctionOptions(_Model):
    """Per-function settings. Everything is optional."""

    long_running: bool = Field(
        False, description="Takes minutes or longer; agents should poll instead of waiting."
    )
    cache: bool = Field(True, description="Reuse results of identical earlier calls.")
    timeout: float | None = Field(None, gt=0, description="Seconds before a waiting call gives up.")
    params: dict[str, ValueInfo] = Field(default_factory=dict)
    outputs: dict[str, ValueInfo] = Field(default_factory=dict)


class GoldenTest(_Model):
    """A known-good call: ideally a number reproduced from the paper."""

    name: str
    function: str
    args: dict[str, Any] = Field(default_factory=dict)
    expect: dict[str, Any] = Field(
        default_factory=dict,
        description="Checks on the result, keyed by dotted path (e.g. 'energy_ev').",
    )
    reference: str | None = Field(None, description="Where the expected values come from.")
    timeout: float = Field(900, gt=0)
    requires: list[str] = Field(
        default_factory=list,
        description="Secrets or environment variables the test needs; skipped when missing.",
    )
    raises: str | None = Field(
        None,
        description="The call must fail with an error message containing this text "
        "(for checking that invalid inputs are refused).",
    )


class Manifest(_Model):
    """A validated ``motel.yaml``."""

    schema_version: int = Field(SCHEMA_VERSION, alias="schema")
    name: str
    version: str = "0.1.0"
    title: str | None = None
    summary: str = Field(..., min_length=10, max_length=400)
    description: str | None = None
    domains: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    source: Source = Field(default_factory=Source)
    environment: Environment = Field(default_factory=Environment)
    entrypoint: str = Field("api", description="Python module that defines the functions.")
    functions: dict[str, FunctionOptions] | None = Field(
        None, description="Functions to expose. Omit to expose every public function."
    )
    validity: str | None = Field(None, description="When results can and cannot be trusted.")
    golden: list[GoldenTest] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _check_schema(cls, value: int) -> int:
        if value > SCHEMA_VERSION:
            raise ValueError(
                f"schema {value} is newer than this Motel understands ({SCHEMA_VERSION}); "
                "upgrade Motel"
            )
        return value

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if len(value) > NAME_MAX_LENGTH or not NAME_PATTERN.match(value):
            raise ValueError(
                f"'{value}' is not a valid tool name: use lowercase letters, digits and single "
                f"hyphens, at most {NAME_MAX_LENGTH} characters (e.g. 'chgnet-relax')"
            )
        return value

    @field_validator("entrypoint")
    @classmethod
    def _check_entrypoint(cls, value: str) -> str:
        if not _MODULE_PATH.match(value):
            raise ValueError(f"'{value}' is not a Python module path like 'api' or 'pkg.api'")
        return value

    @field_validator("functions", mode="before")
    @classmethod
    def _functions_from_list(cls, value: Any) -> Any:
        # Allow the short form ``functions: [relax, energy]``.
        if isinstance(value, list):
            return {str(name): {} for name in value}
        return value

    @field_validator("functions")
    @classmethod
    def _check_function_names(
        cls, value: dict[str, FunctionOptions] | None
    ) -> dict[str, FunctionOptions] | None:
        for name in value or {}:
            if not _IDENTIFIER.match(name) or name.startswith("_"):
                raise ValueError(f"'{name}' is not a public Python function name")
        return value

    @model_validator(mode="after")
    def _golden_tests_use_exported_functions(self) -> Manifest:
        if self.functions is not None:
            for test in self.golden:
                if test.function not in self.functions:
                    raise ValueError(
                        f"golden test '{test.name}' calls '{test.function}', "
                        "which is not listed under 'functions'"
                    )
        return self

    @property
    def display_title(self) -> str:
        return self.title or self.name

    def options_for(self, function: str) -> FunctionOptions:
        """Settings for ``function`` (defaults when the manifest says nothing)."""
        if self.functions and function in self.functions:
            return self.functions[function]
        return FunctionOptions()

    @property
    def exported_names(self) -> list[str] | None:
        """Explicitly exported function names, or ``None`` for "all public functions"."""
        return list(self.functions) if self.functions is not None else None


def find_manifest(path: Path) -> Path:
    """Return the manifest file for ``path`` (a package folder or the file itself)."""
    candidate = path / MANIFEST_FILENAME if path.is_dir() else path
    if not candidate.is_file():
        raise ManifestError(
            f"No {MANIFEST_FILENAME} found in {path}",
            hint="Point Motel at a tool package folder, or create one with 'motel new <name>'.",
        )
    return candidate


def load_manifest(path: Path) -> Manifest:
    """Read and validate a manifest, raising :class:`ManifestError` with readable messages."""
    manifest_file = find_manifest(path)
    try:
        data = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(
            f"{manifest_file} is not valid YAML: {exc}",
            hint="Check indentation and quoting near the line mentioned above.",
        ) from exc
    if not isinstance(data, dict):
        raise ManifestError(f"{manifest_file} must contain a YAML mapping (key: value pairs).")
    try:
        return Manifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestError(
            f"{manifest_file} has problems:\n{format_validation_error(exc)}",
            hint="See docs/tool-format.md for every field and an example.",
        ) from exc


def format_validation_error(exc: ValidationError) -> str:
    """Turn pydantic's error list into short ``field: message`` lines."""
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "(top level)"
        message = error["msg"].removeprefix("Value error, ")
        if error["type"] == "extra_forbidden":
            message = "unknown field (check the spelling)"
        lines.append(f"  - {location}: {message}")
    return "\n".join(lines)
