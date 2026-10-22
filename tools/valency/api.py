"""Scientific literature through Valency's MCP Bond.

Needs a Valency bearer token from the Settings page at https://app.valency.io
(stored once with `scipatch secret set VALENCY_API_TOKEN`).
"""

from __future__ import annotations

import json
import os

_URL = "https://mcp.valency.io/"
_PROTOCOL = "2025-11-25"
_TOKEN_URL = "https://app.valency.io"


class _Bond:
    """A minimal MCP client for Bond: Streamable HTTP, bearer token, JSON-RPC."""

    def __init__(self) -> None:
        import httpx

        token = os.environ.get("VALENCY_API_TOKEN")
        if not token:
            raise ValueError(
                f"VALENCY_API_TOKEN is not set. Copy your token from Settings at {_TOKEN_URL}."
            )
        self._http = httpx.Client(
            timeout=httpx.Timeout(120.0, connect=15.0),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
        )
        self._next_id = 0
        result = self._request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "scipatch-valency", "version": "0.1.0"},
            },
        )
        self._http.headers["MCP-Protocol-Version"] = result.get("protocolVersion", _PROTOCOL)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def __enter__(self) -> _Bond:
        return self

    def __exit__(self, *exc) -> None:
        self._http.close()

    def _post(self, message: dict):
        response = self._http.post(_URL, json=message)
        if response.status_code in (401, 403):
            raise ValueError(
                f"Valency rejected the token. Copy it again from Settings at {_TOKEN_URL} and "
                "store it with 'scipatch secret set VALENCY_API_TOKEN'."
            )
        response.raise_for_status()
        if session := response.headers.get("mcp-session-id"):
            self._http.headers["Mcp-Session-Id"] = session
        return response

    def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        response = self._post(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        )
        message = _response_message(response, self._next_id)
        if "error" in message:
            raise RuntimeError(f"Valency: {message['error'].get('message', message['error'])}")
        return message["result"]

    def tools(self) -> list[dict]:
        return self._request("tools/list", {})["tools"]

    def call(self, tool: str, arguments: dict):
        """Call a Bond tool; its structured content, or its text parsed as JSON when possible."""
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
        if result.get("isError"):
            raise ValueError(f"Valency: {text or 'the call failed'}")
        if "structuredContent" in result:
            return result["structuredContent"]
        try:
            return json.loads(text)
        except ValueError:
            return text


def _response_message(response, request_id: int) -> dict:
    """The JSON-RPC reply to ``request_id``, from a JSON body or an event stream."""
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                message = json.loads(line[5:])
                if message.get("id") == request_id:
                    return message
        raise RuntimeError("Valency closed the stream without a reply.")
    return response.json()
