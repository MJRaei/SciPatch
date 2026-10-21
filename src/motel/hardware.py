"""What this computer offers, and whether a tool's needs fit it.

Tools declare what they need under ``resources`` in ``motel.yaml`` (a GPU,
memory, an internet connection). Motel compares that with this computer before
installing a tool and before each run, so people and agents learn about a
shortfall before it causes a failure, and it chooses the device a run should
use, passed to the tool as ``MOTEL_DEVICE``: ``cuda``, ``mps``, or ``cpu``.

GPUs are used only when the user allows it (``motel config gpu on``), except by
tools that cannot run without one; results stay reproducible by default.
"""

from __future__ import annotations

import contextlib
import functools
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from motel.manifest import Resources

_GPU_WORDS = {"cuda": "an NVIDIA GPU (CUDA)", "mps": "an Apple silicon GPU"}


@dataclass(frozen=True)
class Gpu:
    kind: str  # "cuda" or "mps"
    name: str
    memory_gb: float | None = None
    shared: bool = False  # uses the computer's main memory (Apple silicon)

    def label(self) -> str:
        if self.shared and self.memory_gb:
            return f"{self.name} (shares the {self.memory_gb:g} GB memory)"
        return f"{self.name} ({self.memory_gb:g} GB)" if self.memory_gb else self.name


@dataclass(frozen=True)
class Machine:
    cpu_cores: int
    memory_gb: float | None
    gpus: tuple[Gpu, ...] = ()

    def summary(self) -> str:
        parts = [f"{self.cpu_cores} CPU cores"]
        if self.memory_gb:
            parts.append(f"{self.memory_gb:g} GB memory")
        parts.append("GPU: " + (", ".join(gpu.label() for gpu in self.gpus) or "none found"))
        return ", ".join(parts)


@functools.cache
def detect() -> Machine:
    """This computer's processor cores, memory, and GPUs (looked up once per process)."""
    memory = _memory_gb()
    gpus = [*_nvidia_gpus()]
    if sys.platform == "darwin" and platform.machine() == "arm64":
        gpus.append(Gpu("mps", f"{_mac_chip()} GPU", memory, shared=True))
    return Machine(os.cpu_count() or 1, memory, tuple(gpus))


def _memory_gb() -> float | None:
    try:
        if sys.platform == "win32":
            return _windows_memory_gb()
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None
    return round(total / 1024**3)


def _windows_memory_gb() -> float | None:
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
        return None
    return float(round(status.ullTotalPhys / 1024**3))


def _nvidia_gpus() -> list[Gpu]:
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return []
    try:
        completed = subprocess.run(
            [smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_nvidia_smi(completed.stdout) if completed.returncode == 0 else []


def parse_nvidia_smi(output: str) -> list[Gpu]:
    """GPUs from ``nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits``."""
    gpus = []
    for line in output.splitlines():
        name, _, memory = line.rpartition(",")
        if not name.strip():
            continue
        try:
            memory_gb: float | None = round(float(memory) / 1024, 1)
        except ValueError:
            memory_gb = None
        gpus.append(Gpu("cuda", name.strip(), memory_gb))
    return gpus


def _mac_chip() -> str:
    try:
        completed = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "Apple silicon"
    return completed.stdout.strip() or "Apple silicon"


def gpu_words(kinds: Sequence[str]) -> str:
    """'an NVIDIA GPU (CUDA)', or 'an NVIDIA GPU (CUDA) or an Apple silicon GPU'."""
    return " or ".join(_GPU_WORDS.get(kind, kind) for kind in kinds)


def describe_needs(needs: Resources) -> list[str]:
    """What a tool or function needs, in words (nothing for the defaults)."""
    words = []
    kinds = needs.gpu_types or ["cuda"]
    if needs.gpu == "required":
        memory = f" with {needs.gpu_memory_gb:g} GB of memory" if needs.gpu_memory_gb else ""
        words.append(f"requires {gpu_words(kinds)}{memory}")
    elif needs.gpu == "optional":
        words.append(f"faster with {gpu_words(kinds)}")
    if needs.memory_gb:
        words.append(f"{needs.memory_gb:g} GB of memory recommended")
    if needs.network:
        words.append("an internet connection")
    return words


@dataclass(frozen=True)
class Fit:
    """How a tool's needs fit this computer."""

    device: str = "cpu"  # what the run should use: cuda, mps, or cpu
    blockers: list[str] = field(default_factory=list)  # it cannot run here
    warnings: list[str] = field(default_factory=list)  # it may run poorly here
    notes: list[str] = field(default_factory=list)  # good to know


def assess(needs: Resources, machine: Machine, *, use_gpu: bool) -> Fit:
    """Compare what a tool or function needs with ``machine``.

    ``use_gpu`` is the user's choice for tools that only run faster on a GPU;
    tools that require one always get it.
    """
    kinds = needs.gpu_types or ["cuda"]
    usable = [gpu for gpu in machine.gpus if gpu.kind in kinds]
    fit = Fit()
    if needs.gpu == "required":
        if not usable:
            others = f" that it can use (it has the {machine.gpus[0].name})" if machine.gpus else ""
            fit.blockers.append(f"needs {gpu_words(kinds)}; this computer has none{others}")
        else:
            gpu = usable[0]
            fit = Fit(device=gpu.kind)
            if needs.gpu_memory_gb and gpu.memory_gb and gpu.memory_gb < needs.gpu_memory_gb:
                fit.warnings.append(
                    f"needs {needs.gpu_memory_gb:g} GB of GPU memory; {gpu.name} has "
                    f"{gpu.memory_gb:g} GB"
                )
    elif needs.gpu == "optional":
        if usable and use_gpu:
            fit = Fit(device=usable[0].kind)
            fit.notes.append(f"runs on the {usable[0].name}")
        elif usable:
            fit.notes.append(
                f"runs on the CPU; turn on GPU use ('motel config gpu on') to run it on the "
                f"{usable[0].name}"
            )
        else:
            fit.notes.append(f"runs on the CPU ({gpu_words(kinds)} would make it faster)")
    if needs.memory_gb and machine.memory_gb and machine.memory_gb < needs.memory_gb:
        fit.warnings.append(
            f"{needs.memory_gb:g} GB of memory recommended; this computer has "
            f"{machine.memory_gb:g} GB (try smaller inputs first)"
        )
    return fit


def install_blocker(needs: Resources) -> str | None:
    """Why a tool with these needs cannot be installed here (it requires a missing GPU)."""
    return "; ".join(assess(needs, detect(), use_gpu=False).blockers) or None


def folder_size_mb(path: Path) -> float | None:
    """Disk space used by the files under ``path`` (symbolic links not followed)."""
    if not path.is_dir():
        return None
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += (Path(root) / name).lstat().st_size
    return round(total / 1024**2, 1)
