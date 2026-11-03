"""CLI to manage per-user Compass API keys. Reads keys from stdin only.

Run inside the container (or on the host with the app environment loaded):

    python -m src.modules.standup.user_keys_cli add U0123ABCDEF
    python -m src.modules.standup.user_keys_cli revoke U0123ABCDEF
    python -m src.modules.standup.user_keys_cli list

The key is typed once on a hidden stdin prompt: it never appears in argv,
process listings, or logs. Requires COMPASS_USER_KEY_SECRET in the
environment so the stored ciphertext is encrypted before it touches Postgres.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _add(user_id: str) -> int:
    from src.modules.standup import user_keys

    api_key = getpass.getpass("Compass API key (input hidden): ").strip()
    if not api_key:
        print("No key entered; nothing changed.", file=sys.stderr)
        return 1
    user_keys.upsert_user_key(user_id, api_key)
    print(f"Stored encrypted Compass key for {user_id}")
    return 0


def _revoke(user_id: str) -> int:
    from src.modules.standup import user_keys

    if user_keys.deactivate_user_key(user_id):
        print(f"Revoked Compass key for {user_id}")
        return 0
    print(f"No stored key for {user_id}", file=sys.stderr)
    return 1


def _list() -> int:
    import src.core.db as db

    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, added_at, active FROM compass_user_api_keys ORDER BY user_id")
            rows = cur.fetchall()
    for user_id, added_at, active in rows:
        print(f"{user_id}  added={added_at}  active={active}")
    if not rows:
        print("No per-user Compass keys stored.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage per-user Compass API keys (encrypted at rest)")
    sub = parser.add_subparsers(dest="command", required=True)
    add_p = sub.add_parser("add", help="Store or replace one user's key (read from hidden stdin)")
    add_p.add_argument("user_id")
    revoke_p = sub.add_parser("revoke", help="Deactivate one user's key")
    revoke_p.add_argument("user_id")
    sub.add_parser("list", help="List stored keys (never the ciphertext)")
    args = parser.parse_args(argv)
    if args.command == "add":
        return _add(args.user_id)
    if args.command == "revoke":
        return _revoke(args.user_id)
    return _list()


if __name__ == "__main__":
    raise SystemExit(main())
