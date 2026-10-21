"""Maturity: how much evidence backs a tool's results.

Each tool declares one of three levels as ``maturity`` in ``motel.yaml``
(``experimental`` when it says nothing):

* ``established``: mature, widely used code with a publication (or citable
  software record), its results checked against independent references or
  exact results;
* ``published``: research code from a publication, checked against the paper or
  its own test suite, but less widely tested;
* ``experimental``: everything else, such as a small project without a
  publication, or code checked only against its own earlier output.

The manifest refuses a level its evidence does not support. Agents see each
tool's level with the evidence behind it, search ranks better-established tools
first among similar matches, and experimental tools carry a caution. Users can
lower a tool's level on their own computer (never raise it) with
``motel maturity``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from motel.manifest import Manifest, Maturity

LEVELS: tuple[Maturity, ...] = ("established", "published", "experimental")

MEANING: dict[str, str] = {
    "established": "Mature, widely used code; results checked against independent references "
    "or exact results.",
    "published": "Research code from a publication; checked against its paper or its own test "
    "suite, but less widely tested than established tools.",
    "experimental": "Little outside validation (for example a small project without a "
    "publication); treat results as provisional.",
}

#: Search score multipliers. Among similar matches, better-established tools come
#: first; a tool that is clearly the best match still ranks first.
WEIGHTS: dict[str, float] = {"established": 1.0, "published": 0.8, "experimental": 0.6}

_AGAINST_LABELS = {
    "independent": "independent references",
    "paper": "its paper",
    "upstream-tests": "upstream tests",
    "exact": "exact results",
    "regression": "its own earlier output",
}
_PREPRINT = re.compile(r"arxiv|10\.48550/|chemrxiv|10\.26434/|10\.1101/\d{4}\.\d{2}\.\d{2}", re.I)
_SOFTWARE_RECORD = re.compile(r"zenodo|10\.5281/|figshare|10\.6084/", re.I)


def rank(level: str) -> int:
    """0 for established, 1 for published, 2 for experimental."""
    return LEVELS.index(level)


def effective(declared: str, lowered: str | None) -> str:
    """The lower of the declared level and the one the user set."""
    return lowered if lowered is not None and rank(lowered) > rank(declared) else declared


def paper_kind(paper: str | None) -> str | None:
    """'preprint', 'software record' (e.g. a Zenodo DOI), 'paper', or None."""
    if not paper:
        return None
    if _PREPRINT.search(paper):
        return "preprint"
    if _SOFTWARE_RECORD.search(paper):
        return "software record"
    return "paper"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def evidence(manifest: Manifest) -> str:
    """One line on what backs a tool's results: its publication and golden tests."""
    kind = paper_kind(manifest.source.paper)
    parts = [f"{kind}: {manifest.source.paper}" if kind else "no publication"]
    checks = [test for test in manifest.golden if test.raises is None]
    if checks:
        counts = Counter(str(test.against) for test in checks if test.against)
        kinds = [
            f"{counts[key]} against {label}"
            for key, label in _AGAINST_LABELS.items()
            if counts[key]
        ]
        if unlabeled := len(checks) - sum(counts.values()):
            kinds.append(f"{unlabeled} other")
        parts.append(f"{_plural(len(checks), 'golden test')} ({', '.join(kinds)})")
    else:
        parts.append("no golden tests of results")
    if refusals := len(manifest.golden) - len(checks):
        parts.append(_plural(refusals, "refusal check"))
    return "; ".join(parts)


def caution(level: str, alternatives: list[str]) -> str | None:
    """What an agent should do differently with an experimental tool (None otherwise)."""
    if level != "experimental":
        return None
    if alternatives:
        names = ", ".join(alternatives[:-1]) + (" or " if len(alternatives) > 1 else "")
        check = f"cross-check key numbers with {names}{alternatives[-1]} where they cover the task"
    else:
        check = "present its numbers as provisional"
    return (
        "Experimental tool: its results are less vetted than those of published or established "
        f"tools. Tell the user when reporting them, and {check}."
    )


class MaturityOverrides:
    """Levels the user lowered on this computer, stored as JSON (tool name → level)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def all(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {name: level for name, level in data.items() if level in LEVELS}

    def get(self, tool: str) -> str | None:
        return self.all().get(tool)

    def set(self, tool: str, level: str | None) -> None:
        """Lower ``tool`` to ``level``, or forget the user's level with None."""
        data = self.all()
        if level is None:
            data.pop(tool, None)
        else:
            data[tool] = level
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
