"""Error types.

Every error Motel raises on purpose derives from :class:`MotelError` and carries
an optional *hint*: one sentence telling a non-expert what to do next. The CLI
and the MCP gateway show both, so messages should be written for people, not
for developers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from motel.manifest import Secret


class MotelError(Exception):
    """Base class for anticipated errors, shown to the user without a traceback."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message}\nHint: {self.hint}" if self.hint else self.message


class ManifestError(MotelError):
    """A ``motel.yaml`` file is missing or invalid."""


class ToolNotFoundError(MotelError):
    """No installed tool (or function) has the requested name."""


class ToolExistsError(MotelError):
    """A tool with the same name is already installed."""


class BuildError(MotelError):
    """Fetching the source, creating the environment, or introspecting the tool failed."""

    def __init__(self, message: str, *, hint: str | None = None, log_path: str | None = None):
        super().__init__(message, hint=hint)
        self.log_path = log_path


class RunError(MotelError):
    """A tool call could not be started or its record could not be found."""


class RunNotFoundError(RunError):
    """No run has the requested id."""


class InvalidArgumentsError(RunError):
    """Arguments for a tool function do not match its signature."""


class MissingSecretsError(RunError):
    """A tool needs secrets (e.g. API keys) that are not set."""

    def __init__(self, tool: str, secrets: list[Secret]) -> None:
        names = ", ".join(secret.name for secret in secrets)
        where = next((s.url for s in secrets if s.url), None)
        super().__init__(
            f"Tool '{tool}' needs {names}, which is not set.",
            hint=f"Set it with 'motel secret set {secrets[0].name}'"
            + (f" (get one at {where})." if where else "."),
        )
        self.tool = tool
        self.secrets = secrets


class ClientConfigError(MotelError):
    """An AI app's configuration file could not be read or updated safely."""
