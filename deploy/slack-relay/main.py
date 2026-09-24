"""Narrow Cloud Run relay for Slack interactive callbacks.

The relay deliberately knows only the two Slack callback paths. It forwards the
raw POST body and Slack signature headers to the existing Pulse deployment; the
Pulse app remains the sole verifier of Slack signatures and owner of all state.
"""

from __future__ import annotations

import http.server
import os
import urllib.error
import urllib.request
from http import HTTPStatus


UPSTREAM_BASE = os.environ.get("UPSTREAM_BASE", "").rstrip("/")
ALLOWED_PATHS = frozenset({"/slack/events", "/slack/interactions"})
FORWARDED_HEADERS = frozenset(
    {
        "content-type",
        "x-slack-request-timestamp",
        "x-slack-signature",
        "x-slack-retry-num",
        "x-slack-retry-reason",
    }
)


class SlackRelayHandler(http.server.BaseHTTPRequestHandler):
    server_version = "CompassSlackRelay/1.0"

    def log_message(self, format: str, *args: object) -> None:  # noqa: ARG002
        """Avoid logging callback bodies or request headers."""

    def do_GET(self) -> None:  # noqa: N802
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in ALLOWED_PATHS:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not UPSTREAM_BASE:
            self.send_error(HTTPStatus.BAD_GATEWAY)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        if content_length < 0 or content_length > 1_000_000:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        body = self.rfile.read(content_length)
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() in FORWARDED_HEADERS
        }
        request = urllib.request.Request(
            f"{UPSTREAM_BASE}{self.path}", data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=2.5) as response:
                response_body = response.read()
                self.send_response(response.status)
                content_type = response.headers.get("Content-Type")
                if content_type:
                    self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)
        except urllib.error.HTTPError as error:
            # Preserve expected client failures such as Slack's signature 401,
            # but never expose upstream error pages or tracebacks publicly.
            if 400 <= error.code < 500:
                self.send_response(error.code)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.send_error(HTTPStatus.BAD_GATEWAY)
        except (OSError, TimeoutError, urllib.error.URLError):
            self.send_error(HTTPStatus.BAD_GATEWAY)


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), SlackRelayHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
