"""Channel rendering for legacy captures without active Compass tickets."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from src.core.state import UserSession
from src.modules.standup import handlers

from tests.support import patch_modules


@pytest.fixture
def complete_legacy():
    db = MagicMock()
    db.get_standup_schedule.return_value = {"id": 7, "name": "DSU TechOps", "channel_id": "C1"}
    db.get_workspace_config.return_value = {}
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "2.2"}
    with (
        patch_modules({"src.core.db": db}),
        patch.object(handlers, "_persist_standup", return_value=42) as persist,
        patch.object(handlers, "state_store"),
        patch.object(handlers, "fire_webhooks"),
        patch.object(handlers, "edit_rule_text", return_value=""),
        patch.object(handlers, "_daily_thread_parent", return_value="1.1"),
        patch("src.core.scheduler.standup_local_date", return_value=date(2026, 11, 2)),
        patch("src.modules.standup.workflow.evaluate_rules"),
    ):

        def complete(answers, *, editing_standup_id=None, notify_on_report=True):
            db.get_standup_schedule.return_value["notify_on_report"] = notify_on_report
            db.get_active_members.return_value = [{"user_id": "U1", "real_name": "Ada"}]
            session = UserSession(
                cache_key="T1:U1",
                team_id="T1",
                channel="C1",
                schedule_id=7,
                compass_tasks=[],
                answers=answers,
                editing_standup_id=editing_standup_id,
            )
            handlers._complete_standup("U1", session, client)
            posts = [call.kwargs for call in client.chat_postMessage.call_args_list if call.kwargs["channel"] == "C1"]
            assert len(posts) == 1
            return posts[0], persist

        yield complete


def test_legacy_capture_without_compass_tasks_posts_modern_layout_and_canonical_ticket_link(complete_legacy):
    answers = ["TECH-121: Terminé la validación del pipeline.", "TECH-121: Desplegar a producción.", "Ninguno"]

    post, persist = complete_legacy(answers)

    blocks = post.get("blocks", [])
    assert [block["type"] for block in blocks] == ["header", "context", "section", "divider", "section"]
    assert blocks[0]["text"]["text"] == "Daily Standup"
    assert "Sin bloqueos" in blocks[1]["elements"][0]["text"]
    link = "<https://compass.zubale.com/portal/tasks/TECH-121|TECH-121>"
    assert blocks[2]["text"]["text"] == f"*Avances*\n{link}: Terminé la validación del pipeline."
    assert blocks[4]["text"]["text"] == f"*Foco de hoy*\n{link}: Desplegar a producción."
    assert post["text"].count(link) == 2
    assert "/requests/" not in str(post)
    assert post["thread_ts"] == "1.1"
    assert post["unfurl_links"] is False
    assert persist.call_args.args[2] == answers


@pytest.mark.parametrize(
    "key",
    ["TECH--121", "tech-121", "TECH-abc", "TECH-121extra", "TECH-121-", "TECH-121-extra", "bad-TECH-121", "TECH-121_"],
)
def test_legacy_malformed_keys_stay_plain(complete_legacy, key):
    post, _ = complete_legacy([f"Validé {key}.", f"Continuar {key}.", "Ninguno"])

    assert key in post["text"]
    assert key in post["blocks"][2]["text"]["text"]
    assert "https://compass.zubale.com" not in str(post)


def test_legacy_edit_posts_modern_avance_without_notifying_or_changing_history(complete_legacy):
    post, persist = complete_legacy(
        ["TECH-121: Validación terminada.", "Desplegar.", "Necesito acceso a producción."],
        editing_standup_id=42,
        notify_on_report=False,
    )

    assert post["text"].startswith("✏️ *Avance editado*\n")
    assert "<@U1>" not in str(post)
    assert post["blocks"][1]["elements"][0]["text"] == "*Ada* · Con bloqueos · ✏️ Avance editado"
    assert post["blocks"][-1]["text"]["text"] == "*Bloqueos*\nNecesito acceso a producción."
    assert "update" not in str(post).lower()
    assert "Pulse" not in str(post)
    persist.assert_not_called()


@pytest.mark.parametrize(
    "reference",
    [
        "<https://compass.zubale.com/portal/tasks/TECH-121|TECH-121>",
        "<https://compass.zubale.com/requests/TECH-121|TECH-121>",
        "https://compass.zubale.com/requests/TECH-121",
    ],
)
def test_legacy_edit_keeps_ticket_links_canonical_without_nesting(complete_legacy, reference):
    post, _ = complete_legacy([f"Validé {reference}.", "Desplegar.", "Ninguno"], editing_standup_id=42)

    expected = "Validé <https://compass.zubale.com/portal/tasks/TECH-121|TECH-121>."
    assert post["blocks"][2]["text"]["text"] == f"*Avances*\n{expected}"
    assert expected in post["text"]
    assert "/requests/" not in str(post)
