"""Scaffold new tool packages and hand repositories to an AI agent for onboarding.

Turning arbitrary research code into a reliable tool needs judgment: which
capabilities matter, how to fix a broken install, which published number to
reproduce. Motel leaves that to a coding agent (Claude Code, Codex, Gemini CLI)
guided by the bundled ``motel-onboard`` skill, and provides the deterministic
parts itself: scaffolding, building, checking, patching, and installing.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from string import Template
from urllib.parse import urlparse

from motel.environments import BuildLog
from motel.errors import MotelError
from motel.manifest import MANIFEST_FILENAME, NAME_MAX_LENGTH, NAME_PATTERN
from motel.reporting import Reporter
from motel.skills import ASSETS_DIR, BUNDLED_SKILLS_DIR, MARKER_FILE
from motel.source import SourceCheckout, resolve_remote_ref

TEMPLATES_DIR = ASSETS_DIR / "templates"
ONBOARD_SKILL = "motel-onboard"
AGENT_PROMPT = (
    "Turn the research repository in ./source into a Motel tool package in this folder. "
    "Read ONBOARDING.md first, then follow the motel-onboard skill step by step."
)

#: Command line that starts each supported agent interactively with a first prompt.
AGENTS: dict[str, list[str]] = {
    "claude": ["claude"],
    "codex": ["codex"],
    "gemini": ["gemini", "-i"],
}
#: Project-level skill folders each agent reads (relative to the folder it starts in).
_PROJECT_SKILL_DIRS = (Path(".claude") / "skills", Path(".agents") / "skills")


@dataclass(frozen=True)
class Workspace:
    directory: Path
    name: str
    repo: str | None
    ref: str | None


def name_from_repo(repo: str) -> str:
    """Derive a valid tool name from a repository URL or path."""
    path = urlparse(repo).path if "://" in repo else repo.rsplit(":", 1)[-1]
    stem = path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    name = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:NAME_MAX_LENGTH].strip("-")
    return name or "tool"


def validate_name(name: str) -> str:
    if len(name) > NAME_MAX_LENGTH or not NAME_PATTERN.match(name):
        raise MotelError(
            f"'{name}' is not a valid tool name.",
            hint="Use lowercase letters, digits, and single hyphens (e.g. 'chgnet-relax').",
        )
    return name


def _yaml_value(value: str | None) -> str:
    return json.dumps(value) if value else "null"  # JSON strings are valid YAML


def scaffold(
    directory: Path,
    name: str,
    *,
    repo: str | None = None,
    ref: str | None = None,
    paper: str | None = None,
    title: str | None = None,
    python: str = "3.11",
) -> list[Path]:
    """Create a new tool package skeleton. Existing files are never overwritten."""
    validate_name(name)
    directory.mkdir(parents=True, exist_ok=True)
    values = {
        "name": name,
        "title": title or name.replace("-", " ").title(),
        "repo": _yaml_value(repo),
        "ref": _yaml_value(ref),
        "paper": _yaml_value(paper),
        "python": python,
        "install_source": "true" if repo else "false",
    }
    created = []
    for template, target in (
        ("motel.yaml.tmpl", MANIFEST_FILENAME),
        ("api.py.tmpl", "api.py"),
        ("SKILL.md.tmpl", "SKILL.md"),
        ("gitignore.tmpl", ".gitignore"),
    ):
        path = directory / target
        if path.exists():
            continue
        text = Template((TEMPLATES_DIR / template).read_text(encoding="utf-8"))
        path.write_text(text.safe_substitute(values), encoding="utf-8")
        created.append(path)
    for folder in ("patches", "tests/data"):
        (directory / folder).mkdir(parents=True, exist_ok=True)
        keep = directory / folder / ".gitkeep"
        if not any((directory / folder).iterdir()):
            keep.touch()
    return created


def prepare_workspace(
    repo: str,
    directory: Path,
    *,
    name: str | None = None,
    ref: str | None = None,
    paper: str | None = None,
    focus: str | None = None,
    reporter: Reporter,
) -> Workspace:
    """Create an onboarding workspace: scaffold, source checkout, brief, and skills."""
    name = validate_name(name or name_from_repo(repo))
    if (directory / MANIFEST_FILENAME).exists():
        reporter.detail(f"Continuing the existing workspace in {directory}")
    reporter.step(f"Resolving {repo}")
    commit = resolve_remote_ref(repo, ref)
    scaffold(directory, name, repo=repo, ref=commit, paper=paper)

    source_dir = directory / "source"
    if not (source_dir / ".git").exists():
        reporter.step("Downloading the source code")
        log = BuildLog(directory / ".motel" / "onboard.log", reporter)
        SourceCheckout(source_dir, log).prepare(repo, commit, [], fresh=True)

    brief = Template((TEMPLATES_DIR / "ONBOARDING.md.tmpl").read_text(encoding="utf-8"))
    (directory / "ONBOARDING.md").write_text(
        brief.safe_substitute(
            name=name,
            repo=repo,
            ref=commit,
            paper=paper or "(none given: look for one in the README)",
            focus=focus or "(none given: pick the capabilities most useful to a scientist)",
        ),
        encoding="utf-8",
    )
    install_project_skills(directory)
    return Workspace(directory, name, repo, commit)


def install_project_skills(directory: Path) -> None:
    """Make the onboarding skills visible to agents started in ``directory``."""
    for relative in _PROJECT_SKILL_DIRS:
        for skill in (ONBOARD_SKILL, "motel"):
            target = directory / relative / skill
            if target.exists() and not (target / MARKER_FILE).exists():
                continue
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(BUNDLED_SKILLS_DIR / skill, target)
            (target / MARKER_FILE).write_text("{}\n", encoding="utf-8")


def available_agents() -> list[str]:
    return [key for key, command in AGENTS.items() if shutil.which(command[0])]


def launch_agent(agent: str, directory: Path, prompt: str = AGENT_PROMPT) -> int:
    """Start an interactive agent session in ``directory``; returns its exit code."""
    if agent not in AGENTS:
        raise MotelError(f"Unknown agent '{agent}'.", hint=f"Choose from: {', '.join(AGENTS)}.")
    executable = shutil.which(AGENTS[agent][0])
    if executable is None:
        raise MotelError(f"'{AGENTS[agent][0]}' is not installed or not on PATH.")
    command = [executable, *AGENTS[agent][1:], prompt]
    return subprocess.call(command, cwd=directory)
