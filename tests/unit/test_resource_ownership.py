"""ADR-018 neutral resource-owner trust and transaction admission checks."""

import asyncio
from dataclasses import replace
from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from businessos.activation import ContributionGate
from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.di import Container
from businessos.errors import ConfigurationError, ConflictError, NotFoundError
from businessos.messages import Command, EventBus, HandlingContext, MessageDispatcher, Query
from businessos.modules.artifact import ApprovedModuleArtifact
from businessos.modules.manifest import ModuleManifest, ResourceOwnership
from businessos.modules.registry import ModuleRegistry, ModuleState
from businessos.modules.sdk import ModuleRegistration
from businessos.persistence import TransactionalPersistence, UnitOfWork
from businessos.providers import ProviderRegistry
from businessos.resources import (
    ResourceLocator,
    ResourceOwnerFacts,
    ResourceOwnershipRegistry,
)


class OwnerModule:
    def __init__(self, module_id: str = "example_owner") -> None:
        self.manifest = _manifest(module_id)

    async def register(self, registration: ModuleRegistration) -> None:
        return None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class RegisteringModule(OwnerModule):
    def __init__(self) -> None:
        super().__init__()
        self.registrations: list[ModuleRegistration] = []

    async def register(self, registration: ModuleRegistration) -> None:
        self.registrations.append(registration)
        registration.resource_owner_facts("example_owner.record", "1", FactsProvider())
        registration.resource_owner_operation("example_owner.record", "1", OperationProvider())


class FailingRegisteringModule(RegisteringModule):
    async def start(self) -> None:
        raise RuntimeError("activation failed")


class CoordinatorModule(OwnerModule):
    def __init__(self) -> None:
        super().__init__("example_governance")
        self.manifest = _manifest("example_governance", resource_ownership=())

    async def register(self, registration: ModuleRegistration) -> None:
        async def handler(_: GovernOwner, handling: HandlingContext) -> object:
            return None

        registration.command(GovernOwner, handler)


def _manifest(module_id: str = "example_owner", **changes: object) -> ModuleManifest:
    values: dict[str, object] = {
        "module_id": module_id,
        "name": "Example owner",
        "publisher": "example-publisher",
        "version": "1.0.0",
        "platform": ">=0.1,<1",
        "sdk": ">=0.1,<1",
        "python": ">=3.12",
        "entry_point": "example:module",
        "resource_ownership": (
            ResourceOwnership(
                resource_namespace=f"{module_id}.record",
                owner_module_id=module_id,
                contract_version="1",
            ),
        ),
    }
    values.update(changes)
    return ModuleManifest.model_validate(values)


def _grant(module: OwnerModule, **changes: object) -> ApprovedModuleArtifact:
    values: dict[str, object] = {
        "loaded_module": module,
        "module_id": module.manifest.module_id,
        "publisher": module.manifest.publisher,
        "package_identity": "example-package",
        "loaded_type": f"{type(module).__module__}:{type(module).__qualname__}",
        "install_identity": "operator-approved-install-1",
    }
    values.update(changes)
    return ApprovedModuleArtifact(**values)  # type: ignore[arg-type]


def test_manifest_canonical_namespace_and_aliases() -> None:
    plain = _manifest(resource_ownership=())
    assert plain.resource_ownership == ()
    for module_id in ("example_owner", "example-owner", "example.owner"):
        assert _manifest(module_id).resource_ownership[0].owner_module_id == module_id
    for bad in ("Example.record", "example.record\uff0fother", "example.recörd", "example..record"):
        with pytest.raises(ValidationError):
            ResourceOwnership(
                resource_namespace=bad, owner_module_id="example", contract_version="1"
            )
    with pytest.raises(ValidationError, match="root"):
        ResourceOwnership(
            resource_namespace="other.record", owner_module_id="example", contract_version="1"
        )
    owned = ResourceOwnership(
        resource_namespace="example.record",
        owner_module_id="example",
        contract_version="1",
        aliases=("example.old",),
    )
    with pytest.raises(ValidationError, match="colliding"):
        _manifest("example", resource_ownership=(owned, owned))
    with pytest.raises(ValidationError, match="unique"):
        owned.model_copy(update={"aliases": ("example.old", "example.old")}).model_validate(
            owned.model_copy(update={"aliases": ("example.old", "example.old")}).model_dump()
        )


