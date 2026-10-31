from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy/check-compass-dsu-endpoints.sh"

DEFAULT_HEALTH_URL = "https://nexus-2.tailf73d68.ts.net/pulse/healthz"
LOCAL_BACKEND_URL = "http://127.0.0.1:8081/pulse/healthz"


def make_executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def check_result(*entries: object) -> str:
    """Build a check-host.net result payload: one node list per entry."""
    return json.dumps({f"node-{index}": entry for index, entry in enumerate(entries, start=1)})


def failed_nodes(count: int, start: int = 1) -> str:
    """A completed failing quorum: each node reports one failed attempt.

    check-host.net maps every node to a list of attempts, so each attempt
    must be wrapped in an outer list to count as a completed node.
    """
    return check_result(*[[[0, 0.5, "Broken pipe", None, f"203.0.113.{start + index}"]] for index in range(count)])


HEALTHY = check_result([[1, 0.2, "OK", 200, "203.0.113.1"]])


@dataclass
class WatchdogHarness:
    """Fakes every external binary the watchdog can invoke.

    ``external_states`` is the ordered list of check-host.net result payloads:
    the Nth ``external_state`` evaluation inside the script returns the Nth
    payload. ``local_backend_up`` drives the loopback probe, and
    ``caddy_validate_ok`` decides whether ``caddy validate`` succeeds (and
    therefore whether ``caddy reload`` may run at all).
    """

    external_states: list[str] = field(default_factory=list)
    local_backend_up: bool = False
    caddy_validate_ok: bool = True
    caddy_reload_ok: bool = True
    docker_exit: int = 0
    funnel_off_exit: int = 0
    env: dict[str, str] = field(default_factory=dict)

    def run(self) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            calls = tmp_path / "calls.log"
            state_file = tmp_path / "external-state"
            state_file.write_text(json.dumps(self.external_states))
            flags = {
                "local_up": self.local_backend_up,
                "validate_ok": self.caddy_validate_ok,
                "reload_ok": self.caddy_reload_ok,
            }
            (tmp_path / "flags").write_text(json.dumps(flags))

            # curl: serves check-host.net requests and the loopback probe.
            # Every check-http call gets the same request id; each
            # check-result call pops the next queued external-state payload.
            make_executable(
                bin_dir / "curl",
                f"""#!/bin/bash
set -eu
url="${{@: -1}}"
printf 'curl %s\\n' "$url" >> "{calls}"
case "$url" in
  *'/check-http?'*)
    printf '%s' '{{"request_id":"req"}}'
    ;;
  *'/check-result/'*)
    /usr/bin/python3 - "{state_file}" <<'PY'
import json, sys
states = json.loads(open(sys.argv[1]).read())
print(states.pop(0) if states else "", end="")
open(sys.argv[1], "w").write(json.dumps(states))
PY
    ;;
  *'127.0.0.1:8081'*)
    /usr/bin/python3 - "{tmp_path / "flags"}" <<'PY'
import json, sys
raise SystemExit(0 if json.loads(open(sys.argv[1]).read())["local_up"] else 7)
PY
    ;;
  *) exit 91 ;;
esac
""",
            )
            make_executable(
                bin_dir / "tailscale",
                f"""#!/bin/bash
printf 'tailscale %s\\n' "$*" >> "{calls}"
if [[ "$1" == 'funnel' && "$2" == '--https=443' ]]; then exit {self.funnel_off_exit}; fi
exit 0
""",
            )
            make_executable(
                bin_dir / "docker",
                f"""#!/bin/bash
printf 'docker %s\\n' "$*" >> "{calls}"
exit {self.docker_exit}
""",
            )
            make_executable(
                bin_dir / "caddy",
                f"""#!/bin/bash
printf 'caddy %s\\n' "$*" >> "{calls}"
case "$1" in
  validate) flag='validate_ok' ;;
  reload) flag='reload_ok' ;;
  *) exit 0 ;;
esac
exec /usr/bin/python3 - "{tmp_path / "flags"}" "$flag" <<'PY'
import json, sys
flags = json.loads(open(sys.argv[1]).read())
raise SystemExit(0 if flags[sys.argv[2]] else 1)
PY
""",
            )
            make_executable(
                bin_dir / "sleep",
                f"""#!/bin/bash
printf 'sleep %s\\n' "$*" >> "{calls}"
""",
            )

            env = os.environ | self.env | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
            result = subprocess.run(["bash", str(SCRIPT)], text=True, capture_output=True, env=env, check=False)
            return result, calls.read_text().splitlines()


