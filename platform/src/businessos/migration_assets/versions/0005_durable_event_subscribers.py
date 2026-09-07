"""Persist durable event subscriber ownership and delivery obligations.

Revision ID: 0005_durable_event_subscribers
Revises: 0004_strict_migration_inventory
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_durable_event_subscribers"
down_revision: str | Sequence[str] | None = "0004_strict_migration_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_subscriber_obligations",
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("subscriber", sa.String(length=200), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("btrim(event_type) <> ''", name="event_type_nonempty"),
        sa.CheckConstraint("btrim(subscriber) <> ''", name="subscriber_nonempty"),
        sa.CheckConstraint("btrim(owner) <> ''", name="owner_nonempty"),
        sa.PrimaryKeyConstraint(
            "event_type",
            "subscriber",
            name="pk_event_subscriber_obligations",
        ),
        schema="eventing",
    )
    op.execute(
        "REVOKE ALL ON TABLE eventing.event_subscriber_obligations FROM PUBLIC, businessos_app"
    )
    op.execute("GRANT SELECT, INSERT ON eventing.event_subscriber_obligations TO businessos_ops")


def downgrade() -> None:
    op.drop_table("event_subscriber_obligations", schema="eventing")
