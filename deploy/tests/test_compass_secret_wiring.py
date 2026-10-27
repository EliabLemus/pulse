"""Static safety checks for Compass runtime secret wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_comment_worker_reads_compass_key_from_host_keychain_without_env_file_persistence():
    deploy_script = (ROOT / "deploy" / "deploy-techops.sh").read_text()
    comment_worker = (ROOT / "deploy" / "run-compass-comment-worker.sh").read_text()
    context_worker = (ROOT / "deploy" / "run-compass-context-worker.sh").read_text()
    compose = (ROOT / "deploy" / "docker-compose.techops.yml").read_text()

    assert "security find-generic-password -s 'Compass MCP API key' -w" in comment_worker
    assert "security find-generic-password -s 'Compass MCP API key' -w" in context_worker
    assert "COMPASS_API_KEY='***'" in deploy_script
    assert "COMPASS_API_KEY" in compose
    assert "COMPASS_TEAM: ${COMPASS_TEAM:-techops}" in compose
    assert "deploy/.env.techops" not in deploy_script
