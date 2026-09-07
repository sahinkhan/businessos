"""Stable public SDK facade for trusted first-party in-process modules."""

from typing import cast

from businessos.context import RequestContext, TenantContext
from businessos.dependencies import CACHE as _CACHE
from businessos.dependencies import MESSAGE_DISPATCHER as _MESSAGES
from businessos.dependencies import OBJECT_STORAGE as _STORAGE
from businessos.di import DependencyKey, DependencyScope
from businessos.errors import BusinessOSError
from businessos.features import FeatureFlag
from businessos.http import Request, Response
from businessos.http.middleware import Middleware
from businessos.jobs import Job
from businessos.messages import Command, DomainEvent, EventHandlingContext, HandlingContext, Query
from businessos.metadata import MetadataDeclaration
from businessos.module_access import CommandClient, ModuleDependencies, TenantCache, TenantStorage
from businessos.modules import ModuleManifest, ModuleRegistration
from businessos.permissions import PermissionDeclaration
from businessos.persistence.repository import Repository

RequestDependencyScope = ModuleDependencies
MESSAGE_DISPATCHER = cast(DependencyKey[CommandClient], _MESSAGES)
OBJECT_STORAGE = cast(DependencyKey[TenantStorage], _STORAGE)
CACHE = cast(DependencyKey[TenantCache], _CACHE)

TransactionalPersistence = Repository

__all__ = [
    "CACHE",
    "MESSAGE_DISPATCHER",
    "OBJECT_STORAGE",
    "BusinessOSError",
    "Command",
    "DependencyKey",
    "DependencyScope",
    "DomainEvent",
    "EventHandlingContext",
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
