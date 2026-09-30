"""Public versioned contracts, commands, queries, and domain events for metadata foundation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from businessos.contracts import PublicContract
from businessos.messages import DomainEvent
from businessos.sdk import Command, DependencyKey, Query

from .diagnostics import MetadataDiagnosticCode, MetadataDiagnosticRecord
from .fence import FenceStateRecord
from .grammar import FieldDefinitionModel, MetadataPayloadModel
from .references import (
    BulkReferenceResolutionQuery,
    ReferenceResolutionQuery,
    ReferenceResolutionRecord,
    ReferenceResolutionResult,
    TargetReferenceState,
)

METADATA_DEFINITION_CONTRACT_V1 = "foundation.metadata.definition.v1"
METADATA_REVISION_CONTRACT_V1 = "foundation.metadata.revision.v1"
METADATA_PUBLISH_CONTRACT_V1 = "foundation.metadata.publish.v1"
METADATA_ROLLBACK_CONTRACT_V1 = "foundation.metadata.rollback.v1"
VALIDATION_GRAMMAR_CONTRACT_V1 = "foundation.metadata.validation-grammar.v1"
REFERENCE_RESOLUTION_CONTRACT_V1 = "foundation.metadata.reference-resolution.v1"
METADATA_PUBLICATION_FENCE_CONTRACT_V1 = "foundation.metadata.publication-fence.v1"


class MetadataLifecycleStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"
    ARCHIVED = "archived"


class PublishStatus(StrEnum):
    SUCCESS = "success"
    STALE_DRAFT = "stale_draft"
    ACTIVE_REVISION_CONFLICT = "active_revision_conflict"
    MODULE_BASE_GENERATION_CHANGED = "module_base_generation_changed"
    SCHEMA_UI_GENERATION_CHANGED = "schema_ui_generation_changed"
    INCOMPATIBLE_DEPENDENCY = "incompatible_dependency"
    QUOTA_EXCEEDED = "quota_exceeded"
    VALIDATION_FAILED = "validation_failed"
    POLICY_DENIED = "policy_denied"


class RollbackStatus(StrEnum):
    SUCCESS = "success"
    ACTIVE_REVISION_CONFLICT = "active_revision_conflict"
    MODULE_BASE_GENERATION_CHANGED = "module_base_generation_changed"
    SCHEMA_UI_GENERATION_CHANGED = "schema_ui_generation_changed"
    INCOMPATIBLE_DEPENDENCY = "incompatible_dependency"
    REVISION_NOT_FOUND = "revision_not_found"
    INCOMPATIBLE_REVISION = "incompatible_revision"
    POLICY_DENIED = "policy_denied"


class MetadataRevisionProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    published_by: str
    published_at: datetime
    draft_generation: int
    module_base_generation: int
    schema_ui_generation: int
    dependencies_generation: int
    comment: str = ""


class MetadataDefinitionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    tenant_id: UUID
    owner_namespace: str
    definition_kind: str
    stable_key: str
    lifecycle_status: MetadataLifecycleStatus
    draft_generation: int
    draft_payload: dict[str, Any] | None = None
    active_revision_id: UUID | None = None
    active_generation: int = 0
    created_by: str
    created_at: datetime
    updated_at: datetime


class MetadataRevisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    tenant_id: UUID
    definition_id: UUID
    revision_seq: int
    schema_version: str
    content_digest: str
    payload: dict[str, Any]
    provenance: MetadataRevisionProvenance
    created_at: datetime


class MetadataActivePointerRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    definition_id: UUID
    revision_id: UUID
    active_generation: int
    activated_at: datetime
    activated_by: str


class PublishPreflightInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_id: UUID
    expected_draft_generation: int
    expected_active_revision_id: UUID | None
    expected_module_base_generation: int
    expected_schema_ui_generation: int
    expected_dependencies_generation: int


class PublishPreflightResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    diagnostic_code: MetadataDiagnosticCode | None = None
    diagnostic_message: str | None = None
    preflight_input: PublishPreflightInput
    current_fence: FenceStateRecord


class PublishResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: PublishStatus
    revision: MetadataRevisionRecord | None = None
    active_pointer: MetadataActivePointerRecord | None = None
    diagnostic: MetadataDiagnosticRecord | None = None


class RollbackPreflightInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_id: UUID
    target_revision_id: UUID
    expected_active_revision_id: UUID
    expected_module_base_generation: int
    expected_schema_ui_generation: int
    expected_dependencies_generation: int


class RollbackPreflightResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    diagnostic_code: MetadataDiagnosticCode | None = None
    diagnostic_message: str | None = None
    preflight_input: RollbackPreflightInput
    current_fence: FenceStateRecord


class RollbackResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RollbackStatus
    active_pointer: MetadataActivePointerRecord | None = None
    diagnostic: MetadataDiagnosticRecord | None = None


# --- Commands and Queries ---


class CreateDraftDefinitionCommand(Command):
    owner_namespace: str = Field(min_length=1, max_length=100)
    definition_kind: str = Field(min_length=1, max_length=50)
    stable_key: str = Field(min_length=2, max_length=100)
    payload: MetadataPayloadModel


class UpdateDraftDefinitionCommand(Command):
    definition_id: UUID
    expected_draft_generation: int
    payload: MetadataPayloadModel


class PublishDraftCommand(Command):
    definition_id: UUID
    preflight: PublishPreflightInput
    comment: str = ""


class RollbackRevisionCommand(Command):
    definition_id: UUID
    target_revision_id: UUID
    preflight: RollbackPreflightInput
    comment: str = ""


class RetireDefinitionCommand(Command):
    definition_id: UUID
    reason: str = Field(default="", max_length=500)


class GetDefinitionQuery(Query):
    definition_id: UUID


class GetPublishedDefinitionQuery(Query):
    owner_namespace: str
    definition_kind: str
    stable_key: str


class ListDefinitionsQuery(Query):
    owner_namespace: str | None = None
    definition_kind: str | None = None
    status: MetadataLifecycleStatus | None = None


class GetActiveRevisionQuery(Query):
    definition_id: UUID


class GetRevisionByIdQuery(Query):
    definition_id: UUID
    revision_id: UUID


class ListRevisionsQuery(Query):
    definition_id: UUID


# --- Domain Events for Outbox Integration ---


class MetadataDraftCreated(DomainEvent):
    event_type: ClassVar[str] = "metadata.draft.created"
    schema_version: ClassVar[int] = 1

    definition_id: UUID
    owner_namespace: str
    definition_kind: str
    stable_key: str
    draft_generation: int


class MetadataDraftUpdated(DomainEvent):
    event_type: ClassVar[str] = "metadata.draft.updated"
    schema_version: ClassVar[int] = 1

    definition_id: UUID
    draft_generation: int


class MetadataRevisionPublished(DomainEvent):
    event_type: ClassVar[str] = "metadata.revision.published"
    schema_version: ClassVar[int] = 1

    definition_id: UUID
    revision_id: UUID
    revision_seq: int
    content_digest: str
    active_generation: int
    published_by: str


class MetadataRevisionReactivated(DomainEvent):
    event_type: ClassVar[str] = "metadata.revision.reactivated"
    schema_version: ClassVar[int] = 1

    definition_id: UUID
    revision_id: UUID
    revision_seq: int
    active_generation: int
    reactivated_by: str


class MetadataDefinitionRetired(DomainEvent):
    event_type: ClassVar[str] = "metadata.definition.retired"
    schema_version: ClassVar[int] = 1

    definition_id: UUID
    retired_by: str


# --- Public Contract Interfaces ---


class MetadataDefinitionContractV1(PublicContract, Protocol):
    @property
    def version(self) -> str: ...

    async def create_draft(
        self,
        tenant_id: UUID,
        owner_namespace: str,
        definition_kind: str,
        stable_key: str,
        payload: MetadataPayloadModel,
        created_by: str,
        *,
        ctx: Any = None,
    ) -> MetadataDefinitionRecord: ...

    async def update_draft(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        expected_draft_generation: int,
        payload: MetadataPayloadModel,
        updated_by: str,
        *,
        ctx: Any = None,
    ) -> MetadataDefinitionRecord: ...

    async def get_definition(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        *,
        executor: Any = None,
    ) -> MetadataDefinitionRecord: ...

    async def get_published_definition(
        self,
        tenant_id: UUID,
        owner_namespace: str,
        definition_kind: str,
        stable_key: str,
        *,
        executor: Any = None,
    ) -> tuple[MetadataDefinitionRecord, MetadataRevisionRecord]: ...

    async def list_definitions(
        self,
        tenant_id: UUID,
        owner_namespace: str | None = None,
        definition_kind: str | None = None,
        status: MetadataLifecycleStatus | None = None,
        *,
        executor: Any = None,
    ) -> tuple[MetadataDefinitionRecord, ...]: ...

    async def retire(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        retired_by: str,
        *,
        ctx: Any = None,
    ) -> MetadataDefinitionRecord: ...


class MetadataRevisionContractV1(PublicContract, Protocol):
    @property
    def version(self) -> str: ...

    async def get_active_revision(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        *,
        executor: Any = None,
    ) -> MetadataRevisionRecord: ...

    async def get_revision_by_id(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        revision_id: UUID,
        *,
        executor: Any = None,
    ) -> MetadataRevisionRecord: ...

    async def list_revisions(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        *,
        executor: Any = None,
    ) -> tuple[MetadataRevisionRecord, ...]: ...


class MetadataPublishContractV1(PublicContract, Protocol):
    @property
    def version(self) -> str: ...

    async def preflight(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        fence_scope: str,
        *,
        executor: Any = None,
    ) -> PublishPreflightResult: ...

    async def publish(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        preflight: PublishPreflightInput,
        published_by: str,
        *,
        comment: str = "",
        fence_scope: str | None = None,
        ctx: Any = None,
    ) -> PublishResult: ...


class MetadataRollbackContractV1(PublicContract, Protocol):
    @property
    def version(self) -> str: ...

    async def preflight_rollback(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        target_revision_id: UUID,
        fence_scope: str,
        *,
        executor: Any = None,
    ) -> RollbackPreflightResult: ...

    async def rollback(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        target_revision_id: UUID,
        preflight: RollbackPreflightInput,
        reactivated_by: str,
        *,
        comment: str = "",
        fence_scope: str | None = None,
        ctx: Any = None,
    ) -> RollbackResult: ...


class ValidationGrammarContractV1(PublicContract, Protocol):
    @property
    def version(self) -> str: ...

    def validate_payload(self, payload: dict[str, Any] | MetadataPayloadModel) -> MetadataPayloadModel: ...


class ReferenceResolutionContractV1(PublicContract, Protocol):
    @property
    def version(self) -> str: ...

    async def resolve_reference(
        self,
        query: ReferenceResolutionQuery,
        *,
        executor: Any = None,
    ) -> ReferenceResolutionRecord: ...

    async def resolve_bulk_references(
        self,
        query: BulkReferenceResolutionQuery,
        *,
        executor: Any = None,
    ) -> ReferenceResolutionResult: ...


class MetadataPublicationFenceContractV1(PublicContract, Protocol):
    @property
    def version(self) -> str: ...

    async def get_fence_state(
        self,
        tenant_id: UUID,
        fence_scope: str,
        *,
        executor: Any = None,
    ) -> FenceStateRecord: ...


METADATA_DEFINITION_SERVICE_V1 = DependencyKey[MetadataDefinitionContractV1](
    METADATA_DEFINITION_CONTRACT_V1, required_owner="foundation.metadata"
)
METADATA_REVISION_SERVICE_V1 = DependencyKey[MetadataRevisionContractV1](
    METADATA_REVISION_CONTRACT_V1, required_owner="foundation.metadata"
)
METADATA_PUBLISH_SERVICE_V1 = DependencyKey[MetadataPublishContractV1](
    METADATA_PUBLISH_CONTRACT_V1, required_owner="foundation.metadata"
)
METADATA_ROLLBACK_SERVICE_V1 = DependencyKey[MetadataRollbackContractV1](
    METADATA_ROLLBACK_CONTRACT_V1, required_owner="foundation.metadata"
)
VALIDATION_GRAMMAR_SERVICE_V1 = DependencyKey[ValidationGrammarContractV1](
    VALIDATION_GRAMMAR_CONTRACT_V1, required_owner="foundation.metadata"
)
REFERENCE_RESOLUTION_SERVICE_V1 = DependencyKey[ReferenceResolutionContractV1](
    REFERENCE_RESOLUTION_CONTRACT_V1, required_owner="foundation.metadata"
)
METADATA_PUBLICATION_FENCE_SERVICE_V1 = DependencyKey[MetadataPublicationFenceContractV1](
    METADATA_PUBLICATION_FENCE_CONTRACT_V1, required_owner="foundation.metadata"
)
