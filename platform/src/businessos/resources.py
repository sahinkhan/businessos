"""Neutral canonical resource ownership and transaction-bound owner providers."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from contextlib import AsyncExitStack
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

from sqlalchemy import text

from businessos.activation import ContributionGate, ContributionGeneration, ContributionState
from businessos.context import RequestContext
from businessos.errors import ConfigurationError, ConflictError, NotFoundError

if TYPE_CHECKING:
    from businessos.messages import HandlerTransaction
    from businessos.modules.manifest import ModuleManifest, ResourceOwnership


@dataclass(frozen=True, slots=True)
class ResourceLocator:
    namespace: str
    contract_version: str
    record_id: UUID
    tenant_id: UUID

    def __post_init__(self) -> None:
        if not _valid_locator_identity(self):
            raise ConfigurationError("Resource locator requires exact canonical identity types")


async def lock_resource_subject_facts(
    locator: ResourceLocator,
    owner_module_id: str,
    entity_type: str,
    request: RequestContext,
    transaction: HandlerTransaction,
) -> None:
    """Neutral entity/subject lock order for owner fact mutations.

    Owner modules use this before locking a row whose category, anchor, or
    destruction lifecycle may change. The current dispatcher UOW owns both
    advisory locks; callers cannot carry them across transactions.
    """
    active_scope = ResourceTransactionScope.current(request, transaction)
    if (
        request.tenant is None
        or locator.tenant_id != request.tenant.tenant_id
        or not owner_module_id
        or not entity_type
        or active_scope.handler_owner != owner_module_id
        or not locator.namespace.startswith(owner_module_id + ".")
    ):
        raise ConfigurationError("Resource fact lock requires trusted tenant and owner")
    for scope, parts in (
        ("entity", (locator.tenant_id, owner_module_id, entity_type)),
        (
            "subject",
            (locator.tenant_id, owner_module_id, locator.namespace, entity_type, locator.record_id),
        ),
    ):
        key = "\x1f".join(("adr017", scope, *(str(part) for part in parts)))
        await transaction.persistence.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
        )


def _valid_locator_identity(locator: ResourceLocator) -> bool:
    return (
        type(locator) is ResourceLocator
        and type(locator.namespace) is str
        and type(locator.contract_version) is str
        and type(locator.record_id) is UUID
        and type(locator.tenant_id) is UUID
    )


@dataclass(frozen=True, slots=True)
class ResourceOwnerFacts:
    tenant_id: UUID
    namespace: str
    record_id: UUID
    owner_module_id: str
    contract_version: str
    lifecycle: str
    facts: Mapping[str, object]

    def __post_init__(self) -> None:
        if (
            type(self.tenant_id) is not UUID
            or type(self.namespace) is not str
            or type(self.record_id) is not UUID
            or type(self.owner_module_id) is not str
            or type(self.contract_version) is not str
            or type(self.lifecycle) is not str
        ):
            raise ConfigurationError("Owner facts require exact canonical identity types")
        object.__setattr__(self, "facts", _freeze_facts(self.facts))


def _freeze_facts(values: Mapping[str, object]) -> Mapping[str, object]:
    def freeze(value: object) -> object:
        if value is None or isinstance(
            value, (str, int, bool, bytes, UUID, Decimal, date, datetime)
        ):
            return value
        if isinstance(value, Mapping):
            return _freeze_facts(cast(Mapping[str, object], value))
        if isinstance(value, (tuple, list)):
            return tuple(freeze(item) for item in cast(tuple[object, ...] | list[object], value))
        if isinstance(value, (set, frozenset)):
            return frozenset(freeze(item) for item in cast(set[object] | frozenset[object], value))
        raise ConfigurationError("Owner facts contain an unsupported mutable value")

    if not all(type(key) is str for key in values):
        raise ConfigurationError("Owner fact names must be strings")
    return MappingProxyType({key: freeze(value) for key, value in values.items()})


class ResourceOwnerFactsProvider(Protocol):
    async def read_facts(
        self, locator: ResourceLocator, request: RequestContext, transaction: HandlerTransaction
    ) -> ResourceOwnerFacts: ...


class ResourceOwnerLockedFactsProvider(Protocol):
    """Optional owner contract for locked, normalized Policy V2 commit facts."""

    async def read_locked_facts(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ResourceOwnerFacts: ...


class ResourceOwnerOperationProvider(Protocol):
    supported_actions: frozenset[str]

    async def validate_operation(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ResourceOwnerFacts: ...

    async def apply_operation(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ResourceOwnerBinding:
    ownership: ResourceOwnership
    generation: ContributionGeneration


@dataclass(frozen=True, slots=True)
class _ProviderEntry:
    binding: ResourceOwnerBinding
    kind: str
    provider: object
    supported_actions: frozenset[str] = frozenset()
    declared_entity_types: frozenset[str] = frozenset()


_current_scope: ContextVar[ResourceTransactionScope | None] = ContextVar(
    "businessos_resource_transaction_scope", default=None
)


class ResourceTransactionScope:
    """Dispatcher-owned admissions released after outer UOW exit."""

    def __init__(
        self,
        gate: ContributionGate,
        request: RequestContext,
        handler_owner: str,
        handler_generation: ContributionGeneration | None,
        coordinator_token: object | None = None,
    ) -> None:
        self._gate = gate
        self.request = request
        self.handler_owner = handler_owner
        self.handler_generation = handler_generation
        self.coordinator_token = coordinator_token
        self.transaction: object | None = None
        self._task: asyncio.Task[object] | None = None
        self._stack = AsyncExitStack()
        self._admitted: set[ContributionGeneration] = set()
        self._validated_operations: set[tuple[int, ResourceLocator, str]] = set()
        self._token: Token[ResourceTransactionScope | None] | None = None
        self._closed = False

    async def __aenter__(self) -> ResourceTransactionScope:
        self._task = asyncio.current_task()
        self._token = _current_scope.set(self)
        return self

    async def __aexit__(self, *_: object) -> None:
        self._closed = True
        try:
            await self._stack.aclose()
        finally:
            if self._token is not None:
                _current_scope.reset(self._token)

    def bind_transaction(self, transaction: object) -> None:
        if self.transaction is not None:
            raise ConfigurationError("Resource transaction is already bound")
        self.transaction = transaction

    async def admit(self, generation: ContributionGeneration) -> None:
        if self._closed or self.transaction is None or asyncio.current_task() is not self._task:
            raise ConfigurationError(
                "Resource admission requires the active dispatcher transaction"
            )
        if generation not in self._admitted:
            await self._stack.enter_async_context(self._gate.admit(generation))
            self._admitted.add(generation)

    def record_validation(
        self, entry: _ProviderEntry, locator: ResourceLocator, action: str
    ) -> None:
        self._validated_operations.add((id(entry), locator, action))

    def consume_validation(
        self, entry: _ProviderEntry, locator: ResourceLocator, action: str
    ) -> None:
        validation = (id(entry), locator, action)
        if validation not in self._validated_operations:
            raise ConfigurationError("Owner operation requires validation in this transaction")
        self._validated_operations.remove(validation)

    @classmethod
    def current(cls, request: RequestContext, transaction: object) -> ResourceTransactionScope:
        scope = _current_scope.get()
        if (
            scope is None
            or scope._closed
            or scope.request is not request
            or scope.transaction is not transaction
            or asyncio.current_task() is not scope._task
        ):
            raise ConfigurationError("Resource use requires the trusted dispatcher transaction")
        return scope

    @classmethod
    def reject_nested_dispatch_if_leased(cls) -> None:
        scope = _current_scope.get()
        if (
            scope is not None
            and not scope._closed
            and asyncio.current_task() is scope._task
            and scope._admitted
        ):
            raise ConfigurationError(
                "Nested message dispatch cannot leave an admitted resource transaction"
            )


@dataclass(frozen=True, slots=True)
class AdmittedResourceProvider:
    """An immutable binding; methods recheck its active transaction and identity."""

    _registry: ResourceOwnershipRegistry
    _entry: _ProviderEntry
    _request: RequestContext
    _transaction: object
    _locator: ResourceLocator

    @property
    def binding(self) -> ResourceOwnerBinding:
        return self._entry.binding

    @property
    def declared_entity_types(self) -> frozenset[str]:
        self._check("facts")
        return self._entry.declared_entity_types

    def _check(self, kind: str) -> None:
        ResourceTransactionScope.current(self._request, self._transaction)
        if self._entry.kind != kind or not self._registry.entry_is_current(self._entry):
            raise NotFoundError("Resource provider is stale or unavailable")
        self._registry.verify_locator(self._locator, self._request, self.binding)

    def _check_facts(self, facts: ResourceOwnerFacts) -> ResourceOwnerFacts:
        if type(facts) is not ResourceOwnerFacts:
            raise ConfigurationError("Owner facts provider returned an invalid projection")
        if (
            type(facts.tenant_id) is not UUID
            or type(facts.namespace) is not str
            or type(facts.record_id) is not UUID
            or type(facts.owner_module_id) is not str
            or type(facts.contract_version) is not str
            or type(facts.lifecycle) is not str
        ):
            raise ConfigurationError("Owner facts require exact canonical identity types")
        ownership = self.binding.ownership
        if (
            facts.tenant_id != self._locator.tenant_id
            or facts.namespace != ownership.resource_namespace
            or facts.record_id != self._locator.record_id
            or facts.owner_module_id != ownership.owner_module_id
            or facts.contract_version != ownership.contract_version
            or not facts.lifecycle
        ):
            raise ConfigurationError("Owner facts do not match trusted resource binding")
        return facts

    async def read_facts(self) -> ResourceOwnerFacts:
        self._check("facts")
        provider = cast(ResourceOwnerFactsProvider, self._entry.provider)
        result = await provider.read_facts(
            self._locator, self._request, cast("HandlerTransaction", self._transaction)
        )
        return self._check_facts(result)

    async def read_locked_facts(self, action: str) -> ResourceOwnerFacts:
        self._check("facts")
        if type(action) is not str or not re.fullmatch(r"[a-z][a-z0-9_.-]*", action, re.ASCII):
            raise ConfigurationError("Locked facts require a canonical action")
        method = getattr(self._entry.provider, "read_locked_facts", None)
        if not callable(method):
            raise NotFoundError("Owner does not provide locked Policy operation facts")
        provider = cast(ResourceOwnerLockedFactsProvider, self._entry.provider)
        result = await provider.read_locked_facts(
            self._locator, action, self._request, cast("HandlerTransaction", self._transaction)
        )
        self._check("facts")
        return self._check_facts(result)

    async def validate_operation(self, action: str) -> ResourceOwnerFacts:
        self._check("operation")
        if type(action) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]*", action, re.ASCII):
            raise ConfigurationError("Operation action must be nonempty canonical ASCII")
        provider = cast(ResourceOwnerOperationProvider, self._entry.provider)
        if action not in self._entry.supported_actions:
            raise ConfigurationError("Owner does not support the requested operation")
        result = await provider.validate_operation(
            self._locator, action, self._request, cast("HandlerTransaction", self._transaction)
        )
        facts = self._check_facts(result)
        if facts.lifecycle != "current":
            raise ConfigurationError("Owner operation requires current resource state")
        scope = ResourceTransactionScope.current(self._request, self._transaction)
        scope.record_validation(self._entry, self._locator, action)
        return facts

    async def apply_operation(self, action: str) -> None:
        self._check("operation")
        if type(action) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]*", action, re.ASCII):
            raise ConfigurationError("Operation action must be nonempty canonical ASCII")
        scope = ResourceTransactionScope.current(self._request, self._transaction)
        scope.consume_validation(self._entry, self._locator, action)
        provider = cast(ResourceOwnerOperationProvider, self._entry.provider)
        await provider.apply_operation(
            self._locator, action, self._request, cast("HandlerTransaction", self._transaction)
        )


class ResourceOwnerResolver(Protocol):
    """Narrow SDK lookup; admission still requires the dispatcher's transaction."""

    def resolve_owner(self, namespace: str, version: str) -> ResourceOwnerBinding: ...

    def assert_owner_handler(
        self, locator: ResourceLocator, request: RequestContext, transaction: HandlerTransaction
    ) -> None: ...

    async def resolve_provider(
        self,
        locator: ResourceLocator,
        kind: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> AdmittedResourceProvider: ...


class ResourceOwnershipRegistry:
    def __init__(
        self, gate: ContributionGate, *, coordinator_ids: frozenset[str] = frozenset()
    ) -> None:
        self._gate = gate
        self._coordinator_ids = coordinator_ids
        self._coordinator_tokens: dict[ContributionGeneration, object] = {}
        self._bindings: dict[tuple[str, str], ResourceOwnerBinding] = {}
        self._aliases: dict[tuple[str, str], tuple[str, str]] = {}
        self._providers: dict[tuple[str, str, str], _ProviderEntry] = {}

    def stage(self, manifest: ModuleManifest, generation: ContributionGeneration) -> None:
        if self._gate.state(generation) is not ContributionState.STAGED:
            raise ConfigurationError("Resource claims must stage before activation")
        if generation.owner != manifest.module_id:
            raise ConfigurationError("Resource generation owner mismatch")
        new_names: set[tuple[str, str]] = set()
        for ownership in manifest.resource_ownership:
            if (
                ownership.owner_module_id != generation.owner
                or not ownership.resource_namespace.startswith(generation.owner + ".")
            ):
                raise ConfigurationError("Resource declaration must belong to its canonical owner")
            for name in (ownership.resource_namespace, *ownership.aliases):
                key = (name, ownership.contract_version)
                if key in new_names or key in self._bindings or key in self._aliases:
                    raise ConflictError("Resource namespace/version is already claimed")
                new_names.add(key)
        for ownership in manifest.resource_ownership:
            key = (ownership.resource_namespace, ownership.contract_version)
            self._bindings[key] = ResourceOwnerBinding(ownership, generation)
            for alias in ownership.aliases:
                self._aliases[(alias, ownership.contract_version)] = key

    def register_provider(
        self,
        manifest: ModuleManifest,
        generation: ContributionGeneration,
        namespace: str,
        version: str,
        kind: str,
        provider: object,
    ) -> None:
        if self._gate.state(generation) is not ContributionState.STAGED:
            raise ConfigurationError("Resource providers must register before activation")
        if kind not in {"facts", "operation"}:
            raise ConfigurationError("Unsupported resource provider kind")
        ownership = next(
            (
                item
                for item in manifest.resource_ownership
                if item.resource_namespace == namespace and item.contract_version == version
            ),
            None,
        )
        if (
            ownership is None
            or generation.owner != manifest.module_id
            or ownership.owner_module_id != generation.owner
            or not namespace.startswith(generation.owner + ".")
        ):
            raise ConfigurationError("Resource provider requires this owner's declaration")
        required = ("read_facts",) if kind == "facts" else ("validate_operation", "apply_operation")
        if not all(callable(getattr(provider, name, None)) for name in required):
            raise ConfigurationError("Resource provider does not implement its typed contract")
        supported_actions: frozenset[str] = frozenset()
        declared_entity_types: frozenset[str] = frozenset()
        if kind == "facts":
            empty_types: frozenset[str] = frozenset()
            raw_types: object = getattr(provider, "declared_entity_types", empty_types)
            if type(raw_types) is not frozenset or any(
                type(entity_type) is not str
                or not re.fullmatch(r"[a-z][a-z0-9_.-]*", entity_type, re.ASCII)
                for entity_type in cast(frozenset[object], raw_types)
            ):
                raise ConfigurationError("Owner facts provider entity types must be canonical")
            declared_entity_types = cast(frozenset[str], raw_types)
        if kind == "operation":
            raw_actions = getattr(provider, "supported_actions", None)
            if (
                not isinstance(raw_actions, frozenset)
                or type(cast(object, raw_actions)) is not frozenset
                or not raw_actions
                or any(
                    type(action) is not str
                    or not re.fullmatch(r"[a-z][a-z0-9_-]*", action, re.ASCII)
                    for action in cast(frozenset[object], raw_actions)
                )
            ):
                raise ConfigurationError("Owner operation provider requires supported actions")
            supported_actions = cast(frozenset[str], raw_actions)
        key = (namespace, version, kind)
        if key in self._providers:
            raise ConflictError("Resource provider already registered")
        self._providers[key] = _ProviderEntry(
            ResourceOwnerBinding(ownership, generation),
            kind,
            provider,
            supported_actions,
            declared_entity_types,
        )

    def authorize_coordinator_generation(
        self, generation: ContributionGeneration, token: object
    ) -> None:
        if generation.owner not in self._coordinator_ids:
            raise ConfigurationError("Coordinator is not approved by protected composition")
        if self._gate.state(generation) is not ContributionState.STAGED:
            raise ConfigurationError("Coordinator admission must stage before activation")
        if generation in self._coordinator_tokens:
            raise ConflictError("Coordinator generation is already approved")
        self._coordinator_tokens[generation] = token

    def resolve_owner(self, namespace: str, version: str) -> ResourceOwnerBinding:
        key = self._aliases.get((namespace, version), (namespace, version))
        binding = self._bindings.get(key)
        if binding is None or not self._gate.is_active(binding.generation):
            raise NotFoundError("Canonical resource owner is unavailable")
        return binding

    def assert_owner_handler(
        self, locator: ResourceLocator, request: RequestContext, transaction: HandlerTransaction
    ) -> None:
        scope = ResourceTransactionScope.current(request, transaction)
        binding = self.resolve_owner(locator.namespace, locator.contract_version)
        self.verify_locator(locator, request, binding)
        if (
            scope.handler_owner != binding.ownership.owner_module_id
            or scope.handler_generation != binding.generation
        ):
            raise ConfigurationError("Policy commit requires the canonical owner handler")

    async def resolve_provider(
        self,
        locator: ResourceLocator,
        kind: str,
        request: RequestContext,
        transaction: object,
    ) -> AdmittedResourceProvider:
        if kind not in {"facts", "operation"}:
            raise NotFoundError("Unsupported resource provider kind")
        scope = ResourceTransactionScope.current(request, transaction)
        if not _valid_locator_identity(locator):
            raise ConfigurationError("Resource locator requires exact canonical identity types")
        binding = self.resolve_owner(locator.namespace, locator.contract_version)
        self.verify_locator(locator, request, binding)
        key = (binding.ownership.resource_namespace, locator.contract_version, kind)
        entry = self._providers.get(key)
        if entry is None or entry.binding != binding:
            raise NotFoundError("Exact resource provider is unavailable")
        if kind == "operation" and (
            scope.handler_owner not in self._coordinator_ids
            or scope.handler_generation is None
            or not self._gate.is_active(scope.handler_generation)
            or self._coordinator_tokens.get(scope.handler_generation) is not scope.coordinator_token
        ):
            raise ConfigurationError("Operation requires an admitted framework coordinator")
        await scope.admit(binding.generation)
        canonical_locator = ResourceLocator(
            binding.ownership.resource_namespace,
            locator.contract_version,
            locator.record_id,
            locator.tenant_id,
        )
        return AdmittedResourceProvider(self, entry, request, transaction, canonical_locator)

    def entry_is_current(self, entry: _ProviderEntry) -> bool:
        binding = entry.binding
        return (
            self._providers.get(
                (
                    binding.ownership.resource_namespace,
                    binding.ownership.contract_version,
                    entry.kind,
                )
            )
            is entry
        )

    def verify_locator(
        self, locator: ResourceLocator, request: RequestContext, binding: ResourceOwnerBinding
    ) -> None:
        if not _valid_locator_identity(locator):
            raise ConfigurationError("Resource locator requires exact canonical identity types")
        ownership = binding.ownership
        if (
            request.tenant is None
            or locator.tenant_id != request.tenant.tenant_id
            or locator.namespace not in (ownership.resource_namespace, *ownership.aliases)
            or locator.contract_version != ownership.contract_version
        ):
            raise ConfigurationError("Resource locator does not match trusted tenant or owner")

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        self._coordinator_tokens.pop(generation, None)
        self._providers = {
            key: entry
            for key, entry in self._providers.items()
            if entry.binding.generation != generation
        }
        keys = {key for key, binding in self._bindings.items() if binding.generation == generation}
        self._bindings = {key: value for key, value in self._bindings.items() if key not in keys}
        self._aliases = {key: value for key, value in self._aliases.items() if value not in keys}
