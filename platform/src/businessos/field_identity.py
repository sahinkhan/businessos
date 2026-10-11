"""ADR-025 v1 neutral field values, not issued authority or provider admission.

Every public value in this module is freely constructible representation data.
Equality, validation and serialization cannot authenticate a provider, confer a
permission, retain an admission, or issue an invocation/UOW-bound witness. Those
runtime guarantees require separately authorized implementation gates.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)

from businessos.context import RequestContext
from businessos.messages import HandlerTransaction

FIELD_CONTRACT_VERSION: Literal["1.0"] = "1.0"
CANONICAL_FIELD_LOCATOR_CONTRACT_ID = "platform.canonical-field-locator.v1"
OWNER_FIELD_WITNESS_CONTRACT_ID = "platform.owner-field-witness.v1"
MAX_FIELD_OPERATION_FIELDS = 128

_IDENTITY = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*\Z", re.ASCII)
_NAMESPACE = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+\Z", re.ASCII)
_VERSION = re.compile(r"[1-9][0-9]*(?:\.(?:0|[1-9][0-9]*)){0,2}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_OPAQUE_IDENTITY = re.compile(r"[!-~]{1,200}\Z", re.ASCII)


def _canonical_uuid(value: object, info: ValidationInfo) -> UUID:
    if info.mode == "json":
        if type(value) is not str:
            raise ValueError("UUID JSON identity must be canonical text")
        try:
            identity = UUID(value)
        except ValueError as exc:
            raise ValueError("UUID JSON identity must be canonical text") from exc
        if str(identity) != value:
            raise ValueError("UUID JSON identity must be lowercase hyphenated text")
        return identity
    if type(value) is not UUID:
        raise ValueError("Python identity must be an exact UUID")
    return value


def _canonical_identity(value: object) -> str:
    if type(value) is not str or len(value) > 200 or not _IDENTITY.fullmatch(value):
        raise ValueError("Identity must use bounded canonical lowercase ASCII segments")
    return value


def _canonical_namespace(value: object) -> str:
    if type(value) is not str or len(value) > 200 or not _NAMESPACE.fullmatch(value):
        raise ValueError("Namespace must use bounded canonical lowercase ASCII segments")
    return value


def _canonical_version(value: object) -> str:
    if type(value) is not str or len(value) > 30 or not _VERSION.fullmatch(value):
        raise ValueError("Version must be an exact bounded numeric contract version")
    return value


def _canonical_sha256(value: object) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise ValueError("Digest must be exactly 64 lowercase hexadecimal characters")
    return value


def _provenance_identity(value: object) -> str:
    if type(value) is not str or not _OPAQUE_IDENTITY.fullmatch(value):
        raise ValueError("Provenance identity must be bounded exact visible ASCII")
    return value


def _utc_instant(value: datetime) -> datetime:
    if type(value) is not datetime or value.utcoffset() != timedelta(0):
        raise ValueError("Effective instant must be an aware UTC datetime")
    return value


type CanonicalUUID = Annotated[UUID, BeforeValidator(_canonical_uuid)]
type CanonicalIdentity = Annotated[str, BeforeValidator(_canonical_identity)]
type CanonicalNamespace = Annotated[str, BeforeValidator(_canonical_namespace)]
type CanonicalVersion = Annotated[str, BeforeValidator(_canonical_version)]
type CanonicalSHA256 = Annotated[str, BeforeValidator(_canonical_sha256)]
type CanonicalProvenanceIdentity = Annotated[str, BeforeValidator(_provenance_identity)]
type UTCInstant = Annotated[datetime, AfterValidator(_utc_instant)]


class FieldContractModel(BaseModel):
    """Strict, recursively immutable v1 boundary; canonical JSON is inert data."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, revalidate_instances="always"
    )

    def canonical_json(self) -> str:
        """Encode all members, including null absence, without issuing authority."""
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def canonical_bytes(self) -> bytes:
        return self.canonical_json().encode("utf-8")


