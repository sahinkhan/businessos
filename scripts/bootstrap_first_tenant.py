"""Offline, one-time first-tenant operation for an authenticated installation operator.

This is deliberately not an ASGI route. Run it only after migrations, with the
separately credentialed ``businessos_ops`` URL supplied by the operator's secret
store. The normal application role still performs the tenant-scoped command.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
from businessos_tenant import DeploymentMode, ProvisionTenant, TenantModule
from sqlalchemy.engine import make_url

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.security import Authorizer

_LOCK_NAME = "businessos.first-tenant.bootstrap"
_PERMISSION = "foundation.tenant.provision"


class BootstrapUnavailableError(RuntimeError):
    """The one-time installation bootstrap cannot proceed."""


class _FirstTenantPolicy:
    def __init__(self, installation_id: UUID, tenant_id: UUID, operator_id: UUID) -> None:
        self._installation_id = installation_id
        self._tenant_id = tenant_id
        self._operator_id = operator_id

    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return (
            principal_id == self._operator_id
            and tenant.principal_id == self._operator_id
            and tenant.installation_id == self._installation_id
            and tenant.tenant_id == self._tenant_id
            and tenant.authentication_strength == "installation-bootstrap"
            and permission == _PERMISSION
        )


async def bootstrap_first_tenant(
    settings: Settings,
    operations_database_url: str,
    command: ProvisionTenant,
    *,
    enabled: bool,
) -> dict[str, object]:
    """Authenticate the operations role, serialize first use, then dispatch normally."""
    if not enabled:
        raise BootstrapUnavailableError("First-tenant bootstrap is disabled")
    runtime_database = make_url(settings.database_url)
    operations_database = make_url(operations_database_url)
    if (
        runtime_database.host,
        runtime_database.port or 5432,
        runtime_database.database,
    ) != (
        operations_database.host,
        operations_database.port or 5432,
        operations_database.database,
    ):
        raise BootstrapUnavailableError("Operations and runtime database targets differ")

    operator_id = uuid5(NAMESPACE_URL, f"businessos:{settings.installation_id}:businessos_ops")
    driver_url = operations_database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    async with await psycopg.AsyncConnection.connect(driver_url) as operations:
        role_result = await operations.execute("SELECT current_user")
        if (await role_result.fetchone()) != ("businessos_ops",):
            raise BootstrapUnavailableError("The businessos_ops database role is required")
        await operations.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (_LOCK_NAME,))
        existing = await operations.execute("SELECT id FROM platform_tenant.tenants LIMIT 1")
        if await existing.fetchone() is not None:
            raise BootstrapUnavailableError("First-tenant bootstrap is already complete")

        app = create_application(
            settings,
            modules=(TenantModule(),),
            authorizer=Authorizer(
                _FirstTenantPolicy(settings.installation_id, command.tenant_id, operator_id)
            ),
        )
        try:
            await app.startup()
            if app.runtime is None:
                raise RuntimeError("Tenant bootstrap runtime is unavailable")
            request = RequestContext(
                tenant=TenantContext(
                    installation_id=settings.installation_id,
                    tenant_id=command.tenant_id,
                    principal_id=operator_id,
                    authentication_strength="installation-bootstrap",
                )
            )
            async with app.container.request_scope() as dependencies:
                result = await app.runtime.messages.command(command, request, dependencies)
        finally:
            await app.shutdown()

        if not isinstance(result, dict):
            raise RuntimeError("Tenant bootstrap returned an invalid result")
        logging.getLogger("businessos.tenant.bootstrap").info(
            "First tenant provisioned",
            extra={
                "tenant_id": str(command.tenant_id),
                "operator_id": str(operator_id),
                "correlation_id": request.correlation_id,
            },
        )
        return cast(dict[str, object], result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision the first BusinessOS tenant offline")
    parser.add_argument("--tenant-id", type=UUID, default=None)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--deployment-mode", choices=[item.value for item in DeploymentMode], required=True
    )
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    if not os.getenv("BOS_DATABASE_URL"):
        parser.error("BOS_DATABASE_URL must be explicitly configured")
    operations_url = os.getenv("BOS_OPERATIONS_DATABASE_URL")
    if not operations_url:
        parser.error("BOS_OPERATIONS_DATABASE_URL must be supplied from an operator secret store")
    command = ProvisionTenant(
        tenant_id=args.tenant_id or uuid4(),
        slug=args.slug,
        name=args.name,
        deployment_mode=args.deployment_mode,
        region=args.region,
    )
    try:
        result = asyncio.run(
            bootstrap_first_tenant(
                Settings(),
                operations_url,
                command,
                enabled=os.getenv("BOS_FIRST_TENANT_BOOTSTRAP_ENABLED") == "true",
            )
        )
    except BootstrapUnavailableError as error:
        raise SystemExit(str(error)) from None
    print(json.dumps({"tenant_id": str(result["tenant_id"]), "status": result["status"]}))


if __name__ == "__main__":
    main()
