"""One-shot Compass comment worker, invoked only with an ephemeral credential."""

from __future__ import annotations

import argparse
import logging
import os

from src.modules.standup.comment_jobs import (
    claim_pending_comment_jobs,
    mark_comment_delivered,
    mark_comment_unknown,
    mark_stale_guided_deliveries_unknown,
    mark_stale_processing_comments_unknown,
)
from src.modules.standup.compass import CompassClient

logger = logging.getLogger(__name__)


def run_pending_comments(api_key: str, *, limit: int = 25) -> dict[str, int]:
    """Post each claimed job once; uncertain outcomes intentionally are not retried.

    Each job is posted with the submitting user's own Compass key when one is
    stored (comments are authored by the person who wrote them), and with the
    global credential otherwise, so nobody is blocked while keys are issued.
    """
    if not api_key.startswith("cmp_"):
        raise ValueError("A Compass API key is required for the comment worker")
    fallback_client = CompassClient(api_key)
    clients: dict[str, CompassClient] = {"": fallback_client}
    result = {
        "delivered": 0,
        "impersonated": 0,
        "unknown": mark_stale_guided_deliveries_unknown() + mark_stale_processing_comments_unknown(),
    }
    for job in claim_pending_comment_jobs(limit):
        job_id = int(job["id"])
        client, impersonated = _client_for(job.get("user_id"), api_key, clients)
        try:
            client.post_comment(str(job["ticket_key"]), str(job["body"]))
        except Exception as exc:  # an ambiguous remote outcome must not be retried
            logger.warning("Compass comment job %s became unknown: %s", job_id, exc)
            mark_comment_unknown(job_id, str(exc))
            result["unknown"] += 1
        else:
            mark_comment_delivered(job_id)
            result["delivered"] += 1
            if impersonated:
                result["impersonated"] += 1
    return result


def _client_for(user_id: object, global_key: str, clients: dict[str, CompassClient]):
    """Return (client, impersonated) for a job's user, memoized per run.

    Key resolution failures degrade to the global client: the comment still
    goes out, just under the shared credential instead of the user's.
    """
    from src.modules.standup import user_keys  # imported lazily: needs the key secret only here

    user = str(user_id or "").strip()
    if not user or user in clients:
        return clients.get(user, clients[""]), False
    api_key = user_keys.active_key_for_user(user)
    if not api_key:
        clients[user] = clients[""]
        return clients[""], False
    clients[user] = CompassClient(api_key)
    return clients[user], True


def main() -> int:
    parser = argparse.ArgumentParser(description="Deliver queued Compass ticket comments once")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    result = run_pending_comments(os.environ.get("COMPASS_API_KEY", ""), limit=args.limit)
    print(f"delivered={result['delivered']} unknown={result['unknown']} impersonated={result['impersonated']}")
    # Hermes cron turns a real nonzero result into a user-visible failure alert.
    return 1 if result["unknown"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