class FieldIdentityKind(StrEnum):
    FIXED = "fixed"
    DEFINITION = "definition"
    TYPED_DEFINITION = "typed_definition"


type FieldLogicalKey = tuple[UUID, str, str, str, UUID, str, str, UUID | None, UUID | None]


class CanonicalFieldLocator(FieldContractModel):
    """Canonical logical identity intent; its tenant/owner claims are not trusted."""

    version: Literal["1.0"] = FIELD_CONTRACT_VERSION
    tenant_id: CanonicalUUID
    resource_namespace: CanonicalNamespace
    resource_contract_version: CanonicalVersion
    resource_owner_module_id: CanonicalIdentity
    field_id: CanonicalUUID
    field_contract_id: CanonicalIdentity
    field_contract_version: CanonicalVersion
    identity_kind: FieldIdentityKind
    dynamic_definition_id: CanonicalUUID | None = None
    dynamic_type_id: CanonicalUUID | None = None

    @model_validator(mode="after")
    def canonical_family(self) -> Self:
        if not self.resource_namespace.startswith(self.resource_owner_module_id + "."):
            raise ValueError("Resource namespace must have the exact owner module root")
        expected_definition = self.identity_kind is not FieldIdentityKind.FIXED
        expected_type = self.identity_kind is FieldIdentityKind.TYPED_DEFINITION
        if (self.dynamic_definition_id is not None) != expected_definition or (
            (self.dynamic_type_id is not None) != expected_type
        ):
            raise ValueError("Dynamic IDs must match the explicit field identity family")
        return self

    def logical_key(self) -> FieldLogicalKey:
        """Exact structured equality; neither display names nor digests replace it."""
        return (
            self.tenant_id,
            self.resource_namespace,
            self.resource_contract_version,
            self.resource_owner_module_id,
            self.field_id,
            self.field_contract_id,
            self.field_contract_version,
            self.dynamic_definition_id,
            self.dynamic_type_id,
        )

    def family_key(self) -> tuple[object, ...]:
        """One bounded operation family, including its exact dynamic definition/type."""
        return (
            self.resource_namespace,
            self.resource_contract_version,
            self.resource_owner_module_id,
            self.field_contract_id,
            self.field_contract_version,
            self.identity_kind,
            self.dynamic_definition_id,
            self.dynamic_type_id,
        )


class FieldSchemaPin(FieldContractModel):
    definition_id: CanonicalUUID
    revision_id: CanonicalUUID
    digest: CanonicalSHA256


class DynamicFieldPin(FieldContractModel):
    """Selected immutable definition meaning; not a historical tag/Policy epoch."""

    definition_id: CanonicalUUID
    revision_id: CanonicalUUID
    revision_digest: CanonicalSHA256
    schema_pin: FieldSchemaPin

    @model_validator(mode="after")
    def exact_schema_pin(self) -> Self:
        if (
            self.schema_pin.definition_id != self.definition_id
            or self.schema_pin.revision_id != self.revision_id
            or self.schema_pin.digest != self.revision_digest
        ):
            raise ValueError("Schema pin must select the exact immutable definition revision")
        return self


class FieldProviderDescriptor(FieldContractModel):
    """Claims identifying a future owner-scoped provider, never registry admission."""

    version: Literal["1.0"] = FIELD_CONTRACT_VERSION
    owner_module_id: CanonicalIdentity
    contract_id: CanonicalIdentity
    contract_version: CanonicalVersion
    registration_id: CanonicalProvenanceIdentity
    resource_namespace: CanonicalNamespace | None = None
    resource_contract_version: CanonicalVersion | None = None

    @model_validator(mode="after")
    def resource_family(self) -> Self:
        if (self.resource_namespace is None) != (self.resource_contract_version is None):
            raise ValueError("Resource provider namespace and version must occur together")
        if self.resource_namespace is not None and not self.resource_namespace.startswith(
            self.owner_module_id + "."
        ):
            raise ValueError("Resource provider namespace must belong to its exact owner")
        return self


