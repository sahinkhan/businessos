"""Metadata/Studio Foundation; persistent definitions are not kernel metadata declarations."""

from .custom_entities import (
    CustomEntityExport,
    CustomEntityIdentity,
    CustomEntityLifecycle,
    CustomEntityLimits,
    CustomEntityPage,
    CustomEntityQueryCapabilities,
    CustomEntityRecord,
    CustomEntityScopeKind,
)
from .module import (
    ArchiveCustomEntity,
    CreateCustomEntity,
    ExportCustomEntity,
    ListCustomEntities,
    MetadataModule,
    ReadCustomEntity,
    UpdateCustomEntity,
)

__all__ = [
    "ArchiveCustomEntity",
    "CreateCustomEntity",
    "CustomEntityExport",
    "CustomEntityIdentity",
    "CustomEntityLifecycle",
    "CustomEntityLimits",
    "CustomEntityPage",
    "CustomEntityQueryCapabilities",
    "CustomEntityRecord",
    "CustomEntityScopeKind",
    "ExportCustomEntity",
    "ListCustomEntities",
    "MetadataModule",
    "ReadCustomEntity",
    "UpdateCustomEntity",
]