def repairs(calls: list[str]) -> list[str]:
    return [call for call in calls if call.startswith(("tailscale ", "docker ", "caddy "))]


class CompassEndpointWatchdogTests(unittest.TestCase):
    def assert_no_repair(self, calls: list[str]) -> None:
        self.assertEqual(repairs(calls), [], calls)

    # -- silent when healthy or inconclusive -------------------------------

    def test_external_http_200_is_silent_and_does_not_repair(self) -> None:
        result, calls = WatchdogHarness(external_states=[HEALTHY]).run()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assert_no_repair(calls)
        self.assertEqual(sum("/check-http?" in call for call in calls), 1)

    def test_pending_and_failed_nodes_is_inconclusive_without_repair(self) -> None:
        pending = check_result([[0, None, None, None, "203.0.113.2"]])
        result, calls = WatchdogHarness(external_states=[pending]).run()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assert_no_repair(calls)

    def test_single_failed_node_is_inconclusive_without_repair(self) -> None:
        single = check_result([[0, 0.5, "Broken pipe", None, "203.0.113.9"]])
        result, calls = WatchdogHarness(external_states=[single]).run()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_no_repair(calls)

    def test_missing_or_malformed_external_result_is_silent_and_does_not_repair(self) -> None:
        for payload in ("", "<html>rate limited</html>", "{}"):
            with self.subTest(payload=payload):
                result, calls = WatchdogHarness(external_states=[payload]).run()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "")
                self.assert_no_repair(calls)

    # -- bounded repair chain ----------------------------------------------

    def test_outage_resets_funnel_once_then_proves_recovery_externally(self) -> None:
        result, calls = WatchdogHarness(external_states=[failed_nodes(3), HEALTHY]).run()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "Compass DSU watchdog restored public Funnel ingress.\n")
        off = calls.index("tailscale funnel --https=443 off")
        on = calls.index("tailscale funnel --bg --yes http://localhost:8081")
        retry = [i for i, call in enumerate(calls) if "/check-http?" in call][1]
        self.assertLess(off, on)
        self.assertLess(on, retry)
        # Funnel recovery alone must not touch the local service chain.
        self.assertFalse(any(call.startswith(("docker ", "caddy ")) for call in calls), calls)

    def test_local_repair_runs_each_step_once_and_proves_recovery(self) -> None:
        result, calls = WatchdogHarness(
            external_states=[failed_nodes(3), failed_nodes(3, start=10), HEALTHY],
            local_backend_up=False,
        ).run()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("restored public Funnel ingress after local service-chain repair", result.stdout)
        # Loopback probe failed => docker start runs once with every container.
        docker_calls = [c for c in calls if c.startswith("docker ")]
        self.assertEqual(docker_calls, ["docker start pulse-techops-app-1 pulse-techops-redis-1 pulse-techops-db-1"])
        # Validate gates reload, each at most once.
        self.assertEqual(sum("caddy validate" in c for c in calls), 1)
        self.assertEqual(sum("caddy reload" in c for c in calls), 1)
        validate = next(i for i, c in enumerate(calls) if c.startswith("caddy validate"))
        reload = next(i for i, c in enumerate(calls) if c.startswith("caddy reload"))
        self.assertLess(validate, reload)
        # Single Funnel reset, never a second one.
        self.assertEqual(sum("funnel --https=443 off" in c for c in calls), 1)
        self.assertEqual(sum("funnel --bg" in c for c in calls), 1)

    def test_healthy_loopback_skips_docker_start(self) -> None:
        result, calls = WatchdogHarness(
            external_states=[failed_nodes(3), failed_nodes(3, start=10), HEALTHY],
            local_backend_up=True,
        ).run()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(call.startswith("docker ") for call in calls), calls)
        # Caddy reload is still attempted after a successful validate.
        self.assertEqual(sum("caddy reload" in c for c in calls), 1)

    def test_caddy_validate_failure_blocks_reload(self) -> None:
        result, calls = WatchdogHarness(
            external_states=[failed_nodes(3), failed_nodes(3, start=10), failed_nodes(3, start=20)],
            caddy_validate_ok=False,
        ).run()

        # Still a bounded failure, never a crash, and reload never happened.
        self.assertEqual(result.returncode, 1)
        self.assertFalse(any(call.startswith("caddy reload") for call in calls), calls)
        self.assertEqual(sum("caddy validate" in c for c in calls), 1)
        self.assertIn("remains unavailable after registration reset and local repair", result.stderr)

    def test_failed_chain_alerts_once_without_second_reset(self) -> None:
        result, calls = WatchdogHarness(
            external_states=[
                failed_nodes(3),
                failed_nodes(3, start=10),
                failed_nodes(3, start=20),
            ]
        ).run()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("ALERT: Compass DSU public Funnel ingress remains unavailable", result.stderr)
        self.assertIn("after registration reset and local repair", result.stderr)
        self.assertEqual(sum("funnel --https=443 off" in c for c in calls), 1)
        self.assertEqual(sum("funnel --bg" in c for c in calls), 1)
        self.assertEqual(sum(c.startswith("docker start") for c in calls), 1)
        self.assertEqual(sum("caddy reload" in c for c in calls), 1)

    def test_reset_tolerates_already_off_funnel(self) -> None:
        result, calls = WatchdogHarness(external_states=[failed_nodes(3), HEALTHY], funnel_off_exit=1).run()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("tailscale funnel --https=443 off", calls)
        self.assertIn("tailscale funnel --bg --yes http://localhost:8081", calls)

    # -- environment parameterization ---------------------------------------

    def test_health_url_and_repair_targets_are_env_parameterized(self) -> None:
        custom_health = "https://compass.example.internal/pulse/healthz"
        custom_caddyfile = "/tmp/compass-Caddyfile-test"
        result, calls = WatchdogHarness(
            external_states=[failed_nodes(3), failed_nodes(3, start=10), failed_nodes(3, start=20)],
            env={
                "COMPASS_HEALTH_URL": custom_health,
                "COMPASS_CADDYFILE": custom_caddyfile,
                "COMPASS_REPAIR_CONTAINERS": "app-box cache-box",
            },
        ).run()

        # The external quorum must probe the configured URL, not the default.
        self.assertTrue(any("compass.example.internal" in c for c in calls), calls)
        self.assertFalse(any(DEFAULT_HEALTH_URL in c for c in calls), calls)
        # Repair targets come from the environment.
        self.assertIn("docker start app-box cache-box", calls)
        self.assertTrue(any(c.startswith(f"caddy validate --config {custom_caddyfile}") for c in calls), calls)
        # The alert names the configured URL.
        self.assertIn(custom_health, result.stderr)

    # -- static safety -------------------------------------------------------

    def test_source_contains_no_destructive_commands(self) -> None:
        source = SCRIPT.read_text()
        for forbidden in (
            "tailscale down",
            "tailscale up",
            "tailscale quit",
            "docker restart",
            "docker stop",
            "docker kill",
            "docker compose down",
            "osascript",
        ):
            self.assertNotIn(forbidden, source, f"watchdog must never run: {forbidden}")


if __name__ == "__main__":
    unittest.main()
