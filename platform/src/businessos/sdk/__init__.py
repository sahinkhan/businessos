"""Stable public SDK facade for trusted first-party in-process modules."""

from businessos.context import RequestContext, TenantContext
from businessos.dependencies import (
    MESSAGE_DISPATCHER,
    OBJECT_STORAGE,
    RESOURCE_OWNER_RESOLVER,
    UNIT_OF_WORK_FACTORY,
)
from businessos.di import DependencyKey, DependencyScope, RequestDependencyScope
from businessos.errors import BusinessOSError
from businessos.features import FeatureFlag
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
from businessos.persistence.uow import UnitOfWork, UnitOfWorkFactory
from businessos.resources import (
    AdmittedResourceProvider,
    ResourceLocator,
    ResourceOwnerFacts,
    ResourceOwnerFactsProvider,
    ResourceOwnerOperationProvider,
    ResourceOwnerResolver,
)
from businessos.security import (
    Principal,
    PrincipalType,
    RequestIdentity,
    TrustedContextResolver,
)

__all__ = [
    "MESSAGE_DISPATCHER",
    "OBJECT_STORAGE",
    "RESOURCE_OWNER_RESOLVER",
    "UNIT_OF_WORK_FACTORY",
    "AdmittedResourceProvider",
    "BusinessOSError",
    "Command",
    "DependencyKey",
    "DependencyScope",
    "DomainEvent",
    "EventHandlingContext",
    "FeatureFlag",
    "HandlerTransaction",
    "HandlingContext",
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
    "ResourceOwnerOperationProvider",
    "ResourceOwnerResolver",
    "ResourceOwnership",
    "Response",
    "TenantContext",
    "TransactionalPersistence",
    "TrustedContextResolver",
    "UnitOfWork",
    "UnitOfWorkFactory",
]
