from __future__ import annotations

import http.client
import importlib.util
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("main.py")
spec = importlib.util.spec_from_file_location("slack_relay", MODULE_PATH)
relay = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(relay)


class UpstreamHandler(BaseHTTPRequestHandler):
    received: dict[str, object] = {}

    def log_message(self, format: str, *args: object) -> None:  # noqa: ARG002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        if self.path == "/slack/events":
            self.rfile.read(length)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"upstream traceback marker")
            return
        self.__class__.received = {
            "path": self.path,
            "body": self.rfile.read(length),
            "signature": self.headers.get("X-Slack-Signature"),
            "timestamp": self.headers.get("X-Slack-Request-Timestamp"),
        }
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


class RelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        cls.upstream_thread = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.upstream_thread.start()
        relay.UPSTREAM_BASE = f"http://127.0.0.1:{cls.upstream.server_port}"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), relay.SlackRelayHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.upstream.shutdown()

    def request(self, method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        payload = response.read()
        conn.close()
        return response.status, payload

    def test_relays_only_slack_interactions_with_signature_and_body(self) -> None:
        status, payload = self.request(
            "POST",
            "/slack/interactions",
            body=b"payload=example",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Slack-Signature": "v0=test",
                "X-Slack-Request-Timestamp": "123",
            },
        )

        self.assertEqual((status, payload), (200, b"ok"))
        self.assertEqual(UpstreamHandler.received["path"], "/slack/interactions")
        self.assertEqual(UpstreamHandler.received["body"], b"payload=example")
        self.assertEqual(UpstreamHandler.received["signature"], "v0=test")
        self.assertEqual(UpstreamHandler.received["timestamp"], "123")

    def test_upstream_5xx_becomes_generic_502(self) -> None:
        status, payload = self.request("POST", "/slack/events", body=b"payload=example")

        self.assertEqual(status, 502)
        self.assertNotIn(b"upstream traceback marker", payload)

    def test_rejects_get_and_unknown_post_without_contacting_upstream(self) -> None:
        self.assertEqual(self.request("GET", "/slack/interactions")[0], 405)
        self.assertEqual(self.request("POST", "/anything")[0], 404)


if __name__ == "__main__":
    unittest.main()
