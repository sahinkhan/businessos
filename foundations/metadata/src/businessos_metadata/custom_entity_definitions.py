"""Dedicated v1 custom-type envelopes; frozen ordinary definition v1 coexists."""

import hashlib
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    DefinitionKind,
    DefinitionLifecycle,
    DefinitionSnapshot,
    FieldDefinition,
    MetadataLimits,
    ValidationRule,
)


class CustomEntityDefinitionKind(StrEnum):
    CUSTOM_ENTITY = "custom_entity"


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CustomEntityDefinitionSnapshot(_Contract):
    contract_version: Literal["1.0"] = "1.0"
    kind: CustomEntityDefinitionKind = CustomEntityDefinitionKind.CUSTOM_ENTITY
    fields: tuple[FieldDefinition, ...] = Field(default=(), max_length=1024)
    rules: tuple[ValidationRule, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def certified_grammar(self) -> Self:
        self._grammar()
        return self

    def _grammar(self) -> DefinitionSnapshot:
        return DefinitionSnapshot(
            kind=DefinitionKind.FIELD_SET, fields=self.fields, rules=self.rules
        )

    def validate_limits(self, limits: MetadataLimits) -> None:
        self._grammar().validate_limits(limits)
        if len(self.model_dump_json().encode("utf-8")) > limits.max_document_bytes:
            raise ValueError("metadata byte quota exceeded")

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


class CustomEntityDefinitionIdentity(_Contract):
    contract_version: Literal["1.0"] = "1.0"
    definition_id: UUID
    tenant_id: UUID
    owner_module_id: Literal["foundation.metadata"] = "foundation.metadata"
    resource_namespace: Literal["foundation.metadata.custom_entity"] = (
        "foundation.metadata.custom_entity"
    )
    owner_contract_version: Literal["1"] = "1"
    kind: CustomEntityDefinitionKind = CustomEntityDefinitionKind.CUSTOM_ENTITY


class CustomEntityDefinitionRecord(_Contract):
    identity: CustomEntityDefinitionIdentity
    lifecycle: DefinitionLifecycle
    draft_generation: int = Field(ge=1)
    active_revision_id: UUID | None
    active_generation: int = Field(ge=0)


class CustomEntityDraftRecord(_Contract):
    definition: CustomEntityDefinitionRecord
    snapshot: CustomEntityDefinitionSnapshot


class CustomEntityRevisionRecord(_Contract):
    contract_version: Literal["1.0"] = "1.0"
    revision_id: UUID
    tenant_id: UUID
    definition_id: UUID
    sequence: int = Field(ge=1)
    snapshot: CustomEntityDefinitionSnapshot
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    published_at: datetime
    provenance: str = Field(min_length=1, max_length=200)


def internal_snapshot(value: object) -> DefinitionSnapshot | CustomEntityDefinitionSnapshot:
    """Private persisted-kind decoding, never an ordinary v1 response adapter."""
    if isinstance(value, dict) and cast(Mapping[str, object], value).get("kind") == "custom_entity":
        return CustomEntityDefinitionSnapshot.model_validate(value)
    return DefinitionSnapshot.model_validate(value)
