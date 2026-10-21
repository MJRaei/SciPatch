"""Data models shared by the registry, builder, runner, and interfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class FunctionInfo(BaseModel):
    """One callable capability of a tool, as introspected from its code plus manifest options."""

    name: str
    summary: str = ""
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    returns: dict[str, Any] = Field(default_factory=dict)
    is_async: bool = False
    warnings: list[str] = Field(default_factory=list)
    long_running: bool = False
    cache: bool = True
    timeout: float | None = None
    outputs: dict[str, dict[str, str]] = Field(default_factory=dict)

    @property
    def properties(self) -> dict[str, dict[str, Any]]:
        props: dict[str, dict[str, Any]] = self.parameters.get("properties", {})
        return props

    @property
    def required(self) -> list[str]:
        required: list[str] = self.parameters.get("required", [])
        return required

    @property
    def accepts_extra_arguments(self) -> bool:
        return self.parameters.get("additionalProperties", True) is not False

    def signature(self) -> str:
        """A compact human signature such as ``relax(structure, fmax=0.05)``."""
        parts = []
        for name, schema in self.properties.items():
            parts.append(f"{name}={schema['default']!r}" if "default" in schema else name)
        return f"{self.name}({', '.join(parts)})"


class GoldenResult(BaseModel):
    """Outcome of one golden test."""

    name: str
    function: str
    passed: bool
    skipped: bool = False
    failures: list[str] = Field(default_factory=list)
    error: str | None = None
    duration: float | None = None
    reference: str | None = None


ToolStatus = Literal["ready", "failing-tests", "broken"]


class ToolState(BaseModel):
    """What Motel knows about an installed tool after building it."""

    status: ToolStatus
    installed_from: str
    linked: bool = False
    installed_at: datetime = Field(default_factory=utcnow)
    built_at: datetime = Field(default_factory=utcnow)
    motel_version: str = ""
    python_version: str | None = None
    env_manager: str = "uv"
    env_fingerprint: str = ""
    source_commit: str | None = None
    functions: list[FunctionInfo] = Field(default_factory=list)
    golden: list[GoldenResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def golden_summary(self) -> str:
        if not self.golden:
            return "no golden tests"
        passed = sum(result.passed for result in self.golden)
        skipped = sum(result.skipped for result in self.golden)
        summary = f"{passed}/{len(self.golden) - skipped} golden tests passed"

        def count(prefix: str) -> int:
            return sum((r.error or "").startswith(prefix) for r in self.golden if r.skipped)

        reasons = [
            (count("skipped: needs"), "skipped (missing secrets)"),
            (count("skipped: not run at install"), "more run with 'motel test'"),
            (count("skipped: not run on"), "for other platforms"),
        ]
        return ", ".join([summary, *(f"{n} {text}" for n, text in reasons if n)])


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def finished(self) -> bool:
        return self is not RunStatus.RUNNING


class RunRecord(BaseModel):
    """One call of a tool function, with full provenance."""

    id: str
    tool: str
    function: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: RunStatus = RunStatus.RUNNING
    tool_version: str | None = None
    source_commit: str | None = None
    result: Any = None
    error: dict[str, Any] | None = None
    files: list[str] = Field(default_factory=list)
    workdir: str = ""
    run_dir: str = ""
    pid: int | None = None
    origin: str = "cli"
    cache_key: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    duration: float | None = None
    #: Set (not stored) when a request was answered from an earlier identical run.
    cached: bool = False
