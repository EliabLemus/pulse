"""Pin the Compass context-refresh cron job to the 10-minute staggered schedule.

The operator script must update the EXISTING Hermes job ``0afe4463e25d`` to
``04,14,24,34,44,54 * * * *``, must fail when the job is absent, and must
never create a second job. This test pins the artifact itself.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "configure-compass-context-refresh.sh"

EXPECTED_JOB_ID = "0afe4463e25d"
EXPECTED_SCHEDULE = "04,14,24,34,44,54 * * * *"


def test_script_exists_and_is_executable_bit_ready():
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    text = SCRIPT.read_text()
    assert text.startswith("#!"), "script must start with a shebang"


def test_script_updates_existing_job_by_id_with_expected_schedule():
    text = SCRIPT.read_text()
    assert EXPECTED_JOB_ID in text, "must pin the exact existing job id"
    assert EXPECTED_SCHEDULE in text, "must set the staggered 10-minute schedule"


def test_script_has_no_every_10m_shorthand():
    text = SCRIPT.read_text()
    assert not re.search(r"every\s+10m", text), "must not use the 'every 10m' shorthand"


def test_script_never_creates_a_job():
    text = SCRIPT.read_text()
    assert not re.search(r"cron\s+(create|add)\b", text), "must not create a second job"


def test_script_fails_when_job_is_absent():
    text = SCRIPT.read_text()
    # A guard must verify the job exists before/after editing (grep/hermes cron
    # list or status check) and abort when it is missing.
    assert re.search(r"list|status", text), "must check the job exists"
    assert re.search(r"exit 1", text), "must exit nonzero when the job is absent"
