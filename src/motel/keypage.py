"""A one-time page on this computer where the user types an API key.

API keys must never pass through an AI app's chat: they would be sent to the
model and kept in the conversation. Desktop apps cannot ask for them either, so
when a run needs a key that is not set, the gateway gives the app a link to
this page instead (and asks the app to open it, where the app supports that).
The gateway serves the page on 127.0.0.1, and only while it is needed.

Each link:

* works once, and only for ``LINK_LIFETIME_SECONDS``;
* can only *store* the secrets it was made for, and never shows a stored value;
* is refused unless the browser asks for a local host name (against DNS rebinding).
"""

from __future__ import annotations

import html
import secrets
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from motel.manifest import Secret
from motel.secrets import SecretStore

LINK_LIFETIME_SECONDS = 30 * 60
MAX_FORM_BYTES = 64 * 1024
_PATH_PREFIX = "/keys/"
_HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
    # Keeps the link out of the Referer header when the user follows "Get one at".
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
}


@dataclass
class _Request:
    tool: str
    secrets: list[Secret]
    expires: float


class KeyPage:
    """Serves one-time links where the user enters secrets for a tool."""

    def __init__(self, store: SecretStore, *, host: str = "127.0.0.1") -> None:
        self.store = store
        self.host = host
        self._pending: dict[str, _Request] = {}
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._port = 0

    def link(self, tool: str, needed: list[Secret]) -> str:
        """A new one-time URL where the user can enter ``needed`` for ``tool``."""
        port = self._start()
        token = secrets.token_urlsafe(24)
        with self._lock:
            now = time.monotonic()
            self._pending = {k: v for k, v in self._pending.items() if v.expires > now}
            self._pending[token] = _Request(tool, list(needed), now + LINK_LIFETIME_SECONDS)
        return f"http://{self.host}:{port}{_PATH_PREFIX}{token}"

    def close(self) -> None:
        with self._lock:
            server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

    def _start(self) -> int:
        with self._lock:
            if self._server is None:
                server = ThreadingHTTPServer((self.host, 0), _handler(self))
                server.daemon_threads = True
                thread = threading.Thread(
                    target=server.serve_forever, name="motel-key-page", daemon=True
                )
                thread.start()
                self._server = server
                self._port = int(server.server_address[1])
            return self._port

    def _find(self, token: str) -> _Request | None:
        with self._lock:
            request = self._pending.get(token)
            return request if request and request.expires > time.monotonic() else None

    def _save(self, token: str, form: dict[str, list[str]]) -> tuple[_Request, list[Secret]] | None:
        """Store the submitted values; return the request and what is still missing."""
        request = self._find(token)
        if request is None:
            return None
        for secret in request.secrets:
            value = (form.get(secret.name) or [""])[0].strip()
            if value:
                self.store.set(secret.name, value)
        available = self.store.resolve(s.name for s in request.secrets)
        missing = [s for s in request.secrets if s.name not in available]
        if not missing:
            with self._lock:
                self._pending.pop(token, None)
        return request, missing


def _handler(page: KeyPage) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "motel"
        sys_version = ""

        def log_message(self, format: str, *args: object) -> None:
            """Stay quiet: request lines contain the one-time token."""

        def do_GET(self) -> None:
            if not self._local():
                return
            request = page._find(self._token())
            if request is None:
                self._send(HTTPStatus.NOT_FOUND, _expired_page())
            else:
                self._send(HTTPStatus.OK, _form_page(request.tool, request.secrets))

        def do_POST(self) -> None:
            if not self._local():
                return
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"http://{self.headers.get('Host')}":
                self._send(HTTPStatus.FORBIDDEN, _page("Not allowed", "<p>Wrong origin.</p>"))
                return
            length = int(self.headers.get("Content-Length") or 0) if self._sized() else -1
            if not 0 <= length <= MAX_FORM_BYTES:
                self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, _page("Too large", ""))
                return
            form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            outcome = page._save(self._token(), form)
            if outcome is None:
                self._send(HTTPStatus.NOT_FOUND, _expired_page())
                return
            request, missing = outcome
            if missing:
                note = "Please fill in every key below."
                self._send(HTTPStatus.OK, _form_page(request.tool, missing, note))
            else:
                self._send(HTTPStatus.OK, _saved_page(request.tool))

        def _sized(self) -> bool:
            return (self.headers.get("Content-Length") or "0").isdigit()

        def _token(self) -> str:
            path = self.path.split("?", 1)[0]
            return path[len(_PATH_PREFIX) :] if path.startswith(_PATH_PREFIX) else ""

        def _local(self) -> bool:
            port = page._port
            if self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                return True
            self._send(HTTPStatus.FORBIDDEN, _page("Not allowed", "<p>Unknown host.</p>"))
            return False

        def _send(self, status: HTTPStatus, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            for name, value in _HEADERS.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)} · Motel</title>
