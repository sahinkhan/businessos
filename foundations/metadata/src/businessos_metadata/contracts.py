"""Version 1 public Metadata definition, publication, and reference contracts.

These are boundary values. No persistence model, SQL handle, browser authority, or
executable expression is part of a public contract.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from ipaddress import ip_address
from typing import Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

CONTRACT_VERSION: Literal["1.0"] = "1.0"
_NAME = re.compile(r"[a-z][a-z0-9_]{0,79}\Z", re.ASCII)
_NAMESPACE = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+\Z", re.ASCII)
_PROTECTED = frozenset(
    {
        "id",
        "tenant_id",
        "owner_module_id",
        "resource_namespace",
        "company_id",
        "site_id",
        "created_by",
        "created_at",
        "updated_at",
        "classification_ref",
    }
)


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DefinitionKind(StrEnum):
    FIELD_SET = "field_set"
    REFERENCE_SET = "reference_set"


class DefinitionLifecycle(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class FieldType(StrEnum):
    TEXT = "text"
    LONG_TEXT = "long_text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    INSTANT = "instant"
    ENUM = "enum"
    UUID = "uuid"
    REFERENCE = "reference"
    MONEY = "money"
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"


class Comparison(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"


class MoneyLiteral(_Contract):
    """Exact decimal amount plus explicit ISO-style currency code; never binary float."""

    amount: StrictStr = Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$", max_length=60)
    currency: StrictStr = Field(pattern=r"^[A-Z]{3}$")


LiteralValue = StrictStr | StrictInt | StrictBool | MoneyLiteral


class ValidationRule(_Contract):
    """One total, non-recursive comparison or conditional-required expression."""

    left_field: str = Field(max_length=80)
    comparison: Comparison
    right_literal: LiteralValue
    require_field: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def names(self) -> Self:
        if not _NAME.fullmatch(self.left_field) or (
            self.require_field is not None and not _NAME.fullmatch(self.require_field)
        ):
            raise ValueError("validation rule field identity is invalid")
        if type(self.right_literal) is str and len(self.right_literal) > 1024:
            raise ValueError("validation literal exceeds budget")
        return self


class FieldDefinition(_Contract):
    field_id: UUID
    name: str = Field(max_length=80)
    value_type: FieldType
    nullable: StrictBool = True
    max_length: int | None = Field(default=None, ge=1, le=16384, strict=True)
    precision: int | None = Field(default=None, ge=1, le=38, strict=True)
    scale: int | None = Field(default=None, ge=0, le=18, strict=True)
    enum_choices: tuple[str, ...] = Field(default=(), max_length=100)
    reference_namespace: str | None = Field(default=None, max_length=200)
    reference_contract_version: str | None = Field(default=None, max_length=30)
    classification_ref: str | None = Field(default=None, max_length=200)
    literal_default: LiteralValue | None = None

    @model_validator(mode="after")
    def bounded_type(self) -> Self:
        if not _NAME.fullmatch(self.name) or self.name in _PROTECTED:
            raise ValueError("field name is invalid or owner-protected")
        if self.value_type is FieldType.ENUM:
            if not self.enum_choices or len(set(self.enum_choices)) != len(self.enum_choices):
                raise ValueError("enum choices must be nonempty and unique")
            if any(not _NAME.fullmatch(choice) for choice in self.enum_choices):
                raise ValueError("enum choice identity is invalid")
        elif self.enum_choices:
            raise ValueError("enum choices require enum type")
        if self.value_type is FieldType.REFERENCE:
            if (
                self.reference_namespace is None
                or not _NAMESPACE.fullmatch(self.reference_namespace)
                or not self.reference_contract_version
            ):
                raise ValueError("reference type requires canonical namespace")
        elif self.reference_namespace is not None or self.reference_contract_version is not None:
            raise ValueError("reference namespace requires reference type")
        if (self.precision is None) != (self.scale is None) or (
            self.precision is not None and self.scale is not None and self.scale > self.precision
        ):
            raise ValueError("decimal precision and scale must be valid together")
        if self.precision is not None and self.value_type not in {
            FieldType.DECIMAL,
            FieldType.MONEY,
        }:
            raise ValueError("precision requires decimal or money type")
        if self.max_length is not None and self.value_type not in {
            FieldType.TEXT,
            FieldType.LONG_TEXT,
            FieldType.EMAIL,
            FieldType.PHONE,
            FieldType.URL,
        }:
            raise ValueError("max_length requires text type")
        if self.classification_ref is not None and not _NAMESPACE.fullmatch(
            self.classification_ref
        ):
            raise ValueError("classification reference must be qualified")
        if self.value_type in {FieldType.DECIMAL, FieldType.MONEY} and self.precision is None:
            raise ValueError("decimal and money require precision and scale")
        if self.literal_default is not None:
            self.validate_literal(self.literal_default)
        return self

    def validate_literal(self, value: LiteralValue) -> None:
        """Validate the complete bounded literal grammar without coercion or execution."""
        kind = self.value_type
        if kind is FieldType.BOOLEAN:
            if type(value) is not bool:
                raise ValueError("boolean literal required")
            return
        if kind is FieldType.INTEGER:
            if type(value) is not int or not -(2**63) <= value < 2**63:
                raise ValueError("signed 64-bit integer literal required")
            return
        if kind is FieldType.REFERENCE:
            raise ValueError(
                "reference literals require authoritative resolution and are unsupported"
            )
        if kind in {FieldType.DECIMAL, FieldType.MONEY}:
            amount = value.amount if isinstance(value, MoneyLiteral) else value
            if (kind is FieldType.MONEY) != isinstance(value, MoneyLiteral):
                raise ValueError("money literal requires an amount and currency")
            if (
                not isinstance(amount, str)
                or len(amount) > 60
                or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", amount, re.ASCII)
            ):
                raise ValueError("exact bounded decimal literal required")
            number = Decimal(amount)
            _, digits, exponent = number.as_tuple()
            assert isinstance(exponent, int)
            assert self.precision is not None and self.scale is not None
            fraction = max(-exponent, 0)
            integral = 0 if number.is_zero() else max(len(digits) + exponent, 0)
            if fraction > self.scale or integral > self.precision - self.scale:
                raise ValueError("decimal literal exceeds precision or scale")
            return
        if not isinstance(value, str) or len(value) > (self.max_length or 16384):
            raise ValueError("bounded string literal required")
        if kind is FieldType.ENUM and value not in self.enum_choices:
            raise ValueError("literal is not an enum choice")
        if kind is FieldType.UUID:
            if str(UUID(value)) != value:
                raise ValueError("canonical UUID literal required")
        if kind is FieldType.DATE:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError("ISO date literal required")
            date.fromisoformat(value)
        if kind is FieldType.INSTANT:
            if not re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])",
                value,
            ):
                raise ValueError("timezone-qualified ISO instant literal required")
            datetime.fromisoformat(value)
        if kind is FieldType.EMAIL:
            if (
                len(value) > 254
                or not re.fullmatch(
                    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
                    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",
                    value,
                )
                or len(value.split("@", 1)[0]) > 64
            ):
                raise ValueError("bounded email literal required")
        if kind is FieldType.URL:
            parts = urlsplit(value)
            if (
                len(value) > 2048
                or parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or any(char.isspace() or ord(char) < 32 for char in value)
                or "\\" in value
            ):
                raise ValueError("absolute HTTP(S) URL without credentials required")
            _ = parts.port  # Validates numeric port range.
            hostname = parts.hostname
            assert hostname is not None
            try:
                ip_address(hostname)
            except ValueError:
                host = hostname.encode("idna").decode("ascii")
                if len(host) > 253 or any(
                    not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                    for label in host.split(".")
                ):
                    raise ValueError("invalid URL hostname") from None
        if kind is FieldType.PHONE and not re.fullmatch(r"\+?[0-9][0-9 ()-]{1,30}[0-9]", value):
            raise ValueError("bounded phone literal required")


class MetadataLimits(_Contract):
    max_definitions_per_tenant: int = Field(default=1000, ge=1, le=100000)
    max_document_bytes: int = Field(default=65536, ge=1024, le=1048576)
    max_fields: int = Field(default=128, ge=1, le=1024)
    max_rules: int = Field(default=32, ge=0, le=256)
    max_bulk_references: int = Field(default=100, ge=1, le=1000)


class DefinitionSnapshot(_Contract):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    kind: DefinitionKind
    fields: tuple[FieldDefinition, ...] = Field(default=(), max_length=1024)
    rules: tuple[ValidationRule, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if not self.fields:
            raise ValueError("definition must contain fields")
        names = {field.name for field in self.fields}
        if len(names) != len(self.fields) or len({field.field_id for field in self.fields}) != len(
            self.fields
        ):
            raise ValueError("field names and stable IDs must be unique")
        if any(
            rule.left_field not in names
            or (rule.require_field is not None and rule.require_field not in names)
            for rule in self.rules
        ):
            raise ValueError("validation rule references an unknown field")
        by_name = {field.name: field for field in self.fields}
        ordered = {FieldType.INTEGER, FieldType.DECIMAL, FieldType.DATE, FieldType.INSTANT}
        for rule in self.rules:
            field = by_name[rule.left_field]
            field.validate_literal(rule.right_literal)
            if (
                rule.comparison not in {Comparison.EQ, Comparison.NE}
                and field.value_type not in ordered
            ):
                raise ValueError("ordering comparison is incompatible with field type")
        return self

    def validate_limits(self, limits: MetadataLimits) -> None:
        if len(self.fields) > limits.max_fields or len(self.rules) > limits.max_rules:
            raise ValueError("metadata count quota exceeded")
        if len(self.model_dump_json().encode("utf-8")) > limits.max_document_bytes:
            raise ValueError("metadata byte quota exceeded")

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


class DefinitionIdentity(_Contract):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    definition_id: UUID
    tenant_id: UUID
    owner_module_id: str = Field(max_length=150)
    resource_namespace: str = Field(max_length=200)
    owner_contract_version: str = Field(min_length=1, max_length=30)
    kind: DefinitionKind

    @model_validator(mode="after")
    def canonical_owner(self) -> Self:
        if not _NAMESPACE.fullmatch(
            self.resource_namespace
        ) or not self.resource_namespace.startswith(self.owner_module_id + "."):
            raise ValueError("resource namespace must belong to canonical owner")
        return self


class DefinitionRecord(_Contract):
    identity: DefinitionIdentity
    lifecycle: DefinitionLifecycle
    draft_generation: int = Field(ge=1)
    active_revision_id: UUID | None
    active_generation: int = Field(ge=0)


class DraftRecord(_Contract):
    definition: DefinitionRecord
    snapshot: DefinitionSnapshot


class RevisionRecord(_Contract):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    revision_id: UUID
    tenant_id: UUID
    definition_id: UUID
    sequence: int = Field(ge=1)
    snapshot: DefinitionSnapshot
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    published_at: datetime
    provenance: str = Field(min_length=1, max_length=200)


class GenerationExpectation(_Contract):
    module_id: str
    artifact_identity: str = Field(min_length=1, max_length=200)
    generation: int = Field(ge=1)


class PublishPreflight(_Contract):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    definition_id: UUID
    target_revision_id: UUID | None = None
    expected_draft_generation: int = Field(ge=1)
    expected_active_revision_id: UUID | None
    expected_active_generation: int = Field(ge=0)
    expected_base: GenerationExpectation
    expected_schema_generation: int = Field(ge=1)
    expected_ui_generation: int = Field(ge=1)
    dependencies: tuple[GenerationExpectation, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def unique_dependencies(self) -> Self:
        names = (self.expected_base.module_id, *(item.module_id for item in self.dependencies))
        if len(set(names)) != len(names):
            raise ValueError("module generation expectations must be unique")
        return self


class PublicationStatus(StrEnum):
    SUCCESS = "success"
    STALE_DRAFT = "stale_draft"
    ACTIVE_REVISION_CONFLICT = "active_revision_conflict"
    MODULE_BASE_CHANGED = "module_base_changed"
    INCOMPATIBLE_DEPENDENCY = "incompatible_dependency"
    QUOTA_VALIDATION_FAILURE = "quota_validation_failure"
    AUTHORITY_DENIED = "authority_denied"
    CLASSIFICATION_UNAVAILABLE = "classification_unavailable"
    RETIRED_TARGET = "retired_target"
    UNAVAILABLE_TARGET = "unavailable_target"
    CROSS_OWNER_DELETE_UNSUPPORTED = "cross_owner_delete_unsupported"


class PublicationResult(_Contract):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    status: PublicationStatus
    definition_id: UUID
    revision_id: UUID | None = None
    active_generation: int | None = None
    diagnostic: str | None = Field(default=None, max_length=300)


class CanonicalResourceReference(_Contract):
    tenant_id: UUID
    resource_namespace: str = Field(max_length=200)
    contract_version: str = Field(min_length=1, max_length=30)
    record_id: UUID

    @model_validator(mode="after")
    def canonical_namespace(self) -> Self:
        if not _NAMESPACE.fullmatch(self.resource_namespace):
            raise ValueError("reference namespace is not canonical")
        return self


class ReferenceState(StrEnum):
    AVAILABLE = "available"
    RETIRED = "retired"
    UNAVAILABLE = "unavailable"


class ReferenceResolution(_Contract):
    reference: CanonicalResourceReference
    state: ReferenceState
    referenceable: bool
    diagnostic: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def valid_state(self) -> Self:
        if self.referenceable != (self.state is ReferenceState.AVAILABLE):
            raise ValueError("only available targets are referenceable")
        return self


class BulkReferenceRequest(_Contract):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    tenant_id: UUID
    references: tuple[CanonicalResourceReference, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def tenant_bound(self) -> Self:
        if any(item.tenant_id != self.tenant_id for item in self.references):
            raise ValueError("cross-tenant reference resolution is forbidden")
        if len(set(self.references)) != len(self.references):
            raise ValueError("duplicate references are forbidden")
        return self


class BulkReferenceResult(_Contract):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    results: tuple[ReferenceResolution, ...] = Field(max_length=100)


def require_referenceable(result: ReferenceResolution, tenant_id: UUID) -> None:
    """Source owner validates a new reference; historical values remain diagnosable."""
    if result.reference.tenant_id != tenant_id or not result.referenceable:
        raise ValueError("target is not tenant-bound and referenceable")
