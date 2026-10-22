"""Install tools in the background, so an AI app can install one on first use.

``install_tool`` in the MCP gateway starts an install here and returns while it
is still running; calling it again reports progress (the latest build steps) or
the outcome. Installs run in threads of the server process, with their own
:class:`SciPatch` instance and a reporter that keeps the recent messages.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from scipatch.errors import SciPatchError
from scipatch.paths import SciPatchPaths

#: Progress messages kept per install.
_KEPT_LINES = 12


class RecordingReporter:
    """Reporter that keeps the most recent messages."""

    def __init__(self) -> None:
        self.lines: deque[str] = deque(maxlen=_KEPT_LINES)

    def step(self, message: str) -> None:
        self.lines.append(message)

    def detail(self, message: str) -> None:
        self.lines.append(f"  {message}")

    def warn(self, message: str) -> None:
        self.lines.append(f"! {message}")

    def success(self, message: str) -> None:
        self.lines.append(f"✓ {message}")


@dataclass
class Install:
    tool: str
    started: float
    reporter: RecordingReporter
    thread: threading.Thread | None = None
    error: str | None = None
    finished: float | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    @property
    def elapsed(self) -> float:
        return round((self.finished or time.time()) - self.started, 1)


@dataclass
class BackgroundInstalls:
    paths: SciPatchPaths
    _installs: dict[str, Install] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, tool: str) -> Install:
        """Start installing ``tool`` (by catalog name), or return the install under way."""
        with self._lock:
            current = self._installs.get(tool)
            if current is not None and current.running:
                return current
            install = Install(tool=tool, started=time.time(), reporter=RecordingReporter())
            install.thread = threading.Thread(
                target=self._work, args=(install,), name=f"scipatch-install-{tool}", daemon=True
            )
            self._installs[tool] = install
            install.thread.start()
            return install

    def _work(self, install: Install) -> None:
        from scipatch.app import SciPatch

        try:
            SciPatch(self.paths, reporter=install.reporter).add(install.tool)
        except SciPatchError as exc:
            install.error = str(exc)
        except Exception as exc:  # report anything, the server must keep running
            install.error = f"{type(exc).__name__}: {exc}"
        finally:
            install.finished = time.time()

    def get(self, tool: str) -> Install | None:
        return self._installs.get(tool)