<style>
  :root {{ --bg:#f7f7f5; --panel:#fff; --text:#1d1d1f; --muted:#6b6b70; --line:#e4e4e0;
          --accent:#2f5bea; --ok:#1a7f37; --bad:#c62828; color-scheme: light dark;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#141416; --panel:#1c1c1f; --text:#ececee;
          --muted:#9a9aa2; --line:#2c2c31; --accent:#7b9cff; --ok:#5cc777; --bad:#ff7b72; }} }}
  body {{ margin:0; background:var(--bg); color:var(--text); line-height:1.5; }}
  main {{ max-width:520px; margin:48px auto; padding:24px; background:var(--panel);
          border:1px solid var(--line); border-radius:12px; }}
  h1 {{ font-size:20px; margin:0 0 12px; }}
  label {{ display:block; font-weight:600; margin-top:18px; }}
  .muted {{ color:var(--muted); font-size:14px; }}
  .note {{ color:var(--bad); }} .ok {{ color:var(--ok); }}
  input {{ font:inherit; width:100%; box-sizing:border-box; margin-top:6px; padding:8px 10px;
           border:1px solid var(--line); border-radius:8px; background:var(--panel);
           color:var(--text); }}
  button {{ margin-top:20px; font:inherit; font-weight:600; background:var(--accent); color:#fff;
            border:0; border-radius:8px; padding:9px 18px; cursor:pointer; }}
  a {{ color:var(--accent); }}
</style></head>
<body><main>{body}</main></body></html>
"""


def _get_one_at(url: str | None) -> str:
    if not url:
        return ""
    if url.startswith(("https://", "http://")):
        link = f'<a href="{_e(url)}" target="_blank" rel="noopener noreferrer">{_e(url)}</a>'
    else:
        link = _e(url)
    return f'<div class="muted">Get one at {link}</div>'


def _form_page(tool: str, needed: list[Secret], note: str | None = None) -> str:
    fields = "".join(
        f'<label for="{_e(s.name)}">{_e(s.label)}'
        + (f' <span class="muted">({_e(s.name)})</span>' if s.description else "")
        + "</label>"
        + _get_one_at(s.url)
        + f'<input id="{_e(s.name)}" name="{_e(s.name)}" type="password" autocomplete="off" '
        'spellcheck="false" required>'
        for s in needed
    )
    return _page(
        "Add a key",
        f"<h1>The tool “{_e(tool)}” needs a key</h1>"
        + (f'<p class="note">{_e(note)}</p>' if note else "")
        + '<p class="muted">Motel keeps it only on this computer and gives it only to the tools '
        "that need it. It is never sent to your AI app.</p>"
        + f'<form method="post">{fields}<button type="submit">Save</button></form>',
    )


def _saved_page(tool: str) -> str:
    return _page(
        "Saved",
        '<h1 class="ok">✓ Saved</h1>'
        f"<p>“{_e(tool)}” can use it now. Go back to your AI app and ask it to try again.</p>"
        '<p class="muted">You can close this tab. To change or remove the key later, use the '
        "Keys page of the Motel dashboard ('motel ui').</p>",
    )


def _expired_page() -> str:
    return _page(
        "Link expired",
        "<h1>This link has expired</h1>"
        f"<p>Each link works once, for {LINK_LIFETIME_SECONDS // 60} minutes. Ask your AI app to "
        "run the tool again, and it will give you a new link.</p>",
    )
