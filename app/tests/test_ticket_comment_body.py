
"""Regression: comment body drops the author prefix when a per-user key exists."""
from unittest.mock import patch

from src.modules.standup.handlers import _ticket_comment_body


def test_ticket_comment_body_without_user_key_keeps_prefix():
    with patch("src.modules.standup.user_keys.active_key_for_user", return_value=None):
        assert _ticket_comment_body("U123", "Hugo Muñoz", "avance x") == "Avance de Hugo Muñoz:\navance x"


def test_ticket_comment_body_with_user_key_drops_prefix():
    with patch("src.modules.standup.user_keys.active_key_for_user", return_value="cmp_test"):
        assert _ticket_comment_body("U123", "Hugo Muñoz", "avance x") == "avance x"