def test_installation_grant_is_required_and_matches_loaded_module() -> None:
    module = OwnerModule()
    registry = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    with pytest.raises(ConfigurationError, match="approved artifact"):
        registry.add(module)
    for mismatch in (
        {"module_id": "other"},
        {"publisher": "other"},
        {"loaded_type": "other:Module"},
        {"revoked": True},
    ):
        registry = ModuleRegistry(
            platform_version="0.1.0",
            sdk_version="0.1.0",
            approved_artifacts={module.manifest.module_id: _grant(module, **mismatch)},
        )
        with pytest.raises(ConfigurationError):
            registry.add(module)
    registry = ModuleRegistry(
        platform_version="0.1.0",
        sdk_version="0.1.0",
        approved_artifacts={module.manifest.module_id: _grant(module)},
    )
    registry.add(module)
    assert registry.get(module.manifest.module_id).module is module
    ordinary = OwnerModule()
    ordinary.manifest = _manifest(resource_ownership=())
    ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0").add(ordinary)


def test_copied_manifest_cannot_claim_another_modules_canonical_root() -> None:
    module = OwnerModule()
    foreign = ResourceOwnership(
        resource_namespace="foundation.party.party",
        owner_module_id="foundation.party",
        contract_version="1",
    )
    module.manifest = module.manifest.model_copy(update={"resource_ownership": (foreign,)})
    registry = ModuleRegistry(
        platform_version="0.1.0",
        sdk_version="0.1.0",
        approved_artifacts={"example_owner": _grant(module)},
    )
    with pytest.raises(ConfigurationError, match="admission validation"):
        registry.add(module)
    assert tuple(registry.entries()) == ()

    original = OwnerModule()
    replacement_registry = ModuleRegistry(
        platform_version="0.1.0",
        sdk_version="0.1.0",
        approved_artifacts={"example_owner": _grant(original)},
    )
    replacement_registry.add(original)
    replacement_registry.get("example_owner").state = ModuleState.INSTALLED
    with pytest.raises(ConfigurationError, match="admission validation"):
        replacement_registry.replace(
            module, _grant(module, install_identity="operator-approved-install-2")
        )
    assert replacement_registry.get("example_owner").module is original

    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    generation = gate.reserve("example_owner")
    with pytest.raises(ConfigurationError, match="canonical owner"):
        resources.stage(module.manifest, generation)
    with pytest.raises(ConfigurationError, match="owner's declaration"):
        resources.register_provider(
            module.manifest, generation, "foundation.party.party", "1", "facts", FactsProvider()
        )


def test_reserved_id_and_replacement_preserve_allocation() -> None:
    business = OwnerModule("business.sales")
    with pytest.raises(ConfigurationError, match="first-party"):
        ModuleRegistry(
            platform_version="0.1.0",
            sdk_version="0.1.0",
            approved_artifacts={"business.sales": _grant(business)},
        ).add(business)
    first = OwnerModule("foundation.party")
    with pytest.raises(ConfigurationError, match="first-party"):
        ModuleRegistry(
            platform_version="0.1.0",
            sdk_version="0.1.0",
            approved_artifacts={"foundation.party": _grant(first)},
        ).add(first)
    registry = ModuleRegistry(
        platform_version="0.1.0",
        sdk_version="0.1.0",
        approved_artifacts={"foundation.party": _grant(first, first_party=True)},
    )
    registry.add(first)
    registry.get("foundation.party").state = ModuleState.INSTALLED
    replacement = OwnerModule("foundation.party")
    replacement.manifest = replacement.manifest.model_copy(update={"version": "1.1.0"})
    with pytest.raises(ConfigurationError, match="fresh"):
        registry.replace(
            replacement,
            _grant(replacement, first_party=True),
        )
    with pytest.raises(ConfigurationError, match="allocation"):
        registry.replace(
            replacement,
            _grant(
                replacement,
                first_party=True,
                package_identity="other-package",
                install_identity="operator-approved-install-2",
            ),
        )
    registry.replace(
        replacement,
        _grant(replacement, first_party=True, install_identity="operator-approved-install-2"),
    )
    assert registry.get("foundation.party").state is ModuleState.INSTALLED
    assert registry.get("foundation.party").module is replacement


def test_grant_is_bound_to_exact_loaded_instance() -> None:
    approved = OwnerModule()
    substituted = OwnerModule()
    registry = ModuleRegistry(
        platform_version="0.1.0",
        sdk_version="0.1.0",
        approved_artifacts={"example_owner": _grant(approved)},
    )
    with pytest.raises(ConfigurationError, match="installation evidence"):
        registry.add(substituted)


def test_coordinator_identity_also_requires_protected_grant() -> None:
    module = OwnerModule("example_governance")
    module.manifest = _manifest("example_governance", resource_ownership=())
    registry = ModuleRegistry(
        platform_version="0.1.0",
        sdk_version="0.1.0",
        coordinator_ids=frozenset({"example_governance"}),
    )
    with pytest.raises(ConfigurationError, match="approved artifact"):
        registry.add(module)
    approved = ModuleRegistry(
        platform_version="0.1.0",
        sdk_version="0.1.0",
        coordinator_ids=frozenset({"example_governance"}),
        approved_artifacts={"example_governance": _grant(module)},
    )
    approved.add(module)
    assert approved.is_approved_coordinator("example_governance")


