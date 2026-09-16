"""Deployment contract: Pulse must share active sessions through Redis."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_compose_provisions_redis_and_wires_it_into_pulse_runtime():
    compose = (ROOT / "deploy" / "docker-compose.techops.yml").read_text()

    assert "  redis:" in compose
    assert "image: redis:7-alpine" in compose
    assert "REDIS_URL: redis://redis:6379/0" in compose
    assert "redis:\n        condition: service_healthy" in compose
    assert "pulse-techops-redis:" in compose
