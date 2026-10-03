"""Custom entity typed boundaries and adversarial handler authority probes."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from businessos_metadata import MetadataModule
from businessos_metadata.contracts import (
    Comparison,
    FieldDefinition,
    FieldType,
    MetadataLimits,
    ValidationRule,
)
from businessos_metadata.custom_entities import (
    CustomEntityLimits,
    CustomEntityQueryCapabilities,
    CustomEntityScopeKind,
)
from businessos_metadata.custom_entity_definitions import CustomEntityDefinitionSnapshot
from businessos_metadata.custom_entity_store import CustomEntityStore
from businessos_metadata.module import (
    ArchiveCustomEntity,
    CreateCustomEntity,
    ListCustomEntities,
    UpdateCustomEntity,
)
from pydantic import ValidationError

from businessos.activation import ContributionGate
from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError, ConfigurationError
from businessos.handler_invocation import HandlerInvocationKind, internal_issue_handler_invocation
from businessos.messages import HandlingContext
from businessos.resources import ResourceOwnershipRegistry, ResourceTransactionScope


class UntouchedTransaction:
    statements = 0
    messages = 0

    @property
    def persistence(self) -> Any:
        return self

    async def execute(self, *args: object) -> object:
        self.statements += 1
        raise AssertionError("Denied adapter must not reach persistence")

    def add_outbox(self, message: Any) -> None:
        self.messages += 1
        raise AssertionError("Denied adapter must not emit success")


def _validator(
    metadata_limits: MetadataLimits | None = None, entity_limits: CustomEntityLimits | None = None
) -> Any:
    store = CustomEntityStore(
        metadata_limits or MetadataLimits(), entity_limits or CustomEntityLimits()
    )
    return store._values  # pyright: ignore[reportPrivateUsage] -- isolated same-owner boundary probe


@pytest.mark.parametrize(
    "kind,good,bad,settings",
    [
        ("text", "bounded", {}, {}),
        ("long_text", "long", [], {}),
        ("integer", 7, True, {}),
        ("boolean", True, 1, {}),
        ("decimal", "12.34", 12.34, {"precision": 6, "scale": 2}),
        (
            "money",
            {"amount": "12.34", "currency": "USD"},
            {"amount": "NaN", "currency": "USD"},
            {"precision": 6, "scale": 2},
        ),
        ("enum", "open", "unknown", {"enum_choices": ("open", "closed")}),
        ("uuid", "e02a427b-ce8d-f362-7d34-0e84cc9ea362", "wrong", {}),
        ("date", "2026-10-03", "2026-02-30", {}),
        ("instant", "2026-10-03T01:02:03Z", "2026-10-03T01:02:03", {}),
        ("email", "person@example.com", "person@", {}),
        ("phone", "+880 12345678", "call me", {}),
        ("url", "https://example.com/a", "javascript:alert(1)", {}),
    ],
)
def test_values_reuse_certified_literal_grammar(
    kind: str, good: Any, bad: Any, settings: dict[str, Any]
) -> None:
    field = FieldDefinition(
        field_id=uuid4(),
        name="custom_value",
        value_type=FieldType(kind),
        nullable=False,
        **settings,
    )
    snapshot = CustomEntityDefinitionSnapshot(fields=(field,))
    validate = _validator()
    assert validate(snapshot, {str(field.field_id): good}, uuid4())[0]
    with pytest.raises((BusinessOSError, ValueError)):
        validate(snapshot, {str(field.field_id): bad}, uuid4())
    with pytest.raises(BusinessOSError):
        validate(snapshot, {}, uuid4())
    with pytest.raises(BusinessOSError):
        validate(snapshot, {str(uuid4()): good}, uuid4())


@pytest.mark.parametrize("kind", list(CustomEntityScopeKind))
def test_scope_uses_only_exact_trusted_context_fields(kind: CustomEntityScopeKind) -> None:
    tenant = TenantContext(installation_id=uuid4(), tenant_id=uuid4(), principal_id=uuid4())
    if kind is CustomEntityScopeKind.TENANT:
        assert kind.trusted_id(tenant) == tenant.tenant_id
    else:
        with pytest.raises(BusinessOSError):
            kind.trusted_id(tenant)
        value = uuid4()
        attribute = (
            "active_company_id" if kind is CustomEntityScopeKind.COMPANY else f"{kind.value}_id"
        )
        changes: dict[str, Any] = {attribute: value}
        assert kind.trusted_id(replace(tenant, **changes)) == value


@pytest.mark.parametrize(
    "injected",
    [
        "tenant_id",
        "scope_id",
        "revision_id",
        "revision_digest",
        "created_by",
        "instance_id",
        "lifecycle",
        "created_at",
    ],
)
def test_create_boundary_rejects_caller_authority(injected: str) -> None:
    with pytest.raises(ValidationError):
        CreateCustomEntity.model_validate(
            {"entity_type_id": uuid4(), "values": [], injected: str(uuid4())}
        )


@pytest.mark.parametrize("operation", ["filter", "sort", "search", "uniqueness", "analytics"])
def test_unsupported_queries_fail_explicitly(operation: str) -> None:
    with pytest.raises(BusinessOSError, match="unsupported"):
        CustomEntityQueryCapabilities().require(operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update", "archive", "read", "export", "list"])
@pytest.mark.parametrize(
    "attack",
    ["missing", "fake", "stale", "task", "request", "transaction", "kind", "owner", "generation"],
)
async def test_raw_custom_entity_store_has_no_invocation_authority(
    operation: str, attack: str
) -> None:
    gate = ContributionGate()
    owners = ResourceOwnershipRegistry(gate)
    generation = gate.reserve("foundation.metadata")
    owners.stage(MetadataModule().manifest, generation)
    gate.publish(generation)
    request = RequestContext(
        tenant=TenantContext(installation_id=uuid4(), tenant_id=uuid4(), principal_id=uuid4())
    )
    unit = UntouchedTransaction()

    async def resolve(key: object) -> object:
        return owners

    context = HandlingContext(request, SimpleNamespace(resolve=resolve), unit)  # type: ignore[arg-type]
    kind = (
        HandlerInvocationKind.COMMAND
        if operation in {"create", "update", "archive"}
        else HandlerInvocationKind.QUERY
    )
    identity = uuid4()
    store = CustomEntityStore(MetadataLimits(), CustomEntityLimits())

    async def invoke() -> None:
        if operation == "create":
            await store.create(CreateCustomEntity(entity_type_id=identity, values=()), context)
        elif operation in {"update", "archive"}:
            cmd = (
                ArchiveCustomEntity(instance_id=identity, expected_version=1)
                if operation == "archive"
                else UpdateCustomEntity(instance_id=identity, expected_version=1, values=())
            )
            await store.mutate(cmd, context, archive=operation == "archive")
        elif operation == "list":
            await store.list(ListCustomEntities(entity_type_id=identity), context)
        elif operation == "export":
            await store.export(identity, context)
        else:
            await store.read(identity, context)

    async def deny() -> None:
        with pytest.raises((PermissionError, ConfigurationError)):
            await invoke()
        assert unit.statements == unit.messages == 0
        assert context.emitted_events == ()

    issued_generation = generation
    if attack == "owner":
        issued_generation = gate.reserve("foundation.party")
    elif attack == "generation":
        await gate.close_and_drain(generation, timeout_seconds=1)
        owners.remove_owner_generation(generation)
        generation = gate.reserve("foundation.metadata")
        owners.stage(MetadataModule().manifest, generation)
        gate.publish(generation)
    async with ResourceTransactionScope(gate, request, "foundation.metadata", generation) as scope:
        scope.bind_transaction(unit)
        with internal_issue_handler_invocation(
            owner_module_id=issued_generation.owner,
            generation=issued_generation,
            invocation_kind=(
                HandlerInvocationKind.QUERY
                if kind is HandlerInvocationKind.COMMAND
                else HandlerInvocationKind.COMMAND
            )
            if attack == "kind"
            else kind,
            direct_dependencies=(),
            request=request,
            transaction=unit,
        ) as binding:
            context.invocation = binding
            if attack == "missing":
                context.invocation = None
            elif attack == "fake":
                forged: Any = SimpleNamespace(owner_module_id="foundation.metadata")
                context.invocation = forged
            elif attack == "request":
                context.request = replace(request)
            elif attack == "transaction":
                context.unit_of_work = UntouchedTransaction()
            if attack == "task":
                await asyncio.create_task(deny())
            elif attack != "stale":
                await deny()
        if attack == "stale":
            await deny()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {"arbitrary": []}, [], None])
def test_document_rejects_non_literals(value: Any) -> None:
    field = FieldDefinition(
        field_id=uuid4(), name="value", value_type=FieldType.TEXT, nullable=False
    )
    snapshot = CustomEntityDefinitionSnapshot(fields=(field,))
    validate = _validator()
    with pytest.raises((BusinessOSError, ValueError)):
        validate(snapshot, {str(field.field_id): value}, uuid4())


def test_reference_conditional_rule_and_document_reference_budgets() -> None:
    tenant = uuid4()
    label = FieldDefinition(field_id=uuid4(), name="label", value_type=FieldType.TEXT)
    reference = FieldDefinition(
        field_id=uuid4(),
        name="link",
        value_type=FieldType.REFERENCE,
        reference_namespace="foundation.metadata.custom_entity",
        reference_contract_version="1",
    )
    snapshot = CustomEntityDefinitionSnapshot(
        fields=(label, reference),
        rules=(
            ValidationRule(
                left_field="label",
                comparison=Comparison.EQ,
                right_literal="linked",
                require_field="link",
            ),
        ),
    )
    validate = _validator()
    with pytest.raises(BusinessOSError):
        validate(snapshot, {str(label.field_id): "linked"}, tenant)
    values: dict[str, Any] = {
        str(label.field_id): "linked",
        str(reference.field_id): {
            "tenant_id": str(tenant),
            "resource_namespace": "foundation.metadata.custom_entity",
            "contract_version": "1",
            "record_id": str(uuid4()),
        },
    }
    assert len(validate(snapshot, values, tenant)[1]) == 1
    no_refs = _validator(entity_limits=CustomEntityLimits(max_references=0))
    with pytest.raises(BusinessOSError, match="Reference count"):
        no_refs(snapshot, values, tenant)
    small_doc = _validator(metadata_limits=MetadataLimits(max_document_bytes=1024))
    with pytest.raises(BusinessOSError, match="published schema"):
        small_doc(snapshot, {str(label.field_id): "x" * 2048}, tenant)
    small_fields = _validator(metadata_limits=MetadataLimits(max_fields=1))
    with pytest.raises(ValueError, match="count quota"):
        small_fields(snapshot, values, tenant)


def test_duplicate_fields_and_bigint_bounds_are_boundary_errors() -> None:
    from businessos.sdk import CustomFieldValue

    value = CustomFieldValue(field_id=uuid4(), value="x")
    with pytest.raises(ValidationError, match="Duplicate"):
        CreateCustomEntity(entity_type_id=uuid4(), values=(value, value))
    for version in (0, -1, True, 2**63 - 1, 2**63):
        with pytest.raises(ValidationError):
            ArchiveCustomEntity(instance_id=uuid4(), expected_version=version)
