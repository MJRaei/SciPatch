"""The Typer application object and global options (separate to avoid import cycles)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

import typer

from scipatch import __version__
from scipatch.app import SciPatch
from scipatch.cli.console import RichReporter, console

PANEL_USE = "Use tools"
PANEL_MANAGE = "Manage tools"
PANEL_CONNECT = "Connect AI apps"
PANEL_BUILD = "Build new tools"

app = typer.Typer(
    name="scipatch",
    help=(
        "[bold]SciPatch[/]: turn research repositories into tools that any AI agent can find, "
        "run, and remember.\n\n"
        "New here? Run [cyan]scipatch setup[/]."
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@dataclass
class Settings:
    verbose: bool = False
    debug: bool = False


settings = Settings()


def get_scipatch() -> SciPatch:
    return SciPatch(reporter=RichReporter(verbose=settings.verbose))


def reporter_of(scipatch: SciPatch) -> RichReporter:
    reporter = scipatch.reporter
    assert isinstance(reporter, RichReporter)  # noqa: S101 - set by get_scipatch
    return reporter


def _show_version(value: bool) -> None:
    if value:
        console.print(f"scipatch {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show every command run during builds.")
    ] = False,
    debug: Annotated[bool, typer.Option("--debug", help="Show full tracebacks on errors.")] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    settings.verbose = verbose
    settings.debug = debug
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
