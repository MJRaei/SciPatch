"""The platforms tools are built for, named like conda's platform subdirectories.

``scipatch freeze`` resolves each tool's environment for every platform here, so a
tool's lock file says where it can be installed, with exact versions for each.
Package lists may carry PEP 508 environment markers (``"ambertools; sys_platform
!= 'win32'"``) to differ between platforms, for conda packages as for PyPI ones.
"""

from __future__ import annotations

import platform

from packaging.markers import InvalidMarker, Marker

PLATFORMS = ("linux-64", "linux-aarch64", "osx-arm64", "osx-64", "win-64")

LABELS = {
    "linux-64": "Linux (x86-64)",
    "linux-aarch64": "Linux (ARM)",
    "osx-arm64": "macOS (Apple silicon)",
    "osx-64": "macOS (Intel)",
    "win-64": "Windows",
}

#: uv's ``--python-platform`` for each platform. Linux wheels are resolved for
#: glibc 2.34 (RHEL 9, Ubuntu 22.04, and newer), as found on current clusters.
_UV_TARGETS = {
    "linux-64": "x86_64-manylinux_2_34",
    "linux-aarch64": "aarch64-manylinux_2_34",
    "osx-arm64": "aarch64-apple-darwin",
    "osx-64": "x86_64-apple-darwin",
    "win-64": "x86_64-pc-windows-msvc",
}

_MARKER_VALUES = {
    "linux-64": ("linux", "Linux", "x86_64", "posix"),
    "linux-aarch64": ("linux", "Linux", "aarch64", "posix"),
    "osx-arm64": ("darwin", "Darwin", "arm64", "posix"),
    "osx-64": ("darwin", "Darwin", "x86_64", "posix"),
    "win-64": ("win32", "Windows", "AMD64", "nt"),
}

_CURRENT = {
    ("Darwin", "arm64"): "osx-arm64",
    ("Darwin", "x86_64"): "osx-64",
    ("Linux", "x86_64"): "linux-64",
    ("Linux", "aarch64"): "linux-aarch64",
    ("Linux", "arm64"): "linux-aarch64",
    ("Windows", "amd64"): "win-64",
}


def current() -> str | None:
    """This computer's platform, or None if SciPatch has no name for it."""
    return _CURRENT.get((platform.system(), platform.machine().lower()))


def label(name: str | None) -> str:
    return LABELS.get(name or "", name or f"{platform.system()} {platform.machine()}")


def uv_target(name: str) -> str:
    return _UV_TARGETS[name]


def marker_environment(name: str, python: str) -> dict[str, str]:
    """Values of PEP 508 marker variables on a platform, for a Python like '3.12'."""
    sys_platform, system, machine, os_name = _MARKER_VALUES[name]
    return {
        "sys_platform": sys_platform,
        "platform_system": system,
        "platform_machine": machine,
        "os_name": os_name,
        "python_version": ".".join(python.split(".")[:2]),
        "python_full_version": python if python.count(".") == 2 else f"{python}.0",
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
    }


def split_marker(requirement: str) -> tuple[str, Marker | None]:
    """A requirement without its environment marker, and the marker (if any)."""
    spec, _, marker = requirement.partition(";")
    if not marker.strip():
        return spec.strip(), None
    try:
        return spec.strip(), Marker(marker.strip())
    except InvalidMarker as exc:
        raise ValueError(f"'{requirement}' has an invalid environment marker: {exc}") from exc


def applies(requirement: str, name: str, python: str) -> bool:
    """Whether a requirement (with an optional marker) is wanted on a platform."""
    _, marker = split_marker(requirement)
    return marker is None or marker.evaluate(marker_environment(name, python))


def for_platform(requirements: list[str], name: str, python: str) -> list[str]:
    """The requirements wanted on a platform, without their markers."""
    return [split_marker(r)[0] for r in requirements if applies(r, name, python)]


def for_this_platform(requirements: list[str], python: str) -> list[str]:
    """The requirements wanted on this computer, without their markers."""
    name = current()
    if name is not None:
        return for_platform(requirements, name, python)
    wanted = []
    for requirement in requirements:
        spec, marker = split_marker(requirement)
        if marker is None or marker.evaluate():
            wanted.append(spec)
    return wanted
