"""Policy field decisions consume Governance's locked classification port."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from businessos_data_governance.classification_runtime import DataGovernanceClassificationV2
from businessos_identity import AuthenticatedPrincipalBinding, PrincipalIdentity
from businessos_identity.authority import DatabaseMembershipAuthority
from businessos_policy.delegation_authority import PolicyDelegationActionAuthority
from businessos_policy.models import FieldAccessType
from businessos_policy.v2_contracts import POLICY_CLASSIFICATION_FACTS_V2
from businessos_policy.v2_runtime import PolicyV2Service
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from businessos.context import RequestContext, TenantContext
from businessos.messages import handler_transaction_view
from businessos.persistence.uow import SQLAlchemyUnitOfWork
from businessos.sdk import ResourceLocator, ResourceOwnerFacts
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_adr015_classification_v2 import _application
from tests.integration.test_phase2_foundations import _seed_tenant


class _AdmittedFacts:
    def __init__(
        self,
        facts: ResourceOwnerFacts | None = None,
        *,
        governance: DataGovernanceClassificationV2 | None = None,
        locator: ResourceLocator | None = None,
        request: RequestContext | None = None,
        transaction: object | None = None,
    ) -> None:
        self.facts = facts
        self.governance = governance
        self.locator = locator
        self.request = request
        self.transaction = transaction

    async def read_locked_facts(self, action: str) -> ResourceOwnerFacts:
        if self.facts is not None:
            assert action == "field.read"
            return self.facts
        assert self.governance is not None
        assert self.locator is not None
        assert self.request is not None
        assert self.transaction is not None
        return await self.governance.read_locked_facts(
            self.locator,
            action,
            self.request,
            self.transaction,  # type: ignore[arg-type]
        )


class _Resources:
    def __init__(self, order: ResourceOwnerFacts, governance: DataGovernanceClassificationV2):
        self.order = order
        self.governance = governance

    def resolve_owner(self, namespace: str, version: str) -> Any:
        assert version in ("1", "2")
        if namespace == "example.order":
            return SimpleNamespace(
                ownership=SimpleNamespace(resource_namespace=namespace, owner_module_id="example")
            )
        assert namespace == "foundation.governance.data-classification"
        return SimpleNamespace(
            ownership=SimpleNamespace(
                resource_namespace="foundation.data_governance.data-classification",
                owner_module_id="foundation.data_governance",
            )
        )

    async def resolve_provider(
        self, locator: ResourceLocator, kind: str, request: RequestContext, tx: object
    ) -> _AdmittedFacts:
        assert kind == "facts"
        if locator.namespace == "example.order":
            return _AdmittedFacts(self.order)
        assert locator.namespace == "foundation.governance.data-classification"
        canonical = ResourceLocator(
            "foundation.data_governance.data-classification",
            locator.contract_version,
            locator.record_id,
            locator.tenant_id,
        )
        return _AdmittedFacts(
            governance=self.governance, locator=canonical, request=request, transaction=tx
        )


class _Dependencies:
    def __init__(self, governance: DataGovernanceClassificationV2) -> None:
        self.governance = governance

    async def resolve(self, key: object) -> DataGovernanceClassificationV2:
        assert key == POLICY_CLASSIFICATION_FACTS_V2
        return self.governance


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_policy_field_decision_uses_locked_governance_classification(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id, actor_id, role_id, order_id, definition_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    _seed_tenant(postgres_database.migration_url, tenant_id, "adr015-policy-field")
    now = datetime.now(UTC)
    migration_url = postgres_database.migration_url.replace(
        "postgresql+psycopg://", "postgresql://"
    )
    with psycopg.connect(migration_url) as connection:
        connection.execute(
            "INSERT INTO platform_gov.classification_definitions "
            "(id, code, qualified_ref, name, is_active) "
            "VALUES (%s, 'PERSONAL', 'core:PERSONAL', 'Personal', true)",
            (definition_id,),
        )
        connection.execute(
            "INSERT INTO platform_gov.classification_versions "
            "(id, definition_id, version, valid_from, sensitivity_level, "
            "required_controls, restrictions, mandatory_masking) "
            "VALUES (%s, %s, 1, %s, 3, '{}', '{}', true)",
            (uuid4(), definition_id, now - timedelta(days=1)),
        )
        connection.execute(
            "INSERT INTO platform_identity.users (id, tenant_id, email, display_name) "
            "VALUES (%s, %s, %s, 'Field reader')",
            (actor_id, tenant_id, f"{actor_id}@example.test"),
        )
        connection.execute(
            "INSERT INTO platform_identity.memberships "
            "(id, tenant_id, principal_id, principal_type, status, valid_from, valid_until) "
            "VALUES (%s, %s, %s, 'user', 'active', %s, %s)",
            (uuid4(), tenant_id, actor_id, now - timedelta(days=1), now + timedelta(days=1)),
        )
        connection.execute(
            "INSERT INTO platform_policy.permissions (code, name, category) "
            "VALUES ('field.read', 'Read field', 'field')"
        )
        connection.execute(
            "INSERT INTO platform_policy.roles (id, tenant_id, code, name) "
            "VALUES (%s, %s, 'reader', 'Reader')",
            (role_id, tenant_id),
        )
        connection.execute(
            "INSERT INTO platform_policy.role_permissions "
            "(id, tenant_id, role_id, permission_code) "
            "VALUES (%s, %s, %s, 'field.read')",
            (uuid4(), tenant_id, role_id),
        )
        connection.execute(
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
        field_policy_id = uuid4()
        connection.execute(
            "INSERT INTO platform_policy.field_policies "
            "(id, tenant_id, resource_type, field_name, role_id, access_type) "
            "VALUES (%s, %s, 'example.order', 'secret', %s, 'read')",
            (field_policy_id, tenant_id, role_id),
        )
    tenant = TenantContext(uuid4(), tenant_id, actor_id)
    request = RequestContext(tenant=tenant)
    binding = AuthenticatedPrincipalBinding(
        request,
        PrincipalIdentity(
            tenant_id=tenant_id,
            principal_id=actor_id,
            principal_type="user",
            authentication_strength="password",
        ),
    )
    governance = DataGovernanceClassificationV2()
    owner = ResourceOwnerFacts(
        tenant_id=tenant_id,
        namespace="example.order",
        record_id=order_id,
        owner_module_id="example",
        contract_version="1",
        lifecycle="current",
        facts={"field_classifications": {"secret": "core:PERSONAL"}},
    )
    service = PolicyV2Service(
        binding,
        DatabaseMembershipAuthority(),
        _Resources(owner, governance),  # type: ignore[arg-type]
        PolicyDelegationActionAuthority(),
        {"field.read": ("example.order", "1")},
        _Dependencies(governance),  # type: ignore[arg-type]
    )
    locator = ResourceLocator("example.order", "1", order_id, tenant_id)
    engine = create_async_engine(postgres_database.runtime_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with SQLAlchemyUnitOfWork(sessions, tenant) as uow:
            allowed = await service.evaluate_field(
                request, handler_transaction_view(uow), locator, "secret"
            )
        assert allowed.evidence.allowed
        assert allowed.field_access is FieldAccessType.READ
        with psycopg.connect(migration_url) as connection:
            connection.execute(
                "DELETE FROM platform_policy.field_policies WHERE id = %s", (field_policy_id,)
            )
        async with SQLAlchemyUnitOfWork(sessions, tenant) as uow:
            denied = await service.evaluate_field(
                request, handler_transaction_view(uow), locator, "secret"
            )
        assert not denied.evidence.allowed
        assert denied.field_access is FieldAccessType.DENY
    finally:
        await engine.dispose()
