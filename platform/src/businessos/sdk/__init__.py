"""Stable public SDK facade for trusted first-party in-process modules."""

from businessos.context import RequestContext, TenantContext
from businessos.dependencies import (
    AUTHORIZER,
    INSTALLATION_ID,
    MESSAGE_DISPATCHER,
    OBJECT_STORAGE,
    OBJECT_STORAGE_DELETE,
    OBJECT_STORAGE_FENCED,
    OBJECT_STORAGE_FENCED_ERASURE,
    RESOURCE_OWNER_RESOLVER,
    UNIT_OF_WORK_FACTORY,
)
from businessos.di import DependencyKey, DependencyResolver, DependencyScope, RequestDependencyScope
from businessos.errors import BusinessOSError, ConfigurationError
from businessos.features import FeatureFlag
from businessos.handler_invocation import (
    HandlerInvocationBinding,
    HandlerInvocationDependency,
    HandlerInvocationKind,
    validate_handler_invocation,
)
from businessos.http import Request, Response
from businessos.http.middleware import Middleware
from businessos.jobs import Job
from businessos.messages import (
    Command,
    DomainEvent,
    EventHandlingContext,
    HandlerTransaction,
    HandlingContext,
    Query,
)
from businessos.metadata import MetadataDeclaration
from businessos.modules import (
    ModuleContractDeclaration,
    ModuleManifest,
    ModuleRegistration,
    ResourceOwnership,
)
from businessos.permissions import PermissionDeclaration
from businessos.persistence.contracts import TransactionalPersistence
from businessos.persistence.uow import (
    InstallationUnitOfWorkFactory,
    UnitOfWork,
    UnitOfWorkFactory,
)
from businessos.resources import (
    AdmittedResourceProvider,
    ResourceLocator,
    ResourceOwnerFacts,
    ResourceOwnerFactsProvider,
    ResourceOwnerLockedFactsProvider,
    ResourceOwnerOperationProvider,
    ResourceOwnerResolver,
)
from businessos.security import (
    Principal,
    PrincipalType,
    RequestIdentity,
    TrustedContextResolver,
)
from businessos.workload import WorkloadAdmissionDenied

__all__ = [
    "AUTHORIZER",
    "INSTALLATION_ID",
    "MESSAGE_DISPATCHER",
    "OBJECT_STORAGE",
    "OBJECT_STORAGE_DELETE",
    "OBJECT_STORAGE_FENCED",
    "OBJECT_STORAGE_FENCED_ERASURE",
    "RESOURCE_OWNER_RESOLVER",
    "UNIT_OF_WORK_FACTORY",
    "AdmittedResourceProvider",
    "BusinessOSError",
    "Command",
    "ConfigurationError",
    "DependencyKey",
    "DependencyResolver",
    "DependencyScope",
    "DomainEvent",
    "EventHandlingContext",
    "FeatureFlag",
    "HandlerInvocationBinding",
    "HandlerInvocationDependency",
    "HandlerInvocationKind",
    "HandlerTransaction",
    "HandlingContext",
    "InstallationUnitOfWorkFactory",
    "Job",
    "MetadataDeclaration",
    "Middleware",
    "ModuleContractDeclaration",
    "ModuleManifest",
    "ModuleRegistration",
    "PermissionDeclaration",
    "Principal",
    "PrincipalType",
    "Query",
    "Request",
    "RequestContext",
    "RequestDependencyScope",
    "RequestIdentity",
    "ResourceLocator",
    "ResourceOwnerFacts",
    "ResourceOwnerFactsProvider",
    "ResourceOwnerLockedFactsProvider",
    "ResourceOwnerOperationProvider",
    "ResourceOwnerResolver",
    "ResourceOwnership",
    "Response",
    "TenantContext",
    "TransactionalPersistence",
    "TrustedContextResolver",
    "UnitOfWork",
    "UnitOfWorkFactory",
    "WorkloadAdmissionDenied",
    "validate_handler_invocation",
]