def test_legacy_alias_requires_independent_exact_approval() -> None:
    module = OwnerModule()
    alias = ResourceOwnership(
        resource_namespace="example_owner.record",
        owner_module_id="example_owner",
        contract_version="1",
        aliases=("legacy_owner.old-record",),
    )
    module.manifest = _manifest(resource_ownership=(alias,))
    with pytest.raises(ConfigurationError, match="alias"):
        ModuleRegistry(
            platform_version="0.1.0",
            sdk_version="0.1.0",
            approved_artifacts={"example_owner": _grant(module)},
        ).add(module)
    approved = _grant(
        module,
        approved_aliases=frozenset({("legacy_owner.old-record", "example_owner.record", "1")}),
    )
    registry = ModuleRegistry(
        platform_version="0.1.0",
        sdk_version="0.1.0",
        approved_artifacts={"example_owner": approved},
    )
    registry.add(module)
    assert registry.get("example_owner").module is module


@pytest.mark.asyncio
async def test_owner_scoped_registration_follows_lifecycle_generation() -> None:
    module = RegisteringModule()
    app = create_application(
        Settings(
            environment="test",
            database_url="postgresql+psycopg://test:test@db/test",
            database_readiness_enabled=False,
        ),
        modules=(module,),
        approved_module_artifacts={"example_owner": _grant(module)},
    )
    await app.startup()
    assert app.runtime is not None
    first = app.runtime.resources.resolve_owner("example_owner.record", "1")
    assert first.generation == module.registrations[0].generation
    with pytest.raises(RuntimeError, match="before activation"):
        module.registrations[0].resource_owner_facts("example_owner.other", "1", FactsProvider())
    with pytest.raises(RuntimeError, match="before activation"):
        module.registrations[0].resource_owner_facts("example_owner.record", "1", FactsProvider())
    await app.runtime.lifecycle.disable("example_owner")
    with pytest.raises(NotFoundError):
        app.runtime.resources.resolve_owner("example_owner.record", "1")
    await app.runtime.lifecycle.enable("example_owner")
    second = app.runtime.resources.resolve_owner("example_owner.record", "1")
    assert second.generation != first.generation
    await module.registrations[0].remove()
    assert app.runtime.resources.resolve_owner("example_owner.record", "1") == second
    await app.shutdown()


@pytest.mark.asyncio
async def test_manifest_swap_after_admission_cannot_create_resource_claim() -> None:
    module = OwnerModule()
    module.manifest = _manifest(resource_ownership=())
    app = create_application(
        Settings(
            environment="test",
            database_url="postgresql+psycopg://test:test@db/test",
            database_readiness_enabled=False,
        ),
        modules=(module,),
    )
    module.manifest = _manifest()
    with pytest.raises(ConfigurationError, match="manifest changed"):
        await app.startup()
    assert app.runtime is not None
    with pytest.raises(NotFoundError):
        app.runtime.resources.resolve_owner("example_owner.record", "1")


@pytest.mark.asyncio
async def test_failed_activation_rolls_back_staged_resource_contributions() -> None:
    module = FailingRegisteringModule()
    app = create_application(
        Settings(
            environment="test",
            database_url="postgresql+psycopg://test:test@db/test",
            database_readiness_enabled=False,
        ),
        modules=(module,),
        approved_module_artifacts={"example_owner": _grant(module)},
    )
    with pytest.raises(RuntimeError, match="activation failed"):
        await app.startup()
    assert app.runtime is not None
    with pytest.raises(NotFoundError):
        app.runtime.resources.resolve_owner("example_owner.record", "1")
    with pytest.raises(ConfigurationError, match="Unknown"):
        app.runtime.contributions.state(module.registrations[0].generation)


@pytest.mark.asyncio
async def test_composition_issues_token_only_to_approved_coordinator_registration() -> None:
    owner = RegisteringModule()
    coordinator = CoordinatorModule()
    app = create_application(
        Settings(
            environment="test",
            database_url="postgresql+psycopg://test:test@db/test",
            database_readiness_enabled=False,
        ),
        modules=(owner, coordinator),
        approved_module_artifacts={
            "example_owner": _grant(owner),
            "example_governance": _grant(coordinator),
        },
        resource_coordinator_ids=frozenset({"example_governance"}),
    )
    await app.startup()
    assert app.runtime is not None
    registered = app.runtime.messages.commands.resolve(GovernOwner())
    assert registered.coordinator_token is not None
    assert registered.generation is not None
    assert app.runtime.resources._coordinator_tokens[registered.generation] is (
        registered.coordinator_token
    )
    await app.shutdown()


