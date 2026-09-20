"""Enforce typed, tenant-owned identity principals.

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
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM platform_identity.devices AS device
            WHERE NOT EXISTS (
              SELECT 1 FROM platform_identity.users AS principal
              WHERE principal.tenant_id = device.tenant_id
                AND principal.id = device.principal_id AND principal.active
            )
          ) THEN
            RAISE EXCEPTION
              'existing devices must reference active users in the same tenant'
              USING ERRCODE = '23503';
          END IF;

          IF EXISTS (
            SELECT 1 FROM platform_identity.memberships AS membership
            WHERE NOT (
              (membership.principal_type = 'user' AND EXISTS (
                SELECT 1 FROM platform_identity.users
                WHERE tenant_id = membership.tenant_id AND id = membership.principal_id
              )) OR
              (membership.principal_type = 'service_account' AND EXISTS (
                SELECT 1 FROM platform_identity.service_accounts
                WHERE tenant_id = membership.tenant_id AND id = membership.principal_id
              )) OR
              (membership.principal_type = 'device' AND EXISTS (
                SELECT 1 FROM platform_identity.devices
                WHERE tenant_id = membership.tenant_id AND id = membership.principal_id
              ))
            )
          ) THEN
            RAISE EXCEPTION
              'existing memberships must reference principals in the same tenant'
              USING ERRCODE = '23503';
          END IF;

          IF EXISTS (
            SELECT 1 FROM platform_identity.authentication_sessions AS session
            WHERE NOT EXISTS (
              SELECT 1 FROM platform_identity.users AS principal
              WHERE principal.tenant_id = session.tenant_id
                AND principal.id = session.principal_id
            )
          ) THEN
            RAISE EXCEPTION
              'existing authentication sessions must reference users in the same tenant'
              USING ERRCODE = '23503';
          END IF;

          IF EXISTS (
            SELECT 1 FROM platform_identity.mfa_policies
            WHERE minimum_strength NOT IN (
              'unspecified', 'password', 'oidc', 'mfa',
              'phishing_resistant', 'break_glass'
            )
          ) THEN
            RAISE EXCEPTION 'existing MFA policies contain an unsupported strength'
              USING ERRCODE = '23514';
          END IF;
        END $$
        """
    )
    op.create_check_constraint(
        "mfa_policy_minimum_strength",
        "mfa_policies",
        "minimum_strength IN ("
        "'unspecified','password','oidc','mfa','phishing_resistant','break_glass')",
        schema="platform_identity",
    )
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
    op.add_column(
        "authentication_sessions",
        sa.Column("principal_type", sa.String(length=30), server_default="user", nullable=False),
        schema="platform_identity",
    )
    op.create_check_constraint(
        "authentication_session_principal_type",
        "authentication_sessions",
        "principal_type IN ('user','service_account','device')",
        schema="platform_identity",
    )
    op.execute(
        """
        CREATE FUNCTION platform_identity.principal_exists(
          checked_tenant_id uuid,
          checked_principal_type text,
          checked_principal_id uuid,
          require_active boolean DEFAULT false
        ) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
        BEGIN
          IF checked_principal_type = 'user' THEN
            RETURN EXISTS (
              SELECT 1 FROM platform_identity.users
              WHERE tenant_id = checked_tenant_id AND id = checked_principal_id
                AND (NOT require_active OR active)
            );
          ELSIF checked_principal_type = 'service_account' THEN
            RETURN EXISTS (
              SELECT 1 FROM platform_identity.service_accounts
              WHERE tenant_id = checked_tenant_id AND id = checked_principal_id
                AND (NOT require_active OR active)
            );
          ELSIF checked_principal_type = 'device' THEN
            RETURN EXISTS (
              SELECT 1 FROM platform_identity.devices
              WHERE tenant_id = checked_tenant_id AND id = checked_principal_id
                AND (NOT require_active OR active)
            );
          END IF;
          RETURN false;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform_identity.validate_device_principal()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.principal_type NOT IN ('user', 'service_account') OR NOT
            platform_identity.principal_exists(
              NEW.tenant_id, NEW.principal_type, NEW.principal_id, true
            )
          THEN
            RAISE EXCEPTION 'active tenant device principal does not exist'
              USING ERRCODE = '23503';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform_identity.validate_typed_principal()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT platform_identity.principal_exists(
            NEW.tenant_id, NEW.principal_type, NEW.principal_id
          ) THEN
            RAISE EXCEPTION 'tenant principal does not exist' USING ERRCODE = '23503';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform_identity.protect_principal_references()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          principal_kind text := TG_ARGV[0];
        BEGIN
          IF EXISTS (
            SELECT 1 FROM platform_identity.memberships
            WHERE tenant_id = OLD.tenant_id AND principal_type = principal_kind
              AND principal_id = OLD.id
          ) OR EXISTS (
            SELECT 1 FROM platform_identity.authentication_sessions
            WHERE tenant_id = OLD.tenant_id AND principal_type = principal_kind
              AND principal_id = OLD.id
          ) OR (
            principal_kind IN ('user', 'service_account') AND EXISTS (
              SELECT 1 FROM platform_identity.devices
              WHERE tenant_id = OLD.tenant_id AND principal_type = principal_kind
                AND principal_id = OLD.id
            )
          ) THEN
            RAISE EXCEPTION 'principal is referenced by tenant identity records'
              USING ERRCODE = '23001';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
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
        FOR EACH ROW EXECUTE FUNCTION platform_identity.validate_device_principal();

        CREATE TRIGGER memberships_validate_principal
        BEFORE INSERT OR UPDATE OF tenant_id, principal_id, principal_type
        ON platform_identity.memberships
        FOR EACH ROW EXECUTE FUNCTION platform_identity.validate_typed_principal();

        CREATE TRIGGER authentication_sessions_validate_principal
        BEFORE INSERT OR UPDATE OF tenant_id, principal_id, principal_type
        ON platform_identity.authentication_sessions
        FOR EACH ROW EXECUTE FUNCTION platform_identity.validate_typed_principal();

        CREATE TRIGGER users_protect_principal_references
        BEFORE DELETE OR UPDATE OF tenant_id, id ON platform_identity.users
        FOR EACH ROW EXECUTE FUNCTION platform_identity.protect_principal_references('user');

        CREATE TRIGGER service_accounts_protect_principal_references
        BEFORE DELETE OR UPDATE OF tenant_id, id ON platform_identity.service_accounts
        FOR EACH ROW EXECUTE FUNCTION
          platform_identity.protect_principal_references('service_account');

        CREATE TRIGGER devices_protect_principal_references
        BEFORE DELETE OR UPDATE OF tenant_id, id ON platform_identity.devices
        FOR EACH ROW EXECUTE FUNCTION platform_identity.protect_principal_references('device')
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "mfa_policy_minimum_strength",
        "mfa_policies",
        schema="platform_identity",
        type_="check",
    )
    for table in ("users", "service_accounts", "devices"):
        op.execute(
            f"DROP TRIGGER IF EXISTS {table}_protect_principal_references "
            f"ON platform_identity.{table}"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS authentication_sessions_validate_principal "
        "ON platform_identity.authentication_sessions"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS memberships_validate_principal ON platform_identity.memberships"
    )
    op.execute("DROP TRIGGER IF EXISTS devices_validate_principal ON platform_identity.devices")
    op.execute("DROP FUNCTION IF EXISTS platform_identity.protect_principal_references()")
    op.execute("DROP FUNCTION IF EXISTS platform_identity.validate_typed_principal()")
    op.execute("DROP FUNCTION IF EXISTS platform_identity.validate_device_principal()")
    op.execute(
        "DROP FUNCTION IF EXISTS platform_identity.principal_exists(uuid, text, uuid, boolean)"
    )
    op.drop_constraint(
        "authentication_session_principal_type",
        "authentication_sessions",
        schema="platform_identity",
        type_="check",
    )
    op.drop_column("authentication_sessions", "principal_type", schema="platform_identity")
    op.drop_constraint(
        "device_principal_type", "devices", schema="platform_identity", type_="check"
    )
    op.drop_column("devices", "principal_type", schema="platform_identity")
