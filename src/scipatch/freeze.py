"""Pin a tool's packages for every platform (``scipatch freeze``).

The platform the tool was built and tested on is pinned from its environment.
Every other platform is resolved without installing anything: conda packages by
a dry-run solve for that platform, PyPI packages by uv for that platform, using
only prebuilt wheels (except pure-Python packages published only as source), so
a platform where something would have to be compiled counts as unsupported.
The tested versions are kept wherever they exist on the other platform.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from scipatch import platforms
from scipatch.environments.conda import channel_arguments, channels_of, conda_frontend
from scipatch.environments.uv import UvBackend, find_uv
from scipatch.errors import BuildError
from scipatch.hardware import folder_size_mb
from scipatch.lock import Lock, PlatformLock, inputs_hash, save
from scipatch.manifest import Environment, Manifest
from scipatch.runtime.executor import environment_python

Runner = Callable[
    [list[str], str | None, dict[str, str] | None], "subprocess.CompletedProcess[str]"
]
WheelCheck = Callable[[str, str | None], bool | None]

#: Versions of the virtual packages conda needs to solve for another operating system.
_VIRTUAL_PACKAGES = {
    "win": ("CONDA_OVERRIDE_WIN", "10"),
    "osx": ("CONDA_OVERRIDE_OSX", "13.0"),
    "linux": ("CONDA_OVERRIDE_GLIBC", "2.34"),  # as for the PyPI wheels (platforms.py)
}
_NO_WHEEL = re.compile(
    r"(?:Because|and) (?:all versions of )?(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\{[^}]*\})?"
    r"(?P<spec>(?:==|>=|<=|~=|>|<)[^\s,]+)? (?:has|have) no "
    r"(?:usable wheels|wheels with a matching)"
)
_MAX_SOURCE_ONLY = 12


def _run(
    command: list[str], stdin: str | None, env: dict[str, str] | None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, input=stdin, capture_output=True, text=True, env=env, check=False
    )


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pypi_has_wheels(name: str, version: str | None) -> bool | None:
    """Whether a release on PyPI publishes any wheel (None if PyPI cannot be asked)."""
    url = (
        f"https://pypi.org/pypi/{name}/{version}/json"
        if version
        else f"https://pypi.org/pypi/{name}/json"
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed https URL
            files = json.load(response).get("urls", [])
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return any(item.get("packagetype") == "bdist_wheel" for item in files)


@dataclass
class FreezeResult:
    path: Path
    tested_on: str | None
    platforms: dict[str, PlatformLock]
    env_dir: Path
    warnings: list[str] = field(default_factory=list)


def freeze(
    manifest: Manifest,
    package_dir: Path,
    env_dir: Path,
    source_dir: Path | None,
    *,
    progress: Callable[[str], None] = lambda _: None,
    run: Runner = _run,
    has_wheels: WheelCheck = pypi_has_wheels,
) -> FreezeResult:
    """Write ``scipatch.lock`` for a tool whose environment at ``env_dir`` passed its tests."""
    spec = manifest.environment
    uv = find_uv()
    if uv is None:
        raise BuildError("uv is not installed.", hint=UvBackend.install_hint)
    python = environment_python(env_dir)
    host = platforms.current()
    host_conda = installed_conda(env_dir) if spec.manager == "conda" else []
    conda_names = {normalize(pin.split("==")[0]) for pin in host_conda}
    host_pip = [
        pin
        for pin in installed_pip(uv, python, run)
        if normalize(pin.split("==")[0]) not in conda_names
    ]
    requirements, warnings = pip_requirements(spec, package_dir, source_dir, python, run)
    wanted = spec.platforms or list(platforms.PLATFORMS)
    entries: dict[str, PlatformLock] = {}
    for name in platforms.PLATFORMS:
        if name not in wanted:
            entries[name] = PlatformLock(
                unavailable="not supported by this tool (environment.platforms in scipatch.yaml)"
            )
        elif name == host:
            entries[name] = PlatformLock(conda=host_conda, pip=host_pip)
        else:
            progress(name)
            entries[name] = _resolve_platform(
                name, spec, package_dir, requirements, host_conda, host_pip, uv, run, has_wheels
            )
    lock = Lock(
        inputs=inputs_hash(manifest, package_dir),
        tested_on=host,
        tested_size_mb=folder_size_mb(env_dir),
        platforms=entries,
    )
    return FreezeResult(save(package_dir, lock), host, entries, env_dir, warnings)


def installed_conda(env_dir: Path) -> list[str]:
    """``name==version=build`` of every conda package in an environment."""
    pins = []
    for record in sorted((env_dir / "conda-meta").glob("*.json")):
        data = json.loads(record.read_text(encoding="utf-8"))
        build = data.get("build") or data.get("build_string")
        if data.get("name") and data.get("version") and build:
            pins.append(f"{data['name']}=={data['version']}={build}")
    return sorted(pins, key=str.lower)


def installed_pip(uv: str, python: Path, run: Runner = _run) -> list[str]:
    """``name==version`` of every PyPI package in an environment (not editable ones)."""
    result = run([uv, "pip", "freeze", "--python", str(python), "--exclude-editable"], None, None)
    if result.returncode != 0:
        raise BuildError(f"Could not list the environment's packages: {result.stderr.strip()}")
    return sorted(
        (line for line in result.stdout.splitlines() if "==" in line and " @ " not in line),
        key=str.lower,
    )


def pip_requirements(
    spec: Environment,
    package_dir: Path,
    source_dir: Path | None,
    python: Path,
    run: Runner = _run,
) -> tuple[list[str], list[str]]:
    """What the PyPI side asks for: packages, a requirements file, and the source's needs.

    The upstream source itself is not resolved (it is installed from its
    checkout); its declared dependencies are. Returns the requirements and
    warnings (such as compiled code in the source).
    """
    requirements = list(spec.packages)
    if spec.requirements:
        requirements.append(f"-r {package_dir / spec.requirements}")
    warnings = []
    if source_dir is not None and source_dir.is_dir():
        script = (
            "import importlib.metadata as m, json, sys, pathlib, urllib.parse\n"
            "target = pathlib.Path(sys.argv[1]).resolve()\n"
            "for d in m.distributions():\n"
            "    info = json.loads(d.read_text('direct_url.json') or '{}')\n"
            "    path = urllib.parse.urlparse(info.get('url', '')).path\n"
            "    if info.get('dir_info', {}).get('editable') and path and "
            "pathlib.Path(urllib.parse.unquote(path)).resolve() == target:\n"
            "        print(json.dumps(d.requires or []))\n"
            "        break\n"
        )
        result = run([str(python), "-c", script, str(source_dir)], None, None)
        lines = result.stdout.strip().splitlines()
        needs = json.loads(lines[-1]) if result.returncode == 0 and lines else []
        requirements += [need for need in needs if "extra ==" not in need.replace("'", '"')]
        compiled = [
            path.name
            for pattern in ("*.so", "*.pyd", "*.dylib")
            for path in source_dir.rglob(pattern)
            if ".git" not in path.parts
        ]
        if compiled:
            warnings.append(
                "the upstream source contains compiled code "
                f"({', '.join(sorted(set(compiled))[:3])}); installing it on another platform "
                "needs a compiler there. Prefer a prebuilt PyPI or conda package if there is one."
            )
    return requirements, warnings


def _resolve_platform(
    name: str,
    spec: Environment,
    package_dir: Path,
    requirements: list[str],
    host_conda: list[str],
    host_pip: list[str],
    uv: str,
    run: Runner,
    has_wheels: WheelCheck,
) -> PlatformLock:
    notes = []
    conda_pins: list[str] = []
    if spec.manager == "conda":
        conda_pins, error, note = solve_conda(name, spec, package_dir, host_conda, run)
        if error:
            return PlatformLock(unavailable=error)
        if note:
            notes.append(note)
    provided = {normalize(pin.split("==")[0]) for pin in conda_pins}
    pip_pins, error, note = resolve_pip(
        uv, name, requirements, spec.python, host_pip, run, has_wheels
    )
    if error:
        return PlatformLock(unavailable=error)
    if note:
        notes.append(note)
    pip_pins = [pin for pin in pip_pins if normalize(pin.split("==")[0]) not in provided]
    return PlatformLock(conda=conda_pins, pip=pip_pins, note="; ".join(notes) or None)


def solve_conda(
    name: str,
    spec: Environment,
    package_dir: Path,
    host_conda: list[str],
    run: Runner = _run,
) -> tuple[list[str], str | None, str | None]:
    """Conda packages for a platform: (pins, why it is impossible, note)."""
    conda, env = conda_frontend()
    here = (platforms.current() or "").split("-")[0]
    system = name.split("-")[0]
    if system != here and system in _VIRTUAL_PACKAGES:
        variable, value = _VIRTUAL_PACKAGES[system]
        env = {**env, variable: value}
    channels = channels_of(spec, package_dir)
    if spec.conda_file:
        requested = ["-f", str(package_dir / spec.conda_file)]
    else:
        wanted = platforms.for_platform(spec.conda_packages, name, spec.python)
        requested = [f"python={spec.python}", *wanted]
    records, error = _dry_run(conda, env, name, channels, requested, run)
    if records is None:
        return [], error, None
    tested = {pin.split("==")[0]: pin.split("==")[1].split("=")[0] for pin in host_conda}
    keep = [
        f"{record['name']}=={tested[record['name']]}"
        for record in records
        if record["name"] in tested and record["version"] != tested[record["name"]]
    ]
    note = None
    if keep:
        preferred, _ = _dry_run(conda, env, name, channels, [*requested, *keep], run)
        if preferred is not None:
            records = preferred
        else:
            differs = ", ".join(pin.split("==")[0] for pin in keep[:6])
            note = f"conda versions differ from the tested platform ({differs})"
    pins = [f"{r['name']}=={r['version']}={r['build_string']}" for r in records]
    return sorted(pins, key=str.lower), None, note


def _dry_run(
    conda: str,
    env: dict[str, str],
    name: str,
    channels: list[str],
    requested: list[str],
    run: Runner,
) -> tuple[list[dict[str, str]] | None, str | None]:
    with tempfile.TemporaryDirectory(prefix="scipatch-freeze-") as scratch:
        command = [
            conda, "create", "--dry-run", "--json", "-y",
            "-p", str(Path(scratch) / "probe"), "--platform", name,
            *channel_arguments(channels), *requested,
        ]  # fmt: skip
        result = run(command, None, env)
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        data = {}
    links = (data.get("actions") or {}).get("LINK")
    if result.returncode == 0 and data.get("success", True) and links is not None:
        return [
            {
                "name": link["name"],
                "version": link["version"],
                "build_string": link.get("build_string") or link.get("build", ""),
            }
            for link in links
        ], None
    messages = [entry.get("message", "") for entry in data.get("log_history", [])]
    message = "\n".join(filter(None, [*messages, data.get("message"), data.get("error")]))
    return None, conda_reason(message or result.stderr, name, channels)


def _clean_spec(text: str) -> str:
    text = re.sub(r",\s*which$", "", text.strip()).strip()
    text = re.sub(r"\s*\*$", "", text).strip()
    return re.sub(r"\s*=\*$", "", text).strip()


def conda_reason(message: str, name: str, channels: list[str]) -> str:
    """A one-line explanation of why conda cannot solve for a platform."""
    label = platforms.label(name)
    where = ", ".join(channels) or "the channels"
    lines = [line.strip(" │├└─\t") for line in message.splitlines()]
    tree = [line for line in lines if line]
    missing = [
        _clean_spec(line.split(" does not exist")[0]) for line in tree if " does not exist" in line
    ]
    if missing:
        by_package: dict[str, str] = {}
        for spec in missing:  # the same package deeper in the tree is more specific
            by_package[spec.split()[0]] = spec
        names = list(by_package.values())
        listed = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        return f"{where} has no {label} build of {listed}"
    summary = " ".join(" ".join(tree).split())
    return f"the conda packages cannot be solved for {label}: {summary[:300]}"


def resolve_pip(
    uv: str,
    name: str,
    requirements: list[str],
    python: str,
    tested: list[str],
    run: Runner = _run,
    has_wheels: WheelCheck = pypi_has_wheels,
) -> tuple[list[str], str | None, str | None]:
    """PyPI packages for a platform: (pins, why it is impossible, note).

    The tested versions are used where possible; otherwise the platform gets the
    versions uv picks for it, and the note names the differences.
    """
    if not requirements:
        return [], None, None
    pins, error = _compile(uv, name, requirements, python, tested, run, has_wheels)
    if error is None or not tested:
        return pins, error, None
    pins, error = _compile(uv, name, requirements, python, [], run, has_wheels)
    if error is not None:
        return [], error, None
    tested_versions = {normalize(pin.split("==")[0]): pin.split("==")[1] for pin in tested}
    differs = [
        f"{pin.split('==')[0]} {pin.split('==')[1]} (tested {tested_versions[key]})"
        for pin in pins
        if (key := normalize(pin.split("==")[0])) in tested_versions
        and tested_versions[key] != pin.split("==")[1]
    ]
    if not differs:
        return pins, None, None
    return pins, None, f"PyPI versions differ from the tested platform: {', '.join(differs[:5])}"


def _compile(
    uv: str,
    name: str,
    requirements: list[str],
    python: str,
    constraints: list[str],
    run: Runner,
    has_wheels: WheelCheck,
) -> tuple[list[str], str | None]:
    label = platforms.label(name)
    source_only: list[str] = []
    with tempfile.TemporaryDirectory(prefix="scipatch-freeze-") as scratch:
        constraint_file = Path(scratch) / "constraints.txt"
        constraint_file.write_text("".join(f"{pin}\n" for pin in constraints), encoding="utf-8")
        for _ in range(_MAX_SOURCE_ONLY):
            command = [
                uv, "pip", "compile", "-", "--quiet", "--no-header", "--no-annotate",
                "--python-version", python, "--python-platform", platforms.uv_target(name),
                "--only-binary", ":all:",
                *[arg for package in source_only for arg in ("--no-binary", package)],
            ]  # fmt: skip
            if constraints:
                command += ["--constraint", str(constraint_file)]
            result = run(command, "\n".join(requirements) + "\n", None)
            if result.returncode == 0:
                pins = [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if "==" in line and not line.startswith(("#", " ", "-e"))
                ]
                return sorted(pins, key=str.lower), None
            text = " ".join(result.stderr.split())
            match = _NO_WHEEL.search(text)
            if match is None:
                return [], f"the PyPI packages cannot be resolved for {label}: {text[:300]}"
            package, spec = match["name"], match["spec"] or ""
            version = spec[2:] if spec.startswith("==") else None
            if package not in source_only and has_wheels(package, version) is False:
                source_only.append(package)  # pure Python, published as source only
                continue
            release = f"{package} {version}" if version else f"{package}{spec}"
            return [], f"{release} has no prebuilt package for {label} (Python {python})"
    return [], f"too many source-only packages for {label}"
