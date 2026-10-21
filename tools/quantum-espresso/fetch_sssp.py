"""Download the SSSP pseudopotential library into the tool environment (run at install).

SSSP 1.3.0 PBE efficiency, from the Materials Cloud Archive record of version 1.3
(doi:10.24435/materialscloud:f3-ym), checked against its published MD5 checksums.
"""

import hashlib
import sys
import tarfile
import urllib.request
from pathlib import Path

RECORD = "https://archive.materialscloud.org/api/records/rcyfm-68h65/files"
FILES = {
    "SSSP_1.3.0_PBE_efficiency.tar.gz": "a58f1b3373f330179fd0832c48bb9a52",
    "SSSP_1.3.0_PBE_efficiency.json": "3153c4b20fc90a44fba0236627525644",
}
TARGET = Path(sys.prefix) / "share" / "sssp"


def download(name: str, checksum: str) -> Path:
    path = TARGET / name
    if path.exists() and hashlib.md5(path.read_bytes()).hexdigest() == checksum:  # noqa: S324
        return path
    print(f"Downloading {name} ...", flush=True)
    with urllib.request.urlopen(f"{RECORD}/{name}/content", timeout=600) as response:  # noqa: S310
        data = response.read()
    if hashlib.md5(data).hexdigest() != checksum:  # noqa: S324 - the archive publishes MD5
        sys.exit(f"Checksum mismatch for {name}; the download is incomplete or altered.")
    path.write_bytes(data)
    return path


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    archive = download(
        "SSSP_1.3.0_PBE_efficiency.tar.gz", FILES["SSSP_1.3.0_PBE_efficiency.tar.gz"]
    )
    download("SSSP_1.3.0_PBE_efficiency.json", FILES["SSSP_1.3.0_PBE_efficiency.json"])
    pseudos = TARGET / "pseudos"
    pseudos.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name.lower().endswith(".upf"):
                member.name = Path(member.name).name  # flatten; never write outside the folder
                tar.extract(member, pseudos, filter="data")
    archive.unlink()
    print(f"SSSP installed: {len(list(pseudos.glob('*')))} pseudopotentials in {pseudos}")


if __name__ == "__main__":
    main()
