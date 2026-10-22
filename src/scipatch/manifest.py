"""The ``scipatch.yaml`` manifest: the catalog card of a tool package.

A *tool package* is a folder containing ``scipatch.yaml`` plus a Python module
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

from scipatch import golden, platforms
from scipatch.errors import ManifestError

MANIFEST_FILENAME = "scipatch.yaml"
SCHEMA_VERSION = 1

#: Tool names become folder names, skill names (``scipatch-<name>``) and CLI words.
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

#: How much evidence backs a tool's results, most to least (see ``scipatch.maturity``).
Maturity = Literal["established", "published", "experimental"]

#: Where a golden test's expected values come from.
Against = Literal["independent", "paper", "upstream-tests", "exact", "regression"]

#: The ``against`` values that back each maturity level (besides a paper).
_LEVEL_EVIDENCE: dict[str, frozenset[str]] = {
    "established": frozenset({"independent", "exact"}),
    "published": frozenset({"independent", "exact", "paper", "upstream-tests"}),
}

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


class Secret(_Model):
    """A secret (e.g. an API key) the tool receives as an environment variable."""

    name: str = Field(description="Environment variable name, e.g. MP_API_KEY.")
    description: str | None = Field(
        None, description="What it is, e.g. 'Materials Project API key'."
    )
    url: str | None = Field(None, description="Where the user can get one.")

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _SECRET_NAME.match(value):
            raise ValueError(f"'{value}' is not an environment variable name like MP_API_KEY")
        return value

    @property
    def label(self) -> str:
        return self.description or self.name


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
    secrets: list[Secret] = Field(
        default_factory=list,
        description="Secrets (e.g. API keys) the tool receives as environment variables: "
        "names, or objects with name, description, and url.",
    )
    platforms: list[str] | None = Field(
        None,
        description="Platforms the tool supports (default: every platform its packages "
        "exist for), e.g. [linux-64, osx-arm64].",
    )

    @field_validator("python")
    @classmethod
    def _check_python(cls, value: str) -> str:
        if not _PYTHON_VERSION.match(value):
            raise ValueError(f"'{value}' is not a Python version like '3.11'")
        return value

    @field_validator("conda_packages")
    @classmethod
    def _check_markers(cls, value: list[str]) -> list[str]:
        for requirement in value:
            platforms.split_marker(requirement)  # raises on an invalid marker
        return value

    @field_validator("platforms")
    @classmethod
    def _check_platforms(cls, value: list[str] | None) -> list[str] | None:
        unknown = [name for name in value or [] if name not in platforms.PLATFORMS]
        if unknown:
            raise ValueError(
                f"unknown platform(s) {', '.join(unknown)}; use {', '.join(platforms.PLATFORMS)}"
            )
        return value

    @field_validator("secrets", mode="before")
    @classmethod
    def _secret_names_as_objects(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [{"name": item} if isinstance(item, str) else item for item in value]
        return value

    @property
    def secret_names(self) -> list[str]:
        return [secret.name for secret in self.secrets]

    @model_validator(mode="after")
    def _conda_fields_need_conda(self) -> Environment:
        if self.manager != "conda" and (self.conda_packages or self.conda_file):
            raise ValueError("conda_packages and conda_file need 'manager: conda'")
        return self


class Resources(_Model):
    """What a tool, or one of its functions, needs from the computer.

    Unset fields of a function's ``resources`` are taken from the tool's.
    """

    gpu: Literal["none", "optional", "required"] | None = Field(
        None, description="'none' (default), 'optional' (faster with one), or 'required'."
    )
    gpu_types: list[Literal["cuda", "mps"]] | None = Field(
        None,
        description="GPUs it can use: 'cuda' (NVIDIA) and 'mps' (Apple silicon). Default: cuda.",
    )
    gpu_memory_gb: float | None = Field(None, gt=0, description="GPU memory it needs, in GB.")
    memory_gb: float | None = Field(
        None, gt=0, description="Memory (RAM) recommended for typical inputs, in GB."
    )
    network: bool | None = Field(
        None, description="Needs an internet connection, e.g. to call a web service."
    )

    def over(self, base: Resources) -> Resources:
        """These settings, with unset fields taken from ``base``."""
        return Resources.model_validate({**base.model_dump(), **self.model_dump(exclude_none=True)})


#: What a tool needs when its manifest says nothing.
DEFAULT_RESOURCES = Resources(gpu="none", gpu_types=["cuda"], network=False)


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
    resources: Resources = Field(
        default_factory=Resources, description="What this function needs, if not the tool's."
    )
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
    against: Against | None = Field(
        None,
        description="Kind of reference: 'independent' (experiment, reference data, or another "
        "program), 'paper' (the tool's own publication), 'upstream-tests' (the project's test "
        "suite or documentation), 'exact' (an analytical result, sum rule, symmetry, or count), "
        "or 'regression' (the tool's own earlier output).",
    )
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
    platforms: list[str] | None = Field(
        None,
        description="Run only on these platforms, e.g. when a package the test needs "
        "does not exist everywhere (see environment markers).",
    )
    quick: bool = Field(
        False,
        description="Also run when the tool is installed (keep these to seconds). The "
        "other tests run with 'scipatch check' and 'scipatch test'.",
    )

    @field_validator("platforms")
    @classmethod
    def _check_platforms(cls, value: list[str] | None) -> list[str] | None:
        unknown = [name for name in value or [] if name not in platforms.PLATFORMS]
        if unknown:
            raise ValueError(f"unknown platform(s) {', '.join(unknown)}")
        return value

    @field_validator("expect")
    @classmethod
    def _check_matchers(cls, value: dict[str, Any]) -> dict[str, Any]:
        problems = golden.matcher_problems(value)
        if problems:
            raise ValueError("; ".join(problems))
        return value

    @model_validator(mode="after")
    def _refusals_have_no_reference_values(self) -> GoldenTest:
        if self.raises is not None and self.against is not None:
            raise ValueError("'against' describes expected values; a test with 'raises' has none")
        return self


class Manifest(_Model):
    """A validated ``scipatch.yaml``."""

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
    resources: Resources = Field(
        default_factory=Resources, description="What the tool needs from the computer."
    )
    entrypoint: str = Field("api", description="Python module that defines the functions.")
    functions: dict[str, FunctionOptions] | None = Field(
        None, description="Functions to expose. Omit to expose every public function."
    )
    validity: str | None = Field(None, description="When results can and cannot be trusted.")
    maturity: Maturity = Field(
        "experimental",
        description="'established' (mature, widely used, independently checked), 'published' "
        "(research code from a publication), or 'experimental'.",
    )
    golden: list[GoldenTest] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _check_schema(cls, value: int) -> int:
        if value > SCHEMA_VERSION:
            raise ValueError(
                f"schema {value} is newer than this SciPatch understands ({SCHEMA_VERSION}); "
                "upgrade SciPatch"
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

    @model_validator(mode="after")
    def _maturity_has_evidence(self) -> Manifest:
        accepted = _LEVEL_EVIDENCE.get(self.maturity)
        if accepted is None:
            return self
        missing = []
        if not self.source.paper:
            missing.append("source.paper (its publication or citable software record)")
        if not any(test.against in accepted for test in self.golden):
            kinds = " or ".join(f"'{kind}'" for kind in sorted(accepted))
            missing.append(f"a golden test with 'against' set to {kinds}")
        if missing:
            raise ValueError(f"maturity '{self.maturity}' needs {' and '.join(missing)}")
        return self

    @property
    def display_title(self) -> str:
        return self.title or self.name

    def options_for(self, function: str) -> FunctionOptions:
        """Settings for ``function`` (defaults when the manifest says nothing)."""
        if self.functions and function in self.functions:
            return self.functions[function]
        return FunctionOptions()

    def resources_for(self, function: str | None = None) -> Resources:
        """What the tool, or one of its functions, needs, with defaults filled in."""
        tool = self.resources.over(DEFAULT_RESOURCES)
        return tool if function is None else self.options_for(function).resources.over(tool)

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
            hint=(
                "Point SciPatch at a tool package folder, or create one with 'scipatch new <name>'."
            ),
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
