"""Stable public SDK facade for trusted first-party in-process modules."""

from businessos.activation import ContributionGeneration
from businessos.context import RequestContext, TenantContext
from businessos.custom_fields import (
    PUBLISHED_CUSTOM_FIELD_SCHEMA,
    CustomFieldQueryCapabilities,
    CustomFieldValue,
    CustomizableResource,
    CustomSchemaPin,
    CustomValueDocument,
    PublishedCustomFieldSchema,
    PublishedCustomFieldSchemaResolver,
)
from businessos.dependencies import (
    AUTHORIZER,
    INSTALLATION_ID,
    MESSAGE_DISPATCHER,
    METADATA_CATALOG,
    OBJECT_STORAGE,
    OBJECT_STORAGE_DELETE,
    OBJECT_STORAGE_FENCED,
    OBJECT_STORAGE_FENCED_ERASURE,
    RESOURCE_OWNER_RESOLVER,
    UNIT_OF_WORK_FACTORY,
)
from businessos.di import DependencyKey, DependencyResolver, DependencyScope, RequestDependencyScope
from businessos.errors import BusinessOSError, ConfigurationError, NotFoundError
from businessos.features import FeatureFlag
from businessos.handler_invocation import (
    HandlerInvocationBinding,
    HandlerInvocationDependency,
    HandlerInvocationKind,
    assert_resource_owner_invocation,
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
from businessos.metadata import AdmittedMetadataDeclaration, MetadataCatalog, MetadataDeclaration
from businessos.modules import (
    ModuleContractDeclaration,
    ModuleManifest,
    ModuleRegistration,
    ResourceOwnership,
)
from businessos.permissions import PermissionDeclaration
from businessos.persistence.contracts import TransactionalPersistence
from businessos.persistence.uow import (
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
    "METADATA_CATALOG",
    "OBJECT_STORAGE",
    "OBJECT_STORAGE_DELETE",
    "OBJECT_STORAGE_FENCED",
    "OBJECT_STORAGE_FENCED_ERASURE",
    "PUBLISHED_CUSTOM_FIELD_SCHEMA",
    "RESOURCE_OWNER_RESOLVER",
    "UNIT_OF_WORK_FACTORY",
    "AdmittedMetadataDeclaration",
    "AdmittedResourceProvider",
    "BusinessOSError",
    "Command",
    "ConfigurationError",
    "ContributionGeneration",
    "CustomFieldQueryCapabilities",
    "CustomFieldValue",
    "CustomSchemaPin",
    "CustomValueDocument",
    "CustomizableResource",
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
    "Job",
    "MetadataCatalog",
    "MetadataDeclaration",
    "Middleware",
    "ModuleContractDeclaration",
    "ModuleManifest",
    "ModuleRegistration",
    "NotFoundError",
    "PermissionDeclaration",
    "Principal",
    "PrincipalType",
    "PublishedCustomFieldSchema",
    "PublishedCustomFieldSchemaResolver",
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
    "assert_resource_owner_invocation",
    "validate_handler_invocation",
]
