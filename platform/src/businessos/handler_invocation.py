"""Framework-issued, invocation-local module provenance for command/query handlers."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from weakref import WeakKeyDictionary

from businessos.activation import ContributionGeneration

if TYPE_CHECKING:
    from businessos.context import RequestContext
    from businessos.messages import HandlerTransaction
    from businessos.modules.manifest import ModuleManifest


class HandlerInvocationKind(StrEnum):
    COMMAND = "command"
    QUERY = "query"


@dataclass(frozen=True, slots=True)
class HandlerInvocationDependency:
    module_id: str
    version: str


class HandlerInvocationBinding(Protocol):
    """Read-only public view of a protected dispatcher invocation."""

    @property
    def owner_module_id(self) -> str: ...

    @property
    def generation(self) -> ContributionGeneration: ...

    @property
    def invocation_kind(self) -> HandlerInvocationKind: ...

    @property
    def direct_dependencies(self) -> tuple[HandlerInvocationDependency, ...]: ...

    def has_direct_dependency(self, module_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class _AuthorityFacts:
    owner_module_id: str
    generation: ContributionGeneration
    invocation_kind: HandlerInvocationKind
    direct_dependencies: tuple[HandlerInvocationDependency, ...]
    request: "RequestContext"
    transaction: "HandlerTransaction"
    task: asyncio.Task[object]
    lease: "_InvocationLease"


@dataclass(frozen=True, slots=True)
class _PublicFacts:
    owner_module_id: str
    generation: ContributionGeneration
    invocation_kind: HandlerInvocationKind
    direct_dependencies: tuple[HandlerInvocationDependency, ...]


@dataclass(slots=True)
class _InvocationLease:
    active: bool = True


class _IssuedBinding:
    """No public constructor arguments or writable authority facts."""

    __slots__ = ("__weakref__",)

    @property
    def owner_module_id(self) -> str:
        return _public[self].owner_module_id

    @property
    def generation(self) -> ContributionGeneration:
        return _public[self].generation

    @property
    def invocation_kind(self) -> HandlerInvocationKind:
        return _public[self].invocation_kind

    @property
    def direct_dependencies(self) -> tuple[HandlerInvocationDependency, ...]:
        return _public[self].direct_dependencies

    def has_direct_dependency(self, module_id: str) -> bool:
        facts = _issued.get(self)
        if facts is None:
            raise PermissionError("Handler invocation is no longer active")
        _require_live(facts, self)
        return any(dependency.module_id == module_id for dependency in facts.direct_dependencies)


_issued: WeakKeyDictionary[_IssuedBinding, _AuthorityFacts] = WeakKeyDictionary()
_public: WeakKeyDictionary[_IssuedBinding, _PublicFacts] = WeakKeyDictionary()
_active_binding: ContextVar[_IssuedBinding | None] = ContextVar(
    "businessos_active_handler_invocation", default=None
)


class _TrustedHandlerProvenance:
    __slots__ = ("__weakref__",)


@dataclass(frozen=True, slots=True)
class _RegistrationFacts:
    owner: str
    generation: ContributionGeneration
    dependencies: tuple[HandlerInvocationDependency, ...]


_registrations: WeakKeyDictionary[_TrustedHandlerProvenance, _RegistrationFacts] = (
    WeakKeyDictionary()
)


def _capture_handler_provenance(
    manifest: "ModuleManifest | None", owner: str, generation: ContributionGeneration
) -> _TrustedHandlerProvenance | None:
    if manifest is None:
        return None
    if manifest.module_id != owner or generation.owner != owner:
        raise ValueError("Handler manifest must match the exact registration owner")
    provenance = _TrustedHandlerProvenance()
    _registrations[provenance] = _RegistrationFacts(
        owner,
        generation,
        tuple(
            HandlerInvocationDependency(dependency.module_id, dependency.version)
            for dependency in manifest.dependencies
        ),
    )
    return provenance


def _trusted_handler_dependencies(
    provenance: object, owner: str, generation: ContributionGeneration | None
) -> tuple[HandlerInvocationDependency, ...] | None:
    if type(provenance) is not _TrustedHandlerProvenance:
        return None
    facts = _registrations.get(provenance)
    if facts is None or facts.owner != owner or facts.generation is not generation:
        return None
    return facts.dependencies


def _require_live(facts: _AuthorityFacts, binding: _IssuedBinding) -> None:
    try:
        task = asyncio.current_task()
    except RuntimeError as exc:
        raise PermissionError("Handler invocation requires its issuing task") from exc
    if not facts.lease.active or task is not facts.task or _active_binding.get() is not binding:
        raise PermissionError("Handler invocation is no longer active in this task")


def validate_handler_invocation(
    binding: object,
    request: "RequestContext",
    transaction: "HandlerTransaction",
    *,
    invocation_kind: HandlerInvocationKind,
) -> HandlerInvocationBinding:
    """Reject structural fakes, stale leases, and mismatched invocation objects."""
    if type(binding) is not _IssuedBinding:
        raise PermissionError("Handler invocation was not issued by the framework")
    issued_binding = binding
    facts = _issued.get(issued_binding)
    if facts is None:
        raise PermissionError("Handler invocation was not issued by the framework")
    _require_live(facts, issued_binding)
    if (
        request is not facts.request
        or transaction is not facts.transaction
        or invocation_kind is not facts.invocation_kind
    ):
        raise PermissionError("Handler invocation does not match this request or transaction")
    return issued_binding


@contextmanager
def _issue_handler_invocation(
    *,
    owner_module_id: str,
    generation: ContributionGeneration,
    invocation_kind: HandlerInvocationKind,
    direct_dependencies: tuple[HandlerInvocationDependency, ...],
    request: "RequestContext",
    transaction: "HandlerTransaction",
) -> Iterator[HandlerInvocationBinding]:
    """Called only by the dispatcher inside an admitted generation and active UOW."""
    task = asyncio.current_task()
    if task is None or generation.owner != owner_module_id:
        raise RuntimeError("Handler invocation requires a matching admitted generation and task")
    lease = _InvocationLease()
    binding = _IssuedBinding()
    _public[binding] = _PublicFacts(
        owner_module_id, generation, invocation_kind, direct_dependencies
    )
    _issued[binding] = _AuthorityFacts(
        owner_module_id,
        generation,
        invocation_kind,
        direct_dependencies,
        request,
        transaction,
        task,
        lease,
    )
    token = _active_binding.set(binding)
    try:
        yield binding
    finally:
        lease.active = False
        _issued.pop(binding, None)
        _active_binding.reset(token)


@contextmanager
def _without_handler_invocation() -> Iterator[None]:
    """Prevent a nested legacy handler from inheriting its caller's authority."""
    token = _active_binding.set(None)
    try:
        yield
    finally:
        _active_binding.reset(token)