def test_generic_provider_is_not_resource_owner_authority() -> None:
    gate = ContributionGate()
    ordinary = ProviderRegistry(gate)
    ordinary.register("platform.resource-owner-facts.v1", "caller", FactsProvider())
    resources = ResourceOwnershipRegistry(gate)
    with pytest.raises(NotFoundError):
        resources.resolve_owner("example_owner.record", "1")


def test_owner_provider_registration_rejects_undeclared_duplicate_and_kind() -> None:
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    generation = gate.reserve("example_owner")
    manifest = _manifest()
    with pytest.raises(ConfigurationError, match="declaration"):
        resources.register_provider(
            manifest, generation, "example_owner.other", "1", "facts", FactsProvider()
        )
    with pytest.raises(ConfigurationError, match="Unsupported"):
        resources.register_provider(
            manifest, generation, "example_owner.record", "1", "other", FactsProvider()
        )
    resources.register_provider(
        manifest, generation, "example_owner.record", "1", "facts", FactsProvider()
    )
    with pytest.raises(ConflictError, match="already registered"):
        resources.register_provider(
            manifest, generation, "example_owner.record", "1", "facts", FactsProvider()
        )
    malformed_operation = OperationProvider()
    malformed_operation.supported_actions = frozenset({1})  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="supported actions"):
        resources.register_provider(
            manifest, generation, "example_owner.record", "1", "operation", malformed_operation
        )

    class DeceptiveActions(frozenset[str]):
        def __contains__(self, action: object) -> bool:
            return action == "purge" or super().__contains__(action)

    deceptive_operation = OperationProvider()
    deceptive_operation.supported_actions = DeceptiveActions({"archive"})
    with pytest.raises(ConfigurationError, match="supported actions"):
        resources.register_provider(
            manifest, generation, "example_owner.record", "1", "operation", deceptive_operation
        )

    class DeceptiveAction(str):
        def __hash__(self) -> int:
            return hash("purge")

        def __eq__(self, other: object) -> bool:
            return other == "purge" or super().__eq__(other)

    deceptive_member = OperationProvider()
    deceptive_member.supported_actions = frozenset({DeceptiveAction("archive")})
    with pytest.raises(ConfigurationError, match="supported actions"):
        resources.register_provider(
            manifest, generation, "example_owner.record", "1", "operation", deceptive_member
        )


class FactsProvider:
    async def read_facts(
        self, locator: ResourceLocator, request: RequestContext, transaction: object
    ) -> ResourceOwnerFacts:
        return ResourceOwnerFacts(
            tenant_id=locator.tenant_id,
            namespace=locator.namespace,
            record_id=locator.record_id,
            owner_module_id="example_owner",
            contract_version="1",
            lifecycle="current",
            facts={"state": "open"},
        )


class WrongFactsProvider(FactsProvider):
    def __init__(self, wrong_field: str) -> None:
        self.wrong_field = wrong_field

    async def read_facts(
        self, locator: ResourceLocator, request: RequestContext, transaction: object
    ) -> ResourceOwnerFacts:
        correct = await super().read_facts(locator, request, transaction)
        if self.wrong_field == "tenant_id":
            return replace(correct, tenant_id=uuid4())
        if self.wrong_field == "record_id":
            return replace(correct, record_id=uuid4())
        if self.wrong_field == "namespace":
            return replace(correct, namespace="other")
        if self.wrong_field == "owner_module_id":
            return replace(correct, owner_module_id="other")
        return replace(correct, contract_version="other")


class LockedFactsProvider(FactsProvider):
    async def read_locked_facts(
        self, locator: ResourceLocator, action: str, request: RequestContext, transaction: object
    ) -> ResourceOwnerFacts:
        assert action == "record.update"
        return await self.read_facts(locator, request, transaction)


class OperationProvider:
    supported_actions = frozenset({"archive"})

    async def validate_operation(
        self, locator: ResourceLocator, action: str, request: RequestContext, transaction: object
    ) -> ResourceOwnerFacts:
        return await FactsProvider().read_facts(locator, request, transaction)

    async def apply_operation(
        self, locator: ResourceLocator, action: str, request: RequestContext, transaction: object
    ) -> None:
        return None


