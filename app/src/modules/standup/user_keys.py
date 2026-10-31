"""Per-user Compass API keys, encrypted at rest with a host-held secret.

The long-lived app never needs these keys: only the ephemeral comment worker
decrypts them so each ticket comment is posted by the person who wrote it.
Encryption uses Fernet (AES-128-CBC + HMAC) keyed from
``COMPASS_USER_KEY_SECRET`` (32 url-safe base64 bytes, e.g.
``openssl rand -base64 32``). With the secret absent, keys cannot be stored
or resolved and the worker falls back to the global credential.
"""

from __future__ import annotations

import logging
import os

import src.core.db as db

logger = logging.getLogger(__name__)

SECRET_ENV = "COMPASS_USER_KEY_SECRET"


def _fernet():
    secret = os.environ.get(SECRET_ENV, "").strip()
    if not secret:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:  # pragma: no cover - cryptography is a hard dep in prod
        logger.error("cryptography is not installed; per-user Compass keys are unavailable")
        return None
    try:
        return Fernet(secret.encode())
    except Exception:
        logger.error("%s is not valid Fernet key material (want: openssl rand -base64 32)", SECRET_ENV)
        return None


def encrypt_key(api_key: str) -> str | None:
    """Return the ciphertext for a Compass key, or None when unencryptable."""
    if not api_key.startswith("cmp_"):
        raise ValueError("A Compass API key must start with 'cmp_'")
    fernet = _fernet()
    if fernet is None:
        raise RuntimeError(f"{SECRET_ENV} is not configured; cannot store per-user Compass keys")
    return fernet.encrypt(api_key.encode()).decode()


def decrypt_key(key_ciphertext: str) -> str | None:
    from cryptography.fernet import InvalidToken  # noqa: PLC0415

    fernet = _fernet()
    if fernet is None:
        return None
    try:
        return fernet.decrypt(key_ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("Could not decrypt a per-user Compass key; was %s rotated?", SECRET_ENV)
        return None


def upsert_user_key(user_id: str, api_key: str) -> None:
    """Store (or replace) one user's active key. Never logs the plaintext."""
    user_id = user_id.strip()
    if not user_id.startswith("U"):
        raise ValueError("A Slack user id (e.g. U0123ABCDEF) is required")
    ciphertext = encrypt_key(api_key)
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO compass_user_api_keys (user_id, key_ciphertext, active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (user_id) DO UPDATE
                SET key_ciphertext = EXCLUDED.key_ciphertext,
                    active = TRUE,
                    added_at = NOW()
                """,
                (user_id, ciphertext),
            )


def deactivate_user_key(user_id: str) -> bool:
    """Revoke one user's key; returns whether a row existed."""
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE compass_user_api_keys SET active = FALSE WHERE user_id = %s",
                (user_id.strip(),),
            )
            return bool(cur.rowcount)


def active_key_for_user(user_id: str) -> str | None:
    """Resolve a user's active key, or None when absent/unreadable.

    Called only by the ephemeral worker; failures degrade to the global key.
    """
    value = str(user_id or "").strip()
    if not value:
        return None
    try:
        with db.db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT key_ciphertext FROM compass_user_api_keys WHERE user_id = %s AND active",
                    (value,),
                )
                row = cur.fetchone()
    except Exception:  # noqa: BLE001 - degrade to the global key, never block delivery
        logger.exception("Could not read per-user Compass key for %s", value)
        return None
    if not row:
        return None
    return decrypt_key(str(row[0]))
