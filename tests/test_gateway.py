"""The MCP gateway, exercised through an in-memory MCP client."""

from __future__ import annotations

import re
from typing import Any

import anyio
import httpx
import pytest
from mcp import Client
from mcp_types import ElicitResult

from motel import gateway
from motel.app import Motel
from motel.gateway import build_server
from motel.views import preview

from .conftest import ManifestFactory, requires_uv

FUNCTIONS = {
    "add": {},
    "sleep": {"long_running": True},
    "fail": {},
}


def call(motel: Motel, *calls: tuple[str, dict[str, Any]]) -> list[Any]:
    """Run tool calls against a fresh server and return the raw results."""

    async def session() -> list[Any]:
        async with Client(build_server(motel)) as client:
            return [await client.call_tool(name, arguments) for name, arguments in calls]

    return anyio.run(session)


def test_tool_list_is_small_and_fixed(motel: Motel) -> None:
    async def names() -> list[str]:
        async with Client(build_server(motel)) as client:
            return [tool.name for tool in (await client.list_tools()).tools]

    assert anyio.run(names) == [
        "search_history", "find_tools", "list_tools", "describe_tool",
        "install_tool", "run_tool", "get_run", "cancel_run",
    ]  # fmt: skip


def test_empty_motel_gives_helpful_answers(motel: Motel) -> None:
    found, nothing, missing, not_installed = call(
        motel,
        ("find_tools", {"query": "relax a metal"}),
        ("find_tools", {"query": "zebra crossing"}),
        ("describe_tool", {"tool": "x"}),
        ("run_tool", {"tool": "ase-emt", "function": "relax"}),
    )
    assert found.structured_content["matches"] == []
    suggestion = found.structured_content["not_installed"][0]
    assert suggestion["tool"] == "ase-emt" and suggestion["installable_here"]
    assert "install_tool" in found.structured_content["hint"]
    assert "motel onboard" in nothing.structured_content["hint"]
    assert not_installed.is_error
    assert "call install_tool(tool='ase-emt')" in not_installed.content[0].text
    assert missing.is_error
    assert "No tool named 'x'" in missing.content[0].text
    assert "Hint:" in missing.content[0].text


@pytest.mark.integration
@requires_uv
def test_find_describe_run_and_collect(motel: Motel, make_package: ManifestFactory) -> None:
    motel.add(str(make_package(functions=FUNCTIONS)))
    found, described, ran, bad, failed, slow, listed = call(
        motel,
        ("find_tools", {"query": "add numbers"}),
        ("describe_tool", {"tool": "sample"}),
        ("run_tool", {"tool": "sample", "function": "add", "arguments": {"a": 2}}),
        ("run_tool", {"tool": "sample", "function": "add", "arguments": {}}),
        ("run_tool", {"tool": "sample", "function": "fail", "arguments": {"message": "nope"}}),
        ("run_tool", {"tool": "sample", "function": "sleep", "arguments": {"seconds": 0.2}}),
        ("list_tools", {}),
    )
    assert found.structured_content["matches"][0]["function"] == "add"
    description = described.structured_content
    assert [f["name"] for f in description["functions"]] == ["add", "sleep", "fail"]
    assert description["functions"][0]["parameters"]["required"] == ["a"]

    assert ran.structured_content["status"] == "succeeded"
    assert ran.structured_content["result"] == {"sum": 3.0}

    assert bad.is_error
    assert "missing required argument(s): a" in bad.content[0].text

    assert failed.structured_content["status"] == "failed"
    assert failed.structured_content["error"]["message"] == "nope"

    # Long-running functions return immediately, with a way to collect them.
    run = slow.structured_content
    assert run["status"] == "running"
    assert "get_run" in run["next_step"]
    [collected, history] = call(
        motel,
        ("get_run", {"run_id": run["run_id"], "wait_seconds": 30}),
        ("search_history", {"query": "nope"}),
    )
    assert collected.structured_content["status"] == "succeeded"
    assert [r["run_id"] for r in history.structured_content["runs"]] == [
        failed.structured_content["run_id"]
    ]
    assert listed.structured_content["tools"][0]["name"] == "sample"


