"""Upstream source checkouts and the patches that make them work.

Repositories often need small fixes before they install or run (a pinned
dependency, a hard-coded path, a NumPy 2 incompatibility). Motel never loses
those fixes: they live as ``.patch``/``.diff`` files in the tool package's
``patches/`` folder and are re-applied, in name order, on every rebuild.

In a checkout, each applied patch is a commit on top of the pinned upstream
commit, so ``git status`` shows exactly the edits that are *not yet saved* as
patches. ``motel patch save`` turns those edits into a new patch file.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from motel.environments.base import BuildLog
from motel.errors import BuildError, MotelError

PATCH_SUFFIXES = (".patch", ".diff")
_METADATA_FILE = "motel-source.json"  # stored inside .git so it never shows as a change
_GIT_IDENTITY = ["-c", "user.name=Motel", "-c", "user.email=motel@localhost",
                 "-c", "commit.gpgsign=false"]  # fmt: skip


@dataclass
class SourceInfo:
    commit: str
    patches: list[str] = field(default_factory=list)
    unsaved_changes: list[str] = field(default_factory=list)
    reused: bool = False


def patch_files(package_dir: Path) -> list[Path]:
    """Patch files of a tool package, in the order they are applied."""
    folder = package_dir / "patches"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix in PATCH_SUFFIXES and p.is_file())


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def git_executable() -> str:
    git = shutil.which("git")
    if git is None:
        raise BuildError(
            "git is not installed.",
            hint="Install git (macOS: 'xcode-select --install'; Linux: your package manager).",
        )
    return git


def _git(directory: Path, *args: str, strip: bool = True) -> str:
    completed = subprocess.run(
        [git_executable(), *_GIT_IDENTITY, "-C", str(directory), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise BuildError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip() if strip else completed.stdout


def _git_bytes(directory: Path, *args: str) -> bytes:
    """Output of a git command as bytes (diffs keep CRLF line endings and binary data)."""
    completed = subprocess.run(
        [git_executable(), *_GIT_IDENTITY, "-C", str(directory), *args],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise BuildError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout


def resolve_remote_ref(repo: str, ref: str | None = None) -> str:
    """Commit id that ``ref`` (default: the remote's HEAD) points to."""
    if ref and re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref  # already a full commit id
    completed = subprocess.run(
        [git_executable(), "ls-remote", repo, ref or "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise MotelError(
            f"Could not reach {repo}: {completed.stderr.strip()}",
            hint="Check the URL and your internet connection.",
        )
    refs: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        commit, _, name = line.partition("\t")
        refs[name.strip()] = commit.strip()
    # Annotated tags list the tag object first and the commit as "<tag>^{}".
    for name, commit in refs.items():
        if name.endswith("^{}"):
            return commit
    if refs:
        return next(iter(refs.values()))
    raise MotelError(f"'{ref or 'HEAD'}' was not found in {repo}.")


class SourceCheckout:
    """A git checkout of a tool's upstream repository."""

    def __init__(self, directory: Path, log: BuildLog) -> None:
        self.directory = directory
        self.log = log

    @property
    def _metadata_path(self) -> Path:
        return self.directory / ".git" / _METADATA_FILE

    def _read_metadata(self) -> dict[str, object] | None:
        try:
            data: dict[str, object] = json.loads(self._metadata_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        return data

    def prepare(self, repo: str, ref: str, patches: list[Path], *, fresh: bool) -> SourceInfo:
        """Make the checkout match ``repo@ref`` plus ``patches``.

        An existing checkout that already matches is reused, keeping any unsaved
        edits (they are reported, not discarded). With ``fresh=True`` the
        checkout is always rebuilt from scratch.
        """
        expected = {
            "repo": repo,
            "ref": ref,
            "patches": [f"{p.name}:{_fingerprint(p)}" for p in patches],
        }
        metadata = self._read_metadata()
        if not fresh and metadata is not None:
            unsaved = self.unsaved_changes()
            if all(metadata.get(key) == value for key, value in expected.items()):
                return SourceInfo(
                    commit=str(metadata["commit"]),
                    patches=[p.name for p in patches],
                    unsaved_changes=unsaved,
                    reused=True,
                )
            if unsaved:
                raise BuildError(
                    f"The source checkout in {self.directory} has unsaved edits, but motel.yaml "
                    "or the patches changed since it was prepared.",
                    hint="Save the edits with 'motel patch save', or discard them by "
                    "re-running with --clean.",
                )

        self._clone(repo, ref)
        commit = _git(self.directory, "rev-parse", "HEAD")
        for patch in patches:
            self._apply(patch)
        self._metadata_path.write_text(json.dumps({**expected, "commit": commit}), encoding="utf-8")
        return SourceInfo(commit=commit, patches=[p.name for p in patches])

    def _clone(self, repo: str, ref: str) -> None:
        if self.directory.exists():
            shutil.rmtree(self.directory)
        self.directory.parent.mkdir(parents=True, exist_ok=True)
        git = git_executable()
        hint = "Check that the repository URL and source.ref in motel.yaml are correct."
        # A blobless clone downloads file contents only for the commit we check out.
        self.log.run(
            [
                git,
                "clone",
                "--quiet",
                "--filter=blob:none",
                "--no-checkout",
                repo,
                str(self.directory),
            ],
            title=f"Downloading {repo}",
            hint=hint,
        )
        self.log.run(
            [
                git,
                "-C",
                str(self.directory),
                "-c",
                "advice.detachedHead=false",
                "checkout",
                "--quiet",
                ref,
            ],
            title=f"Checking out '{ref}'",
            hint=hint,
        )
        if (self.directory / ".gitmodules").exists():
            self.log.run(
                [git, "-C", str(self.directory), "submodule", "update", "--init", "--recursive"],
                title="Downloading git submodules",
            )

    def _apply(self, patch: Path) -> None:
        git = git_executable()
        self.log.run(
            [git, "-C", str(self.directory), "apply", "--whitespace=nowarn", str(patch.resolve())],
            title=f"Applying patch {patch.name}",
            hint="The patch no longer matches the source. Re-create it against the pinned "
            "source.ref, or remove it from patches/.",
        )
        _git(self.directory, "add", "--all")
        _git(
            self.directory, "commit", "--quiet", "--allow-empty", "-m", f"motel patch: {patch.name}"
        )

    def unsaved_changes(self) -> list[str]:
        """Files changed in the checkout that are not saved as patches."""
        if not (self.directory / ".git").exists():
            return []
        # Porcelain lines are "XY path"; X may be a space, so don't strip the output.
        output = _git(self.directory, "status", "--porcelain", "--untracked-files=all", strip=False)
        return [line[3:] for line in output.splitlines() if line.strip()]

    def save_patch(self, patches_dir: Path, label: str) -> Path | None:
        """Write unsaved edits to a new numbered patch file and commit them.

        Returns the new patch path, or ``None`` if there was nothing to save.
        """
        if not self.unsaved_changes():
            return None
        _git(self.directory, "add", "--all")
        diff = _git_bytes(self.directory, "diff", "--cached", "--binary", "HEAD")
        patches_dir.mkdir(parents=True, exist_ok=True)
        numbers = [int(m.group()) for p in patch_files(patches_dir.parent)
                   if (m := re.match(r"\d+", p.name))]  # fmt: skip
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "changes"
        path = patches_dir / f"{max(numbers, default=0) + 1:04d}-{slug[:50]}.patch"
        path.write_bytes(diff)
        _git(self.directory, "commit", "--quiet", "-m", f"motel patch: {path.name}")

        metadata = self._read_metadata() or {}
        recorded = list(metadata.get("patches", []))  # type: ignore[call-overload]
        recorded.append(f"{path.name}:{_fingerprint(path)}")
        metadata["patches"] = recorded
        self._metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return path
