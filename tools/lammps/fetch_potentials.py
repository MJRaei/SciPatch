"""Download the interatomic potentials listed in potentials.json (run at install).

The files come from the potentials folder of the LAMMPS release the tool uses
(stable_22Jul2025) and are checked against the SHA-256 recorded for each.
"""

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

CATALOG = json.loads(Path(__file__).with_name("potentials.json").read_text())
TARGET = Path(sys.prefix) / "share" / "lammps" / "potentials"


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    entries = CATALOG["potentials"]
    for entry in entries:
        path = TARGET / entry["file"]
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]:
            continue
        url = CATALOG["source"] + entry["file"]
        with urllib.request.urlopen(url, timeout=300) as response:  # noqa: S310 - fixed https URL
            data = response.read()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            sys.exit(
                f"Checksum mismatch for {entry['file']}; the download is incomplete or altered."
            )
        path.write_bytes(data)
    print(f"{len(entries)} potential files in {TARGET}")


if __name__ == "__main__":
    main()
