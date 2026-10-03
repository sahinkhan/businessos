"""Adversarial Party adapter invocation and SDK resolver capability regressions."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from businessos_metadata import MetadataModule
from businessos_metadata.contracts import MetadataLimits
from businessos_metadata.custom_schema import (
    PublishedSchemaReader,
    internal_configure_schema_reader,
    internal_register_schema_reader,
    internal_start_schema_reader,
    internal_stop_schema_reader,
)
from businessos_party import PartyModule
from businessos_party.custom_fields import (
    ClearPartyCustomValues,
    ExportPartyCustomValues,
    PartyCustomFields,
    ReadPartyCustomValues,
    WritePartyCustomValues,
)

from businessos.activation import ContributionGate
from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError, ConfigurationError
from businessos.handler_invocation import HandlerInvocationKind, internal_issue_handler_invocation
from businessos.messages import HandlingContext
from businessos.resources import ResourceOwnershipRegistry, ResourceTransactionScope


class _UntouchedTransaction:
    statements = 0
    messages = 0

    @property
    def persistence(self) -> Any:
        return self

    async def execute(self, *args: object) -> object:
        self.statements += 1
        raise AssertionError("Denied adapter must not reach persistence")

    def add_outbox(self, *args: object) -> None:
        self.messages += 1
        raise AssertionError("Denied adapter must not emit success")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["write", "clear", "read", "export"])
@pytest.mark.parametrize(
    "attack",
    ["missing", "fake", "stale", "task", "request", "transaction", "kind", "owner", "generation"],
)
async def test_party_adapter_rejects_untrusted_invocations_before_any_effect(
    operation: str, attack: str
) -> None:
    gate = ContributionGate()
    owners = ResourceOwnershipRegistry(gate)
    generation = gate.reserve("foundation.party")
    owners.stage(PartyModule().manifest, generation)
    gate.publish(generation)
    request = RequestContext(
        tenant=TenantContext(installation_id=uuid4(), tenant_id=uuid4(), principal_id=uuid4())
    )
    unit = _UntouchedTransaction()
    dependencies = SimpleNamespace(resolve=None)

    async def resolve(key: object) -> object:
        return owners

    dependencies.resolve = resolve
    context = HandlingContext(request, dependencies, unit)  # type: ignore[arg-type]
    identity = {"tenant_id": request.tenant.tenant_id, "party_id": uuid4()}  # type: ignore[union-attr]
    adapter = PartyCustomFields()
    payload: Any
    if operation == "write":
        payload = WritePartyCustomValues(**identity, expected_version=0, values=())
    elif operation == "clear":
        payload = ClearPartyCustomValues(**identity, expected_version=0)
    else:
        payload = (ReadPartyCustomValues if operation == "read" else ExportPartyCustomValues)(
            **identity
        )
    method = adapter.read if operation in {"read", "export"} else getattr(adapter, operation)
    kind = (
        HandlerInvocationKind.QUERY
        if operation in {"read", "export"}
        else HandlerInvocationKind.COMMAND
    )
    issued_generation = generation
    if attack == "owner":
        issued_generation = gate.reserve("foundation.metadata")
    elif attack == "generation":
        # Reproduce a cached invocation from the replaced Party generation.
        await gate.close_and_drain(generation, timeout_seconds=1)
        owners.remove_owner_generation(generation)
        generation = gate.reserve("foundation.party")
        owners.stage(PartyModule().manifest, generation)
        gate.publish(generation)
    issued_kind = kind
    if attack == "kind":
        issued_kind = (
            HandlerInvocationKind.COMMAND
            if kind is HandlerInvocationKind.QUERY
            else HandlerInvocationKind.QUERY
        )

    async def deny() -> None:
        with pytest.raises((PermissionError, ConfigurationError)):
            await method(payload, context)
        assert unit.statements == unit.messages == 0
        assert context.emitted_events == ()

    async with ResourceTransactionScope(gate, request, "foundation.party", generation) as scope:
        scope.bind_transaction(unit)
        with internal_issue_handler_invocation(
            owner_module_id=issued_generation.owner,
            generation=issued_generation,
            invocation_kind=issued_kind,
            direct_dependencies=(),
            request=request,
            transaction=unit,
        ) as binding:
            context.invocation = binding
            if attack == "missing":
                context.invocation = None
            elif attack == "fake":
                context.invocation = SimpleNamespace(
                    owner_module_id="foundation.party", generation=generation, invocation_kind=kind
                )
            elif attack == "request":
                context.request = replace(request)
            elif attack == "transaction":
                context.unit_of_work = _UntouchedTransaction()
            if attack == "task":
                await asyncio.create_task(deny())
            elif attack != "stale":
                await deny()
        if attack == "stale":
            await deny()


def _instance_graph(root: object) -> list[object]:
    """Traverse stored instance state, containers, bound owners and closures.

    Imported module globals/classes are outside the supported in-process SDK
    capability boundary, as with the existing issued invocation registry.
    """
    seen: set[int] = set()
    pending = [root]
    found = []
    while pending:
        value = pending.pop()
        if id(value) in seen or isinstance(value, (str, bytes, int, float, bool, type(None), type)):
            continue
        seen.add(id(value))
        found.append(value)
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (tuple, list, set, frozenset)):
            pending.extend(value)
        else:
            pending.extend(getattr(value, "__dict__", {}).values())
            for cls in type(value).__mro__:
                slots = cls.__dict__.get("__slots__", ())
                for slot in (slots,) if isinstance(slots, str) else slots:
                    if slot not in {"__weakref__", "__dict__"} and hasattr(value, slot):
                        pending.append(getattr(value, slot))
            bound_owner = getattr(value, "__self__", None)
            if bound_owner is not None:
                pending.append(bound_owner)
            for cell in getattr(value, "__closure__", ()) or ():
                pending.append(cell.cell_contents)
    return found


@pytest.mark.asyncio
async def test_module_and_reader_graphs_do_not_retain_schema_execution_capability() -> None:
    module = MetadataModule()

    class ProtectedAuthority:
        def internal_schema_read(self, tenant: object) -> Any:
            raise AssertionError("Object graph traversal must never invoke SQL authority")

    authority = ProtectedAuthority()
    callback = authority.internal_schema_read
    internal_configure_schema_reader(module, callback)
    gate = ContributionGate()
    first = gate.reserve("foundation.metadata")
    reader = internal_register_schema_reader(module, first, MetadataLimits())
    module._schema_reader = reader
    internal_start_schema_reader(module)
    for surface in (module, reader):
        graph = _instance_graph(surface)
        assert all(value is not authority and value is not callback for value in graph)
        assert not any(callable(value) for value in graph)
    assert not hasattr(reader, "_factory")
    assert not hasattr(module, "_schema_factory")
    internal_stop_schema_reader(module)
    for active_name in ("active", "_active"):
        with pytest.raises(AttributeError):
            setattr(reader, active_name, True)
    context = SimpleNamespace()
    with pytest.raises(BusinessOSError, match="unavailable"):
        await reader.resolve(None, context)  # type: ignore[arg-type]
    second = gate.reserve("foundation.metadata")
    replacement = internal_register_schema_reader(module, second, MetadataLimits())
    internal_start_schema_reader(module)
    assert replacement is not reader
    with pytest.raises(BusinessOSError, match="unavailable"):
        await reader.resolve(None, context)  # type: ignore[arg-type]
    # Constructing a public concrete reader conveys no execution authority.
    unissued = PublishedSchemaReader(MetadataLimits())
    with pytest.raises(BusinessOSError, match="unavailable"):
        await unissued.resolve(None, context)  # type: ignore[arg-type]
