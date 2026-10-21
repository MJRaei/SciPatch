"""YAML frontmatter in Markdown files (the SKILL.md format)."""

from __future__ import annotations

from typing import Any

import yaml


def split(text: str) -> tuple[str, str]:
    """Split Markdown into its frontmatter block (empty if none) and body."""
    if text.startswith("---"):
        lines = text.splitlines(keepends=True)
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "".join(lines[1:index]), "".join(lines[index + 1 :])
    return "", text


def body(text: str) -> str:
    return split(text)[1]


def read(text: str) -> dict[str, Any]:
    """Parse the frontmatter mapping; invalid or missing frontmatter gives ``{}``."""
    block, _ = split(text)
    if not block:
        return {}
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def render(metadata: dict[str, Any], content: str) -> str:
    """Compose a Markdown document with frontmatter."""
    header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True, width=1000).strip()
    return f"---\n{header}\n---\n\n{content.strip()}\n"
