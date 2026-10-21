"""Progress reporting, decoupled from how it is displayed.

Long operations (building environments, running golden tests) report progress
through a :class:`Reporter`. The CLI renders it with Rich; the MCP gateway and
tests use :class:`NullReporter`.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("motel")


class Reporter(Protocol):
    def step(self, message: str) -> None:
        """A new phase of work started."""

    def detail(self, message: str) -> None:
        """Supplementary information about the current phase."""

    def warn(self, message: str) -> None:
        """Something the user should know about, but not fatal."""

    def success(self, message: str) -> None:
        """A phase or operation finished successfully."""


class NullReporter:
    """Reporter that only writes to the ``motel`` logger."""

    def step(self, message: str) -> None:
        logger.info(message)

    def detail(self, message: str) -> None:
        logger.debug(message)

    def warn(self, message: str) -> None:
        logger.warning(message)

    def success(self, message: str) -> None:
        logger.info(message)