def test_resource_identity_rejects_equality_spoofing() -> None:
    record_a = uuid4()
    record_b = uuid4()
    tenant_id = uuid4()

    class DeceptiveRecordId(UUID):
        def __hash__(self) -> int:
            return hash(record_a)

        def __eq__(self, other: object) -> bool:
            return other == record_a or super().__eq__(other)

    deceptive_id = DeceptiveRecordId(str(record_b))
    assert deceptive_id == record_a
    assert UUID(str(deceptive_id)) == record_b
    with pytest.raises(ConfigurationError, match="exact canonical identity"):
        ResourceLocator("example_owner.record", "1", deceptive_id, tenant_id)
    with pytest.raises(ConfigurationError, match="exact canonical identity"):
        ResourceOwnerFacts(
            tenant_id=tenant_id,
            namespace="example_owner.record",
            record_id=deceptive_id,
            owner_module_id="example_owner",
            contract_version="1",
            lifecycle="current",
            facts={},
        )

    forged = object.__new__(ResourceLocator)
    object.__setattr__(forged, "namespace", "example_owner.record")
    object.__setattr__(forged, "contract_version", "1")
    object.__setattr__(forged, "record_id", deceptive_id)
    object.__setattr__(forged, "tenant_id", tenant_id)
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    owner = gate.reserve("example_owner")
    resources.stage(_manifest(), owner)
    gate.publish(owner)
    request = RequestContext(tenant=TenantContext(uuid4(), tenant_id, uuid4()))
    with pytest.raises(ConfigurationError, match="exact canonical identity"):
        binding = resources.resolve_owner("example_owner.record", "1")
        resources.verify_locator(forged, request, binding)


class UseOwner(Command):
    pass


class ReadOwner(Query):
    pass


class GovernOwner(Command):
    pass


class SpoofOwner(Command):
    pass


class FakeUOW:
    def __init__(
        self,
        commit_entered: asyncio.Event,
        commit_release: asyncio.Event,
        *,
        exit_entered: asyncio.Event | None = None,
        exit_release: asyncio.Event | None = None,
        fail_commit: bool = False,
    ) -> None:
        self.commit_entered = commit_entered
        self.commit_release = commit_release
        self.exit_entered = exit_entered
        self.exit_release = exit_release
        self.fail_commit = fail_commit
        self.committed = False

    @property
    def persistence(self) -> TransactionalPersistence:
        return cast(TransactionalPersistence, self)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.exit_entered is not None and self.exit_release is not None:
            self.exit_entered.set()
            await self.exit_release.wait()
        return None

    async def commit(self) -> None:
        self.commit_entered.set()
        await self.commit_release.wait()
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.committed = True

    async def rollback(self) -> None:
        return None

    def add_outbox(self, message: object) -> None:
        return None


class FakeFactory:
    def __init__(self, uow: FakeUOW) -> None:
        self.uow = uow

    def for_tenant(self, context: TenantContext) -> UnitOfWork:
        return cast(UnitOfWork, self.uow)

    def system(self) -> UnitOfWork:
        return cast(UnitOfWork, self.uow)


