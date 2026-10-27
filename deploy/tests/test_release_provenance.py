"""Static release-provenance contracts for the TechOps deployment."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_release_sha_flows_from_deploy_script_to_image_build_metadata():
    compose = (ROOT / "deploy" / "docker-compose.techops.yml").read_text()
    deploy_script = (ROOT / "deploy" / "deploy-techops.sh").read_text()
    dockerfile = (ROOT / "app" / "Dockerfile").read_text()

    assert "APP_VERSION: ${PULSE_RELEASE_SHA:?set PULSE_RELEASE_SHA before deployment}" in compose
    assert 'PULSE_RELEASE_SHA="g$(git -C "$(dirname "$SCRIPT_DIR")" rev-parse --short=12 HEAD)"' in deploy_script
    assert "export PULSE_RELEASE_SHA" in deploy_script
    assert "org.opencontainers.image.revision=$APP_VERSION" in dockerfile


def test_deploy_builds_the_release_image_before_migrations_and_pins_httpx():
    requirements = (ROOT / "app" / "requirements.txt").read_text()
    deploy_script = (ROOT / "deploy" / "deploy-techops.sh").read_text()

    assert "httpx==0.28.1" in requirements
    assert '"${compose[@]}" build --no-cache app' in deploy_script
    assert deploy_script.index('"${compose[@]}" build --no-cache app') < deploy_script.index('"${compose[@]}" run --rm --no-deps migrate')
