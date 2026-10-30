from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy/check-compass-dsu-endpoints.sh"
CHECK_HOST = "https://check-host.net"


def make_executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def check_result(*entries: object) -> str:
    return json.dumps({f"node-{index}": entry for index, entry in enumerate(entries, start=1)})


def run_watchdog(
    first_result: str,
    retry_result: str | None = None,
    *,
    first_request: str = '{"request_id":"first"}',
    retry_request: str = '{"request_id":"retry"}',
    off_exit: int = 0,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        calls = tmp_path / "calls.log"
        result_calls = tmp_path / "result-calls"

        make_executable(
            bin_dir / "curl",
            f"""#!/bin/bash
set -eu
url="${{@: -1}}"
printf 'curl %s\\n' "$url" >> "{calls}"
case "$url" in
  *'/check-http?'*)
    count=0
    if [[ -f "{result_calls}" ]]; then count=$(cat "{result_calls}"); fi
    if [[ "$count" == 0 ]]; then printf '%s' '{first_request}'; else printf '%s' '{retry_request}'; fi
    ;;
  *'/check-result/'*)
    count=0
    if [[ -f "{result_calls}" ]]; then count=$(cat "{result_calls}"); fi
    count=$((count + 1))
    printf '%s' "$count" > "{result_calls}"
    if [[ "$count" == 1 ]]; then printf '%s' '{first_result}'; else printf '%s' '{retry_result if retry_result is not None else first_result}'; fi
    ;;
  *) exit 91 ;;
esac
""",
        )
        make_executable(
            bin_dir / "tailscale",
            f"""#!/bin/bash
printf 'tailscale %s\\n' "$*" >> "{calls}"
if [[ "$*" == 'funnel --https=443 off' ]]; then exit {off_exit}; fi
""",
        )
        make_executable(bin_dir / "sleep", f"#!/bin/bash\nprintf 'sleep %s\\n' \"$*\" >> '{calls}'\n")
        env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
        result = subprocess.run(["bash", str(SCRIPT)], text=True, capture_output=True, env=env, check=False)
        return result, calls.read_text().splitlines()


class CompassEndpointWatchdogTests(unittest.TestCase):
    def assert_no_repair(self, calls: list[str]) -> None:
        self.assertFalse(any(call.startswith("tailscale ") for call in calls), calls)
        self.assertFalse(
            any("nexus-2.tailf73d68.ts.net/pulse/healthz" in call and "check-host.net" not in call for call in calls),
            calls,
        )

    def test_external_http_200_is_silent_and_does_not_repair(self) -> None:
        result, calls = run_watchdog(check_result([[1, 0.2, "OK", 200, "203.0.113.1"]], None, None))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assert_no_repair(calls)
        self.assertEqual(sum("/check-http?" in call for call in calls), 1)
        self.assertEqual(sum("/check-result/" in call for call in calls), 1)

    def test_one_failed_node_and_pending_nodes_is_inconclusive_without_repair(self) -> None:
        result, calls = run_watchdog(check_result([[0, 0.5, "Broken pipe", None, "203.0.113.2"]], None, None))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assert_no_repair(calls)

    def test_missing_or_malformed_external_result_is_silent_and_does_not_repair(self) -> None:
        for payload in ("", "<html>rate limited</html>", "{}"):
            with self.subTest(payload=payload):
                result, calls = run_watchdog(payload)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "")
                self.assert_no_repair(calls)

    def test_external_outage_resets_funnel_mapping_then_proves_recovery_externally(self) -> None:
        all_failed = check_result(
            [[0, 0.5, "Broken pipe", None, "203.0.113.3"]],
            [[0, 0.6, "Broken pipe", None, "203.0.113.4"]],
            [[0, 0.7, "Broken pipe", None, "203.0.113.5"]],
        )
        recovered = check_result([[1, 0.3, "OK", 200, "203.0.113.6"]])
        result, calls = run_watchdog(all_failed, recovered)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "Compass DSU watchdog restored public Funnel ingress.\n")
        self.assertEqual(result.stderr, "")
        off = calls.index("tailscale funnel --https=443 off")
        on = calls.index("tailscale funnel --bg --yes http://localhost:8081")
        retry = [index for index, call in enumerate(calls) if "/check-http?" in call][1]
        self.assertLess(off, on)
        self.assertLess(on, retry)
        self.assertFalse(any(call.startswith(("caddy ", "docker ")) for call in calls), calls)

    def test_reset_tolerates_already_off_funnel(self) -> None:
        all_failed = check_result(
            [[0, 0.5, "Broken pipe", None, "203.0.113.3"]],
            [[0, 0.6, "Broken pipe", None, "203.0.113.4"]],
        )
        recovered = check_result([[1, 0.3, "OK", 200, "203.0.113.6"]])
        result, calls = run_watchdog(all_failed, recovered, off_exit=1)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("tailscale funnel --https=443 off", calls)
        self.assertIn("tailscale funnel --bg --yes http://localhost:8081", calls)

    def test_failed_external_retry_alerts_once_without_a_second_reset(self) -> None:
        all_failed = check_result(
            [[0, 0.5, "Broken pipe", None, "203.0.113.3"]],
            [[0, 0.6, "Broken pipe", None, "203.0.113.4"]],
        )
        retry_failed = check_result(
            [[0, 0.4, "Broken pipe", None, "203.0.113.7"]],
            [[0, 0.5, "Broken pipe", None, "203.0.113.8"]],
        )
        result, calls = run_watchdog(all_failed, retry_failed)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("public Funnel ingress remains unavailable", result.stderr)
        self.assertEqual(calls.count("tailscale funnel --https=443 off"), 1)
        self.assertEqual(calls.count("tailscale funnel --bg --yes http://localhost:8081"), 1)


if __name__ == "__main__":
    unittest.main()
