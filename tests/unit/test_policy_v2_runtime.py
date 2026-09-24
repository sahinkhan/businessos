"""Focused fail-closed proofs for the Policy V2 same-transaction port."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from businessos_identity import (
    AUTHENTICATED_PRINCIPAL,
    MEMBERSHIP_AUTHORITY,
    AuthenticatedPrincipalBinding,
    PrincipalIdentity,
)
from businessos_policy import (
    AuthorizationOperationFactsV2,
    DecisionMode,
    DecisionReason,
    FieldAccessType,
    GrantSupportAccessCommand,
    PolicyClassificationFactsV2,
    PolicyModule,
)
from businessos_policy.models import SUBJECT_ROLE_ASSIGNMENTS
from businessos_policy.v2_runtime import PolicyV2Service
from sqlalchemy import select

from businessos.sdk import (
    BusinessOSError,
    RequestContext,
    ResourceLocator,
    ResourceOwnerFacts,
    TenantContext,
)


class _Memberships:
    def __init__(self, principal_type: str = "user", active: bool = True) -> None:
        self.principal_type = principal_type
        self.active = active
        self.instants: list[datetime] = []

    async def lock_current(
        self, persistence: object, tenant_id: UUID, principal: Any
    ) -> tuple[Any, datetime]:
        instant = datetime.now(UTC)
        self.instants.append(instant)
        if not self.active or principal.principal_type != self.principal_type:
            raise BusinessOSError("forbidden", "Inactive membership", status_code=403)
        return SimpleNamespace(is_effective=lambda at: True), instant

    async def lock_many(
        self,
        persistence: object,
        tenant_id: UUID,
        principals: tuple[Any, ...],
        evaluated_at: datetime,
        valid_from: datetime,
        valid_until: datetime,
    ) -> tuple[()]:
        self.instants.append(evaluated_at)
        if not self.active or any(
            item.principal_type != self.principal_type for item in principals
        ):
            raise BusinessOSError("forbidden", "Inactive membership", status_code=403)
        assert evaluated_at == valid_from and valid_until > evaluated_at
        return ()


class _Authority:
    def __init__(self) -> None:
        self.tenants: list[UUID] = []

    async def acquire(self, tenant_id: UUID, persistence: object) -> None:
        self.tenants.append(tenant_id)


class _Transaction:
    def __init__(self) -> None:
        self.persistence: Any = object()
        self.outbox: list[object] = []

    def add_outbox(self, message: object) -> None:
        self.outbox.append(message)


class _Provider:
    def __init__(self, owner: ResourceOwnerFacts) -> None:
        self.owner = owner
        self.actions: list[str] = []

    async def read_locked_facts(self, action: str) -> ResourceOwnerFacts:
        self.actions.append(action)
        return self.owner


class _Resources:
    def __init__(self, owner: ResourceOwnerFacts) -> None:
        self.provider = _Provider(owner)
        self.classification_owner: ResourceOwnerFacts | None = None
        self.active = True
        self.owner_handler = True

    def resolve_owner(self, namespace: str, version: str) -> Any:
        if (
            namespace == "foundation.governance.data-classification"
            and version == "2"
            and self.classification_owner is not None
        ):
            return SimpleNamespace(
                ownership=SimpleNamespace(owner_module_id="foundation.governance")
            )
        if not self.active or namespace != "example.order" or version != "1":
            raise BusinessOSError("not_found", "Owner unavailable", status_code=404)
        return SimpleNamespace(
            ownership=SimpleNamespace(resource_namespace=namespace, owner_module_id="example")
        )

    def assert_owner_handler(
        self, locator: ResourceLocator, request: RequestContext, transaction: object
    ) -> None:
        if not self.owner_handler:
            raise BusinessOSError("forbidden", "Wrong owner handler", status_code=403)

    async def resolve_provider(
        self, locator: ResourceLocator, kind: str, request: RequestContext, transaction: object
    ) -> _Provider:
        if locator.namespace == "foundation.governance.data-classification":
            if self.classification_owner is None:
                raise BusinessOSError("not_found", "Classification unavailable", status_code=404)
            return _Provider(self.classification_owner)
        if not self.active or kind != "facts":
            raise BusinessOSError("not_found", "Owner unavailable", status_code=404)
        return self.provider


class _Dependencies:
    def __init__(self) -> None:
        self.provider: object | None = None

    async def resolve(self, key: object) -> object:
        if self.provider is not None:
            return self.provider
        raise BusinessOSError("not_found", "Classification unavailable", status_code=404)


@pytest.mark.asyncio
async def test_support_grant_rejects_wrong_typed_target_before_write() -> None:
    service, request, _, _, membership, _ = _harness()
    assert request.tenant is not None
    actor_id = request.tenant.principal_id
    tenant_id = request.tenant.tenant_id
    binding = AuthenticatedPrincipalBinding(
        request,
        PrincipalIdentity(
            tenant_id=tenant_id,
            principal_id=actor_id,
            principal_type="user",
            authentication_strength="password",
        ),
    )
    writes: list[object] = []

    class _Persistence:
        async def execute(self, statement: object) -> None:
            writes.append(statement)

    class _Scope:
        async def resolve(self, key: object) -> object:
            if key is AUTHENTICATED_PRINCIPAL:
                return binding
            if key is MEMBERSHIP_AUTHORITY:
                return membership
            raise AssertionError("Unexpected dependency")

    module = PolicyModule()
    module.delegation_authority = service._authority
    events: list[object] = []
    context = SimpleNamespace(
        request=request,
        dependencies=_Scope(),
        unit_of_work=SimpleNamespace(persistence=_Persistence()),
        emit=events.append,
    )
    command = GrantSupportAccessCommand(
        tenant_id=tenant_id,
        support_principal_id=uuid4(),
        support_principal_type="service_account",
        reason="Investigate incident",
        valid_to=datetime.now(UTC) + timedelta(hours=1),
    )
    with pytest.raises(BusinessOSError, match="Inactive membership"):
        await module._grant_support_access(command, context)  # type: ignore[arg-type]
    assert not writes and not events
    assert module.delegation_authority.tenants == [tenant_id]  # type: ignore[attr-defined]


def _harness(
    *,
    principal_type: str = "user",
    company_id: UUID | None = None,
    operation: AuthorizationOperationFactsV2 | None = None,
    assignment_type: str | None = "user",
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> tuple[PolicyV2Service, RequestContext, _Transaction, _Resources, _Memberships, UUID]:
    tenant_id, actor_id, record_id, role_id = uuid4(), uuid4(), uuid4(), uuid4()
    request = RequestContext(
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id,
            principal_id=actor_id,
            active_company_id=company_id,
        )
    )
    binding = AuthenticatedPrincipalBinding(
        request,
        PrincipalIdentity(
            tenant_id=tenant_id,
            principal_id=actor_id,
            principal_type=principal_type,
            authentication_strength="password",
        ),
    )
    owner = ResourceOwnerFacts(
        tenant_id=tenant_id,
        namespace="example.order",
        record_id=record_id,
        owner_module_id="example",
        contract_version="1",
        lifecycle="current",
        facts={
            "company_id": company_id,
            "record_owner_id": actor_id,
            "record_owner_type": "user",
            "attributes": {"risk": "low"},
            **(
                {
                    "normalized_operation": {
                        "action": operation.action,
                        "amount": operation.amount,
                        "currency": operation.currency,
                        "quantity": operation.quantity,
                        "target_state": operation.target_state,
                        "attributes": dict(operation.attributes),
                    }
                }
                if operation is not None
                else {}
            ),
        },
    )
    resources = _Resources(owner)
    membership = _Memberships(principal_type)
    authority = _Authority()
    service = PolicyV2Service(
        binding,
        membership,
        resources,  # type: ignore[arg-type]
        authority,  # type: ignore[arg-type]
        {
            "order.read": ("example.order", "1"),
            "order.approve": ("example.order", "1"),
            "field.read": ("example.order", "1"),
        },
        _Dependencies(),  # type: ignore[arg-type]
    )
    now = datetime.now(UTC)
    assignment: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "subject_id": actor_id,
        "subject_type": assignment_type,
        "role_id": role_id,
        "scope_type": "company" if company_id else "tenant",
        "scope_id": company_id,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "created_at": now,
    }

    async def rows(transaction: object, statement: Any) -> list[dict[str, object]]:
        table = statement.get_final_froms()[0].name
        if table == "subject_role_assignments":
            return [assignment] if assignment_type == principal_type else []
        if table == "role_permissions":
            return [{"role_id": role_id, "permission_code": "order.read"}]
        return []

    service._rows = rows  # type: ignore[method-assign]
    return service, request, _Transaction(), resources, membership, role_id


def _locator(resources: _Resources) -> ResourceLocator:
    owner = resources.provider.owner
    return ResourceLocator(
        owner.namespace, owner.contract_version, owner.record_id, owner.tenant_id
    )


@pytest.mark.asyncio
async def test_typed_principal_and_live_membership_fail_closed() -> None:
    for wrong_type in ("service_account", "device"):
        service, request, transaction, resources, membership, _ = _harness(
            principal_type=wrong_type, assignment_type="user"
        )
        denied = await service.authorize_read(
            request, transaction, "order.read", _locator(resources)
        )
        assert not denied.evidence.allowed
        assert denied.evidence.reason is DecisionReason.NO_ACTIVE_ROLE
        assert membership.instants[-1] == denied.evidence.decision_at
        assert len(membership.instants) == 1

    service, request, transaction, resources, membership, _ = _harness()
    membership.active = False
    denied = await service.authorize_read(request, transaction, "order.read", _locator(resources))
    assert denied.evidence.reason is DecisionReason.INACTIVE_MEMBERSHIP
    with pytest.raises(BusinessOSError, match="Trusted typed principal required"):
        await service.authorize_read(
            replace(request), transaction, "order.read", _locator(resources)
        )


@pytest.mark.asyncio
async def test_role_effective_window_and_scope_use_owner_facts() -> None:
    company = uuid4()
    service, request, transaction, resources, _, _ = _harness(company_id=company)
    allowed = await service.authorize_read(request, transaction, "order.read", _locator(resources))
    assert allowed.evidence.allowed
    assert allowed.evidence.mode is DecisionMode.READ
    assert resources.provider.actions == ["order.read"]

    resources.provider.owner = replace(
        resources.provider.owner,
        facts={**resources.provider.owner.facts, "company_id": uuid4()},
    )
    denied = await service.authorize_read(request, transaction, "order.read", _locator(resources))
    assert denied.evidence.reason is DecisionReason.NO_ACTIVE_ROLE


@pytest.mark.asyncio
async def test_abac_uses_owner_facts_and_missing_or_malformed_facts_deny() -> None:
    service, request, transaction, resources, _, _ = _harness()
    now = datetime.now(UTC)
    policy: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": _locator(resources).tenant_id,
        "resource_type": "example.order",
        "role_id": None,
        "access_scope": "all",
        "condition_expression": json.dumps(
            {"all": [{"attribute": "risk", "operator": "eq", "value": "low"}]}
        ),
        "created_at": now,
    }
    original_rows = service._rows

    async def rows(tx: object, statement: Any) -> list[dict[str, object]]:
        if statement.get_final_froms()[0].name == "record_policies":
            return [policy]
        return await original_rows(tx, statement)  # type: ignore[arg-type]

    service._rows = rows  # type: ignore[method-assign,assignment]
    locator = _locator(resources)
    allowed = await service.authorize_read(request, transaction, "order.read", locator)
    assert allowed.evidence.allowed
    resources.provider.owner = replace(resources.provider.owner, facts={"attributes": {}})
    absent = await service.authorize_read(request, transaction, "order.read", locator)
    assert absent.evidence.reason is DecisionReason.RECORD_DENIED
    policy["condition_expression"] = "{"  # malformed policy never falls through to allow
    malformed = await service.authorize_read(request, transaction, "order.read", locator)
    assert malformed.evidence.reason is DecisionReason.RECORD_DENIED

    future, request, transaction, resources, _, _ = _harness(
        valid_from=datetime.now(UTC) + timedelta(days=1)
    )
    denied = await future.authorize_read(request, transaction, "order.read", _locator(resources))
    assert denied.evidence.reason is DecisionReason.NO_ACTIVE_ROLE
    expired, request, transaction, resources, _, _ = _harness(
        valid_to=datetime.now(UTC) - timedelta(seconds=1)
    )
    denied = await expired.authorize_read(request, transaction, "order.read", _locator(resources))
    assert denied.evidence.reason is DecisionReason.NO_ACTIVE_ROLE


@pytest.mark.asyncio
async def test_canonical_owner_and_action_mapping_fail_closed() -> None:
    service, request, transaction, resources, _, _ = _harness()
    locator = _locator(resources)
    assert (
        await service.authorize_read(request, transaction, "order.read", locator)
    ).evidence.allowed
    assert not (
        await service.authorize_read(request, transaction, "order.unknown", locator)
    ).evidence.allowed
    resources.provider.owner = replace(resources.provider.owner, tenant_id=uuid4())
    denied = await service.authorize_read(request, transaction, "order.read", locator)
    assert denied.evidence.reason is DecisionReason.OWNER_UNAVAILABLE
    resources.active = False
    assert not (
        await service.authorize_read(request, transaction, "order.read", locator)
    ).evidence.allowed


@pytest.mark.asyncio
async def test_commit_permit_requires_exact_locked_owner_operation() -> None:
    operation = AuthorizationOperationFactsV2("order.read", Decimal("10.00"), "USD")
    service, request, transaction, resources, _, _ = _harness(operation=operation)
    decision = await service.authorize_mutation(
        request, transaction, operation, _locator(resources)
    )
    assert decision.evidence.allowed and decision.permit is not None
    applied: list[AuthorizationOperationFactsV2] = []

    async def owner_apply(
        value: AuthorizationOperationFactsV2,
    ) -> AuthorizationOperationFactsV2:
        applied.append(value)
        return value

    with pytest.raises(BusinessOSError, match="Operation has changed"):
        await decision.permit.apply(
            AuthorizationOperationFactsV2("order.read", Decimal("11.00"), "USD"), owner_apply
        )
    assert not applied and not transaction.outbox
    await decision.permit.apply(operation, owner_apply)
    assert applied == [operation] and len(transaction.outbox) == 1
    with pytest.raises(BusinessOSError, match="Operation authority is invalid"):
        await decision.permit.apply(operation, owner_apply)
    second = await service.authorize_mutation(request, transaction, operation, _locator(resources))
    assert second.permit is not None

    async def changed_apply(
        value: AuthorizationOperationFactsV2,
    ) -> AuthorizationOperationFactsV2:
        return AuthorizationOperationFactsV2(value.action, Decimal("11.00"), "USD")

    with pytest.raises(BusinessOSError, match="Committed operation differs"):
        await second.permit.apply(operation, changed_apply)
    assert len(transaction.outbox) == 1


@pytest.mark.asyncio
async def test_owner_then_policy_then_identity_then_rows_lock_order() -> None:
    operation = AuthorizationOperationFactsV2("order.read", Decimal("1"), "USD")
    service, request, transaction, resources, membership, _ = _harness(operation=operation)
    order: list[str] = []
    original_owner = resources.provider.read_locked_facts
    original_lock = service._authority.acquire
    original_membership = membership.lock_current
    original_rows = service._rows

    async def owner(action: str) -> ResourceOwnerFacts:
        order.append("owner")
        return await original_owner(action)

    async def policy(tenant_id: UUID, persistence: object) -> None:
        order.append("policy")
        await original_lock(tenant_id, persistence)  # type: ignore[arg-type]

    async def identity(
        persistence: object, tenant_id: UUID, principal: Any
    ) -> tuple[Any, datetime]:
        order.append("identity")
        return await original_membership(persistence, tenant_id, principal)

    async def rows(tx: object, statement: Any) -> list[dict[str, object]]:
        order.append("rows")
        return await original_rows(tx, statement)  # type: ignore[arg-type]

    resources.provider.read_locked_facts = owner  # type: ignore[method-assign]
    service._authority.acquire = policy  # type: ignore[method-assign]
    membership.lock_current = identity  # type: ignore[method-assign]
    service._rows = rows  # type: ignore[method-assign,assignment]
    result = await service.authorize_mutation(request, transaction, operation, _locator(resources))
    assert result.evidence.allowed
    assert order[:4] == ["owner", "policy", "identity", "rows"]


@pytest.mark.asyncio
async def test_missing_owner_operation_and_classification_deny() -> None:
    operation = AuthorizationOperationFactsV2("order.read", Decimal("1"), "USD")
    service, request, transaction, resources, _, _ = _harness()
    mutation = await service.authorize_mutation(
        request, transaction, operation, _locator(resources)
    )
    assert mutation.evidence.reason is DecisionReason.OPERATION_MISMATCH
    assert mutation.permit is None
    field = await service.evaluate_field(request, transaction, _locator(resources), "secret")
    assert field.field_access is FieldAccessType.DENY
    assert not field.evidence.allowed


@pytest.mark.asyncio
async def test_approval_decimal_currency_and_live_role_limit() -> None:
    operation = AuthorizationOperationFactsV2("order.approve", Decimal("100.00"), "USD")
    service, request, transaction, resources, _, role_id = _harness(operation=operation)
    tenant_id = _locator(resources).tenant_id
    now = datetime.now(UTC)
    limit: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "action_type": "order.approve",
        "currency": "USD",
        "amount_limit": Decimal("100.00"),
        "role_id": role_id,
        "subject_id": None,
        "valid_from": now - timedelta(days=1),
        "valid_to": now + timedelta(days=1),
        "created_at": now,
    }
    original_rows = service._rows

    async def rows(tx: object, statement: Any) -> list[dict[str, object]]:
        if statement.get_final_froms()[0].name == "approval_limits":
            return [limit]
        return await original_rows(tx, statement)  # type: ignore[arg-type]

    service._rows = rows  # type: ignore[method-assign,assignment]
    locator = _locator(resources)
    equal = await service.evaluate_approval(request, transaction, operation, locator)
    assert equal.evidence.allowed and equal.permit is not None

    limit["amount_limit"] = Decimal("99.99")
    above = await service.evaluate_approval(request, transaction, operation, locator)
    assert above.evidence.reason is DecisionReason.APPROVAL_LIMIT_EXCEEDED
    limit["amount_limit"] = Decimal("100.00")
    limit["currency"] = "EUR"
    wrong_currency = await service.evaluate_approval(request, transaction, operation, locator)
    assert wrong_currency.evidence.reason is DecisionReason.CURRENCY_MISMATCH
    limit["currency"] = "USD"
    limit["valid_to"] = now - timedelta(seconds=1)
    expired = await service.evaluate_approval(request, transaction, operation, locator)
    assert expired.evidence.reason is DecisionReason.APPROVAL_LIMIT_MISSING
    limit["valid_to"] = now + timedelta(days=1)
    limit["subject_id"] = request.tenant.principal_id if request.tenant else uuid4()
    legacy_direct = await service.evaluate_approval(request, transaction, operation, locator)
    assert legacy_direct.evidence.reason is DecisionReason.APPROVAL_LIMIT_MISSING


@pytest.mark.asyncio
async def test_commit_denies_wrong_owner_handler_and_changed_owner_facts() -> None:
    operation = AuthorizationOperationFactsV2("order.read", Decimal("10"), "USD")
    service, request, transaction, resources, _, _ = _harness(
        operation=operation, company_id=uuid4()
    )
    resources.owner_handler = False
    denied = await service.authorize_mutation(request, transaction, operation, _locator(resources))
    assert denied.evidence.reason is DecisionReason.OWNER_UNAVAILABLE
    resources.owner_handler = True
    allowed = await service.authorize_mutation(request, transaction, operation, _locator(resources))
    assert allowed.permit is not None
    resources.provider.owner = replace(
        resources.provider.owner,
        facts={**resources.provider.owner.facts, "company_id": uuid4()},
    )

    async def owner_apply(
        value: AuthorizationOperationFactsV2,
    ) -> AuthorizationOperationFactsV2:
        raise AssertionError("Changed facts must prevent this owner call")

    with pytest.raises(BusinessOSError, match="Live authority changed"):
        await allowed.permit.apply(operation, owner_apply)
    assert not transaction.outbox


@pytest.mark.asyncio
async def test_classified_field_requires_trusted_definition_and_explicit_policy() -> None:
    service, request, transaction, resources, _, role_id = _harness()
    locator = _locator(resources)
    tenant_id = locator.tenant_id
    definition_id = uuid4()
    resources.provider.owner = replace(
        resources.provider.owner,
        facts={**resources.provider.owner.facts, "field_classifications": {"secret": "secret-v1"}},
    )
    resources.classification_owner = ResourceOwnerFacts(
        tenant_id=tenant_id,
        namespace="foundation.governance.data-classification",
        record_id=definition_id,
        owner_module_id="foundation.governance",
        contract_version="2",
        lifecycle="current",
        facts={
            "classification_ref": "secret-v1",
            "definition_version": "1",
            "active": True,
            "sensitive": True,
        },
    )

    class ClassificationProvider:
        async def resolve(
            self, tenant_id: UUID, reference: str, instant: datetime, tx: object
        ) -> PolicyClassificationFactsV2:
            return PolicyClassificationFactsV2(
                tenant_id, reference, "foundation.governance", definition_id, "1", True
            )

    dependencies = _Dependencies()
    dependencies.provider = ClassificationProvider()
    service._dependencies = dependencies  # type: ignore[assignment]
    original_rows = service._rows
    policies: list[dict[str, object]] = []

    async def rows(tx: object, statement: Any) -> list[dict[str, object]]:
        if statement.get_final_froms()[0].name == "field_policies":
            return policies
        return await original_rows(tx, statement)  # type: ignore[arg-type]

    service._rows = rows  # type: ignore[method-assign,assignment]
    absent = await service.evaluate_field(request, transaction, locator, "secret")
    assert absent.evidence.reason is DecisionReason.FIELD_NOT_ALLOWED
    policies.append(
        {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "resource_type": "example.order",
            "field_name": "secret",
            "role_id": role_id,
            "access_type": "read",
            "mask_pattern": None,
            "condition_expression": None,
            "created_at": datetime.now(UTC),
        }
    )
    allowed = await service.evaluate_field(request, transaction, locator, "secret")
    assert allowed.evidence.allowed
    assert allowed.field_access is FieldAccessType.READ
    resources.classification_owner = replace(
        resources.classification_owner,
        facts={**resources.classification_owner.facts, "active": False},
    )
    denied = await service.evaluate_field(request, transaction, locator, "secret")
    assert denied.evidence.reason is DecisionReason.CLASSIFICATION_UNAVAILABLE


def test_operation_facts_reject_float_and_mutable_payloads() -> None:
    with pytest.raises(ValueError, match="finite Decimal"):
        AuthorizationOperationFactsV2("order.approve", 1.2, "USD")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="canonical ISO"):
        AuthorizationOperationFactsV2("order.approve", Decimal("1"), "usd")
    with pytest.raises(ValueError, match="Unsupported Policy V2 fact shape"):
        AuthorizationOperationFactsV2("order.approve", attributes={"unsafe": ["mutable"]})


@pytest.mark.asyncio
async def test_policy_query_bound_fails_closed_for_heavy_tenant() -> None:
    class Persistence:
        async def execute(self, statement: object) -> object:
            return SimpleNamespace(mappings=lambda: [{} for _ in range(257)])

    transaction = SimpleNamespace(persistence=Persistence())
    with pytest.raises(BusinessOSError, match="authority set is too large"):
        await PolicyV2Service._rows(
            transaction,
            select(SUBJECT_ROLE_ASSIGNMENTS),
        )


@pytest.mark.asyncio
async def test_registered_v1_query_is_explicitly_retired() -> None:
    module = PolicyModule()
    with pytest.raises(BusinessOSError, match="Policy V1 lacks trusted live authority"):
        await module._authorize_action(None, None)  # type: ignore[arg-type]