class FieldAuthorityProvenance(FieldContractModel):
    """Inert claims to be checked against protected state in a later runtime gate.

    Install/artifact identities and both generations are independently attributed.
    A serialized value retains no protected generation object or admission lease.
    """

    version: Literal["1.0"] = FIELD_CONTRACT_VERSION
    provider: FieldProviderDescriptor
    approved_install_id: CanonicalProvenanceIdentity
    artifact_identity: CanonicalProvenanceIdentity
    artifact_sha256: CanonicalSHA256 | None = None
    process_generation: int = Field(ge=1, lt=2**63)
    durable_fence_id: CanonicalProvenanceIdentity
    durable_generation: int = Field(ge=1, lt=2**63)


class FieldFailureReason(StrEnum):
    OWNER_UNAVAILABLE = "owner_unavailable"
    FIELD_UNAVAILABLE = "field_unavailable"
    FIELD_RETIRED = "field_retired"
    FIELD_IDENTITY_MISMATCH = "field_identity_mismatch"
    DEFINITION_REVISION_MISMATCH = "definition_revision_mismatch"
    TAG_BINDING_UNAVAILABLE = "tag_binding_unavailable"
    TAG_COVERAGE_MISMATCH = "tag_coverage_mismatch"
    CLASSIFICATION_UNAVAILABLE = "classification_unavailable"
    PROVIDER_MISMATCH = "provider_mismatch"
    TENANT_MISMATCH = "tenant_mismatch"
    UNSUPPORTED_CONTRACT_VERSION = "unsupported_contract_version"
    UNSUPPORTED_CAPABILITY_ENROLLMENT = "unsupported_capability_enrollment"
    STALE_AUTHORITY_PROVENANCE = "stale_authority_provenance"


class FieldContractFailure(FieldContractModel):
    """A bounded failure; no reason confers PUBLIC, unclassified access or fallback."""

    version: Literal["1.0"] = FIELD_CONTRACT_VERSION
    reason: FieldFailureReason
    contract_id: CanonicalIdentity | None = None
    requested_contract_version: CanonicalProvenanceIdentity | None = None

    @model_validator(mode="after")
    def version_diagnostic(self) -> Self:
        if (self.contract_id is None) != (self.requested_contract_version is None):
            raise ValueError("Unsupported version metadata must identify contract and version")
        if self.contract_id is not None and self.reason is not (
            FieldFailureReason.UNSUPPORTED_CONTRACT_VERSION
        ):
            raise ValueError("Version diagnostics require the unsupported-version failure")
        return self


class OwnerFieldLifecycle(StrEnum):
    CURRENT = "current"
    UNAVAILABLE = "unavailable"
    RETIRED = "retired"


