"""Install the official Windows build of AutoDock Vina (run at install).

conda-forge has no Windows build of vina, so on Windows the program comes from
the official release (github.com/ccsb-scripps/AutoDock-Vina, v1.2.7; a single
statically linked executable), checked against the SHA-256 recorded here. On
Linux and macOS the conda-forge vina package provides the program, and this
script does nothing.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

URL = "https://github.com/ccsb-scripps/AutoDock-Vina/releases/download/v1.2.7/vina_1.2.7_win.exe"
SHA256 = "e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5"


def install(target: Path) -> None:
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == SHA256:
        return
    with urllib.request.urlopen(URL, timeout=300) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        sys.exit(
            "The downloaded vina.exe does not match its checksum; it is incomplete or altered."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"Installed AutoDock Vina 1.2.7 at {target}")


if __name__ == "__main__":
    if sys.platform == "win32":
        install(Path(sys.prefix) / "Library" / "bin" / "vina.exe")
