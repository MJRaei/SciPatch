"""Agent Skills (SKILL.md) for Motel and for every installed tool.

Skills are the portable "manuals" of the Agent Skills standard, read by Claude
Code, Codex, Gemini CLI, Cursor, Copilot and others. Motel provides:

* ``motel``: how to find, run, and cite tools (bundled);
* ``motel-onboard``: how to turn a repository into a tool package (bundled);
* ``motel-<tool>``: one per installed tool, generated from its manifest,
  introspected functions, and the package's own SKILL.md notes.

Syncing writes these into an agent's skills folder. Folders Motel writes carry
a ``.motel-managed`` marker; Motel never modifies or deletes anything else.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from motel import __version__, frontmatter
from motel.models import FunctionInfo
from motel.registry import InstalledTool, Registry
from motel.schema import type_label

ASSETS_DIR = Path(__file__).parent / "assets"
BUNDLED_SKILLS_DIR = ASSETS_DIR / "skills"
MARKER_FILE = ".motel-managed"
SKILL_PREFIX = "motel"
DESCRIPTION_LIMIT = 1024

#: A skill is a mapping of relative file path to content.
SkillFiles = dict[str, str | bytes]


def tool_skill_name(tool_name: str) -> str:
    return f"{SKILL_PREFIX}-{tool_name}"


@dataclass(frozen=True)
class SkillTarget:
    """A folder that some AI agent reads skills from."""

    key: str
    label: str
    directory: Path


def skill_targets() -> dict[str, SkillTarget]:
    """Known user-level skills folders."""
    home = Path.home()
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude"))
    targets = [
        SkillTarget("claude", "Claude Code", claude_dir / "skills"),
        SkillTarget(
            "agents", "Codex, Gemini CLI, OpenCode and other agents", home / ".agents" / "skills"
        ),
        SkillTarget("cursor", "Cursor", home / ".cursor" / "skills"),
        SkillTarget("copilot", "GitHub Copilot", home / ".copilot" / "skills"),
        SkillTarget("gemini", "Gemini CLI", home / ".gemini" / "skills"),
    ]
    return {target.key: target for target in targets}


@dataclass
class SyncReport:
    directory: Path
    written: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class SkillManager:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def desired(self, *, include_tools: bool = True) -> dict[str, SkillFiles]:
        skills = bundled_skills()
        if include_tools:
            for tool in self.registry.tools():
                if tool.usable:
                    skills[tool_skill_name(tool.name)] = render_tool_skill(tool)
        return skills

    def sync(self, directory: Path, *, include_tools: bool = True) -> SyncReport:
        """Make ``directory`` contain exactly the current Motel skills."""
        report = SyncReport(directory)
        directory.mkdir(parents=True, exist_ok=True)
        desired = self.desired(include_tools=include_tools)
        for name, files in desired.items():
            target = directory / name
            if target.exists() and not (target / MARKER_FILE).exists():
                report.skipped.append(name)  # the user's own skill; leave it alone
                continue
            _write_skill(target, files)
            report.written.append(name)
        for entry in sorted(directory.iterdir()):
            if (
                entry.name.startswith(SKILL_PREFIX)
                and entry.name not in desired
                and (entry / MARKER_FILE).exists()
            ):
                shutil.rmtree(entry)
                report.removed.append(entry.name)
        return report

    @staticmethod
    def remove_all(directory: Path) -> list[str]:
        """Delete every Motel-managed skill from ``directory``."""
        removed = []
        if directory.is_dir():
            for entry in sorted(directory.iterdir()):
                if entry.name.startswith(SKILL_PREFIX) and (entry / MARKER_FILE).exists():
                    shutil.rmtree(entry)
                    removed.append(entry.name)
        return removed

    def export(self, out_dir: Path, *, as_zip: bool = False) -> list[Path]:
        """Write skills as folders (or zip files, for uploading to Claude apps)."""
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for name, files in self.desired().items():
            if as_zip:
                path = out_dir / f"{name}.zip"
                path.write_bytes(_zip_skill(name, files))
            else:
                path = out_dir / name
                _write_skill(path, files, marker=False)
            written.append(path)
        return written


def bundled_skills() -> dict[str, SkillFiles]:
    skills: dict[str, SkillFiles] = {}
    for folder in sorted(BUNDLED_SKILLS_DIR.iterdir()):
        if (folder / "SKILL.md").is_file():
            skills[folder.name] = {
                str(path.relative_to(folder)): path.read_bytes()
                for path in sorted(folder.rglob("*"))
                if path.is_file() and "__pycache__" not in path.parts
            }
    return skills


def _write_skill(target: Path, files: SkillFiles, *, marker: bool = True) -> None:
    """Replace ``target`` with ``files`` (written to a temporary folder first)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        for relative, content in files.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
        if marker:
            (staging / MARKER_FILE).write_text(
                json.dumps({"motel_version": __version__}) + "\n", encoding="utf-8"
            )
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _zip_skill(name: str, files: SkillFiles) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative, content in sorted(files.items()):
            archive.writestr(f"{name}/{relative}", content)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Rendering a tool's skill
# --------------------------------------------------------------------------- #


def skill_description(tool: InstalledTool) -> str:
    """What the tool does and when to use it: the text agents match tasks against."""
    manifest = tool.manifest
    description = tool.guide_description() or (
        f"{manifest.summary.rstrip('.')}. Use when a task needs "
        f"{manifest.display_title}"
        + (f" ({', '.join(manifest.domains)})" if manifest.domains else "")
        + "."
    )
    description += f" Runs locally through Motel as tool '{manifest.name}'."
    return description[:DESCRIPTION_LIMIT]


