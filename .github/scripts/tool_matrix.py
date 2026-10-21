"""Print the CI matrix for the given tools: one job per tool and supported runner.

A tool's motel.lock says which platforms it can be installed on; tools without
a lock are checked on every runner. A tool with Linux packages but no Windows
ones is checked on Windows inside WSL, as Motel runs it there.
"""

import json
import sys
from pathlib import Path

RUNNERS = {"linux-64": "ubuntu-latest", "osx-arm64": "macos-latest", "win-64": "windows-latest"}

include = []
for tool in sys.argv[1:]:
    lock = Path("tools") / tool / "motel.lock"
    platforms = json.loads(lock.read_text())["platforms"] if lock.is_file() else {}
    for platform, runner in RUNNERS.items():
        if not platforms.get(platform, {}).get("unavailable"):
            include.append({"tool": tool, "os": runner, "wsl": False})
        elif platform == "win-64" and not platforms.get("linux-64", {}).get("unavailable"):
            include.append({"tool": tool, "os": runner, "wsl": True})
print(json.dumps({"include": include}))
