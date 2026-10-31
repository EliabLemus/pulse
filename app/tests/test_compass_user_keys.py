"""Encrypted per-user Compass API keys."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet


def _fernet_key() -> str:
    return Fernet.generate_key().decode()


def _transaction(cursor):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def transaction():
        yield conn

    return transaction


def test_round_trip_encrypts_and_decrypts(monkeypatch):
    from src.modules.standup import user_keys

    monkeypatch.setenv(user_keys.SECRET_ENV, _fernet_key())
    ciphertext = user_keys.encrypt_key("cmp_user7")
    assert ciphertext is not None
    assert "cmp_user7" not in ciphertext
    assert user_keys.decrypt_key(ciphertext) == "cmp_user7"


def test_encrypt_requires_secret(monkeypatch):
    from src.modules.standup import user_keys

    monkeypatch.delenv(user_keys.SECRET_ENV, raising=False)
    with pytest.raises(RuntimeError):
        user_keys.encrypt_key("cmp_user7")


def test_encrypt_rejects_non_compass_keys(monkeypatch):
    from src.modules.standup import user_keys

    monkeypatch.setenv(user_keys.SECRET_ENV, _fernet_key())
    with pytest.raises(ValueError):
        user_keys.encrypt_key("not-a-compass-key")


def test_decrypt_with_rotated_secret_returns_none(monkeypatch):
    from src.modules.standup import user_keys

    monkeypatch.setenv(user_keys.SECRET_ENV, _fernet_key())
    ciphertext = user_keys.encrypt_key("cmp_user7")
    monkeypatch.setenv(user_keys.SECRET_ENV, _fernet_key())
    assert user_keys.decrypt_key(ciphertext or "") is None


def test_upsert_stores_only_ciphertext(monkeypatch):
    from src.modules.standup import user_keys

    monkeypatch.setenv(user_keys.SECRET_ENV, _fernet_key())
    cursor = MagicMock()
    monkeypatch.setattr(user_keys.db, "db_conn", _transaction(cursor))

    user_keys.upsert_user_key("U7", "cmp_user7")

    sql, params = cursor.execute.call_args.args
    assert "compass_user_api_keys" in sql
    assert params[0] == "U7"
    assert params[1] != "cmp_user7"
    assert "cmp_user7" not in params[1]


def test_upsert_rejects_non_slack_user_id(monkeypatch):
    from src.modules.standup import user_keys

    monkeypatch.setenv(user_keys.SECRET_ENV, _fernet_key())
    with pytest.raises(ValueError):
        user_keys.upsert_user_key("not-a-user", "cmp_user7")


def test_active_key_for_user_returns_decrypted_key(monkeypatch):
    from src.modules.standup import user_keys

    monkeypatch.setenv(user_keys.SECRET_ENV, _fernet_key())
    ciphertext = user_keys.encrypt_key("cmp_user7")
    assert ciphertext is not None
    cursor = MagicMock()
    cursor.fetchone.return_value = (ciphertext,)
    monkeypatch.setattr(user_keys.db, "db_conn", _transaction(cursor))

    assert user_keys.active_key_for_user("U7") == "cmp_user7"
    sql, params = cursor.execute.call_args.args
    assert "active" in sql
    assert params == ("U7",)


def test_active_key_for_user_without_row_returns_none(monkeypatch):
    from src.modules.standup import user_keys

    cursor = MagicMock()
    cursor.fetchone.return_value = None
    monkeypatch.setattr(user_keys.db, "db_conn", _transaction(cursor))

    assert user_keys.active_key_for_user("U7") is None


def test_active_key_for_user_survives_db_failure(monkeypatch):
    from src.modules.standup import user_keys

    @contextmanager
    def broken():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(user_keys.db, "db_conn", broken)
    assert user_keys.active_key_for_user("U7") is None


def test_active_key_for_user_blank_returns_none():
    from src.modules.standup import user_keys

    assert user_keys.active_key_for_user("  ") is None


def test_cli_add_reads_hidden_stdin_and_stores_ciphertext(monkeypatch, capsys):
    from src.modules.standup import user_keys, user_keys_cli

    monkeypatch.setenv(user_keys.SECRET_ENV, _fernet_key())
    cursor = MagicMock()
    monkeypatch.setattr(user_keys.db, "db_conn", _transaction(cursor))
    monkeypatch.setattr("getpass.getpass", lambda *a: "cmp_cli_key")

    exit_code = user_keys_cli.main(["add", "U9"])

    assert exit_code == 0
    assert "U9" in capsys.readouterr().out
    stored = cursor.execute.call_args.args[1][1]
    assert stored != "cmp_cli_key"
    assert "cmp_cli_key" not in stored


def test_cli_add_without_key_exits_nonzero(monkeypatch, capsys):
    from src.modules.standup import user_keys_cli

    monkeypatch.setattr("getpass.getpass", lambda *a: "   ")
    assert user_keys_cli.main(["add", "U9"]) == 1


def test_cli_revoke_reports_missing_key(monkeypatch, capsys):
    from src.modules.standup import user_keys, user_keys_cli

    cursor = MagicMock()
    cursor.rowcount = 0
    monkeypatch.setattr(user_keys.db, "db_conn", _transaction(cursor))
    assert user_keys_cli.main(["revoke", "U9"]) == 1


def test_cli_list_prints_no_ciphertext(monkeypatch, capsys):
    from src.modules.standup import user_keys_cli

    cursor = MagicMock()
    cursor.fetchall.return_value = [("U7", "2026-10-31", True)]
    import src.core.db as db

    monkeypatch.setattr(db, "db_conn", _transaction(cursor))

    assert user_keys_cli.main(["list"]) == 0
    assert "U7" in capsys.readouterr().out
