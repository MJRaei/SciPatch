"""Motel: turn research repositories into tools that any AI agent can find, run, and remember."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("motel")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
