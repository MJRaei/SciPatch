"""Command-line interface. Entry point: :func:`main` (installed as ``motel``)."""

from __future__ import annotations

import sys
import traceback
from datetime import datetime

# Command modules register themselves on import; the order sets the order of help panels.
from motel.cli import tools  # noqa: F401

from motel.cli import running  # noqa: F401  # isort: skip
from motel.cli import integrate  # noqa: F401  # isort: skip
from motel.cli import develop  # noqa: F401  # isort: skip
from motel.cli._app import app, settings
from motel.cli.console import err_console, render_error
from motel.errors import MotelError
from motel.paths import MotelPaths

GLOBAL_FLAGS = frozenset({"--verbose", "-v", "--debug"})


def hoist_global_flags(argv: list[str]) -> list[str]:
    """Allow global flags anywhere: ``motel run x y --verbose`` = ``motel --verbose run x y``.

    Arguments after ``--`` belong to another program (``motel exec . -- python -v``).
    """
    split = argv.index("--") if "--" in argv else len(argv)
    head, tail = argv[:split], argv[split:]
    flags = [arg for arg in head if arg in GLOBAL_FLAGS]
    return flags + [arg for arg in head if arg not in GLOBAL_FLAGS] + tail


def main() -> None:
    try:
        app(args=hoist_global_flags(sys.argv[1:]))
    except MotelError as exc:
        render_error(exc)
        sys.exit(1)
    except KeyboardInterrupt:
        err_console.print("\nInterrupted.")
        sys.exit(130)
    except Exception as exc:
        if settings.debug:
            raise
        log = _write_crash_log()
        err_console.print(f"[bold red]Unexpected error:[/] {type(exc).__name__}: {exc}")
        err_console.print(
            f"[dim]Details were saved to {log}. Run again with --debug to see them here.[/]"
        )
        sys.exit(1)


def _write_crash_log() -> str:
    try:
        logs = MotelPaths.from_env().logs
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / f"crash-{datetime.now():%Y%m%d-%H%M%S}.log"
        path.write_text(traceback.format_exc(), encoding="utf-8")
        return str(path)
    except OSError:
        return "(could not write a crash log)"


__all__ = ["app", "main"]
