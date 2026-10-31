"""Standup module.

Registered through the module contract rather than wired directly into
main.py, so enabling, disabling or removing it is a registry change.
"""

from __future__ import annotations

from pathlib import Path

from src.core.modules import ModuleSpec, NavItem
from src.modules.standup.compass_context import SnapshotCompassClient, compass_context_for_members
from src.modules.standup.dashboard import register_routes
from src.modules.standup.handlers import claim_dm, claim_dm_command, on_channel_join, register_handlers


def configure_compass_context() -> None:
    """Attach the standup-owned snapshot adapter to core's generic seam."""
    from src.core.scheduler import register_compass_context

    register_compass_context(SnapshotCompassClient, compass_context_for_members)


def configure_owner_health_check() -> None:
    """Attach the standup-owned owner health-check job builder to core's seam.

    Core's scheduler calls the builder when it registers each schedule's jobs;
    this keeps the dependency module→core, never core→module.
    """
    from src.core.scheduler import register_owner_health_check_builder
    from src.modules.standup.owner_healthcheck import register_owner_health_check

    register_owner_health_check_builder(register_owner_health_check)


configure_compass_context()
configure_owner_health_check()


MODULE = ModuleSpec(
    name="standup",
    required_scopes=(),
    migrations_dir=Path(__file__).parent / "migrations",
    register_slack=register_handlers,
    register_routes=register_routes,
    plan_jobs=None,
    claim_dm=claim_dm,
    claim_dm_command=claim_dm_command,
    on_channel_join=on_channel_join,
    purge=None,
    nav=(NavItem(label="Standups", path="/"),),
    default_enabled=True,
    delegable=True,
    help_lines=(
        "`/standup`: start your standup now",
        "`/skip`: skip today's standup",
        "In a DM with me, send `standup`, `skip`, `I'm away`, `I'm back`, `help` "
        "or `timezone America/New_York` as a message on its own",
        "While answering, send `pass` to leave a question blank. Press *Edit my answers* to change what you sent",
    ),
)
