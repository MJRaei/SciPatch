"""The one-time page where users enter API keys, outside the chat."""

from __future__ import annotations

import http.client
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import pytest

from motel import keypage
from motel.keypage import KeyPage
from motel.manifest import Secret
from motel.secrets import SecretStore

DEMO = Secret(name="DEMO_KEY", description="Demo service API key", url="https://example.org/key")


@pytest.fixture
def page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[KeyPage]:
    for name in ("DEMO_KEY", "OTHER_KEY"):
        monkeypatch.delenv(name, raising=False)
    page = KeyPage(SecretStore(tmp_path / "secrets.json"))
    yield page
    page.close()


def fetch(
    url: str, *, form: dict[str, str] | None = None, headers: dict[str, str] | None = None
) -> tuple[int, str, http.client.HTTPMessage]:
    """GET the page, or POST ``form`` to it, like a browser would."""
    parts = urlsplit(url)
    connection = http.client.HTTPConnection(parts.hostname or "", parts.port, timeout=5)
    sent = {"Content-Type": "application/x-www-form-urlencoded"} if form is not None else {}
    sent.update(headers or {})
    method = "GET" if form is None else "POST"
    body = None if form is None else urlencode(form)
    try:
        connection.request(method, parts.path, body=body, headers=sent)
        response = connection.getresponse()
        return response.status, response.read().decode(), response.headers
    finally:
        connection.close()


def test_a_link_stores_a_key_once(page: KeyPage) -> None:
    url = page.link("demo-tool", [DEMO])
    assert url.startswith("http://127.0.0.1:")
    status, html, headers = fetch(url)
    assert status == 200
    assert "Demo service API key" in html
    assert 'name="DEMO_KEY"' in html and 'type="password"' in html
    assert 'href="https://example.org/key"' in html
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store"

    status, html, _ = fetch(url, form={"DEMO_KEY": "  s3cret  "})
    assert status == 200
    assert "Saved" in html and "s3cret" not in html
    assert page.store.resolve(["DEMO_KEY"]) == {"DEMO_KEY": "s3cret"}

    # The link is used up: it can neither show the form nor change the key again.
    assert fetch(url)[0] == 404
    assert fetch(url, form={"DEMO_KEY": "replaced"})[0] == 404
    assert page.store.resolve(["DEMO_KEY"]) == {"DEMO_KEY": "s3cret"}


def test_every_requested_key_is_needed(page: KeyPage) -> None:
    url = page.link("demo-tool", [DEMO, Secret(name="OTHER_KEY")])
    status, html, _ = fetch(url, form={"DEMO_KEY": "a", "OTHER_KEY": ""})
    assert status == 200 and "Please fill in every key" in html
    assert 'name="OTHER_KEY"' in html and 'name="DEMO_KEY"' not in html
    assert "Saved" in fetch(url, form={"OTHER_KEY": "b"})[1]
    assert page.store.resolve(["DEMO_KEY", "OTHER_KEY"]) == {"DEMO_KEY": "a", "OTHER_KEY": "b"}


def test_only_this_computer_and_the_page_itself_are_answered(page: KeyPage) -> None:
    url = page.link("demo-tool", [DEMO])
    port = urlsplit(url).port
    assert fetch(url, headers={"Host": "attacker.example"})[0] == 403  # DNS rebinding
    other_site = {"Origin": "http://attacker.example"}
    assert fetch(url, form={"DEMO_KEY": "x"}, headers=other_site)[0] == 403
    assert fetch(url + "x")[0] == 404  # a guessed token
    assert page.store.names() == []
    assert fetch(url, headers={"Host": f"localhost:{port}"})[0] == 200


def test_links_expire(page: KeyPage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keypage, "LINK_LIFETIME_SECONDS", 0)
    url = page.link("demo-tool", [DEMO])
    status, html, _ = fetch(url)
    assert status == 404 and "expired" in html
    assert fetch(url, form={"DEMO_KEY": "x"})[0] == 404
    assert page.store.names() == []


def test_text_from_manifests_cannot_inject_markup(page: KeyPage) -> None:
    sneaky = Secret(name="DEMO_KEY", description="<script>alert(1)</script>", url="javascript:x")
    _, html, _ = fetch(page.link("<b>tool</b>", [sneaky]))
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert 'href="javascript' not in html
    assert "<b>tool</b>" not in html
