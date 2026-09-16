"""Domain and application contracts for the reference data foundation."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ReferenceSetRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    description: str | None = None
    owning_module: str
    is_extensible: bool = True
    is_system: bool = False
    is_active: bool = True
    created_at: datetime


class ReferenceValueRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    set_code: str
    code: str
    label_key: str
    default_label: str
    description: str | None = None
    external_id: str | None = None
    sort_order: int = 0
    seed_version: int = 1
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    is_active: bool = True
    properties: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class NumberSequenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    code: str
    prefix: str
    suffix: str
    next_value: int
    step: int
    padding: int
    is_active: bool = True


class GeneratedNumberRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence_code: str
    formatted_number: str
    numeric_value: int
