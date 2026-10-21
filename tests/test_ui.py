"""The local dashboard's API, including its protections."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from motel.app import Motel
from motel.ui import TOKEN_HEADER, create_app

from .conftest import ManifestFactory, requires_uv

TOKEN = "test-token"  # noqa: S105 - a fixed token for tests


@pytest.fixture
def client(motel: Motel) -> TestClient:
    app = create_app(motel, TOKEN, allowed_hosts=["testserver"])
    return TestClient(app, headers={TOKEN_HEADER: TOKEN})


def test_page_is_served_without_token(motel: Motel) -> None:
    client = TestClient(create_app(motel, TOKEN, allowed_hosts=["testserver"]))
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>Motel</title>" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_api_requires_the_session_token(motel: Motel) -> None:
    app = create_app(motel, TOKEN, allowed_hosts=["testserver"])
    assert TestClient(app).get("/api/tools").status_code == 403
    wrong = TestClient(app, headers={TOKEN_HEADER: "guess"})
    assert wrong.get("/api/tools").status_code == 403
    assert wrong.post("/api/run", json={"tool": "x", "function": "y"}).status_code == 403


def test_unknown_hosts_are_rejected(motel: Motel) -> None:
    """Protects against DNS rebinding: only local host names are served."""
    client = TestClient(create_app(motel, TOKEN), headers={TOKEN_HEADER: TOKEN})
    assert client.get("/api/tools", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/tools", headers={"host": "127.0.0.1"}).status_code == 200


def test_errors_are_json_with_hints(client: TestClient) -> None:
    missing = client.get("/api/tools/nope")
    assert missing.status_code == 404
    assert "No tool named 'nope'" in missing.json()["error"]
    assert client.get("/api/runs/20260101-000000-000000").status_code == 404


def test_keys_can_be_set_and_removed_but_never_read(
    client: TestClient, motel: Motel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEMO_KEY", raising=False)
    assert client.get("/api/secrets").json() == []
    saved = client.post("/api/secrets", json={"name": "DEMO_KEY", "value": " s3cret "})
    assert saved.status_code == 200
    assert saved.json() == [
        {"name": "DEMO_KEY", "description": None, "get_one_at": None, "used_by": [],
         "source": "stored"},
    ]  # fmt: skip
    assert "s3cret" not in saved.text
    assert motel.secrets.resolve(["DEMO_KEY"]) == {"DEMO_KEY": "s3cret"}
    bad = client.post("/api/secrets", json={"name": "bad name", "value": "x"})
    assert bad.status_code == 400 and "not a valid secret name" in bad.json()["error"]
    assert client.delete("/api/secrets/DEMO_KEY").json() == []
    assert motel.secrets.names() == []


def test_upload_stores_files_with_safe_names(client: TestClient, motel: Motel) -> None:
    response = client.post("/api/upload", files={"file": ("../../evil name.cif", b"data_x")})
    assert response.status_code == 200
    path = response.json()["path"]
    assert path.startswith(str(motel.paths.home / "uploads"))
    assert path.endswith("evil_name.cif")
    assert Path(path).read_bytes() == b"data_x"


@pytest.mark.integration
@requires_uv
def test_run_and_collect_through_the_dashboard(
    client: TestClient, motel: Motel, make_package: ManifestFactory
) -> None:
    motel.add(str(make_package(functions=["add", "write_text", "sleep"])))
    assert [t["name"] for t in client.get("/api/tools").json()] == ["sample"]
    assert client.get("/api/find", params={"q": "add numbers"}).json()[0]["function"] == "add"

    run = client.post(
        "/api/run", json={"tool": "sample", "function": "write_text", "arguments": {"text": "hi"}}
    ).json()
    assert run["status"] == "succeeded"
    download = client.get(f"/api/runs/{run['run_id']}/files/0")
    assert download.status_code == 200
    assert download.content == b"hi"
    assert client.get(f"/api/runs/{run['run_id']}/files/7").status_code == 404

    bad = client.post("/api/run", json={"tool": "sample", "function": "add", "arguments": {}})
    assert bad.status_code == 400
    assert "missing required argument" in bad.json()["error"]

    slow = client.post(
        "/api/run", json={"tool": "sample", "function": "sleep", "arguments": {"seconds": 60}}
    ).json()
    assert slow["status"] == "running"
    started = time.monotonic()
    cancelled = client.post(f"/api/runs/{slow['run_id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert time.monotonic() - started < 10
    statuses = {r["status"] for r in client.get("/api/runs").json()}
    assert statuses == {"succeeded", "cancelled"}
