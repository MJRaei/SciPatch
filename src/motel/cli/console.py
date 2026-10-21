"""Console output shared by CLI commands."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.status import Status

from motel.errors import BuildError, MotelError

# soft_wrap: let the terminal wrap long lines, so printed paths stay copyable.
console = Console(highlight=False, soft_wrap=True)
err_console = Console(stderr=True, highlight=False, soft_wrap=True)


def print_json(data: Any) -> None:
    """Machine-readable output for agents and scripts (always plain JSON on stdout)."""
    sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")


def render_error(exc: MotelError) -> None:
    err_console.print(f"[bold red]Error:[/] {escape(exc.message)}")
    if isinstance(exc, BuildError) and exc.log_path:
        err_console.print(f"[dim]Log: {escape(exc.log_path)}[/]")
    if exc.hint:
        err_console.print(f"[yellow]Hint:[/] {escape(exc.hint)}")


class RichReporter:
    """Shows build progress: a spinner for the current step, plus a line per event."""

    def __init__(self, *, verbose: bool = False) -> None:
        self.verbose = verbose
        self._status: Status | None = None

    @contextmanager
    def live(self, message: str = "Working...") -> Iterator[RichReporter]:
        with err_console.status(message) as status:
            self._status = status
            try:
                yield self
            finally:
                self._status = None

    def step(self, message: str) -> None:
        err_console.print(f"[bold cyan]→[/] {escape(message)}")
        if self._status is not None:
            self._status.update(f"{escape(message)}...")

    def detail(self, message: str) -> None:
        if self.verbose:
            err_console.print(f"  [dim]{escape(message)}[/]")

    def warn(self, message: str) -> None:
        err_console.print(f"  [yellow]![/] {escape(message)}")

    def success(self, message: str) -> None:
        err_console.print(f"  [green]✓[/] {escape(message)}")
