"""Isolated environments: one per tool, so dependencies never conflict."""

from __future__ import annotations

from motel.environments.base import BuildLog, EnvironmentBackend
from motel.environments.conda import CondaBackend
from motel.environments.uv import UvBackend
from motel.errors import BuildError

_BACKENDS: dict[str, type[EnvironmentBackend]] = {
    UvBackend.name: UvBackend,
    CondaBackend.name: CondaBackend,
}


def get_backend(manager: str) -> EnvironmentBackend:
    """Return the backend for ``environment.manager``, checking it is installed."""
    try:
        backend = _BACKENDS[manager]()
    except KeyError:
        raise BuildError(
            f"Unknown environment manager '{manager}'.",
            hint=f"Use one of: {', '.join(sorted(_BACKENDS))}.",
        ) from None
    if not backend.is_available():
        raise BuildError(f"'{manager}' is needed to build this tool.", hint=backend.install_hint)
    return backend


__all__ = ["BuildLog", "CondaBackend", "EnvironmentBackend", "UvBackend", "get_backend"]
