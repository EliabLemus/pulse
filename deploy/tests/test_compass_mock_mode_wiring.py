"""Static safety checks for the Compass mock write-mode wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_compose_passes_mock_write_mode_through_without_defaulting_to_it():
    compose = (ROOT / "deploy" / "docker-compose.techops.yml").read_text()

    assert "PULSE_COMPASS_WRITE_MODE: ${PULSE_COMPASS_WRITE_MODE:-}" in compose


def test_mock_mode_is_opt_in_and_never_hardcoded_in_the_deploy_script():
    deploy_script = (ROOT / "deploy" / "deploy-techops.sh").read_text()
    compass = (ROOT / "app" / "src" / "compass.py").read_text()

    assert "PULSE_COMPASS_WRITE_MODE=mock" not in deploy_script
    assert compass.count('"mock"') >= 1
    assert 'os.environ.get("PULSE_COMPASS_WRITE_MODE"' in compass


def test_deploy_script_never_lets_shell_mock_leak_into_compose():
    deploy_script = (ROOT / "deploy" / "deploy-techops.sh").read_text()

    assert '[[ "${PULSE_COMPASS_WRITE_MODE:-}" == "mock" ]]' in deploy_script
    assert "unset PULSE_COMPASS_WRITE_MODE" in deploy_script
