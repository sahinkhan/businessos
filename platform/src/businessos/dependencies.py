"""Stable dependency keys published by the protected framework SDK."""

from uuid import UUID

from businessos.di import DependencyKey
from businessos.messages import MessageDispatcher
from businessos.persistence import Database, UnitOfWorkFactory
from businessos.providers import (
    CacheProvider,
    EventPublisher,
    FencedObjectHistoryErasureProvider,
    FencedObjectStorageProvider,
    ObjectStorageDeleteProvider,
    ObjectStorageProvider,
)
from businessos.resources import ResourceOwnerResolver
from businessos.security import Authorizer

DATABASE = DependencyKey[Database]("businessos.database")
INSTALLATION_ID = DependencyKey[UUID]("businessos.installation_id")
UNIT_OF_WORK_FACTORY = DependencyKey[UnitOfWorkFactory]("businessos.unit_of_work_factory")
AUTHORIZER = DependencyKey[Authorizer]("businessos.authorizer")
MESSAGE_DISPATCHER = DependencyKey[MessageDispatcher]("businessos.message_dispatcher")
CACHE = DependencyKey[CacheProvider]("businessos.cache")
EVENT_PUBLISHER = DependencyKey[EventPublisher]("businessos.event_publisher")
OBJECT_STORAGE = DependencyKey[ObjectStorageProvider]("businessos.object_storage")
OBJECT_STORAGE_DELETE = DependencyKey[ObjectStorageDeleteProvider](
    "businessos.object_storage_delete"
)
OBJECT_STORAGE_FENCED = DependencyKey[FencedObjectStorageProvider](
    "businessos.object_storage_fenced"
)
OBJECT_STORAGE_FENCED_ERASURE = DependencyKey[FencedObjectHistoryErasureProvider](
    "businessos.object_storage_fenced_erasure"
)
RESOURCE_OWNER_RESOLVER = DependencyKey[ResourceOwnerResolver]("businessos.resource_owner_resolver")
