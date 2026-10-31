"""Static safety tests for deploy/send-compass-dsu-trial.sh.

The trial script must be inert by default: without the explicit opt-in
environment variables it exits before performing any external write. These
tests check the script's source (never execute the sending path) so no real
Slack, Compass, Docker, or pilot service is ever contacted.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy/send-compass-dsu-trial.sh"
SOURCE = SCRIPT.read_text()


class TrialScriptSafetyTests(unittest.TestCase):
    def test_inert_by_default_before_any_write(self) -> None:
        # The dry-run banner prints first; the opt-in gate must appear before
        # any command that contacts Slack, Compass, Docker, or the pilot.
        gate = SOURCE.index("COMPASS_DSU_TRIAL_CONFIRM:-}\" != 'YES-SEND-DSU-DM'")
        self.assertLess(
            gate,
            SOURCE.index('"$SCRIPT_DIR/check-compass-dsu-endpoints.sh"'),
            "opt-in gate must run before the watchdog subcommand",
        )
        self.assertLess(gate, SOURCE.index('docker exec "$REDIS_CONTAINER"'), "gate precedes redis DEL")
        self.assertLess(gate, SOURCE.index("docker exec -i"), "gate precedes the app send")
        # Without opt-in the script exits 0 having only printed the summary.
        self.assertIn("exit 0", SOURCE[SOURCE.index('if [[ "${COMPASS_DSU_TRIAL_CONFIRM:-}') :])

    def test_requires_both_opt_in_and_mock_write_mode(self) -> None:
        self.assertIn("COMPASS_DSU_TRIAL_CONFIRM=YES-SEND-DSU-DM", SOURCE)
        self.assertIn("PULSE_COMPASS_WRITE_MODE:-}\" != 'mock'", SOURCE)
        # The mock-mode refusal exits non-zero before any send happens.
        refusal = SOURCE.index("Refusing to send: PULSE_COMPASS_WRITE_MODE")
        self.assertIn("exit 2", SOURCE[refusal:])

    def test_root_derived_from_bash_source(self) -> None:
        self.assertIn('dirname "${BASH_SOURCE[0]}"', SOURCE)
        self.assertNotIn('ROOT="/Users/openjaime', SOURCE)
        self.assertNotIn('ROOT="/Users/', SOURCE)

    def test_no_hardcoded_operator_paths(self) -> None:
        self.assertNotIn("/Users/openjaime/projects/morgenruf", SOURCE)
        self.assertNotIn("/Users/openjaime/Projects/morgenruf", SOURCE)

    def test_parameters_are_env_overridable(self) -> None:
        for variable in (
            "PULSE_APP_CONTAINER",
            "PULSE_REDIS_CONTAINER",
            "PULSE_SCHEDULE_ID",
            "PULSE_SESSION_KEY",
        ):
            self.assertIn(variable, SOURCE)

    def test_no_secrets_in_source(self) -> None:
        for forbidden in ("xoxb-", "cmp_", "sk-", "ghp_", "AKIA"):
            self.assertNotIn(forbidden, SOURCE)


if __name__ == "__main__":
    unittest.main()
