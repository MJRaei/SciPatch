"""Download AiZynthFinder's public models and stock into the tool environment (run at install).

The files and sources are those of AiZynthFinder's own download_public_data: the
USPTO expansion, ring-breaker, and filter policies (ONNX, doi:10.5281/zenodo.7797465),
their reaction templates (doi:10.5281/zenodo.7341155), and the ZINC stock of
purchasable compounds (doi:10.6084/m9.figshare.12334577), each checked against the
MD5 checksum its archive publishes. The stock is then stored as a sorted array of
InChIKeys, which the tool memory-maps instead of loading 17 million keys into a set.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

TARGET = Path(sys.prefix) / "share" / "aizynthfinder"
STOCK_KEYS = TARGET / "zinc_stock_inchikeys.npy"
STOCK_SIZE = 17_422_831
FILES = {
    "uspto_model.onnx": (
        "https://zenodo.org/records/7797465/files/uspto_model.onnx",
        "b466a436b6a8eceaba8c14ef5e2a88c8",
    ),
    "uspto_templates.csv.gz": (
        "https://zenodo.org/records/7341155/files/uspto_unique_templates.csv.gz",
        "e8fb29d4dcd54073658000e212b7845a",
    ),
    "uspto_ringbreaker_model.onnx": (
        "https://zenodo.org/records/7797465/files/uspto_ringbreaker_model.onnx",
        "2aa7ee99d29a910369e723a73fc13044",
    ),
    "uspto_ringbreaker_templates.csv.gz": (
        "https://zenodo.org/records/7341155/files/uspto_ringbreaker_unique_templates.csv.gz",
        "a6d0117ee6122e2cca3b7f8efa35541d",
    ),
    "uspto_filter_model.onnx": (
        "https://zenodo.org/records/7797465/files/uspto_filter_model.onnx",
        "ab0df54b62a0aeceecd68051f8dc3f2e",
    ),
    "zinc_stock.hdf5": (
        "https://ndownloader.figshare.com/files/23086469",
        "00de71724ec1d4a8463c1b0d8a5d0941",
    ),
}


def md5(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - the archives publish MD5
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(name: str, url: str, checksum: str) -> None:
    path = TARGET / name
    if path.exists() and md5(path) == checksum:
        return
    print(f"Downloading {name} ...", flush=True)
    partial = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(url, timeout=600) as response, open(partial, "wb") as out:  # noqa: S310
        while block := response.read(1 << 20):
            out.write(block)
    if md5(partial) != checksum:
        partial.unlink()
        sys.exit(f"Checksum mismatch for {name}; the download is incomplete or altered.")
    partial.replace(path)


def stock_ready() -> bool:
    return STOCK_KEYS.exists() and len(np.load(STOCK_KEYS, mmap_mode="r")) == STOCK_SIZE


def convert_stock() -> None:
    source = TARGET / "zinc_stock.hdf5"
    keys = pd.read_hdf(source, key="table")["inchi_key"].to_numpy().astype("S27")
    keys = np.unique(keys)  # sorted, for binary search
    if len(keys) != STOCK_SIZE:
        sys.exit(f"The ZINC stock has {len(keys)} InChIKeys, expected {STOCK_SIZE}.")
    np.save(STOCK_KEYS, keys)
    source.unlink()


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, (url, checksum) in FILES.items():
        if name == "zinc_stock.hdf5" and stock_ready():
            continue
        download(name, url, checksum)
    if not stock_ready():
        convert_stock()
    print(f"AiZynthFinder data installed in {TARGET}")


if __name__ == "__main__":
    main()
