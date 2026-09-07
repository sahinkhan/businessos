"""Stable public SDK facade for trusted first-party in-process modules."""

from businessos.context import RequestContext, TenantContext
from businessos.dependencies import MESSAGE_DISPATCHER, OBJECT_STORAGE
from businessos.di import DependencyKey, DependencyScope, RequestDependencyScope
from businessos.errors import BusinessOSError
from businessos.features import FeatureFlag
from businessos.http import Request, Response
from businessos.http.middleware import Middleware
from businessos.jobs import Job
from businessos.messages import Command, DomainEvent, HandlingContext, Query
from businessos.metadata import MetadataDeclaration
from businessos.modules import ModuleManifest, ModuleRegistration
from businessos.permissions import PermissionDeclaration
from businessos.persistence.contracts import TransactionalPersistence

__all__ = [
    "MESSAGE_DISPATCHER",
    "OBJECT_STORAGE",
    "BusinessOSError",
    "Command",
    "DependencyKey",
    "DependencyScope",
    "DomainEvent",
    "FeatureFlag",
    "HandlingContext",
    "Job",
    "MetadataDeclaration",
    "Middleware",
    "ModuleManifest",
    "ModuleRegistration",
    "PermissionDeclaration",
    "Query",
    "Request",
    "RequestContext",
    "RequestDependencyScope",
    "Response",
    "TenantContext",
    "TransactionalPersistence",
]
