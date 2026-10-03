"""Additive v1 owner customization contracts; no field grammar or persistence authority.

Metadata derives the immutable schema projection from its certified grammar.
Owners consume that projection inside their admitted resource transaction.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from businessos.di import DependencyKey
from businessos.errors import BusinessOSError
from businessos.messages import HandlingContext
from businessos.resources import ResourceLocator


class CustomFieldValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    field_id: UUID
    value: JsonValue


class CustomValueDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    contract_version: Literal["1.0"] = "1.0"
    tenant_id: UUID
    resource_namespace: str
    record_id: UUID
    definition_id: UUID
    revision_id: UUID
    revision_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    value_version: int = Field(ge=1)
    cleared: bool
    values: tuple[CustomFieldValue, ...]


@dataclass(frozen=True, slots=True)
class CustomFieldQueryCapabilities:
    version: str = "1.0"
    display: bool = True
    filter: bool = False
    sort: bool = False
    search: bool = False
    uniqueness: bool = False

    def require(self, operation: str) -> None:
        if operation != "display":
            raise BusinessOSError(
                "custom_query_unsupported", "Only direct record display is supported"
            )


@dataclass(frozen=True, slots=True)
class CustomizableResource:
    version: str
    resource_namespace: str
    owner_contract_version: str
    field_grammar: str = "foundation.metadata.definition@1.0"
    max_fields: int = 128
    max_document_bytes: int = 65536
    readable: bool = True
    writable: bool = True
    clearable: bool = True
    exportable: bool = True
    optimistic_concurrency: bool = True
    writes_require_active: bool = True
    reference_fields: bool = False
    classified_fields: bool = False
    query: CustomFieldQueryCapabilities = CustomFieldQueryCapabilities()


@dataclass(frozen=True, slots=True)
class CustomSchemaPin:
    definition_id: UUID
    revision_id: UUID
    digest: str


class PublishedCustomFieldSchema(Protocol):
    """Safe immutable facts and bounded validation derived by Metadata, never draft data."""

    @property
    def pin(self) -> CustomSchemaPin: ...

    @property
    def canonical_schema_json(self) -> str: ...

    @property
    def supported_field_types(self) -> tuple[str, ...]: ...

    def validate_values(self, values: Mapping[str, object], *, cleared: bool = False) -> str:
        """Return canonical JSON, rejecting unsupported, classified or malformed values."""
        ...


class PublishedCustomFieldSchemaResolver(Protocol):
    version: str

    async def resolve(
        self,
        locator: ResourceLocator,
        context: HandlingContext,
        *,
        pin: CustomSchemaPin | None = None,
    ) -> PublishedCustomFieldSchema: ...


PUBLISHED_CUSTOM_FIELD_SCHEMA: DependencyKey[PublishedCustomFieldSchemaResolver] = DependencyKey(
    "foundation.metadata.published-custom-field-schema.v1", required_owner="foundation.metadata"
)
