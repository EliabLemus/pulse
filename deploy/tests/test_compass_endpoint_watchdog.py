from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy/check-compass-dsu-endpoints.sh"
PUBLIC_BASE = "https://nexus-2.tailf73d68.ts.net/pulse"


def make_executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run_watchdog(curl_body: str, direct_healthy: bool) -> tuple[subprocess.CompletedProcess[str], str]:
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        calls = tmp_path / "calls.log"
        healthy_cases = (
            f'''case "$url" in
  "{PUBLIC_BASE}/healthz") printf '{{"status":"ok"}}\\n200' ;;
  "{PUBLIC_BASE}/slack/events"|"{PUBLIC_BASE}/slack/interactions") printf 'Method Not Allowed\\n405' ;;
  *) printf '{curl_body}' ;;
esac'''
            if direct_healthy
            else f"printf '{curl_body}'"
        )
        make_executable(
            bin_dir / "curl",
            f"""#!/bin/bash
set -eu
url="${{@: -1}}"
printf '%s\\n' "$url" >> "{calls}"
{healthy_cases}
""",
        )
        for command in ("tailscale", "caddy", "docker", "sleep"):
            make_executable(
                bin_dir / command,
                f"#!/bin/bash\nprintf '%s %s\\n' '{command}' \"$*\" >> '{calls}'\n",
            )
        env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
        result = subprocess.run(["bash", str(SCRIPT)], text=True, capture_output=True, env=env, check=False)
        return result, calls.read_text()


class CompassEndpointWatchdogTests(unittest.TestCase):
    def test_healthy_direct_endpoints_exit_silently_without_repair(self) -> None:
        result, calls = run_watchdog("000", direct_healthy=True)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("r.jina.ai", calls)
        self.assertEqual(
            calls.splitlines(),
            [
                f"{PUBLIC_BASE}/healthz",
                f"{PUBLIC_BASE}/slack/events",
                f"{PUBLIC_BASE}/slack/interactions",
            ],
        )

    def test_unhealthy_endpoints_attempt_repair_before_failing(self) -> None:
        result, calls = run_watchdog("000", direct_healthy=False)

        self.assertEqual(result.returncode, 1)
        self.assertIn("tailscale funnel --bg --yes http://localhost:8081", calls)
        self.assertIn("caddy reload --config /Users/openjaime/Caddyfile --adapter caddyfile", calls)
        self.assertIn("docker start pulse-techops-app-1 pulse-techops-redis-1 pulse-techops-db-1", calls)


if __name__ == "__main__":
    unittest.main()
