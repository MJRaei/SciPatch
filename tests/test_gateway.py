"""The MCP gateway, exercised through an in-memory MCP client."""

from __future__ import annotations

import re
from typing import Any

import anyio
import httpx
import pytest
from mcp import Client, MCPError
from mcp_types import URL_ELICITATION_REQUIRED

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
        "run_tool", "get_run", "cancel_run",
    ]  # fmt: skip


def test_empty_motel_gives_helpful_answers(motel: Motel) -> None:
    found, missing = call(
        motel, ("find_tools", {"query": "relax"}), ("describe_tool", {"tool": "x"})
    )
    assert found.structured_content["matches"] == []
    assert "motel onboard" in found.structured_content["hint"]
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
    run = {"tool": "sample", "function": "secret_values"}

    async def never_called(context: Any, params: Any) -> Any:
        raise AssertionError("URL elicitation is requested through the error, not a request")

    async def session() -> tuple[Any, MCPError]:
        server = build_server(motel)
        async with Client(server) as plain:
            asked = await plain.call_tool("run_tool", run)
        # Passing an elicitation callback declares support for URL elicitation.
        async with Client(server, elicitation_callback=never_called) as capable:
            with pytest.raises(MCPError) as raised:
                await capable.call_tool("run_tool", run)
        return asked, raised.value

    asked, required = anyio.run(session)
    # Apps that cannot open links get one for the agent to pass on.
    text = asked.content[0].text
    assert asked.is_error
    assert "Demo service key" in text and "Do not ask for the key in the chat" in text
    match = re.search(r"http://127\.0\.0\.1:\d+/keys/\S+", text)
    assert match is not None
    # Apps that can are asked to open the page themselves.
    assert required.code == URL_ELICITATION_REQUIRED
    [elicitation] = required.data["elicitations"]
    assert elicitation["mode"] == "url"
    assert elicitation["url"].startswith("http://127.0.0.1:")
    assert elicitation["url"] != match.group(0)  # every link is new and single-use

    # The user enters the key on the page, and the next run has it.
    saved = httpx.post(match.group(0), data={"DEMO_KEY": "s3cret"})
    assert saved.status_code == 200 and "Saved" in saved.text
    [ran] = call(motel, ("run_tool", run))
    assert ran.structured_content["result"]["demo"] == "s3cret"


def test_preview_truncates_large_results() -> None:
    value, cut = preview({"values": list(range(500)), "text": "x" * 10_000, "n": 1})
    assert cut
    assert len(value["values"]) == 101
    assert value["values"][-1] == "... [400 more items]"
    assert value["text"].endswith("[6000 more characters]")
    assert value["n"] == 1
    assert preview({"a": [1, 2]}) == ({"a": [1, 2]}, False)