class OwnerFieldWitness(FieldContractModel):
    """Neutral witness representation, freely constructible and NEVER issued authority.

    This value does not authenticate request/tenant/provider facts. Future neutral
    admission must separately bind the facts to the exact protected invocation,
    active transaction, current installation and retained owner generations.
    """

    version: Literal["1.0"] = FIELD_CONTRACT_VERSION
    locator: CanonicalFieldLocator
    field_exists: bool
    lifecycle: OwnerFieldLifecycle
    operation: CanonicalIdentity
    resource_record_id: CanonicalUUID | None = None
    field_meaning_fingerprint: CanonicalSHA256
    dynamic_pin: DynamicFieldPin | None = None
    owner_provenance: FieldAuthorityProvenance
    definition_owner_module_id: CanonicalIdentity | None = None
    definition_owner_provenance: FieldAuthorityProvenance | None = None

    @model_validator(mode="after")
    def identity_consistency(self) -> Self:
        owner = self.owner_provenance.provider
        if (
            owner.owner_module_id != self.locator.resource_owner_module_id
            or owner.resource_namespace != self.locator.resource_namespace
            or owner.resource_contract_version != self.locator.resource_contract_version
            or owner.contract_id != OWNER_FIELD_WITNESS_CONTRACT_ID
            or owner.contract_version != FIELD_CONTRACT_VERSION
        ):
            raise ValueError("Witness provider must match exact owner/resource/contract identity")
        if self.field_exists != (self.lifecycle is not OwnerFieldLifecycle.UNAVAILABLE):
            raise ValueError("Field existence must match the declared lifecycle")
        dynamic = self.locator.dynamic_definition_id is not None
        if (
            (self.dynamic_pin is not None) != dynamic
            or (self.definition_owner_module_id is not None) != dynamic
            or (self.definition_owner_provenance is not None) != dynamic
        ):
            raise ValueError(
                "Dynamic field requires complete, separately attributed definition pin"
            )
        if self.dynamic_pin is not None and (
            self.dynamic_pin.definition_id != self.locator.dynamic_definition_id
        ):
            raise ValueError("Dynamic pin must match the locator definition")
        if self.definition_owner_provenance is not None and (
            self.definition_owner_provenance.provider.owner_module_id
            != self.definition_owner_module_id
            or self.definition_owner_provenance.provider.contract_id
            != OWNER_FIELD_WITNESS_CONTRACT_ID
            or self.definition_owner_provenance.provider.contract_version != FIELD_CONTRACT_VERSION
        ):
            raise ValueError("Definition provenance must retain its actual owner/witness contract")
        return self

    def require_matches(
        self,
        locator: CanonicalFieldLocator,
        operation: str,
        resource_record_id: UUID | None,
    ) -> None:
        """Check representation consistency only; this cannot authenticate authority."""
        if type(locator) is not CanonicalFieldLocator or self.locator != locator:
            raise ValueError("Witness representation has a tenant/field identity mismatch")
        if type(operation) is not str or operation != self.operation:
            raise ValueError("Witness representation has an operation mismatch")
        if (resource_record_id is not None and type(resource_record_id) is not UUID) or (
            resource_record_id != self.resource_record_id
        ):
            raise ValueError("Witness representation has a record identity mismatch")


class OwnerFieldWitnessResult(FieldContractModel):
    """Exactly one representation or bounded failure, never an authorization decision."""

    version: Literal["1.0"] = FIELD_CONTRACT_VERSION
    status: Literal["facts", "failure"]
    witness: OwnerFieldWitness | None = None
    failure: FieldContractFailure | None = None

    @model_validator(mode="after")
    def result_shape(self) -> Self:
        if self.status == "facts":
            if self.witness is None or self.failure is not None:
                raise ValueError("Facts result requires only a witness representation")
        elif self.failure is None or self.witness is not None:
            raise ValueError("Failure result requires only a bounded failure")
        return self


class FieldOperationIntent(FieldContractModel):
    """Bounded untrusted intent, without operation enrollment or authority fallback."""

    version: Literal["1.0"] = FIELD_CONTRACT_VERSION
    tenant_id: CanonicalUUID
    operation: CanonicalIdentity
    resource_record_id: CanonicalUUID | None = None
    fields: tuple[CanonicalFieldLocator, ...] = Field(
        min_length=1, max_length=MAX_FIELD_OPERATION_FIELDS
    )

    @model_validator(mode="after")
    def one_family(self) -> Self:
        first = self.fields[0]
        field_ids: set[UUID] = set()
        for locator in self.fields:
            if locator.tenant_id != self.tenant_id:
                raise ValueError("Field operation cannot mix tenants")
            if locator.family_key() != first.family_key():
                raise ValueError("Field operation requires one exact resource/field family")
            if locator.field_id in field_ids:
                raise ValueError("Field operation cannot repeat or conflict on a field identity")
            field_ids.add(locator.field_id)
        return self


class OwnerFieldWitnessProvider(Protocol):
    """Future owner-adapter interface; no implementation/admission is enabled here."""

    version: Literal["1.0"]
    descriptor: FieldProviderDescriptor

    async def describe_fields(
        self,
        intent: FieldOperationIntent,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> tuple[OwnerFieldWitnessResult, ...]: ...
