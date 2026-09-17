"""Stable dependency keys published by the protected framework SDK."""

from businessos.di import DependencyKey
from businessos.messages import MessageDispatcher
from businessos.persistence import Database, UnitOfWorkFactory
from businessos.providers import (
    CacheProvider,
    EventPublisher,
    ObjectStorageProvider,
    ProviderRegistry,
)
from businessos.security import Authorizer, TrustedContextResolver

DATABASE = DependencyKey[Database]("businessos.database")
UNIT_OF_WORK_FACTORY = DependencyKey[UnitOfWorkFactory]("businessos.unit_of_work_factory")
AUTHORIZER = DependencyKey[Authorizer]("businessos.authorizer")
MESSAGE_DISPATCHER = DependencyKey[MessageDispatcher]("businessos.message_dispatcher")
CACHE = DependencyKey[CacheProvider]("businessos.cache")
EVENT_PUBLISHER = DependencyKey[EventPublisher]("businessos.event_publisher")
OBJECT_STORAGE = DependencyKey[ObjectStorageProvider]("businessos.object_storage")
PROVIDER_REGISTRY = DependencyKey[ProviderRegistry]("businessos.provider_registry")
TRUSTED_CONTEXT_RESOLVER = DependencyKey[TrustedContextResolver](
    "businessos.trusted_context_resolver"
)
