from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from motel.history import RunStore, new_run_id
from motel.models import RunRecord, RunStatus


def record(run_id: str, *, tool: str = "ase-emt", minutes: int = 0, **fields: object) -> RunRecord:
    started = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes)
    return RunRecord(
        id=run_id,
        tool=tool,
        function=str(fields.pop("function", "relax")),
        args=fields.pop("args", {"element": "Cu"}),  # type: ignore[arg-type]
        workdir="/tmp/w",
        run_dir="/tmp/r",
        started_at=started,
        **fields,  # type: ignore[arg-type]
    )


def test_run_ids_are_sortable_and_unique() -> None:
    first = new_run_id(datetime(2026, 10, 18, 11, 45, 1))
    assert re.fullmatch(r"20261018-114501-[0-9a-f]{6}", first)
    assert len({new_run_id() for _ in range(200)}) == 200


def test_insert_get_and_finish(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "motel.db")
    store.insert(record("r1"))
    loaded = store.get("r1")
    assert loaded is not None
    assert loaded.status is RunStatus.RUNNING
    assert loaded.args == {"element": "Cu"}

    finished = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    assert store.finish(
        "r1",
        status=RunStatus.SUCCEEDED,
        result={"energy": -1.5},
        files=["/tmp/w/out.cif"],
        finished_at=finished,
        duration=60.0,
    )
    # A second finish (e.g. a concurrent observer) does not overwrite the first.
    assert not store.finish("r1", status=RunStatus.FAILED, finished_at=finished, duration=1.0)
    done = store.get("r1")
    assert done is not None
    assert done.status is RunStatus.SUCCEEDED
    assert done.result == {"energy": -1.5}
    assert done.files == ["/tmp/w/out.cif"]
    assert done.finished_at == finished
    assert store.get("missing") is None


def test_list_filters_and_searches(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "motel.db")
    store.insert(record("a", minutes=1, args={"element": "Cu"}))
    store.insert(record("b", minutes=2, args={"element": "Au"}, function="equation_of_state"))
    store.insert(record("c", minutes=3, tool="rdkit-descriptors", args={"smiles": "CCO"}))
    store.insert(record("d", minutes=4, args={"element": "100%_pure"}))

    assert [r.id for r in store.query()] == ["d", "c", "b", "a"]  # newest first
    assert [r.id for r in store.query(limit=2)] == ["d", "c"]
    assert [r.id for r in store.query(tool="rdkit-descriptors")] == ["c"]
    assert [r.id for r in store.query(query="Au equation")] == ["b"]
    assert [r.id for r in store.query(query="CCO")] == ["c"]
    # LIKE wildcards in the query are matched literally.
    assert [r.id for r in store.query(query="100%_")] == ["d"]
    assert store.query(query="Fe") == []
    assert len(store.running()) == 4
    assert store.count() == 4


def test_cache_lookup_returns_newest_success(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "motel.db")
    store.insert(record("old", minutes=1, cache_key="k"))
    store.insert(record("new", minutes=2, cache_key="k"))
    store.insert(record("failed", minutes=3, cache_key="k"))
    for run_id in ("old", "new"):
        store.finish(run_id, status=RunStatus.SUCCEEDED, finished_at=datetime.now(UTC), duration=1)
    store.finish("failed", status=RunStatus.FAILED, finished_at=datetime.now(UTC), duration=1)
    cached = store.find_cached("k")
    assert cached is not None
    assert cached.id == "new"
    assert store.find_cached("other") is None


def test_database_reopens_without_remigrating(tmp_path: Path) -> None:
    path = tmp_path / "motel.db"
    RunStore(path).insert(record("a"))
    assert RunStore(path).count() == 1