@pytest.mark.integration
@requires_uv
def test_missing_keys_are_entered_outside_the_chat(
    motel: Motel, make_package: ManifestFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEMO_KEY", raising=False)
    described = {"name": "DEMO_KEY", "description": "Demo service key", "url": "https://x.org"}
    environment = {"manager": "uv", "python": "3.12", "secrets": [described]}
    motel.add(str(make_package(functions=["secret_values"], environment=environment)))
    run = {"tool": "sample", "function": "secret_values", "use_cache": False}

    async def enter_key(context: Any, params: Any) -> ElicitResult:
        """The user agrees to open the page and types the key there."""
        assert params.mode == "url" and "Demo service key" in params.message
        async with httpx.AsyncClient() as http:
            saved = await http.post(params.url, data={"DEMO_KEY": "s3cret"})
        assert "Saved" in saved.text
        return ElicitResult(action="accept")

    async def decline(context: Any, params: Any) -> ElicitResult:
        return ElicitResult(action="decline")

    async def accept_only(context: Any, params: Any) -> ElicitResult:
        return ElicitResult(action="accept")

    def call_with(callback: Any = None, mode: str = "auto") -> Any:
        async def session() -> Any:
            server = build_server(motel)
            async with Client(server, elicitation_callback=callback, mode=mode) as client:
                return await client.call_tool("run_tool", run)

        motel.secrets.remove("DEMO_KEY")
        return anyio.run(session)

    # Apps that cannot open links: the agent gets one to pass on.
    plain = call_with()
    text = plain.content[0].text
    assert plain.is_error
    assert "Demo service key" in text and "Do not ask for the key in the chat" in text
    link = re.search(r"http://127\.0\.0\.1:\d+/keys/\S+", text)
    assert link is not None
    saved = httpx.post(link.group(0), data={"DEMO_KEY": "s3cret"})
    assert saved.status_code == 200 and "Saved" in saved.text
    [ran] = call(motel, ("run_tool", run))
    assert ran.structured_content["result"]["demo"] == "s3cret"

    # Apps that can open the page themselves: the run continues once the key is
    # saved, with the 2026-07-28 protocol (InputRequiredResult) and with older ones.
    for mode in ("auto", "legacy"):
        result = call_with(enter_key, mode)
        assert not result.is_error, (mode, result.content)
        assert result.structured_content["result"]["demo"] == "s3cret"

    # When the user declines or never enters the key, the agent still gets a link.
    declined = call_with(decline)
    assert declined.is_error and "did not open the page" in declined.content[0].text
    monkeypatch.setattr(gateway, "KEY_WAIT_SECONDS", 0.5)
    late = call_with(accept_only, "legacy")
    assert late.is_error and "not entered in time" in late.content[0].text
    assert "/keys/" in late.content[0].text


def test_preview_truncates_large_results() -> None:
    value, cut = preview({"values": list(range(500)), "text": "x" * 10_000, "n": 1})
    assert cut
    assert len(value["values"]) == 101
    assert value["values"][-1] == "... [400 more items]"
    assert value["text"].endswith("[6000 more characters]")
    assert value["n"] == 1
    assert preview({"a": [1, 2]}) == ({"a": [1, 2]}, False)


@pytest.mark.integration
@requires_uv
def test_tools_can_be_installed_from_the_ai_app(motel: Motel) -> None:
    started, unknown = call(
        motel,
        ("install_tool", {"tool": "ase-emt", "wait_seconds": 600}),
        ("install_tool", {"tool": "no-such-tool"}),
    )
    assert started.structured_content["status"] == "ready", started.structured_content
    assert motel.tool("ase-emt").usable
    assert unknown.is_error and "No catalog has a tool named" in unknown.content[0].text
    (again,) = call(motel, ("install_tool", {"tool": "ase-emt"}))
    assert again.structured_content["status"] == "ready"


@pytest.mark.integration
@requires_uv
def test_a_long_install_is_collected_by_calling_again(motel: Motel) -> None:
    server = build_server(motel)

    async def install_twice() -> tuple[Any, Any]:
        async with Client(server) as client:
            first = await client.call_tool(
                "install_tool", {"tool": "rdkit-descriptors", "wait_seconds": 0}
            )
            second = await client.call_tool(
                "install_tool", {"tool": "rdkit-descriptors", "wait_seconds": 600}
            )
            return first, second

    first, second = anyio.run(install_twice)
    assert first.structured_content["status"] == "installing"
    assert first.structured_content["next_step"].startswith("Call install_tool")
    assert second.structured_content["status"] == "ready", second.structured_content
