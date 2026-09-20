"""Enforce typed, tenant-owned device principals.

Revision ID: identity_0002
Revises: identity_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "identity_0002"
down_revision: str | Sequence[str] | None = "identity_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("principal_type", sa.String(length=30), server_default="user", nullable=False),
        schema="platform_identity",
    )
    op.create_check_constraint(
        "device_principal_type",
        "devices",
        "principal_type IN ('user','service_account')",
        schema="platform_identity",
    )
    op.execute(
        """
        CREATE FUNCTION platform_identity.validate_device_principal()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.principal_type = 'user' THEN
            IF NOT EXISTS (
              SELECT 1 FROM platform_identity.users
              WHERE tenant_id = NEW.tenant_id AND id = NEW.principal_id AND active
            ) THEN
              RAISE EXCEPTION 'active tenant device principal does not exist'
                USING ERRCODE = '23503';
            END IF;
          ELSIF NEW.principal_type = 'service_account' THEN
            IF NOT EXISTS (
              SELECT 1 FROM platform_identity.service_accounts
              WHERE tenant_id = NEW.tenant_id AND id = NEW.principal_id AND active
            ) THEN
              RAISE EXCEPTION 'active tenant device principal does not exist'
                USING ERRCODE = '23503';
            END IF;
          ELSE
            RAISE EXCEPTION 'invalid device principal type' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER devices_validate_principal
        BEFORE INSERT OR UPDATE OF tenant_id, principal_id, principal_type
        ON platform_identity.devices
        FOR EACH ROW EXECUTE FUNCTION platform_identity.validate_device_principal()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS devices_validate_principal ON platform_identity.devices")
    op.execute("DROP FUNCTION IF EXISTS platform_identity.validate_device_principal()")
    op.drop_constraint(
        "device_principal_type", "devices", schema="platform_identity", type_="check"
    )
    op.drop_column("devices", "principal_type", schema="platform_identity")
