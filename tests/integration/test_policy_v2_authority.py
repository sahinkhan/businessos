"""PostgreSQL proof that Policy V2 uses typed live rows in the caller UOW."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from businessos_identity import AuthenticatedPrincipalBinding, PrincipalIdentity
from businessos_identity.authority import DatabaseMembershipAuthority
from businessos_policy.delegation_authority import PolicyDelegationActionAuthority
from businessos_policy.v2_runtime import PolicyV2Service
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from businessos.bootstrap import create_application
from businessos.context import RequestContext, TenantContext
from businessos.messages import handler_transaction_view
from businessos.modules import discover_modules
from businessos.persistence.uow import SQLAlchemyUnitOfWork
from businessos.sdk import BusinessOSError, ResourceLocator, ResourceOwnerFacts
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase2_foundations import AllowAllPolicy, _seed_tenant, _settings


class _OwnerProvider:
    def __init__(self, owner: ResourceOwnerFacts) -> None:
        self.owner = owner

    async def read_locked_facts(self, action: str) -> ResourceOwnerFacts:
        assert action == "order.read"
        return self.owner


class _OwnerResources:
    def __init__(self, owner: ResourceOwnerFacts) -> None:
        self.provider = _OwnerProvider(owner)

    def resolve_owner(self, namespace: str, version: str) -> Any:
        assert namespace == "example.order" and version == "1"
        return SimpleNamespace(
            ownership=SimpleNamespace(resource_namespace=namespace, owner_module_id="example")
        )

    def assert_owner_handler(
        self, locator: ResourceLocator, request: RequestContext, tx: object
    ) -> None:
        return None

    async def resolve_provider(
        self, locator: ResourceLocator, kind: str, request: RequestContext, tx: object
    ) -> _OwnerProvider:
        assert kind == "facts"
        return self.provider


class _UnavailableClassification:
    async def resolve(self, key: object) -> object:
        raise BusinessOSError("not_found", "Classification unavailable", status_code=404)


def _raw(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_policy_v2_typed_assignment_window_and_live_membership(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        _settings(postgres_database.runtime_url),
        modules=tuple(discover_modules()),
        authorizer=Authorizer(AllowAllPolicy()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id, actor_id, role_id, record_id = uuid4(), uuid4(), uuid4(), uuid4()
    _seed_tenant(postgres_database.migration_url, tenant_id, "policy-v2-real-rows")
    now = datetime.now(UTC)
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO platform_identity.users (id, tenant_id, email, display_name) "
                "VALUES (%s, %s, %s, 'Policy V2 actor')",
                (actor_id, tenant_id, f"{actor_id}@example.test"),
            )
            cursor.execute(
                "INSERT INTO platform_identity.service_accounts "
                "(id, tenant_id, name, credential_secret_reference) "
                "VALUES (%s, %s, 'policy-v2-service', 'test-secret-ref')",
                (actor_id, tenant_id),
            )
            for principal_type in ("user", "service_account"):
                cursor.execute(
                    "INSERT INTO platform_identity.memberships "
                    "(id, tenant_id, principal_id, principal_type, status, "
                    "valid_from, valid_until) "
                    "VALUES (%s, %s, %s, %s, 'active', %s, %s)",
                    (
                        uuid4(),
                        tenant_id,
                        actor_id,
                        principal_type,
                        now - timedelta(days=1),
                        now + timedelta(days=1),
                    ),
                )
            cursor.execute(
                "INSERT INTO platform_policy.permissions (code, name, category) "
                "VALUES ('order.read', 'Read order', 'order')"
            )
            cursor.execute(
                "INSERT INTO platform_policy.roles (id, tenant_id, code, name) "
                "VALUES (%s, %s, 'reader', 'Reader')",
                (role_id, tenant_id),
            )
            cursor.execute(
                "INSERT INTO platform_policy.role_permissions "
                "(id, tenant_id, role_id, permission_code) VALUES (%s, %s, %s, 'order.read')",
                (uuid4(), tenant_id, role_id),
            )
            cursor.execute(
                "INSERT INTO platform_policy.subject_role_assignments "
                "(id, tenant_id, subject_id, subject_type, role_id, scope_type, "
                "valid_from, valid_to) "
                "VALUES (%s, %s, %s, 'user', %s, 'tenant', %s, %s)",
                (
                    uuid4(),
                    tenant_id,
                    actor_id,
                    role_id,
                    now - timedelta(days=1),
                    now + timedelta(days=1),
                ),
            )

    owner = ResourceOwnerFacts(
        tenant_id=tenant_id,
        namespace="example.order",
        record_id=record_id,
        owner_module_id="example",
        contract_version="1",
        lifecycle="current",
        facts={"attributes": {"risk": "low"}},
    )
    resources = _OwnerResources(owner)
    locator = ResourceLocator("example.order", "1", record_id, tenant_id)
    engine = create_async_engine(postgres_database.runtime_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        authorities: dict[str, tuple[PolicyV2Service, RequestContext, TenantContext]] = {}
        for principal_type, expected in (("user", True), ("service_account", False)):
            tenant = TenantContext(uuid4(), tenant_id, actor_id)
            request = RequestContext(tenant=tenant)
            binding = AuthenticatedPrincipalBinding(
                request,
                PrincipalIdentity(
                    tenant_id=tenant_id,
                    principal_id=actor_id,
                    principal_type=principal_type,
                    authentication_strength="password",
                ),
            )
            service = PolicyV2Service(
                binding,
                DatabaseMembershipAuthority(),
                resources,  # type: ignore[arg-type]
                PolicyDelegationActionAuthority(),
                {"order.read": ("example.order", "1")},
                _UnavailableClassification(),  # type: ignore[arg-type]
            )
            authorities[principal_type] = (service, request, tenant)
            async with SQLAlchemyUnitOfWork(sessions, tenant) as uow:
                result = await service.authorize_read(
                    request, handler_transaction_view(uow), "order.read", locator
                )
                assert result.evidence.allowed is expected
                assert result.evidence.principal.principal_type == principal_type

        with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO platform_policy.support_access_grants "
                    "(id, tenant_id, support_principal_id, approved_by, reason, "
                    "valid_from, valid_to) "
                    "VALUES (%s, %s, %s, %s, 'legacy untyped', %s, %s)",
                    (
                        uuid4(),
                        tenant_id,
                        actor_id,
                        actor_id,
                        now - timedelta(days=1),
                        now + timedelta(days=1),
                    ),
                )
        user_service, user_request, user_tenant = authorities["user"]
        async with SQLAlchemyUnitOfWork(sessions, user_tenant) as uow:
            legacy = await user_service.authorize_support_access(
                user_request, handler_transaction_view(uow)
            )
            assert not legacy.evidence.allowed

        with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO platform_policy.support_access_grants "
                    "(id, tenant_id, support_principal_id, support_principal_type, "
                    "approved_by, approved_by_type, reason, valid_from, valid_to) "
                    "VALUES (%s, %s, %s, 'user', %s, 'user', 'typed support', %s, %s)",
                    (
                        uuid4(),
                        tenant_id,
                        actor_id,
                        actor_id,
                        now - timedelta(days=1),
                        now + timedelta(days=1),
                    ),
                )
        async with SQLAlchemyUnitOfWork(sessions, user_tenant) as uow:
            typed = await user_service.authorize_support_access(
                user_request, handler_transaction_view(uow)
            )
            assert typed.evidence.allowed
        svc_service, svc_request, svc_tenant = authorities["service_account"]
        async with SQLAlchemyUnitOfWork(sessions, svc_tenant) as uow:
            wrong_type = await svc_service.authorize_support_access(
                svc_request, handler_transaction_view(uow)
            )
            assert not wrong_type.evidence.allowed
        with pytest.raises(RuntimeError, match="Typed support access requires"):
            app.runtime.migrations.downgrade(
                postgres_database.migration_url, revision="policy_0003"
            )
    finally:
        await engine.dispose()
        await app.shutdown()
