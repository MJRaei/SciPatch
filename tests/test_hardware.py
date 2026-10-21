"""Hardware needs: what tools declare, what this computer has, and how they fit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from motel import hardware
from motel.app import Motel
from motel.cli import app
from motel.errors import BuildError, RunError
from motel.hardware import Gpu, Machine, assess, describe_needs, parse_nvidia_smi
from motel.manifest import DEFAULT_RESOURCES, Manifest, Resources
from motel.settings import Settings
from motel.views import tool_view

from .conftest import ManifestFactory, requires_uv

NVIDIA = Machine(16, 64, (Gpu("cuda", "NVIDIA RTX 4090", 24.0),))
APPLE = Machine(8, 16, (Gpu("mps", "Apple M2 GPU", 16, shared=True),))
NO_GPU = Machine(4, 8)

GPU_API = '''
import os


def device() -> str:
    """Report the device Motel chose for this run."""
    return os.environ.get("MOTEL_DEVICE", "unset")


def train() -> str:
    """Pretend to train a model on a GPU."""
    return os.environ.get("MOTEL_DEVICE", "unset")
'''


def needs(**fields: Any) -> Resources:
    return Resources(**fields).over(DEFAULT_RESOURCES)


def test_nvidia_smi_output_is_parsed() -> None:
    output = "NVIDIA GeForce RTX 4090, 24564\nNVIDIA A100-SXM4-80GB, 81920\n"
    gpus = parse_nvidia_smi(output)
    assert [(gpu.kind, gpu.name, gpu.memory_gb) for gpu in gpus] == [
        ("cuda", "NVIDIA GeForce RTX 4090", 24.0),
        ("cuda", "NVIDIA A100-SXM4-80GB", 80.0),
    ]
    assert parse_nvidia_smi("") == []


def test_functions_inherit_the_tool_needs_unless_they_say_otherwise() -> None:
    manifest = Manifest.model_validate(
        {
            "name": "trainer",
            "summary": "Train and apply a model.",
            "resources": {"gpu": "optional", "network": True},
            "functions": {
                "train": {"resources": {"gpu": "required", "memory_gb": 32}},
                "apply": {},
            },
        }
    )
    assert manifest.resources_for() == needs(gpu="optional", network=True)
    assert manifest.resources_for("apply") == manifest.resources_for()
    assert manifest.resources_for("train") == needs(gpu="required", memory_gb=32, network=True)
    assert Manifest(name="plain", summary="Nothing special.").resources_for() == DEFAULT_RESOURCES


def test_a_required_gpu_blocks_without_one_and_is_used_with_one() -> None:
    required = needs(gpu="required", gpu_memory_gb=40)
    assert assess(required, NO_GPU, use_gpu=False).blockers == [
        "needs an NVIDIA GPU (CUDA); this computer has none"
    ]
    on_mac = assess(required, APPLE, use_gpu=True)
    assert on_mac.blockers == [
        "needs an NVIDIA GPU (CUDA); this computer has none that it can use (it has the "
        "Apple M2 GPU)"
    ]
    fit = assess(required, NVIDIA, use_gpu=False)  # required: used whatever the setting
    assert fit.device == "cuda" and not fit.blockers
    assert fit.warnings == ["needs 40 GB of GPU memory; NVIDIA RTX 4090 has 24 GB"]


def test_an_optional_gpu_is_used_only_when_the_user_allows_it() -> None:
    optional = needs(gpu="optional", gpu_types=["cuda", "mps"])
    off = assess(optional, APPLE, use_gpu=False)
    assert off.device == "cpu" and "motel config gpu on" in off.notes[0]
    assert assess(optional, APPLE, use_gpu=True).device == "mps"
    cuda_only = assess(needs(gpu="optional"), APPLE, use_gpu=True)
    assert cuda_only.device == "cpu" and "would make it faster" in cuda_only.notes[0]


def test_short_memory_is_a_warning() -> None:
    fit = assess(needs(memory_gb=32, network=True), NO_GPU, use_gpu=False)
    assert fit.warnings == [
        "32 GB of memory recommended; this computer has 8 GB (try smaller inputs first)"
    ]
    assert fit.notes == []
    assert describe_needs(needs(gpu="optional", memory_gb=32, network=True)) == [
        "faster with an NVIDIA GPU (CUDA)",
        "32 GB of memory recommended",
        "an internet connection",
    ]
    assert describe_needs(DEFAULT_RESOURCES) == []


def test_folder_sizes_are_measured(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "a.bin").write_bytes(b"0" * 1024**2)
    (tmp_path / "b.bin").write_bytes(b"0" * 1024**2)
    assert hardware.folder_size_mb(tmp_path) == 2.0
    assert hardware.folder_size_mb(tmp_path / "missing") is None


def test_tools_that_require_a_missing_gpu_are_not_installed(
    motel: Motel, make_package: ManifestFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hardware, "detect", lambda: NO_GPU)
    package = make_package("big-model", api=GPU_API, resources={"gpu": "required"})
    with pytest.raises(BuildError, match=r"needs an NVIDIA GPU \(CUDA\); this computer has none"):
        motel.add(str(package))
    assert not motel.registry.exists("big-model")


@pytest.mark.integration
@requires_uv
def test_runs_get_a_device_and_gpu_only_functions_are_refused_without_one(
    motel: Motel, make_package: ManifestFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hardware, "detect", lambda: NO_GPU)
    package = make_package(
        "trainer",
        api=GPU_API,
        resources={"gpu": "optional"},
        functions={"device": {}, "train": {"resources": {"gpu": "required"}}},
    )
    motel.add(str(package))
    assert motel.run("trainer", "device", wait=60).result == "cpu"
    with pytest.raises(RunError, match=r"'trainer.train' cannot run on this computer"):
        motel.run("trainer", "train")
    resources = tool_view(motel.tool("trainer"))["resources"]
    assert resources["needs"] == ["faster with an NVIDIA GPU (CUDA)"]
    assert resources["functions"]["train"]["cannot_run_here"][0].startswith("needs an NVIDIA GPU")
    assert resources["disk_space"].endswith("for its environment, plus files it downloads")

    monkeypatch.setattr(hardware, "detect", lambda: NVIDIA)
    assert motel.run("trainer", "device", wait=60, use_cache=False).result == "cpu"
    Settings(motel.paths.config).set("gpu", True)
    assert motel.run("trainer", "device", wait=60, use_cache=False).result == "cuda"
    assert motel.run("trainer", "train", wait=60).result == "cuda"


def test_gpu_use_is_a_setting() -> None:
    runner = CliRunner()
    shown = runner.invoke(app, ["config"])
    assert shown.exit_code == 0 and "gpu off" in shown.output and "This computer:" in shown.output
    assert runner.invoke(app, ["config", "gpu", "on"]).exit_code == 0
    assert Settings(Motel().paths.config).use_gpu
    assert runner.invoke(app, ["config", "gpu", "maybe"]).exit_code != 0
    assert runner.invoke(app, ["config", "speed", "on"]).exit_code != 0