@pytest.mark.asyncio
async def test_provider_lease_survives_method_return_until_outer_commit() -> None:
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    owner = gate.reserve("example_owner")
    manifest = _manifest()
    resources.register_provider(
        manifest, owner, "example_owner.record", "1", "facts", FactsProvider()
    )
    resources.stage(manifest, owner)
    gate.publish(owner)
    handler_generation = gate.reserve("example_handler")
    gate.publish(handler_generation)
    commit_entered = asyncio.Event()
    commit_release = asyncio.Event()
    dispatcher = MessageDispatcher(
        FakeFactory(FakeUOW(commit_entered, commit_release)),
        EventBus(gate),
        gate,
        resources=resources,
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    request = RequestContext(tenant=tenant)
    locator = ResourceLocator("example_owner.record", "1", uuid4(), tenant.tenant_id)
    handle_holder: list[object] = []

    async def handler(_: UseOwner, handling: HandlingContext) -> object:
        handle = await resources.resolve_provider(
            locator, "facts", handling.request, handling.unit_of_work
        )
        handle_holder.append(handle)
        assert (await handle.read_facts()).record_id == locator.record_id
        assert gate.in_flight(owner) == 1
        with pytest.raises(ConfigurationError, match="Nested message dispatch"):
            await dispatcher.query(ReadOwner(), handling.request, handling.dependencies)
        return "done"

    dispatcher.commands.register(
        UseOwner, "example_handler", handler, generation=handler_generation
    )
    container = Container()
    async with container.request_scope() as dependencies:
        task = asyncio.create_task(dispatcher.command(UseOwner(), request, dependencies))
        try:
            await asyncio.wait_for(commit_entered.wait(), timeout=2)
        except TimeoutError:
            if task.done():
                await task
            raise
        assert gate.in_flight(owner) == 1
        drain = asyncio.create_task(gate.close_and_drain(owner, timeout_seconds=2))
        await asyncio.sleep(0)
        assert not drain.done()
        commit_release.set()
        assert await task == "done"
        await drain
    assert gate.in_flight(owner) == 0
    with pytest.raises(ConfigurationError, match="trusted dispatcher"):
        await handle_holder[0].read_facts()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_locked_policy_facts_require_current_owner_handler() -> None:
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    owner = gate.reserve("example_owner")
    manifest = _manifest()
    resources.register_provider(
        manifest, owner, "example_owner.record", "1", "facts", LockedFactsProvider()
    )
    resources.stage(manifest, owner)
    gate.publish(owner)
    spoof = gate.reserve("example_handler")
    gate.publish(spoof)
    completed = asyncio.Event()
    completed.set()
    dispatcher = MessageDispatcher(
        FakeFactory(FakeUOW(asyncio.Event(), completed)),
        EventBus(gate),
        gate,
        resources=resources,
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    request = RequestContext(tenant=tenant)
    locator = ResourceLocator("example_owner.record", "1", uuid4(), tenant.tenant_id)

    async def owner_handler(_: UseOwner, handling: HandlingContext) -> object:
        resources.assert_owner_handler(locator, handling.request, handling.unit_of_work)
        handle = await resources.resolve_provider(
            locator, "facts", handling.request, handling.unit_of_work
        )
        assert (await handle.read_locked_facts("record.update")).record_id == locator.record_id
        return "owner"

    async def spoof_handler(_: SpoofOwner, handling: HandlingContext) -> object:
        with pytest.raises(ConfigurationError, match="canonical owner handler"):
            resources.assert_owner_handler(locator, handling.request, handling.unit_of_work)
        return "denied"

    dispatcher.commands.register(UseOwner, "example_owner", owner_handler, generation=owner)
    dispatcher.commands.register(SpoofOwner, "example_handler", spoof_handler, generation=spoof)
    container = Container()
    async with container.request_scope() as dependencies:
        assert await dispatcher.command(UseOwner(), request, dependencies) == "owner"
        assert await dispatcher.command(SpoofOwner(), request, dependencies) == "denied"


@pytest.mark.asyncio
async def test_duplicate_claim_and_inactive_owner_fail_closed() -> None:
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    first = gate.reserve("example_owner")
    second = gate.reserve("example_owner")
    resources.stage(_manifest(), first)
    with pytest.raises(ConflictError):
        resources.stage(_manifest(), second)
    with pytest.raises(NotFoundError):
        resources.resolve_owner("example_owner.record", "1")
    resources.remove_owner_generation(first)
    gate.discard(first)
    resources.stage(_manifest(), second)
    gate.publish(second)
    assert resources.resolve_owner("example_owner.record", "1").generation == second


@pytest.mark.asyncio
async def test_operation_requires_framework_coordinator_and_validated_action() -> None:
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate, coordinator_ids=frozenset({"example_governance"}))
    owner = gate.reserve("example_owner")
    manifest = _manifest()
    operation_provider = OperationProvider()
    resources.register_provider(
        manifest, owner, "example_owner.record", "1", "operation", operation_provider
    )
    operation_provider.supported_actions = frozenset({"archive", "purge"})
    resources.stage(manifest, owner)
    gate.publish(owner)
    unapproved = gate.reserve("caller")
    approved = gate.reserve("example_governance")
    coordinator_token = object()
    resources.authorize_coordinator_generation(approved, coordinator_token)
    gate.publish(unapproved)
    gate.publish(approved)
    commit_entered = asyncio.Event()
    commit_release = asyncio.Event()
    commit_release.set()
    dispatcher = MessageDispatcher(
        FakeFactory(FakeUOW(commit_entered, commit_release)),
        EventBus(gate),
        gate,
        resources=resources,
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    request = RequestContext(tenant=tenant)
    locator = ResourceLocator("example_owner.record", "1", uuid4(), tenant.tenant_id)

    class DeceptiveRequestedAction(str):
        def __hash__(self) -> int:
            return hash("archive")

        def __eq__(self, other: object) -> bool:
            return other == "archive" or super().__eq__(other)

    async def caller(_: Command, handling: HandlingContext) -> object:
        with pytest.raises(ConfigurationError, match="coordinator"):
            await resources.resolve_provider(
                locator, "operation", handling.request, handling.unit_of_work
            )
        return None

    async def coordinator(_: GovernOwner, handling: HandlingContext) -> object:
        with pytest.raises(ConfigurationError, match="tenant"):
            await resources.resolve_provider(
                ResourceLocator(locator.namespace, "1", locator.record_id, uuid4()),
                "operation",
                handling.request,
                handling.unit_of_work,
            )
        handle = await resources.resolve_provider(
            locator, "operation", handling.request, handling.unit_of_work
        )
        with pytest.raises(ConfigurationError, match="validation"):
            await handle.apply_operation("archive")
        with pytest.raises(ConfigurationError, match="support"):
            await handle.validate_operation("purge")
        with pytest.raises(ConfigurationError, match="canonical"):
            await handle.validate_operation(DeceptiveRequestedAction("purge"))
        await handle.validate_operation("archive")
        with pytest.raises(ConfigurationError, match="canonical"):
            await handle.apply_operation(DeceptiveRequestedAction("purge"))
        await handle.apply_operation("archive")
        return None

    dispatcher.commands.register(UseOwner, "caller", caller, generation=unapproved)
    dispatcher.commands.register(SpoofOwner, "example_governance", caller, generation=approved)
    dispatcher.commands.register(
        GovernOwner,
        "example_governance",
        coordinator,
        generation=approved,
        coordinator_token=coordinator_token,
    )
    container = Container()
    async with container.request_scope() as dependencies:
        await dispatcher.command(UseOwner(), request, dependencies)
        await dispatcher.command(SpoofOwner(), request, dependencies)
        await dispatcher.command(GovernOwner(), request, dependencies)


@pytest.mark.asyncio
async def test_handler_cancellation_releases_provider_lease() -> None:
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    owner = gate.reserve("example_owner")
    manifest = _manifest()
    resources.register_provider(
        manifest, owner, "example_owner.record", "1", "facts", FactsProvider()
    )
    resources.stage(manifest, owner)
    gate.publish(owner)
    handler_generation = gate.reserve("handler")
    gate.publish(handler_generation)
    entered = asyncio.Event()
    wait_forever = asyncio.Event()
    dispatcher = MessageDispatcher(
        FakeFactory(FakeUOW(asyncio.Event(), asyncio.Event())),
        EventBus(gate),
        gate,
        resources=resources,
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    request = RequestContext(tenant=tenant)
    locator = ResourceLocator("example_owner.record", "1", uuid4(), tenant.tenant_id)

    async def handler(_: UseOwner, handling: HandlingContext) -> object:
        await resources.resolve_provider(locator, "facts", handling.request, handling.unit_of_work)
        entered.set()
        await wait_forever.wait()
        return None

    dispatcher.commands.register(UseOwner, "handler", handler, generation=handler_generation)
    container = Container()
    async with container.request_scope() as dependencies:
        task = asyncio.create_task(dispatcher.command(UseOwner(), request, dependencies))
        await entered.wait()
        assert gate.in_flight(owner) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert gate.in_flight(owner) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["handler", "commit", "cancel_commit"])
async def test_lease_spans_rollback_and_failed_commit_cleanup(failure: str) -> None:
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    owner = gate.reserve("example_owner")
    manifest = _manifest()
    resources.register_provider(
        manifest, owner, "example_owner.record", "1", "facts", FactsProvider()
    )
    resources.stage(manifest, owner)
    gate.publish(owner)
    handler_generation = gate.reserve("handler")
    gate.publish(handler_generation)
    commit_entered, commit_release = asyncio.Event(), asyncio.Event()
    exit_entered, exit_release = asyncio.Event(), asyncio.Event()
    if failure == "commit":
        commit_release.set()
    dispatcher = MessageDispatcher(
        FakeFactory(
            FakeUOW(
                commit_entered,
                commit_release,
                exit_entered=exit_entered,
                exit_release=exit_release,
                fail_commit=failure == "commit",
            )
        ),
        EventBus(gate),
        gate,
        resources=resources,
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    request = RequestContext(tenant=tenant)
    locator = ResourceLocator("example_owner.record", "1", uuid4(), tenant.tenant_id)

    async def handler(_: UseOwner, handling: HandlingContext) -> object:
        await resources.resolve_provider(locator, "facts", handling.request, handling.unit_of_work)
        if failure == "handler":
            raise RuntimeError("handler failed")
        return None

    dispatcher.commands.register(UseOwner, "handler", handler, generation=handler_generation)
    container = Container()
    async with container.request_scope() as dependencies:
        task = asyncio.create_task(dispatcher.command(UseOwner(), request, dependencies))
        if failure == "cancel_commit":
            await commit_entered.wait()
            assert gate.in_flight(owner) == 1
            task.cancel()
        await exit_entered.wait()
        assert gate.in_flight(owner) == 1
        exit_release.set()
        if failure == "cancel_commit":
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(RuntimeError, match="failed"):
                await task
    assert gate.in_flight(owner) == 0


@pytest.mark.asyncio
async def test_query_lease_spans_read_uow_close() -> None:
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    owner = gate.reserve("example_owner")
    manifest = _manifest()
    resources.register_provider(
        manifest, owner, "example_owner.record", "1", "facts", FactsProvider()
    )
    resources.stage(manifest, owner)
    gate.publish(owner)
    handler_generation = gate.reserve("reader")
    gate.publish(handler_generation)
    exit_entered, exit_release = asyncio.Event(), asyncio.Event()
    dispatcher = MessageDispatcher(
        FakeFactory(
            FakeUOW(
                asyncio.Event(),
                asyncio.Event(),
                exit_entered=exit_entered,
                exit_release=exit_release,
            )
        ),
        EventBus(gate),
        gate,
        resources=resources,
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    request = RequestContext(tenant=tenant)
    locator = ResourceLocator("example_owner.record", "1", uuid4(), tenant.tenant_id)

    async def reader(_: ReadOwner, handling: HandlingContext) -> object:
        handle = await resources.resolve_provider(
            locator, "facts", handling.request, handling.unit_of_work
        )
        await handle.read_facts()
        return "read"

    dispatcher.queries.register(ReadOwner, "reader", reader, generation=handler_generation)
    container = Container()
    async with container.request_scope() as dependencies:
        task = asyncio.create_task(dispatcher.query(ReadOwner(), request, dependencies))
        await exit_entered.wait()
        assert gate.in_flight(owner) == 1
        exit_release.set()
        assert await task == "read"
    assert gate.in_flight(owner) == 0


@pytest.mark.asyncio
async def test_multiple_providers_pin_each_generation_once() -> None:
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    first = gate.reserve("example_owner")
    first_manifest = _manifest(
        resource_ownership=(
            ResourceOwnership(
                resource_namespace="example_owner.record",
                owner_module_id="example_owner",
                contract_version="1",
            ),
            ResourceOwnership(
                resource_namespace="example_owner.other",
                owner_module_id="example_owner",
                contract_version="1",
            ),
        )
    )
    second = gate.reserve("example_two")
    second_manifest = _manifest("example_two")
    for manifest, generation, namespace in (
        (first_manifest, first, "example_owner.record"),
        (first_manifest, first, "example_owner.other"),
        (second_manifest, second, "example_two.record"),
    ):
        resources.register_provider(manifest, generation, namespace, "1", "facts", FactsProvider())
    resources.stage(first_manifest, first)
    resources.stage(second_manifest, second)
    gate.publish(first)
    gate.publish(second)
    handler_generation = gate.reserve("reader")
    gate.publish(handler_generation)
    commit_entered, commit_release = asyncio.Event(), asyncio.Event()
    dispatcher = MessageDispatcher(
        FakeFactory(FakeUOW(commit_entered, commit_release)),
        EventBus(gate),
        gate,
        resources=resources,
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    request = RequestContext(tenant=tenant)

    async def handler(_: UseOwner, handling: HandlingContext) -> object:
        for namespace in (
            "example_owner.record",
            "example_owner.record",
            "example_owner.other",
            "example_two.record",
        ):
            await resources.resolve_provider(
                ResourceLocator(namespace, "1", uuid4(), tenant.tenant_id),
                "facts",
                handling.request,
                handling.unit_of_work,
            )
        assert gate.in_flight(first) == 1
        assert gate.in_flight(second) == 1
        return None

    dispatcher.commands.register(UseOwner, "reader", handler, generation=handler_generation)
    container = Container()
    async with container.request_scope() as dependencies:
        task = asyncio.create_task(dispatcher.command(UseOwner(), request, dependencies))
        await commit_entered.wait()
        assert gate.in_flight(first) == gate.in_flight(second) == 1
        commit_release.set()
        await task
    assert gate.in_flight(first) == gate.in_flight(second) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wrong_field",
    ["tenant_id", "namespace", "record_id", "owner_module_id", "contract_version"],
)
async def test_wrong_owner_projection_fails_closed(wrong_field: str) -> None:
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    owner = gate.reserve("example_owner")
    manifest = _manifest()
    resources.register_provider(
        manifest, owner, "example_owner.record", "1", "facts", WrongFactsProvider(wrong_field)
    )
    resources.stage(manifest, owner)
    gate.publish(owner)
    handler_generation = gate.reserve("reader")
    gate.publish(handler_generation)
    commit_release = asyncio.Event()
    commit_release.set()
    dispatcher = MessageDispatcher(
        FakeFactory(FakeUOW(asyncio.Event(), commit_release)),
        EventBus(gate),
        gate,
        resources=resources,
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    request = RequestContext(tenant=tenant)
    locator = ResourceLocator("example_owner.record", "1", uuid4(), tenant.tenant_id)

    async def reader(_: ReadOwner, handling: HandlingContext) -> object:
        handle = await resources.resolve_provider(
            locator, "facts", handling.request, handling.unit_of_work
        )
        with pytest.raises(ConfigurationError, match="do not match"):
            await handle.read_facts()
        with pytest.raises(NotFoundError):
            await resources.resolve_provider(
                ResourceLocator("example_owner.unknown", "1", locator.record_id, tenant.tenant_id),
                "facts",
                handling.request,
                handling.unit_of_work,
            )
        with pytest.raises(NotFoundError):
            await resources.resolve_provider(
                ResourceLocator(locator.namespace, "2", locator.record_id, tenant.tenant_id),
                "facts",
                handling.request,
                handling.unit_of_work,
            )
        return None

    dispatcher.queries.register(ReadOwner, "reader", reader, generation=handler_generation)
    container = Container()
    async with container.request_scope() as dependencies:
        await dispatcher.query(ReadOwner(), request, dependencies)
    assert gate.in_flight(owner) == 0