def render_tool_skill(tool: InstalledTool) -> SkillFiles:
    manifest = tool.manifest
    metadata = {
        "name": tool_skill_name(tool.name),
        "description": skill_description(tool),
        "metadata": {"motel-tool": tool.name, "motel-tool-version": manifest.version},
    }
    if manifest.source.license:
        metadata["license"] = manifest.source.license

    sections = [f"# {manifest.display_title}", manifest.summary]
    if manifest.description:
        sections.append(manifest.description.strip())
    status = tool.state.golden_summary if tool.state else "not built"
    sections.append(
        f"> Installed in Motel as `{tool.name}` (version {manifest.version}; {status})."
    )
    sections.append(_how_to_run(tool))
    if manifest.environment.secrets:
        sections.append(_keys_section(tool))
    sections.append("## Functions\n\n" + "\n\n".join(_function_section(f) for f in tool.functions))
    guide = tool.guide()
    if guide:
        sections.append("## Usage notes\n\n" + _demote_headings(guide))
    if manifest.validity:
        sections.append("## Before trusting a result\n\n" + manifest.validity.strip())
    sections.append(_provenance(tool))

    files: SkillFiles = {"SKILL.md": frontmatter.render(metadata, "\n\n".join(sections))}
    references = tool.package_dir / "references"
    if references.is_dir():
        for path in sorted(references.rglob("*")):
            if path.is_file():
                files[str(path.relative_to(tool.package_dir))] = path.read_bytes()
    return files


def _how_to_run(tool: InstalledTool) -> str:
    example = tool.functions[0] if tool.functions else None
    name = tool.name
    if example is None:
        return "## How to run\n\nThis tool has no functions yet."
    args = " ".join(f"{p}=..." for p in example.required) or ""
    call = f"motel run {name} {example.name} {args}".rstrip()
    return (
        "## How to run\n\n"
        "From a terminal (any agent with shell access):\n\n"
        f"```bash\n{call} --json\n```\n\n"
        "Through MCP, if the `motel` server is connected: "
        f'`run_tool(tool="{name}", function="{example.name}", arguments={{...}})`.\n\n'
        "- Relative file paths are resolved from the current folder; outputs go to the run's "
        "own folder unless `--output-dir` (MCP: `output_dir`) is given. Output paths are "
        "returned in the result.\n"
        "- Before running, check whether an identical earlier run exists: "
        f"`motel runs --tool {name} --json` (MCP: `search_history`). Identical calls are "
        "answered from cache automatically.\n"
        "- For slow functions use `--background`, then `motel runs show <run-id> --json` "
        "(MCP: `get_run`)."
    )


def _keys_section(tool: InstalledTool) -> str:
    lines = ["## API keys", "", "This tool needs:", ""]
    for secret in tool.manifest.environment.secrets:
        where = f"get one at {secret.url}" if secret.url else None
        details = "; ".join(part for part in (secret.description, where) if part)
        lines.append(f"- `{secret.name}`" + (f" ({details})" if details else ""))
    lines += [
        "",
        "Never ask the user to type a key into the chat. If a key is not set, `run_tool` "
        "returns a link to a page on the user's computer where they can enter it; give them "
        "the link and run the tool again afterwards. From a shell, run "
        f"`motel secret set {tool.manifest.environment.secrets[0].name}`: it opens that page "
        "in the user's browser and waits until they have entered the key.",
    ]
    return "\n".join(lines)


def _function_section(function: FunctionInfo) -> str:
    lines = [f"### `{function.signature()}`", ""]
    if function.summary:
        lines.append(function.summary)
    if function.description:
        lines += ["", function.description]
    if function.long_running:
        lines += ["", "**Long-running:** start it in the background and poll for the result."]
    if function.properties:
        lines += ["", "| Parameter | Type | Default | Description |", "|---|---|---|---|"]
        for name, schema in function.properties.items():
            default = "*required*" if name in function.required else f"`{schema.get('default')!r}`"
            description = _cell(schema.get("description", ""))
            lines.append(f"| `{name}` | {_cell(type_label(schema))} | {default} | {description} |")
    returns = function.returns.get("description")
    if returns:
        lines += ["", f"**Returns:** {returns}"]
    if function.outputs:
        details = ", ".join(
            f"`{key}`" + (f" ({info['unit']})" if info.get("unit") else "")
            for key, info in function.outputs.items()
        )
        lines += ["", f"**Outputs:** {details}"]
    return "\n".join(lines)


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _demote_headings(markdown: str, top: int = 3) -> str:
    """Shift a document's headings so its highest level becomes ``top``."""
    lines = markdown.splitlines()
    levels = []
    in_code = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
        elif not in_code and line.startswith("#"):
            levels.append(len(line) - len(line.lstrip("#")))
    shift = max(0, top - min(levels)) if levels else 0
    result = []
    in_code = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
        elif not in_code and line.startswith("#"):
            line = "#" * shift + line
        result.append(line)
    return "\n".join(result)


def _provenance(tool: InstalledTool) -> str:
    source = tool.manifest.source
    lines = ["## Provenance and citation", ""]
    if source.repo:
        commit = tool.state.source_commit if tool.state else None
        lines.append(f"- Code: {source.repo} @ `{(commit or source.ref or '')[:12]}`")
    if source.paper:
        lines.append(f"- Paper: {source.paper}")
    if source.citation:
        lines.append(f"- Cite as: {source.citation}")
    if source.license:
        lines.append(f"- License: {source.license}")
    lines.append(
        "- When reporting results, name the tool and cite the paper; "
        "the run id identifies the exact inputs and versions."
    )
    return "\n".join(lines)
