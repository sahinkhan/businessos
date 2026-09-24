"""Neutral canonical resource ownership and transaction-bound owner providers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import AsyncExitStack
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

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
    ) -> None:
        self._gate = gate
        self.request = request
        self.handler_owner = handler_owner
        self.handler_generation = handler_generation
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

    def _check(self, kind: str) -> None:
        ResourceTransactionScope.current(self._request, self._transaction)
        if self._entry.kind != kind or not self._registry.entry_is_current(self._entry):
            raise NotFoundError("Resource provider is stale or unavailable")
        self._registry.verify_locator(self._locator, self._request, self.binding)

    def _check_facts(self, facts: ResourceOwnerFacts) -> ResourceOwnerFacts:
        if not isinstance(cast(object, facts), ResourceOwnerFacts):
            raise ConfigurationError("Owner facts provider returned an invalid projection")
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

    async def validate_operation(self, action: str) -> ResourceOwnerFacts:
        self._check("operation")
        if not action or not action.isascii():
            raise ConfigurationError("Operation action must be nonempty canonical ASCII")
        provider = cast(ResourceOwnerOperationProvider, self._entry.provider)
        if action not in provider.supported_actions:
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
        if not action or not action.isascii():
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
        if ownership is None or generation.owner != manifest.module_id:
            raise ConfigurationError("Resource provider requires this owner's declaration")
        required = ("read_facts",) if kind == "facts" else ("validate_operation", "apply_operation")
        if not all(callable(getattr(provider, name, None)) for name in required):
            raise ConfigurationError("Resource provider does not implement its typed contract")
        if kind == "operation" and (
            not isinstance(getattr(provider, "supported_actions", None), frozenset)
            or not provider.supported_actions  # type: ignore[attr-defined]
        ):
            raise ConfigurationError("Owner operation provider requires supported actions")
        key = (namespace, version, kind)
        if key in self._providers:
            raise ConflictError("Resource provider already registered")
        self._providers[key] = _ProviderEntry(
            ResourceOwnerBinding(ownership, generation), kind, provider
        )

    def resolve_owner(self, namespace: str, version: str) -> ResourceOwnerBinding:
        key = self._aliases.get((namespace, version), (namespace, version))
        binding = self._bindings.get(key)
        if binding is None or not self._gate.is_active(binding.generation):
            raise NotFoundError("Canonical resource owner is unavailable")
        return binding

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
        ownership = binding.ownership
        if (
            request.tenant is None
            or locator.tenant_id != request.tenant.tenant_id
            or locator.namespace not in (ownership.resource_namespace, *ownership.aliases)
            or locator.contract_version != ownership.contract_version
        ):
            raise ConfigurationError("Resource locator does not match trusted tenant or owner")

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        self._providers = {
            key: entry
            for key, entry in self._providers.items()
            if entry.binding.generation != generation
        }
        keys = {key for key, binding in self._bindings.items() if binding.generation == generation}
        self._bindings = {key: value for key, value in self._bindings.items() if key not in keys}
        self._aliases = {key: value for key, value in self._aliases.items() if value not in keys}
